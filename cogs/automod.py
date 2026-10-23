"""Auto Moderation Cog for managing and enforcing server automod rules."""

from __future__ import annotations

import collections
import datetime
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import discord
from discord.ext import commands
from helpers.convert import text_to_seconds
from helpers.regex import DISCORD_INVITE, URL_REGEX

if TYPE_CHECKING:
	from core import Bot

logger = logging.getLogger(__name__)

SUPPORTED_FEATURES = ("phrase", "link", "invite", "spam", "mention", "lines")


class AutoModConfig:
	"""Encapsulates guild auto-moderation settings."""

	def __init__(self, guild_id: int, is_on: bool = True, settings: dict[str, Any] | None = None) -> None:
		self.guild_id = guild_id
		self.is_on = is_on
		self.settings: dict[str, Any] = settings if isinstance(settings, dict) else {}
		self._normalize()

	def _normalize(self) -> None:
		rules = self.settings.setdefault("rules", {})
		rules.setdefault("phrase", {"enabled": False, "phrases": []})
		rules.setdefault("link", {"enabled": False, "allowlist": []})
		rules.setdefault("invite", {"enabled": False, "allowlist": []})
		rules.setdefault("spam", {"enabled": False, "max_messages": 5, "window_seconds": 6.0})
		rules.setdefault("mention", {"enabled": False, "limit": 5})
		rules.setdefault("lines", {"enabled": False, "limit": 15})

		bypasses = self.settings.setdefault("bypasses", {})
		bypasses.setdefault("global", {"channels": [], "categories": [], "users": [], "roles": []})
		features_bypasses = bypasses.setdefault("features", {})
		for feat in SUPPORTED_FEATURES:
			features_bypasses.setdefault(feat, {"channels": [], "categories": [], "users": [], "roles": []})

		actions = self.settings.setdefault("actions", {})
		actions.setdefault(
			"default",
			{
				"delete": True,
				"notify": True,
				"notify_duration": 5,
				"case": None,
				"mute_duration": "5m",
			},
		)
		actions.setdefault("features", {})

	def to_dict(self) -> dict[str, Any]:
		return {"guild_id": self.guild_id, "is_on": self.is_on, "settings": self.settings}

	@classmethod
	def from_row(cls, row: dict[str, Any] | None, guild_id: int) -> AutoModConfig:
		if not row:
			return cls(guild_id=guild_id, is_on=False, settings={})
		settings_raw = row.get("settings")
		if isinstance(settings_raw, str):
			try:
				settings = json.loads(settings_raw)
			except (json.JSONDecodeError, TypeError):
				settings = {}
		elif isinstance(settings_raw, dict):
			settings = settings_raw
		else:
			settings = {}
		return cls(guild_id=guild_id, is_on=bool(row.get("is_on", False)), settings=settings)

	def is_feature_enabled(self, feature: str) -> bool:
		if not self.is_on:
			return False
		rule = self.settings.get("rules", {}).get(feature, {})
		return bool(rule.get("enabled", False))

	def get_action(self, feature: str) -> dict[str, Any]:
		default_action = dict(self.settings.get("actions", {}).get("default", {}))
		feature_action = self.settings.get("actions", {}).get("features", {}).get(feature, {})
		if isinstance(feature_action, dict):
			default_action.update(feature_action)
		return default_action


class AutoMod(commands.Cog, name="AutoMod"):
	"""Auto-moderation system managing filters, spam detection, and bypasses."""

	def __init__(self, client: Bot) -> None:
		self.client = client
		self._config_cache: dict[int, AutoModConfig] = {}
		self._spam_tracker: dict[tuple[int, int], collections.deque[float]] = {}
		self._last_prune: float = time.monotonic()

	def invalidate_cache(self, guild_id: int) -> None:
		"""Clear the config cache for a given guild."""
		self._config_cache.pop(guild_id, None)

	async def get_config(self, guild_id: int) -> AutoModConfig:
		"""Fetch configuration for a guild, reading from cache or database."""
		if guild_id in self._config_cache:
			return self._config_cache[guild_id]

		row = await self.client.db.fetchrow(
			"SELECT guild_id, is_on, settings FROM automod_config WHERE guild_id = $1", guild_id
		)
		cfg = AutoModConfig.from_row(dict(row) if row else None, guild_id)
		self._config_cache[guild_id] = cfg
		return cfg

	async def save_config(self, config: AutoModConfig) -> None:
		"""Persist configuration to the database and update cache."""
		self._config_cache[config.guild_id] = config
		await self.client.db.execute(
			"""
			INSERT INTO automod_config (guild_id, is_on, settings)
			VALUES ($1, $2, $3::jsonb)
			ON CONFLICT (guild_id) DO UPDATE SET
				is_on = $2,
				settings = $3::jsonb
			""",
			config.guild_id,
			config.is_on,
			json.dumps(config.settings),
		)

	def is_bypassed(
		self,
		member: discord.Member,
		channel: discord.abc.GuildChannel | discord.Thread,
		feature: str | None = None,
		config: AutoModConfig | None = None,
	) -> bool:
		"""Check if a member or channel is bypassed from automod globally or for a specific feature."""
		guild = member.guild
		if guild.owner_id == member.id:
			return True
		if member.guild_permissions.administrator:
			return True

		if not config:
			return False

		bypasses = config.settings.get("bypasses", {})
		glob = bypasses.get("global", {})

		# Global user bypass
		if member.id in glob.get("users", []):
			return True

		# Global role bypass
		member_role_ids = {r.id for r in member.roles}
		if member_role_ids.intersection(glob.get("roles", [])):
			return True

		# Global channel bypass
		if channel.id in glob.get("channels", []):
			return True

		# Global category bypass
		category_id = getattr(channel, "category_id", None)
		if category_id and category_id in glob.get("categories", []):
			return True

		# Feature-specific bypass
		if feature:
			feat_bypass = bypasses.get("features", {}).get(feature, {})
			if member.id in feat_bypass.get("users", []):
				return True
			if member_role_ids.intersection(feat_bypass.get("roles", [])):
				return True
			if channel.id in feat_bypass.get("channels", []):
				return True
			if category_id and category_id in feat_bypass.get("categories", []):
				return True

		return False

	def check_phrases(self, content: str, phrases: list[str]) -> bool:
		"""Return True if content contains any forbidden phrases."""
		if not phrases or not content:
			return False

		lower_content = content.lower()
		for phrase in phrases:
			p = phrase.strip().lower()
			if not p:
				continue
			if " " in p:
				if p in lower_content:
					return True
			else:
				# Use word boundaries for single-word checks
				pattern = rf"\b{re.escape(p)}\b"
				if re.search(pattern, lower_content):
					return True
		return False

	def check_links(self, content: str, allowlist: list[str]) -> bool:
		"""Return True if content contains URLs that are not in the allowlist."""
		if not content:
			return False

		matches = URL_REGEX.findall(content)
		if not matches:
			return False

		normalized_allowlist = [item.strip().lower() for item in allowlist if item.strip()]

		for match in matches:
			raw_url = match.strip()
			if not raw_url.startswith(("http://", "https://")):
				test_url = f"http://{raw_url}"
			else:
				test_url = raw_url

			try:
				parsed = urlparse(test_url)
				hostname = (parsed.hostname or "").lower()
			except (ValueError, AttributeError):
				hostname = raw_url.lower().split("/")[0]

			if not hostname:
				continue

			# Check if hostname matches or is a subdomain of any allowed domain
			allowed = False
			for allowed_domain in normalized_allowlist:
				if hostname == allowed_domain or hostname.endswith(f".{allowed_domain}"):
					allowed = True
					break

			if not allowed:
				return True

		return False

	def check_invites(self, content: str, allowlist: list[str], guild: discord.Guild) -> bool:
		"""Return True if content contains Discord invites not permitted for this guild."""
		if not content:
			return False

		matches = DISCORD_INVITE.findall(content)
		if not matches:
			return False

		normalized_allowlist = {item.strip().lower() for item in allowlist if item.strip()}
		guild_vanity = (guild.vanity_url_code or "").lower()

		for invite_str in matches:
			code = invite_str.rstrip("/").split("/")[-1].lower()
			if code in normalized_allowlist:
				continue
			if guild_vanity and code == guild_vanity:
				continue
			return True

		return False

	def check_spam(self, guild_id: int, user_id: int, max_messages: int, window_seconds: float) -> bool:
		"""Check if user has exceeded the message window rate limit."""
		now = time.monotonic()

		# Periodic prune of inactive users
		if now - self._last_prune > 60:
			self._prune_spam_tracker(now)
			self._last_prune = now

		key = (guild_id, user_id)
		dq = self._spam_tracker.setdefault(key, collections.deque())

		cutoff = now - max(window_seconds, 1.0)
		while dq and dq[0] <= cutoff:
			dq.popleft()

		dq.append(now)
		return len(dq) > max_messages

	def _prune_spam_tracker(self, now: float) -> None:
		stale_keys = [k for k, dq in self._spam_tracker.items() if not dq or dq[-1] < now - 30]
		for k in stale_keys:
			self._spam_tracker.pop(k, None)

	def check_mentions(self, message: discord.Message, limit: int) -> bool:
		"""Return True if message exceeds the mention threshold."""
		mention_count = len(message.mentions) + len(message.role_mentions)
		if message.mention_everyone:
			mention_count += 1
		return mention_count > limit

	def check_lines(self, content: str, limit: int) -> bool:
		"""Return True if message exceeds the newline threshold."""
		if not content:
			return False
		line_count = len(content.splitlines())
		return line_count > limit

	async def handle_violation(
		self,
		message: discord.Message,
		feature: str,
		config: AutoModConfig,
	) -> None:
		"""Execute enforcement actions: message deletion, temporary channel notification, moderation case."""
		action = config.get_action(feature)
		guild = message.guild
		if not guild:
			return

		if action.get("delete", True):
			try:
				await message.delete()
			except (discord.NotFound, discord.Forbidden):
				pass
			except Exception as e:  # noqa: BLE001
				logger.warning(f"Failed to delete automod violating message {message.id}: {e}")

		case_type = action.get("case")
		if case_type in ("warn", "mute") and isinstance(message.author, (discord.Member, discord.User)):
			moderator: Any = self.client.user or guild.me
			if not moderator:
				return
			reason = f"[AutoMod] {feature.title()} rule violation"
			try:
				if case_type == "warn":
					from cogs.mod import Warn

					warn_case = Warn(
						_id=message.id,
						bot=self.client,
						guild=guild,
						user=message.author,
						moderator=moderator,  # type: ignore[arg-type]
						reason=reason,
						message=message.content[:500] if message.content else None,
					)
					await warn_case.create(self.client.db)
				elif case_type == "mute":
					from cogs.mod import Mute

					raw_duration = action.get("mute_duration", "5m")
					try:
						duration_sec = text_to_seconds(raw_duration) if raw_duration else 300
					except (ValueError, TypeError):
						duration_sec = 300

					expires = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=duration_sec)
					mute_case = Mute(
						_id=message.id,
						bot=self.client,
						guild=guild,
						user=message.author,
						moderator=moderator,  # type: ignore[arg-type]
						expires=expires,
						reason=reason,
						message=message.content[:500] if message.content else None,
					)
					await mute_case.create(self.client.db)
			except Exception:
				logger.exception(f"Failed to create automod case for {message.author.id}")

		if action.get("notify", True):
			duration = int(action.get("notify_duration", 5))
			key = f"automod.violation.{feature}"
			try:
				payload = await self.client.custom_response.get_message(
					key, guild, member=message.author, user=message.author
				)
				if isinstance(payload, dict):
					await message.channel.send(**payload, delete_after=duration)
				elif isinstance(payload, str):
					await message.channel.send(content=payload, delete_after=duration)
			except (discord.Forbidden, discord.HTTPException):
				pass
			except Exception as e:  # noqa: BLE001
				logger.warning(f"Failed to send automod notification in channel {message.channel.id}: {e}")

	async def inspect_message(self, message: discord.Message, *, skip_spam: bool = False) -> None:
		"""Inspect a message and apply active automod rules in priority sequence."""
		if message.author.bot or message.webhook_id is not None or not message.guild:
			return
		if not isinstance(message.author, discord.Member):
			return
		if not isinstance(message.channel, (discord.abc.GuildChannel, discord.Thread)):
			return

		config = await self.get_config(message.guild.id)
		if not config.is_on:
			return

		if self.is_bypassed(message.author, message.channel, None, config):
			return

		content = message.content or ""
		rules = config.settings.get("rules", {})

		if config.is_feature_enabled("invite") and not self.is_bypassed(
			message.author, message.channel, "invite", config
		):
			allowlist = rules.get("invite", {}).get("allowlist", [])
			if self.check_invites(content, allowlist, message.guild):
				await self.handle_violation(message, "invite", config)
				return

		if config.is_feature_enabled("link") and not self.is_bypassed(message.author, message.channel, "link", config):
			allowlist = rules.get("link", {}).get("allowlist", [])
			if self.check_links(content, allowlist):
				await self.handle_violation(message, "link", config)
				return

		if config.is_feature_enabled("phrase") and not self.is_bypassed(
			message.author, message.channel, "phrase", config
		):
			phrases = rules.get("phrase", {}).get("phrases", [])
			if self.check_phrases(content, phrases):
				await self.handle_violation(message, "phrase", config)
				return

		if config.is_feature_enabled("mention") and not self.is_bypassed(
			message.author, message.channel, "mention", config
		):
			limit = int(rules.get("mention", {}).get("limit", 5))
			if self.check_mentions(message, limit):
				await self.handle_violation(message, "mention", config)
				return

		if config.is_feature_enabled("lines") and not self.is_bypassed(
			message.author, message.channel, "lines", config
		):
			limit = int(rules.get("lines", {}).get("limit", 15))
			if self.check_lines(content, limit):
				await self.handle_violation(message, "lines", config)
				return

		if (
			not skip_spam
			and config.is_feature_enabled("spam")
			and not self.is_bypassed(message.author, message.channel, "spam", config)
		):
			max_msgs = int(rules.get("spam", {}).get("max_messages", 5))
			window_sec = float(rules.get("spam", {}).get("window_seconds", 6.0))
			if self.check_spam(message.guild.id, message.author.id, max_msgs, window_sec):
				await self.handle_violation(message, "spam", config)
				return

	@commands.Cog.listener()
	async def on_message(self, message: discord.Message) -> None:
		"""Process incoming messages through auto-moderation."""
		await self.inspect_message(message, skip_spam=False)

	@commands.Cog.listener()
	async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
		"""Process edited messages through auto-moderation."""
		if before.content == after.content:
			return
		await self.inspect_message(after, skip_spam=True)


async def setup(client: Bot) -> None:
	await client.add_cog(AutoMod(client))
