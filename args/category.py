import datetime
from dataclasses import dataclass

import discord

from args.format_date_time import FormatDateTime
from args.guild import Guild


@dataclass(slots=True)
class Category:
	name: str
	"""The category's name."""
	_guild: discord.Guild
	id: int
	"""The category's ID."""
	position: int
	"""The category's position."""
	nsfw: bool
	"""The category's nsfw status."""
	_channels: list[discord.VoiceChannel | discord.StageChannel | discord.ForumChannel | discord.TextChannel | discord.CategoryChannel]
	_text_channels: list[discord.TextChannel]
	_voice_channels: list[discord.VoiceChannel]
	_stage_channels: list[discord.StageChannel]
	_forums: list[discord.ForumChannel]
	_created_at: datetime.datetime
	_jump_url: str
	mention: str
	"""The category's mention string."""
	_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite]
	permissions_synced: bool
	"""Whether or not the permissions are synced to the parent category."""

	@classmethod
	def from_category(cls, category: discord.CategoryChannel):
		return cls(
			name=category.name,
			_guild=category.guild,
			id=category.id,
			position=category.position,
			nsfw=category.nsfw,
			_channels=category.channels,
			_text_channels=category.text_channels,
			_voice_channels=category.voice_channels,
			_stage_channels=category.stage_channels,
			_forums=category.forums,
			_created_at=category.created_at,
			_jump_url=category.jump_url,
			mention=category.mention,
			_overwrites=category.overwrites,
			permissions_synced=category.permissions_synced,
		)

	@property
	def guild(self) -> Guild:
		"""The category's guild."""
		return Guild.from_guild(self._guild)

	@property
	def channels(self) -> int:
		"""The number of channels in the category."""
		return len(self._channels)

	@property
	def text_channels(self) -> int:
		"""The number of text channels in the category."""
		return len(self._text_channels)

	@property
	def voice_channels(self) -> int:
		"""The number of voice channels in the category."""
		return len(self._voice_channels)

	@property
	def stage_channels(self) -> int:
		"""The number of stage channels in the category."""
		return len(self._stage_channels)

	@property
	def forums(self) -> int:
		"""The number of forums in the category."""
		return len(self._forums)

	@property
	def created_at(self) -> FormatDateTime:
		"""The category's creation date."""
		return FormatDateTime(self._created_at, "f")

	created = created_at

	@property
	def jump_url(self) -> str:
		"""The category's jump URL."""
		return self._jump_url

	url = jump_url

	@property
	def overwrites(self) -> int:
		"""The number of overwrites in the category."""
		return len(self._overwrites)

	def __str__(self) -> str:
		return self.name
