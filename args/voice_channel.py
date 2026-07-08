import datetime
from dataclasses import dataclass
from typing import Optional

import discord

from args.category import Category
from args.format_date_time import FormatDateTime
from args.guild import Guild


@dataclass(slots=True)
class VoiceChannel:
	name: str
	"""Returns the channel's name."""
	_guild: discord.Guild
	id: int
	"""Returns the channel's id."""
	nsfw: bool
	"""Returns the channel's nsfw status."""
	position: int
	"""Returns the channel's position."""
	bitrate: int
	"""Returns the channel's bitrate."""
	user_limit: int
	"""Returns the channel's user limit."""
	_rtc_region: Optional[str]
	_slowmode_delay: int
	_category: Optional[discord.CategoryChannel]
	_created_at: datetime.datetime
	_jump_url: str
	mention: str
	"""Returns the channel's mention string."""
	_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]
	permissions_synced: bool
	"""Returns whether or not the permissions are synced to the parent category."""
	_scheduled_events: list[discord.ScheduledEvent]

	@classmethod
	def from_channel(cls, channel: discord.VoiceChannel):
		return cls(
			name=channel.name,
			_guild=channel.guild,
			id=channel.id,
			nsfw=channel.nsfw,
			position=channel.position,
			bitrate=int(channel.bitrate / 1000),
			user_limit=channel.user_limit,
			_rtc_region=channel.rtc_region,
			_slowmode_delay=channel.slowmode_delay,
			_category=channel.category,
			_created_at=channel.created_at,
			_jump_url=channel.jump_url,
			mention=channel.mention,
			_overwrites=channel.overwrites,
			permissions_synced=channel.permissions_synced,
			_scheduled_events=channel.scheduled_events,
		)

	@property
	def guild(self):
		"""Returns the channel's guild."""
		return Guild.from_guild(self._guild)

	@property
	def rtc_region(self):
		"""Returns the channel's RTC region."""
		return self._rtc_region

	region = rtc_region

	@property
	def slowmode_delay(self) -> int:
		"""Returns the channel's slowmode delay in seconds."""
		return self._slowmode_delay

	slowmode = slowmode_delay

	@property
	def category(self) -> Optional[Category]:
		"""Returns the channel's category."""
		return Category.from_category(self._category) if self._category else None

	@property
	def created_at(self) -> FormatDateTime:
		"""Returns the channel's creation date."""
		return FormatDateTime(self._created_at, "f")

	created = created_at

	@property
	def jump_url(self) -> str:
		"""Returns the channel's jump URL."""
		return self._jump_url

	url = jump_url

	@property
	def overwrites(self) -> int:
		"""Returns the number of channel overwrites."""
		return len(self._overwrites)

	@property
	def scheduled_events(self) -> int:
		"""Returns the number of scheduled events in the channel."""
		return len(self._scheduled_events)

	def __str__(self) -> str:
		return self.name
