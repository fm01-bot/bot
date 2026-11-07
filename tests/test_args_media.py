from __future__ import annotations

import datetime

from args.media import Media
from discord.ext.localization import CustomFormatter


def test_media_properties():
	now = datetime.datetime(2026, 11, 1, 12, 0, 0, tzinfo=datetime.UTC)
	media = Media.create(
		url="https://youtube.com/watch?v=12345",
		title="Amazing Video",
		author_name="Content Creator",
		author_url="https://youtube.com/@Creator",
		author_id="UC12345",
		author_avatar_url="https://example.com/avatar.png",
		media_id="12345",
		platform="youtube",
		thumbnail="https://example.com/thumb.png",
		description="Check out my video",
		published_at=now,
	)

	assert media.url == "https://youtube.com/watch?v=12345"
	assert media.title == "Amazing Video"
	assert str(media.author) == "Content Creator"
	assert media.author.name == "Content Creator"
	assert media.author.url == "https://youtube.com/@Creator"
	assert media.author.id == "UC12345"
	assert media.author.avatar_url == "https://example.com/avatar.png"
	assert media.id == "12345"
	assert media.platform == "youtube"
	assert media.thumbnail == "https://example.com/thumb.png"
	assert media.description == "Check out my video"
	assert str(media) == "Amazing Video"


def test_media_formatting_interpolation():
	formatter = CustomFormatter()
	media = Media.create(
		url="https://twitch.tv/streamer",
		title="Playing Cool Game",
		author_name="Streamer",
		author_url="https://twitch.tv/streamer",
		media_id="live_999",
		platform="twitch",
	)

	template = "{media.author} is live with {media.title}! Watch here: {media.url} (Channel: {media.author.url})"
	formatted = formatter.format(template, media=media)
	assert (
		formatted
		== "Streamer is live with Playing Cool Game! Watch here: https://twitch.tv/streamer (Channel: https://twitch.tv/streamer)"
	)

	name_template = "{media.author.name} went live: {media.url}"
	formatted_name = formatter.format(name_template, media=media)
	assert formatted_name == "Streamer went live: https://twitch.tv/streamer"
