import datetime
from dataclasses import dataclass, field
from typing import Optional

import discord

from args.color import Color
from args.format_date_time import FormatDateTime
from args.user import User


@dataclass(slots=True)
class Member(User):
	_nickname: Optional[str] = field(repr=False)
	_color: Optional[Color] = field(repr=False)
	_accent_color: Optional[Color] = field(repr=False)
	_joined_at: datetime.datetime = field(repr=False)
	_roles: list[discord.Role] = field(repr=False)

	@classmethod
	def from_member(cls, member: discord.Member):
		return cls(
			_name=f"{member.name}#{member.discriminator}" if member.discriminator != "0" else member.name,
			id=member.id,
			_discriminator=member.discriminator if member.discriminator != "0" else None,
			global_name=member.global_name,
			display_name=member.display_name,
			_nickname=member.nick,
			bot=member.bot,
			_color=Color(member.color),
			_accent_color=Color(member.accent_color),
			_avatar=member.display_avatar.url,
			_decoration=member.avatar_decoration.url if member.avatar_decoration else None,
			_banner=member.avatar_decoration.url if member.banner else None,
			_created_at=member.created_at,
			_joined_at=member.joined_at,
			_roles=member.roles,
			mention=member.mention,
		)

	@property
	def nickname(self) -> str:
		"""Returns the nickname of the member."""
		return self._nickname

	nick = nickname

	@property
	def color(self) -> Color:
		"""Returns the member's chat display color, aka. the color of their top role."""
		return self._color

	@property
	def joined_at(self):
		"""Returns the date the member joined the server as a Discord timestamp."""
		return FormatDateTime(self._joined_at, "F")

	joined = joined_at

	@property
	def roles(self) -> Optional[str]:
		"""Returns the roles the user has (excluding @everyone)."""
		self._roles.pop(0)
		roles_string = ", ".join([role.mention for role in self._roles])
		if len(roles_string) > 512:
			return None
		return roles_string

	@property
	def roles_reverse(self) -> Optional[str]:
		self._roles.pop(0)
		roles_string = ", ".join([role.mention for role in reversed(self._roles)])
		if len(roles_string) > 512:
			return None
		return roles_string

	def __str__(self):
		return self.display_name or self.name
