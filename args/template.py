import datetime
from dataclasses import dataclass
from typing import Optional

import discord

from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.user import User


@dataclass(slots=True)
class Template:
	name: str
	_guild: discord.Guild
	_author: discord.User | None
	_created_at: datetime.datetime | None
	code: str
	roles: int
	channels: int
	uses: int
	description: Optional[str]
	_updated_at: Optional[datetime.datetime]
	_is_dirty: Optional[bool]
	url: Optional[str]

	@classmethod
	async def from_dict(cls, client: discord.Client, data: dict):
		return cls(
			name=data["name"],
			_guild=await client.fetch_guild(data["guild_id"]),
			_author=await client.fetch_user(data["author_id"]),
			_created_at=data["date"],
			code=data["code"],
			roles=len(data["payload"].get("roles", [])),
			channels=len(data["payload"].get("channels", [])),
			uses=0,
			description=None,
			_updated_at=None,
			_is_dirty=None,
			url=None,
		)

	@classmethod
	def from_template(cls, template: discord.Template):
		return cls(
			name=template.name,
			_guild=template.source_guild,
			_author=template.creator,
			_created_at=template.created_at,
			code=template.code,
			roles=0,
			channels=0,
			uses=template.uses,
			description=template.description,
			_updated_at=template.updated_at,
			_is_dirty=template.is_dirty,
			url=template.url,
		)

	@property
	def guild(self) -> Guild | None:
		return Guild.from_guild(self._guild) if self._guild else None

	@property
	def author(self) -> User | None:
		return User.from_user(self._author) if self._author else None

	@property
	def created_at(self) -> FormatDateTime | None:
		return FormatDateTime(self._created_at, "f") if self._created_at else None

	created = created_at

	@property
	def updated_at(self) -> Optional[FormatDateTime]:
		return FormatDateTime(self._updated_at, "f") if self._updated_at else None

	updated = updated_at

	@property
	def is_dirty(self) -> bool:
		return self._is_dirty if self._is_dirty else False

	unsynced = dirty = is_dirty
