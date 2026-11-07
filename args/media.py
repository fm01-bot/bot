from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Self

from args.format_date_time import FormatDateTime


@dataclass(slots=True)
class MediaAuthor:
	"""Dataclass representing the author/creator of a media upload."""

	_name: str = field(repr=False)
	_url: str = field(repr=False)
	_id: str | None = field(default=None, repr=False)
	_avatar_url: str | None = field(default=None, repr=False)

	@property
	def name(self) -> str:
		"""The display name or username of the creator."""
		return self._name

	author = author_name = username = name

	@property
	def url(self) -> str:
		"""The profile or channel URL of the creator."""
		return self._url

	link = uri = profile_url = url

	@property
	def id(self) -> str:
		"""The platform identifier of the creator."""
		return self._id or ""

	@property
	def avatar_url(self) -> str:
		"""The avatar or profile image URL of the creator."""
		return self._avatar_url or ""

	avatar = icon_url = avatar_url

	def __str__(self) -> str:
		return self._name


@dataclass(slots=True)
class Media:
	"""Dataclass representing an upload or stream event for formatting."""

	_url: str = field(repr=False)
	_title: str = field(repr=False)
	_author: MediaAuthor = field(repr=False)
	_id: str = field(repr=False)
	_platform: str = field(repr=False)
	_thumbnail: str | None = field(default=None, repr=False)
	_description: str | None = field(default=None, repr=False)
	_published_at: datetime.datetime | None = field(default=None, repr=False)

	@classmethod
	def create(
		cls,
		*,
		url: str,
		title: str,
		author_name: str,
		author_url: str,
		author_id: str | None = None,
		author_avatar_url: str | None = None,
		media_id: str,
		platform: str,
		thumbnail: str | None = None,
		description: str | None = None,
		published_at: datetime.datetime | None = None,
	) -> Self:
		"""Convenience constructor from primitive values."""
		author = MediaAuthor(
			_name=author_name,
			_url=author_url,
			_id=author_id,
			_avatar_url=author_avatar_url,
		)
		return cls(
			_url=url,
			_title=title,
			_author=author,
			_id=media_id,
			_platform=platform.lower(),
			_thumbnail=thumbnail,
			_description=description,
			_published_at=published_at,
		)

	@property
	def url(self) -> str:
		"""The URL of the upload or stream."""
		return self._url

	link = uri = url

	@property
	def title(self) -> str:
		"""The title of the video, stream, or post."""
		return self._title

	@property
	def author(self) -> MediaAuthor:
		"""The creator/author of the media."""
		return self._author

	creator = uploader = author

	@property
	def id(self) -> str:
		"""The platform identifier of the video, stream, or post."""
		return self._id

	video_id = stream_id = post_id = id

	@property
	def platform(self) -> str:
		"""The name of the platform (e.g. youtube, twitch, tiktok, instagram)."""
		return self._platform

	source = platform

	@property
	def thumbnail(self) -> str:
		"""The thumbnail or preview image URL."""
		return self._thumbnail or ""

	image = artwork = preview = thumbnail

	@property
	def description(self) -> str:
		"""The description or caption of the media."""
		return self._description or ""

	caption = summary = description

	@property
	def published_at(self) -> FormatDateTime | str:
		"""The publication or live start timestamp."""
		if self._published_at:
			return FormatDateTime(self._published_at, default_style="F")
		return ""

	timestamp = published_at

	def __str__(self) -> str:
		return self._title
