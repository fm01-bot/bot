import datetime
from dataclasses import dataclass
from typing import Optional

import discord
from helpers import seconds_to_text

from args.category import Category
from args.format_date_time import FormatDateTime
from args.guild import Guild


@dataclass(slots=True)
class TextChannel:
	name: str
	"""The channel's name."""
	_guild: discord.Guild
	id: int
	"""The channel's id."""
	topic: Optional[str]
	"""The channel's topic."""
	position: int
	"""The channel's position."""
	_slowmode_delay: int
	nsfw: bool
	"""The channel's nsfw status."""
	_default_auto_archive_duration: int
	_default_thread_slowmode_delay: int
	_members: list[discord.Member]
	_threads: list[discord.Thread]
	news: bool
	"""The channel's news status."""
	_category: discord.CategoryChannel | None
	_created_at: datetime.datetime
	_jump_url: str
	mention: str
	"""The channel's mention string."""
	_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]
	permissions_synced: bool
	"""Whether or not the permissions are synced to the parent category."""

	@classmethod
	def from_channel(cls, channel: discord.TextChannel):
		return cls(
			name=channel.name,
			_guild=channel.guild,
			id=channel.id,
			topic=channel.topic,
			position=channel.position,
			_slowmode_delay=channel.slowmode_delay,
			nsfw=channel.nsfw,
			_default_auto_archive_duration=channel.default_auto_archive_duration,
			_default_thread_slowmode_delay=channel.default_thread_slowmode_delay,
			_members=channel.members,
			_threads=channel.threads,
			news=channel.is_news(),
			_category=channel.category,
			_created_at=channel.created_at,
			_jump_url=channel.jump_url,
			mention=channel.mention,
			_overwrites=channel.overwrites,
			permissions_synced=channel.permissions_synced,
		)

	@property
	def guild(self) -> Guild:
		"""The channel's guild."""
		return Guild.from_guild(self._guild)

	@property
	def slowmode(self) -> str:
		"""The slowmode delay."""
		return seconds_to_text(self._slowmode_delay)

	slowmode_delay = slowmode

	@property
	def auto_archive(self) -> int:
		"""How long threads have to be inactive to be archived in minutes."""
		return self._default_auto_archive_duration

	@property
	def thread_slowmode(self) -> int:
		"""The channel's thread slowmode delay in minutes."""
		return self._slowmode_delay

	thread_slowmode_delay = thread_slowmode

	@property
	def members(self):
		"""How many members can see the channel."""
		return len(self._members)

	@property
	def threads(self):
		"""How many threads are in the channel."""
		return len(self._threads)

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
	def url(self) -> str:
		"""The channel's jump URL."""
		return self._jump_url

	jump_url = url

	@property
	def overwrites(self) -> int:
		"""The number of channel overwrites."""
		return len(self._overwrites)

	def __str__(self) -> str:
		return self.name
