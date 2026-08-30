from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from args.partial_emoji import PartialEmoji

if TYPE_CHECKING:
	from args.guild import Guild


@dataclass(slots=True)
class Emoji(PartialEmoji):
	managed: bool
	"""Whether or not the emoji is managed by an authorized application."""
	guild: Guild | None
	"""The guild the emoji belongs to."""
	_is_application_owned: bool
	roles: bool
	"""Whether or not the emoji is specific to a role or multiple roles."""

	@classmethod
	def from_emoji(cls, emoji: discord.Emoji):  # type: ignore
		if emoji.guild:
			from args.guild import Guild

			guild = Guild.from_guild(emoji.guild)
		else:
			guild = None

		return cls(
			_name=emoji.name,
			id=emoji.id,
			animated=emoji.animated,
			managed=emoji.managed,
			_created_at=emoji.created_at,
			_url=emoji.url,
			roles=len(emoji.roles) != 0,
			guild=guild,
			_is_application_owned=emoji.is_application_owned(),
			_is_unicode=False,
			display=f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>" if emoji.id else f":{emoji.name}:",
		)

	@property
	def name(self) -> str:
		"""The name of the emoji."""
		return self._name

	__str__ = name

	@property
	def is_application_owned(self) -> bool:
		"""Whether or not this emoji is only usable by a bot."""
		return self._is_application_owned

	application_owned = bot_owned = is_application_owned
