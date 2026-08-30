from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

import discord

from args.color import Color
from args.format_date_time import FormatDateTime

if TYPE_CHECKING:
	from args._emoji import Emoji


@dataclass(slots=True)
class Role:
	name: str
	"""The role's name."""
	id: int
	"""The role's ID."""
	hoist: bool
	"""Whether or not the role is hoisted (aka. shown seperately from other members)."""
	position: int
	"""The role's position in the hierarchy."""
	managed: bool
	"""Whether or not the role is managed by an integration, such as Twitch or Patreon."""
	mentionable: bool
	"""Whether or not the role is mentionable by everyone."""
	_default: bool = field(repr=False)
	_bot: bool = field(repr=False)
	_boost: bool = field(repr=False)
	_integration: bool = field(repr=False)
	_assignable: bool = field(repr=False)
	_color: Optional[Color] = field(repr=False)
	icon: str | None = field(repr=False)
	"""The role's icon URL, or an emoji, if the role has one. This is only available for guilds that are
	boosted to at least level 2."""
	_created_at: datetime.datetime = field(repr=False)
	mention: str
	"""A string that mentions the role."""
	_members: list[discord.Member] = field(repr=False)
	_purchaseable: bool = field(repr=False)
	_permissions: discord.Permissions = field(repr=False)

	@classmethod
	def from_role(cls, role: discord.Role):
		if isinstance(role.display_icon, discord.Asset):
			icon = role.display_icon.url
		elif isinstance(role.display_icon, discord.Emoji):
			from args._emoji import Emoji

			icon = Emoji.from_emoji(role.display_icon).display
		else:
			icon = None

		return cls(
			name=role.name,
			id=role.id,
			hoist=role.hoist,
			position=role.position,
			managed=role.managed,
			mentionable=role.mentionable,
			_default=role.is_default(),
			_bot=role.is_bot_managed(),
			_boost=role.is_premium_subscriber(),
			_integration=role.is_integration(),
			_assignable=role.is_assignable(),
			_color=Color(role.color),
			icon=icon,
			_created_at=role.created_at,
			mention=role.mention,
			_members=role.members,
			_purchaseable=role.tags.is_available_for_purchase() if role.tags else False,
			_permissions=role.permissions,
		)

	@property
	def members(self) -> int:
		return len(self._members)

	@property
	def everyone(self) -> bool:
		"""Whether or not the role is the everyone role."""
		return self._default

	default = is_default = everyone

	@property
	def bot(self) -> bool:
		"""Whether or not the role is managed by a bot."""
		return self._bot

	is_bot = is_bot_managed = bot

	@property
	def boost(self) -> bool:
		"""Whether or not the role is a boost role."""
		return self._boost

	is_boost = is_premium_subscriber = boost

	@property
	def integration(self) -> bool:
		"""Whether or not the role is managed by an integration."""
		return self._integration

	is_integration_managed = integration_managed = is_integration = integration

	@property
	def assignable(self) -> bool:
		"""Whether or not the role is assignable by the bot itself."""
		return self._assignable

	allowed = is_assignable = assignable

	@property
	def purchaseable(self) -> bool:
		"""Whether or not the role is purchaseable."""
		return self._purchaseable

	buy = buyable = is_buyable = purchase = is_purchaseable = purchaseable

	@property
	def color(self) -> Color | None:
		"""The role's color."""
		return Color(self._color) if self._color else None  # type: ignore

	colour = color

	@property
	def created_at(self):
		"""The date the role was created as a Discord timestamp."""
		return FormatDateTime(self._created_at, "F")

	created = created_at

	@property
	def permissions(self):
		"""The role's permissions."""
		return ", ".join([str(perm[0]).upper() for perm in self._permissions if perm[1]])[:1024]

	def __str__(self):
		return self.name

	def __int__(self):
		return self.id

	# TODO: we need to add permissions somehow... no idea how, though
