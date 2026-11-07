from __future__ import annotations

import abc
import datetime
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

import aiohttp
from args.media import Media

if TYPE_CHECKING:
	from core.bot import Bot

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("youtube", "twitch", "tiktok", "instagram")

# XML Namespaces for YouTube Atom feeds
YT_NAMESPACES = {
	"atom": "http://www.w3.org/2005/Atom",
	"yt": "http://www.youtube.com/xml/schemas/2015",
	"media": "http://search.yahoo.com/mrss/",
}


class AlertProvider(abc.ABC):
	"""Abstract base class for all social media alert providers."""

	platform: str
	display_name: str

	@abc.abstractmethod
	async def resolve_channel(
		self,
		session: aiohttp.ClientSession,
		channel_input: str,
		bot: Bot | None = None,
	) -> tuple[str, str]:
		"""Resolves a user-provided handle or URL to an internal account ID and display name.

		Args:
			session: Shared aiohttp ClientSession.
			channel_input: User-entered channel name, handle, or URL.
			bot: Bot instance if needed for credentials.

		Returns:
			tuple[str, str]: (account_id, account_name)

		"""
		...

	@abc.abstractmethod
	async def fetch_latest(
		self,
		session: aiohttp.ClientSession,
		account_id: str,
		account_name: str | None = None,
		bot: Bot | None = None,
	) -> Media | None:
		"""Fetches the latest media upload or live stream for the account.

		Args:
			session: Shared aiohttp ClientSession.
			account_id: The resolved account ID.
			account_name: The display name if known.
			bot: Bot instance if needed for credentials.

		Returns:
			Media | None: The latest media object or None if no media found.

		"""
		...


class YouTubeProvider(AlertProvider):
	"""YouTube alert provider using Atom/RSS feeds and handle resolution."""

	platform = "youtube"
	display_name = "YouTube"

	async def resolve_channel(
		self,
		session: aiohttp.ClientSession,
		channel_input: str,
		bot: Bot | None = None,
	) -> tuple[str, str]:
		cleaned = channel_input.strip()
		# Extract from YouTube URLs if provided
		url_match = re.search(r"youtube\.com/(?:channel/|@|c/)?([^/?#]+)", cleaned)
		candidate = url_match.group(1) if url_match else cleaned
		candidate = candidate.lstrip("@")

		# If already a standard YouTube channel ID (starts with UC and 24 chars long)
		if candidate.startswith("UC") and len(candidate) == 24:
			# Attempt to fetch feed to get real channel name
			feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={candidate}"
			try:
				async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
					if resp.status == 200:
						xml_text = await resp.text()
						root = ET.fromstring(xml_text)
						title_el = root.find("atom:title", YT_NAMESPACES)
						name = title_el.text.strip() if title_el is not None and title_el.text else candidate
						return candidate, name
			except (aiohttp.ClientError, ET.ParseError, TimeoutError, OSError) as e:
				logger.debug(f"Failed to fetch YouTube feed for {candidate}: {e}")
			return candidate, candidate

		# Otherwise resolve handle or username
		handle_url = f"https://www.youtube.com/@{candidate}"
		try:
			headers = {"User-Agent": "Mozilla/5.0 (compatible; fm01-bot/1.0; +https://github.com)"}
			async with session.get(handle_url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
				if resp.status == 200:
					html = await resp.text()
					# Search for channelId in page metadata
					cid_match = re.search(r'"externalId":"(UC[a-zA-Z0-9_-]{22})"', html)
					if not cid_match:
						cid_match = re.search(r'itemprop="identifier"\s+content="(UC[a-zA-Z0-9_-]{22})"', html)
					if not cid_match:
						cid_match = re.search(r"channel/(UC[a-zA-Z0-9_-]{22})", html)
					if cid_match:
						cid = cid_match.group(1)
						# Extract channel title
						title_match = re.search(r'<meta property="og:title" content="([^"]+)">', html)
						title = title_match.group(1) if title_match else candidate
						return cid, title
		except (aiohttp.ClientError, TimeoutError, OSError) as e:
			logger.debug(f"Failed to resolve YouTube handle @{candidate}: {e}")

		# Fallback to candidate as account ID
		return candidate, candidate

	async def fetch_latest(
		self,
		session: aiohttp.ClientSession,
		account_id: str,
		account_name: str | None = None,
		bot: Bot | None = None,
	) -> Media | None:
		if account_id.startswith("UC") and len(account_id) == 24:
			feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={account_id}"
		else:
			feed_url = f"https://www.youtube.com/feeds/videos.xml?user={account_id}"

		try:
			async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
				if resp.status != 200:
					logger.debug(f"YouTube feed returned status {resp.status} for {account_id}")
					return None
				content = await resp.text()
				root = ET.fromstring(content)
		except (aiohttp.ClientError, ET.ParseError, TimeoutError, OSError) as e:
			logger.debug(f"Error fetching YouTube feed for {account_id}: {e}")
			return None

		entry = root.find("atom:entry", YT_NAMESPACES)
		if entry is None:
			return None

		video_id_el = entry.find("yt:videoId", YT_NAMESPACES)
		title_el = entry.find("atom:title", YT_NAMESPACES)
		link_el = entry.find("atom:link[@rel='alternate']", YT_NAMESPACES)
		published_el = entry.find("atom:published", YT_NAMESPACES)

		if video_id_el is None or video_id_el.text is None:
			return None

		video_id = video_id_el.text.strip()
		title = title_el.text.strip() if title_el is not None and title_el.text else "New Video"
		href = link_el.attrib.get("href") if link_el is not None else None
		video_url: str = href if href else f"https://www.youtube.com/watch?v={video_id}"

		# Channel details
		author_el = root.find("atom:author", YT_NAMESPACES)
		author_name_el = author_el.find("atom:name", YT_NAMESPACES) if author_el is not None else None
		author_uri_el = author_el.find("atom:uri", YT_NAMESPACES) if author_el is not None else None

		channel_name = (
			author_name_el.text.strip()
			if author_name_el is not None and author_name_el.text
			else (account_name or account_id)
		)
		channel_url = (
			author_uri_el.text.strip()
			if author_uri_el is not None and author_uri_el.text
			else f"https://www.youtube.com/channel/{account_id}"
		)

		# Media description & thumbnail
		media_group = entry.find("media:group", YT_NAMESPACES)
		description: str | None = None
		thumbnail: str | None = None
		if media_group is not None:
			desc_el = media_group.find("media:description", YT_NAMESPACES)
			if desc_el is not None and desc_el.text:
				description = desc_el.text.strip()
			thumb_el = media_group.find("media:thumbnail", YT_NAMESPACES)
			if thumb_el is not None and "url" in thumb_el.attrib:
				thumbnail = thumb_el.attrib["url"]

		if not thumbnail:
			thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

		published_at: datetime.datetime | None = None
		if published_el is not None and published_el.text:
			try:
				published_at = datetime.datetime.fromisoformat(published_el.text)
			except ValueError:
				published_at = None

		return Media.create(
			url=video_url,
			title=title,
			author_name=channel_name,
			author_url=channel_url,
			author_id=account_id,
			media_id=video_id,
			platform="youtube",
			thumbnail=thumbnail,
			description=description,
			published_at=published_at,
		)


class TwitchProvider(AlertProvider):
	"""Twitch alert provider using Twitch Helix API for live stream alerts."""

	platform = "twitch"
	display_name = "Twitch"

	def __init__(self) -> None:
		self._access_token: str | None = None
		self._token_expires_at: float = 0.0

	def _get_credentials(self, bot: Bot | None) -> tuple[str | None, str | None]:
		client_id = getattr(bot.config, "twitch_client_id", None) if bot and hasattr(bot, "config") else None
		client_secret = getattr(bot.config, "twitch_client_secret", None) if bot and hasattr(bot, "config") else None
		if not client_id:
			client_id = os.getenv("TWITCH_CLIENT_ID")
		if not client_secret:
			client_secret = os.getenv("TWITCH_CLIENT_SECRET")
		return client_id, client_secret

	async def _get_app_token(self, session: aiohttp.ClientSession, bot: Bot | None) -> str | None:
		client_id, client_secret = self._get_credentials(bot)
		if not client_id or not client_secret:
			return None

		now = datetime.datetime.now(datetime.UTC).timestamp()
		if self._access_token and now < (self._token_expires_at - 60):
			return self._access_token

		token_url = "https://id.twitch.tv/oauth2/token"
		params = {
			"client_id": client_id,
			"client_secret": client_secret,
			"grant_type": "client_credentials",
		}
		try:
			async with session.post(token_url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
				if resp.status == 200:
					data = await resp.json()
					self._access_token = data.get("access_token")
					expires_in = data.get("expires_in", 3600)
					self._token_expires_at = now + float(expires_in)
					return self._access_token
				logger.warning(f"Failed to obtain Twitch OAuth token: HTTP {resp.status}")
		except (aiohttp.ClientError, TimeoutError, OSError) as e:
			logger.warning(f"Error fetching Twitch token: {e}")
		return None

	async def resolve_channel(
		self,
		session: aiohttp.ClientSession,
		channel_input: str,
		bot: Bot | None = None,
	) -> tuple[str, str]:
		cleaned = channel_input.strip()
		url_match = re.search(r"twitch\.tv/([^/?#]+)", cleaned)
		login = (url_match.group(1) if url_match else cleaned).lstrip("@").lower()

		token = await self._get_app_token(session, bot)
		client_id, _ = self._get_credentials(bot)
		if token and client_id:
			headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
			try:
				url = f"https://api.twitch.tv/helix/users?login={login}"
				async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
					if resp.status == 200:
						data = await resp.json()
						users = data.get("data", [])
						if users:
							return users[0]["id"], users[0]["display_name"]
			except (aiohttp.ClientError, TimeoutError, OSError) as e:
				logger.debug(f"Twitch user lookup error for {login}: {e}")

		return login, login

	async def fetch_latest(
		self,
		session: aiohttp.ClientSession,
		account_id: str,
		account_name: str | None = None,
		bot: Bot | None = None,
	) -> Media | None:
		token = await self._get_app_token(session, bot)
		client_id, _ = self._get_credentials(bot)
		if not token or not client_id:
			logger.debug("Twitch credentials not configured, skipping Twitch stream check.")
			return None

		headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
		# account_id could be numeric user_id or login name
		param_key = "user_id" if account_id.isdigit() else "user_login"
		url = f"https://api.twitch.tv/helix/streams?{param_key}={account_id.lower()}"

		try:
			async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
				if resp.status != 200:
					logger.debug(f"Twitch streams API returned {resp.status} for {account_id}")
					return None
				res = await resp.json()
				data: list[dict[str, Any]] = res.get("data", [])
		except (aiohttp.ClientError, TimeoutError, OSError) as e:
			logger.debug(f"Error fetching Twitch streams for {account_id}: {e}")
			return None

		if not data:
			return None

		stream = data[0]
		stream_id = str(stream.get("id", ""))
		user_login = stream.get("user_login", account_id)
		display_name = stream.get("user_name", account_name or user_login)
		title = stream.get("title", f"{display_name} is live!")
		game_name = stream.get("game_name", "")
		if game_name and game_name not in title:
			title = f"{title} [{game_name}]"

		raw_thumb = stream.get("thumbnail_url", "")
		thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720") if raw_thumb else None

		started_at_raw = stream.get("started_at")
		published_at: datetime.datetime | None = None
		if started_at_raw:
			try:
				published_at = datetime.datetime.fromisoformat(started_at_raw)
			except ValueError:
				published_at = None

		stream_url = f"https://twitch.tv/{user_login}"
		return Media.create(
			url=stream_url,
			title=title,
			author_name=display_name,
			author_url=stream_url,
			author_id=str(stream.get("user_id", account_id)),
			media_id=f"stream_{stream_id}",
			platform="twitch",
			thumbnail=thumbnail,
			description=game_name,
			published_at=published_at,
		)


class GenericRSSProvider(AlertProvider):
	"""Pluggable RSS-based alert provider for platforms like TikTok and Instagram."""

	def __init__(self, platform: str, display_name: str, path_prefix: str) -> None:
		self.platform = platform
		self.display_name = display_name
		self.path_prefix = path_prefix

	def _get_base_url(self, bot: Bot | None) -> str:
		if bot and hasattr(bot, "config") and getattr(bot.config, "rsshub_url", None):
			return str(bot.config.rsshub_url).rstrip("/")
		env_url = os.getenv("RSSHUB_URL")
		if env_url:
			return env_url.rstrip("/")
		return "https://rsshub.app"

	async def resolve_channel(
		self,
		session: aiohttp.ClientSession,
		channel_input: str,
		bot: Bot | None = None,
	) -> tuple[str, str]:
		cleaned = channel_input.strip()
		handle_match = re.search(r"(?:com|app)/(?:@|p/)?([^/?#]+)", cleaned)
		candidate = handle_match.group(1) if handle_match else cleaned
		candidate = candidate.lstrip("@")
		return candidate, candidate

	async def fetch_latest(
		self,
		session: aiohttp.ClientSession,
		account_id: str,
		account_name: str | None = None,
		bot: Bot | None = None,
	) -> Media | None:
		base_url = self._get_base_url(bot)
		feed_url = f"{base_url}/{self.path_prefix}/{account_id}"

		try:
			async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
				if resp.status != 200:
					return None
				xml_text = await resp.text()
				root = ET.fromstring(xml_text)
		except (aiohttp.ClientError, ET.ParseError, TimeoutError, OSError) as e:
			logger.debug(f"Error fetching feed from {feed_url}: {e}")
			return None

		# Handle RSS 2.0 channel/item structure
		channel = root.find("channel")
		if channel is None:
			return None

		items = channel.findall("item")
		if not items:
			return None

		item = items[0]
		title_el = item.find("title")
		link_el = item.find("link")
		guid_el = item.find("guid")
		pub_date_el = item.find("pubDate")
		desc_el = item.find("description")

		media_id = guid_el.text.strip() if guid_el is not None and guid_el.text else ""
		url = link_el.text.strip() if link_el is not None and link_el.text else ""
		if not media_id and url:
			media_id = url
		if not media_id:
			return None

		title = title_el.text.strip() if title_el is not None and title_el.text else f"New {self.display_name} Post"
		author_title_el = channel.find("title")
		author_name = (
			author_title_el.text.strip()
			if author_title_el is not None and author_title_el.text
			else (account_name or account_id)
		)

		published_at: datetime.datetime | None = None
		if pub_date_el is not None and pub_date_el.text:
			try:
				published_at = datetime.datetime.fromisoformat(pub_date_el.text)
			except ValueError:
				published_at = None

		desc_text = desc_el.text.strip() if desc_el is not None and desc_el.text else None
		author_url = (
			f"https://www.{self.platform}.com/@{account_id}"
			if self.platform == "tiktok"
			else f"https://www.{self.platform}.com/{account_id}"
		)

		return Media.create(
			url=url,
			title=title,
			author_name=author_name,
			author_url=author_url,
			author_id=account_id,
			media_id=media_id,
			platform=self.platform,
			description=desc_text,
			published_at=published_at,
		)


class TikTokProvider(GenericRSSProvider):
	"""TikTok alert provider."""

	def __init__(self) -> None:
		super().__init__(platform="tiktok", display_name="TikTok", path_prefix="tiktok/user")


class InstagramProvider(GenericRSSProvider):
	"""Instagram alert provider."""

	def __init__(self) -> None:
		super().__init__(platform="instagram", display_name="Instagram", path_prefix="instagram/user")


# Registry instance dictionary
ALERT_PROVIDERS: dict[str, AlertProvider] = {
	"youtube": YouTubeProvider(),
	"twitch": TwitchProvider(),
	"tiktok": TikTokProvider(),
	"instagram": InstagramProvider(),
}


def get_provider(platform: str) -> AlertProvider | None:
	"""Fetches the registered alert provider for the platform name."""
	return ALERT_PROVIDERS.get(platform.lower().strip())
