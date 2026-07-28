import datetime
from dataclasses import dataclass
from typing import Optional

import discord

from args.category import Category
from args.format_date_time import FormatDateTime
from args.guild import Guild


@dataclass(slots=True)
class StageChannel:
	name: str
	"""The stage channel's name."""
	_guild: discord.Guild
	id: int
	nsfw: bool
	"""The stage channel's nsfw status."""
	topic: Optional[str]
	"""The stage channel's topic."""
	position: int
	"""The stage channel's position."""
	_bitrate: int
	user_limit: int
	"""The stage channel's user limit."""
	_rtc_region: str | None
	"""The stage channel's RTC region. None when automatically determined."""
	_slowmode_delay: int
	_requesting_to_speak: list[discord.Member]
	_speakers: list[discord.Member]
	_listeners: list[discord.Member]
	_moderators: list[discord.Member]
	_category: Optional[discord.CategoryChannel]
	_created_at: datetime.datetime
	_jump_url: str
	_members: list[discord.Member]
	mention: str
	"""The stage channel's mention string."""
	_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]
	permissions_synced: bool
	"""Whether or not the permissions are synced to the parent category."""
	_scheduled_events: list[discord.ScheduledEvent]

	@classmethod
	def from_channel(cls, channel: discord.StageChannel):
		return cls(
			name=channel.name,
			_guild=channel.guild,
			id=channel.id,
			nsfw=channel.nsfw,
			topic=channel.topic,
			position=channel.position,
			_bitrate=channel.bitrate,
			user_limit=channel.user_limit,
			_rtc_region=channel.rtc_region,
			_slowmode_delay=channel.slowmode_delay,
			_requesting_to_speak=channel.requesting_to_speak,
			_speakers=channel.speakers,
			_listeners=channel.listeners,
			_moderators=channel.moderators,
			_category=channel.category,
			_created_at=channel.created_at,
			_jump_url=channel.jump_url,
			_members=channel.members,
			mention=channel.mention,
			_overwrites=channel.overwrites,
			permissions_synced=channel.permissions_synced,
			_scheduled_events=channel.scheduled_events,
		)

	@property
	def guild(self) -> Guild:
		"""The stage channel's guild."""
		return Guild.from_guild(self._guild)

	@property
	def bitrate(self) -> int:
		"""The stage channel's bitrate in kbps."""
		return int(self._bitrate / 1000)

	@property
	def rtc_region(self) -> str | None:
		"""The stage channel's RTC region."""
		return self._rtc_region

	region = rtc_region

	@property
	def slowmode_delay(self) -> int:
		"""The channel's slowmode delay in seconds."""
		return self._slowmode_delay

	slowmode = slowmode_delay

	@property
	def requesting_to_speak(self) -> int:
		"""The number of requesting speakers."""
		return len(self._requesting_to_speak)

	@property
	def speakers(self) -> int:
		"""The number of speakers."""
		return len(self._speakers)

	@property
	def listeners(self) -> int:
		return len(self._listeners)

	@property
	def moderators(self) -> int:
		"""The number of moderators."""
		return len(self._moderators)

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
		"""The channel's jump URL."""
		return self._jump_url

	url = jump_url

	@property
	def members(self) -> int:
		"""The number of members that can see this channel."""
		return len(self._members)

	@property
	def overwrites(self) -> int:
		"""The number of channel overwrites."""
		return len(self._overwrites)

	@property
	def scheduled_events(self) -> int:
		"""The number of scheduled events in the channel."""
		return len(self._scheduled_events)

	events = scheduled_events

	def __str__(self) -> str:
		return self.name
