from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from helpers.alert_providers import (
	InstagramProvider,
	TikTokProvider,
	TwitchProvider,
	YouTubeProvider,
	get_provider,
)

YOUTUBE_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
  <link rel="self" href="http://www.youtube.com/feeds/videos.xml?channel_id=UC1234567890abcdefghijk"/>
  <id>yt:channel:UC1234567890abcdefghijk</id>
  <yt:channelId>UC1234567890abcdefghijk</yt:channelId>
  <title>Cool Channel</title>
  <author>
    <name>Cool Channel</name>
    <uri>https://www.youtube.com/channel/UC1234567890abcdefghijk</uri>
  </author>
  <published>2026-10-01T00:00:00+00:00</published>
  <entry>
    <id>yt:video:dQw4w9WgXcQ</id>
    <yt:videoId>dQw4w9WgXcQ</yt:videoId>
    <yt:channelId>UC1234567890abcdefghijk</yt:channelId>
    <title>Never Gonna Give You Up</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"/>
    <author>
      <name>Cool Channel</name>
      <uri>https://www.youtube.com/channel/UC1234567890abcdefghijk</uri>
    </author>
    <published>2026-11-01T14:00:00+00:00</published>
    <updated>2026-11-01T14:05:00+00:00</updated>
    <media:group>
      <media:title>Never Gonna Give You Up</media:title>
      <media:description>Music video description</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg" width="480" height="360"/>
    </media:group>
  </entry>
</feed>
"""

RSS_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Popular Creator</title>
    <link>https://www.tiktok.com/@creator</link>
    <description>TikTok posts by creator</description>
    <item>
      <title>Funny Dance Video</title>
      <link>https://www.tiktok.com/@creator/video/987654321</link>
      <guid>https://www.tiktok.com/@creator/video/987654321</guid>
      <pubDate>2026-11-01T12:00:00+00:00</pubDate>
      <description>Check this out #fyp</description>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_youtube_provider_fetch_latest():
	provider = YouTubeProvider()
	session = MagicMock()
	resp = MagicMock()
	resp.status = 200
	resp.text = AsyncMock(return_value=YOUTUBE_SAMPLE_FEED)

	# Mock async context manager for session.get
	session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
	session.get.return_value.__aexit__ = AsyncMock(return_value=None)

	media = await provider.fetch_latest(session, "UC1234567890abcdefghijk", "Cool Channel")
	assert media is not None
	assert media.id == "dQw4w9WgXcQ"
	assert media.title == "Never Gonna Give You Up"
	assert media.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
	assert media.author.name == "Cool Channel"
	assert media.author.url == "https://www.youtube.com/channel/UC1234567890abcdefghijk"
	assert media.thumbnail == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
	assert media.description == "Music video description"
	assert media.platform == "youtube"


@pytest.mark.asyncio
async def test_youtube_provider_resolve_channel_handle():
	provider = YouTubeProvider()
	session = MagicMock()
	resp = MagicMock()
	resp.status = 200
	html_content = """
	<html>
	  <head>
	    <meta property="og:title" content="Rick Astley Official">
	    <meta itemprop="identifier" content="UCuAXFkgsw1L7xaCfnd5JJOw">
	  </head>
	</html>
	"""
	resp.text = AsyncMock(return_value=html_content)
	session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
	session.get.return_value.__aexit__ = AsyncMock(return_value=None)

	cid, title = await provider.resolve_channel(session, "@RickAstleyYT")
	assert cid == "UCuAXFkgsw1L7xaCfnd5JJOw"
	assert title == "Rick Astley Official"


@pytest.mark.asyncio
async def test_twitch_provider_fetch_live_stream():
	provider = TwitchProvider()
	provider._access_token = "mock_token"
	provider._token_expires_at = datetime.datetime.now(datetime.UTC).timestamp() + 3600

	bot = MagicMock()
	bot.config.twitch_client_id = "mock_client_id"
	bot.config.twitch_client_secret = "mock_client_secret"

	session = MagicMock()
	resp = MagicMock()
	resp.status = 200
	resp.json = AsyncMock(
		return_value={
			"data": [
				{
					"id": "41234567890",
					"user_id": "123456",
					"user_login": "ninja",
					"user_name": "Ninja",
					"game_name": "Fortnite",
					"title": "Chasing Victory Royales!",
					"thumbnail_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_ninja-{width}x{height}.jpg",
					"started_at": "2026-11-01T13:30:00Z",
				}
			]
		}
	)

	session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
	session.get.return_value.__aexit__ = AsyncMock(return_value=None)

	media = await provider.fetch_latest(session, "ninja", bot=bot)
	assert media is not None
	assert media.id == "stream_41234567890"
	assert "Ninja" in media.author.name
	assert "Chasing Victory Royales!" in media.title
	assert "[Fortnite]" in media.title
	assert media.url == "https://twitch.tv/ninja"
	assert media.platform == "twitch"
	assert "1280x720" in media.thumbnail


@pytest.mark.asyncio
async def test_twitch_provider_stream_offline():
	provider = TwitchProvider()
	provider._access_token = "mock_token"
	provider._token_expires_at = datetime.datetime.now(datetime.UTC).timestamp() + 3600

	bot = MagicMock()
	bot.config.twitch_client_id = "mock_client_id"
	bot.config.twitch_client_secret = "mock_client_secret"

	session = MagicMock()
	resp = MagicMock()
	resp.status = 200
	resp.json = AsyncMock(return_value={"data": []})

	session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
	session.get.return_value.__aexit__ = AsyncMock(return_value=None)

	media = await provider.fetch_latest(session, "ninja", bot=bot)
	assert media is None


@pytest.mark.asyncio
async def test_generic_rss_provider_tiktok_and_instagram():
	tiktok = TikTokProvider()
	assert tiktok.platform == "tiktok"
	instagram = InstagramProvider()
	assert instagram.platform == "instagram"

	session = MagicMock()
	resp = MagicMock()
	resp.status = 200
	resp.text = AsyncMock(return_value=RSS_SAMPLE_FEED)

	session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
	session.get.return_value.__aexit__ = AsyncMock(return_value=None)

	media = await tiktok.fetch_latest(session, "creator")
	assert media is not None
	assert media.id == "https://www.tiktok.com/@creator/video/987654321"
	assert media.title == "Funny Dance Video"
	assert media.author.name == "Popular Creator"
	assert media.author.url == "https://www.{self.platform}.com/@creator".replace("{self.platform}", "tiktok")
	assert media.platform == "tiktok"


def test_get_provider_registry():
	assert isinstance(get_provider("youtube"), YouTubeProvider)
	assert isinstance(get_provider("YOUTUBE"), YouTubeProvider)
	assert isinstance(get_provider("twitch"), TwitchProvider)
	assert isinstance(get_provider("tiktok"), TikTokProvider)
	assert isinstance(get_provider("instagram"), InstagramProvider)
	assert get_provider("unknown_platform") is None
