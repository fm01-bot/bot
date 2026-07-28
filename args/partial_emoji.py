import datetime
from dataclasses import dataclass
from typing import Optional

import discord
from emoji import demojize

from args.format_date_time import FormatDateTime


@dataclass(slots=True)
class PartialEmoji:
	_name: str
	animated: bool
	id: Optional[int]
	_created_at: Optional[datetime.datetime]
	_url: Optional[str]
	_is_unicode: bool
	display: str

	@classmethod
	def from_emoji(cls, emoji: discord.PartialEmoji):
		return cls(
			_name=emoji.name,
			animated=emoji.animated,
			id=emoji.id,
			_created_at=emoji.created_at,
			_url=emoji.url,
			_is_unicode=emoji.is_unicode_emoji(),
			display=str(emoji),
		)

	@property
	def name(self) -> str:
		"""The name of the emoji."""
		if self._is_unicode:
			name = demojize(self._name)
			return name.strip(":")
		return self._name

	def __str__(self) -> str:
		return self.display

	@property
	def created_at(self):
		"""The creation date of the emoji."""
		return FormatDateTime(self._created_at, "f") if self._created_at else None

	created = created_at

	@property
	def url(self) -> str | None:
		"""The URL of the emoji, if it is a default (unicode) emoji."""
		codepoints = "-".join(f"{ord(code):x}" for code in self._name)
		return None if self._url is None else f"https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoints}.png"
