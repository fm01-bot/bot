import datetime
from dataclasses import dataclass
from typing import Optional, Sequence

import discord

from args.category import Category
from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.partial_emoji import PartialEmoji


@dataclass(slots=True)
class ForumChannel:
	name: str
	"""The forum channel's name."""
	_guild: discord.Guild
	id: int
	"""The forum channel's ID."""
	topic: str
	"""The forum channel's topic."""
	position: int
	"""The forum channel's position."""
	_slowmode_delay: int
	nsfw: bool
	"""The forum channel's nsfw status."""
	_default_auto_archive_duration: int
	_default_thread_slowmode_delay: int
	_default_reaction_emoji: Optional[discord.PartialEmoji]
	_members: list[discord.Member]
	_threads: list[discord.Thread]
	_available_tags: Sequence[discord.ForumTag]
	media: bool
	"""Whether or not the channel is a media channel."""
	_category: Optional[discord.CategoryChannel]
	_created_at: datetime.datetime
	_jump_url: str
	mention: str
	"""A string to mention the channel."""
	_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]
	permissions_synced: bool
	"""Whether or not the permissions are synced to the parent category."""

	@classmethod
	def from_channel(cls, channel: discord.ForumChannel):
		return cls(
			name=channel.name,
			_guild=channel.guild,
			id=channel.id,
			topic=channel.topic or "",
			position=channel.position,
			_slowmode_delay=channel.slowmode_delay,
			nsfw=channel.nsfw,
			_default_auto_archive_duration=channel.default_auto_archive_duration,
			_default_thread_slowmode_delay=channel.default_thread_slowmode_delay,
			_default_reaction_emoji=channel.default_reaction_emoji,
			_members=channel.members,
			_threads=channel.threads,
			_available_tags=channel.available_tags,
			media=channel.is_media(),
			_category=channel.category,
			_created_at=channel.created_at,
			_jump_url=channel.jump_url,
			mention=channel.mention,
			_overwrites=channel.overwrites,
			permissions_synced=channel.permissions_synced,
		)

	@property
	def guild(self) -> Guild:
		return Guild.from_guild(self._guild)

	@property
	def slowmode_delay(self) -> int:
		"""The channel's slowmode delay in seconds."""
		return self._slowmode_delay

	slowmode = slowmode_delay

	@property
	def default_auto_archive_duration(self) -> int:
		"""The channel's default auto-archive duration in seconds."""
		return self._default_auto_archive_duration

	auto_archive_duration = auto_archive = default_auto_archive_duration

	@property
	def default_thread_slowmode_delay(self) -> int:
		"""The channel's default thread slowmode delay in seconds."""
		return self._default_thread_slowmode_delay

	thread_slowmode = default_thread_slowmode_delay

	@property
	def default_reaction_emoji(self) -> Optional[PartialEmoji]:
		return PartialEmoji.from_emoji(self._default_reaction_emoji) if self._default_reaction_emoji else None

	@property
	def members(self) -> int:
		"""The number of members that can see this channel."""
		return len(self._members)

	@property
	def threads(self) -> int:
		"""The number of threads (forum posts) in the channel."""
		return len(self._threads)

	@property
	def available_tags(self) -> int:
		"""The number of available tags."""
		return len(self._available_tags)

	tags = available_tags

	@property
	def category(self) -> Optional[Category]:
		"""The channel's category."""
		return Category.from_category(self._category) if self._category else None

	@property
	def created_at(self) -> FormatDateTime:
		"""The channel's creation date."""
		return FormatDateTime(self._created_at, "f")

	created = created_at

	@property
	def jump_url(self) -> str:
		"""The channel's URL."""
		return self._jump_url

	url = jump_url

	@property
	def overwrites(self) -> int:
		"""The number of channel overwrites."""
		return len(self._overwrites)

	def __str__(self) -> str:
		return self.name
