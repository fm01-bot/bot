from dataclasses import dataclass

import discord

from args.guild import Guild
from args.partial_emoji import PartialEmoji


@dataclass(slots=True)
class Emoji(PartialEmoji):
	managed: bool
	_roles: list[discord.Role]
	_guild: discord.Guild
	_is_application_owned: bool

	@classmethod
	def from_emoji(cls, emoji: discord.Emoji):
		return cls(
			_name=emoji.name,
			id=emoji.id,
			animated=emoji.animated,
			managed=emoji.managed,
			_created_at=emoji.created_at,
			_url=emoji.url,
			_roles=emoji.roles,
			_guild=emoji.guild,
			_is_application_owned=emoji.is_application_owned(),
			_is_unicode=False,
			display=f"<:{emoji.name}:{'a' if emoji.animated else ''}{emoji.id}>" if emoji.id else f":{emoji.name}:",
		)

	@property
	def name(self) -> str:
		return self._name

	@property
	def roles(self) -> bool:
		"""Returns whether or not this emoji is specific to a role or multiple or roles."""
		return len(self._roles) != 0

	__str__ = name

	@property
	def guild(self) -> Guild:
		return Guild.from_guild(self._guild)

	@property
	def is_application_owned(self) -> bool:
		"""Returns whether or not this emoji is only usable by a bot."""
		return self._is_application_owned

	application_owned = bot_owned = is_application_owned
