import datetime
from dataclasses import dataclass, field
from typing import Optional, Union

import discord

from args.color import Color
from args.format_date_time import FormatDateTime


@dataclass(slots=True)
class User:
	_name: str = field(repr=False)
	id: int
	"""The user's ID."""
	_discriminator: str | None = field(repr=False)
	global_name: str = field(repr=False)
	"""The user's global display name. The hierarchy is as follows:

	1. ``name#discriminator`` if the user has a discriminator (only bots).
	2. ``global_name`` if the user has a global name.
	3. ``name`` if the user has neither a discriminator nor a global name."""
	display_name: str = field(repr=False)
	"""The user's display name. This is the name that is shown in the server if they are a member.
	Otherwise, it is the same as ``global_name``."""
	bot: bool
	"""Whether or not the user is a Discord bot."""
	_color: Optional[Color] = field(repr=False)
	_avatar: str = field(repr=False)
	_decoration: Optional[str] = field(repr=False)
	_banner: Optional[str] = field(repr=False)
	_created_at: datetime.datetime = field(repr=False)
	mention: str
	"""A string that mentions the user."""

	@classmethod
	def from_user(cls, user: Union[discord.User, discord.Member]):
		"""Creates a ``CustomUser`` from a ``discord.User`` or a ``discord.Member`` object."""
		return cls(
			_name=f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name,
			id=user.id,
			_discriminator=user.discriminator if user.discriminator != "0" else None,
			global_name=user.global_name or user.name,
			display_name=user.display_name,
			bot=user.bot,
			_color=Color(user.accent_color),
			_avatar=user.display_avatar.url,
			_decoration=user.avatar_decoration.url if user.avatar_decoration else "",
			_banner=user.banner.url if user.banner else Color(user.accent_color).image,
			_created_at=user.created_at,
			mention=user.mention,
		)

	@property
	def name(self) -> str:
		"""The username of the user."""
		return self._name

	user_name = user = username = name

	@property
	def discriminator(self) -> str | None:
		"""The discriminator of the user. This is a legacy concept that only applies to bots."""
		return self._discriminator

	tag = discriminator

	@property
	def color(self) -> Color | None:
		"""The user's accent color."""
		return self._color

	colour = color

	@property
	def avatar(self) -> str:
		"""The user's avatar URL."""
		return self._avatar

	icon = avatar

	@property
	def created_at(self):
		"""The date the user was created as a Discord timestamp."""
		return FormatDateTime(self._created_at, "F")

	created = created_at

	def __str__(self):
		return self.global_name

	def __int__(self):
		return self.id
