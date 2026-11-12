"""The Case module: moderation cases, their lifecycle, and their expiry.

Commands talk to `CaseStore`. It owns every query against ``cases``, turns rows into the right `Case` subclass,
applies the guild's retention policy when a case is closed, and keeps the expiry schedule in step with the table.
The `Case` subclasses only carry data and the Discord side effects of opening and closing a case.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol

import asyncpg
import discord
from args import FormatDateTime, Guild, Member, User
from discord.utils import MISSING
from helpers import custom_response
from helpers.scheduler import ExpiryScheduler

if TYPE_CHECKING:
	from core import Bot

__all__ = (
	"Ban",
	"Case",
	"CaseExpirationManager",
	"CaseStatus",
	"CaseStore",
	"CaseType",
	"CloseOutcome",
	"Kick",
	"Mute",
	"Retention",
	"RetentionCache",
	"Warn",
)

logger = logging.getLogger(__name__)

type Retention = Literal["keep", "delete"]
type RetentionLookup = Callable[[int], Awaitable[Retention]]
type CaseStatus = Literal["active", "expired", "all"]
type CloseOutcome = Literal["deleted", "deactivated"]


class CaseType(Enum):
	WARN = 1
	MUTE = 2
	KICK = 3
	BAN = 4


class Case:
	"""A moderation case. Subclasses override the hooks to perform the case's Discord side effects."""

	def __init__(
		self,
		_type: CaseType,
		_id: int,
		bot: Bot,
		guild: discord.Guild,
		user: discord.Member | discord.User,
		moderator: discord.User | discord.Member,
		created: datetime.datetime = MISSING,
		reason: str | None = None,
		expires: datetime.datetime | None = None,
		message: str | None = None,
		active: bool = True,
	):
		if created is MISSING or not created:
			created = datetime.datetime.now(tz=datetime.UTC)
		elif created.tzinfo is None:
			created = created.replace(tzinfo=datetime.UTC)
		if expires and expires.tzinfo is None:
			expires = expires.replace(tzinfo=datetime.UTC)
		self.bot: Bot = bot
		self.type: CaseType = _type
		self.id: int = _id
		self._guild: discord.Guild = guild
		self._user: discord.Member | discord.User = user
		self.reason: str | None = reason
		self._moderator: discord.User | discord.Member = moderator
		self.expires: datetime.datetime | None = expires
		self.message: str | None = message
		self.active: bool = active
		self._created: datetime.datetime = created

	def __repr__(self) -> str:
		return (
			f"{type(self).__name__}(id={self.id} user={self._user} reason={self.reason} moderator={self._moderator} "
			f"expires={self.expires} message={self.message} active={self.active})"
		)

	def __eq__(self, other: object) -> bool:
		return isinstance(other, Case) and self.id == other.id

	def __hash__(self) -> int:
		return hash(self.id)

	def __int__(self) -> int:
		return self.id

	@property
	def length(self) -> str | None:
		"""The expiry as a relative Discord timestamp, if the case expires."""
		return discord.utils.format_dt(self.expires, "R") if self.expires else None

	@property
	def status(self) -> str:
		"""Returns the status text: 'Active', 'Expired', or 'Inactive'."""
		if not self.active:
			return "Inactive"
		if self.expires and self.expires <= datetime.datetime.now(tz=datetime.UTC):
			return "Expired"
		return "Active"

	@property
	def created(self) -> FormatDateTime:
		"""The creation date of the case."""
		return FormatDateTime(self._created, "R")

	@property
	def guild(self) -> Guild:
		return Guild.from_guild(self._guild)

	@property
	def user(self) -> User:
		return User.from_user(self._user) if isinstance(self._user, discord.User) else Member.from_member(self._user)

	@property
	def moderator(self) -> User:
		return User.from_user(self._moderator)

	@staticmethod
	def generate_id(message: discord.Message) -> int:
		"""Generate a case ID from a message."""
		return message.id

	async def before_creation(self) -> None:
		"""Called before the case is written. The default implementation does nothing."""

	async def after_creation(self) -> None:
		"""Called after the case is written. Raising here rolls the case back."""

	async def before_deletion(self) -> None:
		"""Called before an active case is closed (deleted or deactivated)."""

	async def after_deletion(self) -> None:
		"""Called after an active case is closed (deleted or deactivated)."""

	async def _notify(self, key: str, **kwargs: Any) -> None:
		message = await custom_response.CustomResponse(self.bot, "mod").get_message(key, self._guild, **kwargs)
		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass


class Warn(Case):
	def __init__(
		self,
		_id: int,
		bot: Bot,
		guild: discord.Guild,
		user: discord.Member | discord.User,
		moderator: discord.User | discord.Member,
		reason: str | None = None,
		expires: datetime.datetime | None = None,
		message: str | None = None,
		created: datetime.datetime = MISSING,
		active: bool = True,
	):
		super().__init__(
			CaseType.WARN, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def after_creation(self) -> None:
		"""Notifies the user about the warning."""
		await self._notify("mod.warn.notify", warn=self)

	async def after_deletion(self) -> None:
		"""Notifies the user about the removal of the warning."""
		await self._notify("mod.warn.unwarned", warn=self)


class Kick(Case):
	def __init__(
		self,
		_id: int,
		bot: Bot,
		guild: discord.Guild,
		user: discord.Member | discord.User,
		moderator: discord.User | discord.Member,
		reason: str | None = None,
		message: str | None = None,
		created: datetime.datetime = MISSING,
		expires: datetime.datetime | None = None,
		active: bool = True,
	):
		super().__init__(
			CaseType.KICK, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def before_creation(self) -> None:
		"""Notifies the user about the kick."""
		await self._notify("mod.kick.notify", kick=self)

	async def after_creation(self) -> None:
		"""Kicks the user."""
		if isinstance(self._user, discord.Member):
			await self._user.kick(reason=f"Kicked by {self._moderator}")


class Mute(Case):
	def __init__(
		self,
		_id: int,
		bot: Bot,
		guild: discord.Guild,
		user: discord.Member | discord.User,
		moderator: discord.User | discord.Member,
		expires: datetime.datetime | None,
		reason: str | None = None,
		message: str | None = None,
		created: datetime.datetime = MISSING,
		active: bool = True,
	):
		super().__init__(
			CaseType.MUTE, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def before_creation(self) -> None:
		"""Times the member out until the case expires (Discord caps timeouts at 28 days)."""
		reason = await custom_response.CustomResponse(self.bot, "mod")("mod.mute.reason", self._guild, mute=self)
		if isinstance(self._user, discord.Member) and self.expires is not None:
			now = datetime.datetime.now(tz=datetime.UTC)
			expires_utc = min(self.expires.astimezone(datetime.UTC), now + datetime.timedelta(days=28))
			if expires_utc <= now:
				return
			await self._user.timeout(expires_utc, reason=reason if isinstance(reason, str) else None)

	async def after_creation(self) -> None:
		"""Notifies the user about the mute."""
		await self._notify("mod.mute.notify", mute=self)

	async def before_deletion(self) -> None:
		"""Removes the member's timeout, if they still have one."""
		member = self._guild.get_member(self._user.id)
		if member and member.timed_out_until:
			await member.edit(timed_out_until=None, reason=self.reason)

	async def after_deletion(self) -> None:
		"""Notifies the user about the unmute."""
		await self._notify("mod.unmute.notify", mute=self)


class Ban(Case):
	def __init__(
		self,
		_id: int,
		bot: Bot,
		guild: discord.Guild,
		user: discord.Member | discord.User,
		moderator: discord.User | discord.Member,
		reason: str | None = None,
		expires: datetime.datetime | None = None,
		message: str | None = None,
		created: datetime.datetime = MISSING,
		active: bool = True,
	):
		super().__init__(
			CaseType.BAN, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def before_creation(self) -> None:
		"""Notifies the user about the ban."""
		await self._notify("mod.ban.notify", ban=self)

	async def after_creation(self) -> None:
		"""Bans the user."""
		await self._guild.ban(self._user, reason=f"Banned by {self._moderator}", delete_message_days=0)  # type: ignore

	async def before_deletion(self) -> None:
		"""Unbans the user."""
		try:
			await self._guild.unban(self._user, reason="Ban removed")  # type: ignore
		except discord.NotFound:
			pass

	async def after_deletion(self) -> None:
		"""Notifies the user about the unban, if they share a server with the bot."""
		if self._guild.get_member(self._user.id):
			await self._notify("mod.unban.notify", ban=self)


CASE_CLASSES: dict[CaseType, Callable[..., Case]] = {
	CaseType.WARN: Warn,
	CaseType.MUTE: Mute,
	CaseType.KICK: Kick,
	CaseType.BAN: Ban,
}


class CaseScheduler(Protocol):
	"""What `CaseStore` needs from an expiry scheduler."""

	def schedule_at(self, key: int, guild_id: int, expires: datetime.datetime) -> None: ...
	def cancel(self, key: int) -> None: ...
	def start(self) -> None: ...
	def stop(self) -> None: ...


class RetentionCache:
	"""Per-guild cache of the ``mod_config.case_retention`` setting."""

	def __init__(self, db: asyncpg.Pool) -> None:
		self._db = db
		self._cache: dict[int, Retention] = {}

	async def get(self, guild_id: int) -> Retention:
		"""Return the guild's retention policy, defaulting to ``"keep"``."""
		if guild_id not in self._cache:
			row = await self._db.fetchrow("SELECT case_retention FROM mod_config WHERE guild_id = $1", guild_id)
			self._cache[guild_id] = "delete" if row and row["case_retention"] == "delete" else "keep"
		return self._cache[guild_id]

	def set(self, guild_id: int, retention: Retention) -> None:
		"""Update the cached policy after it changed elsewhere."""
		self._cache[guild_id] = retention


class CaseStore:
	"""Reads, opens, closes, edits and expires moderation cases.

	Args:
		bot: The bot, used to resolve guilds and users from stored IDs.
		db: The database pool holding the ``cases`` table.
		retention: Returns a guild's retention policy; decides whether closing a case deletes or deactivates it.
		scheduler: Expiry scheduler. Defaults to a `CaseExpirationManager` that expires cases through this store.
	"""

	def __init__(
		self,
		bot: Bot,
		db: asyncpg.Pool,
		retention: RetentionLookup,
		scheduler: CaseScheduler | None = None,
	) -> None:
		self._bot = bot
		self._db = db
		self._retention = retention
		self._scheduler: CaseScheduler = scheduler or CaseExpirationManager(bot, self)

	def start(self) -> None:
		"""Start expiring cases."""
		self._scheduler.start()

	def stop(self) -> None:
		"""Stop expiring cases."""
		self._scheduler.stop()

	async def get(self, guild: discord.Guild, case_id: int) -> Case | None:
		"""Return the case with ``case_id`` in ``guild``, or ``None``."""
		row = await self._db.fetchrow("SELECT * FROM cases WHERE case_id = $1 AND guild_id = $2", case_id, guild.id)
		return await self._from_row(row, guild) if row else None

	async def active(
		self, guild: discord.Guild, user: discord.Member | discord.User, case_type: CaseType
	) -> list[Case]:
		"""Return the user's active cases of one type in ``guild``, oldest first."""
		rows = await self._db.fetch(
			"SELECT * FROM cases WHERE guild_id = $1 AND user_id = $2 AND type = $3 AND active = true ORDER BY created",
			guild.id,
			user.id,
			case_type.value,
		)
		return [await self._from_row(row, guild, user) for row in rows]

	async def for_user(
		self, guild: discord.Guild, user: discord.Member | discord.User, status: CaseStatus = "all"
	) -> list[Case]:
		"""Return the user's cases in ``guild``, newest first.

		Args:
			guild: The guild.
			user: The user the cases are about.
			status: ``"active"`` (active and not past expiry), ``"expired"`` (inactive or past expiry), or ``"all"``.
		"""
		query = "SELECT * FROM cases WHERE guild_id = $1 AND user_id = $2"
		params: list[Any] = [guild.id, user.id]
		if status == "active":
			query += " AND active = true AND (expires IS NULL OR expires > $3)"
			params.append(datetime.datetime.now(tz=datetime.UTC))
		elif status == "expired":
			query += " AND (active = false OR (expires IS NOT NULL AND expires <= $3))"
			params.append(datetime.datetime.now(tz=datetime.UTC))
		rows = await self._db.fetch(query + " ORDER BY created DESC", *params)
		return [await self._from_row(row, guild, user) for row in rows]

	async def open(self, case: Case) -> Case | None:
		"""Record a new case and perform its side effects.

		Returns:
			The case, or ``None`` if the target is no longer in the guild (bans may target non-members).

		Raises:
			Exception: Whatever ``after_creation`` raised; the case is removed again first.
		"""
		if case.type != CaseType.BAN and case._guild.get_member(case._user.id) is None:
			return None

		await case.before_creation()
		await self._db.execute(
			"""
			INSERT INTO cases (type, guild_id, case_id, user_id, moderator_id, reason, expires, message, active, created)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
			""",
			case.type.value,
			case._guild.id,
			case.id,
			case._user.id,
			case._moderator.id,
			case.reason,
			case.expires,
			case.message,
			case.active,
			case._created,
		)
		try:
			await case.after_creation()
		except Exception:
			await self._db.execute("DELETE FROM cases WHERE case_id = $1", case.id)
			raise

		if case.active and case.expires:
			self._scheduler.schedule_at(case.id, case._guild.id, case.expires)
		return case

	async def close(self, case: Case) -> CloseOutcome:
		"""Close a case according to the guild's retention policy.

		Runs the case's deletion hooks only if it was still active, so closing twice never repeats an unban,
		unmute or DM.
		"""
		self._scheduler.cancel(case.id)
		was_active = case.active
		if was_active:
			await case.before_deletion()
		if await self._retention(case._guild.id) == "delete":
			await self._db.execute("DELETE FROM cases WHERE case_id = $1", case.id)
			outcome: CloseOutcome = "deleted"
		else:
			await self._db.execute("UPDATE cases SET active = false WHERE case_id = $1", case.id)
			outcome = "deactivated"
		case.active = False
		if was_active:
			await case.after_deletion()
		return outcome

	async def delete(self, case: Case) -> None:
		"""Delete a case regardless of the retention policy, running its deletion hooks if it was active."""
		self._scheduler.cancel(case.id)
		if case.active:
			await case.before_deletion()
		await self._db.execute("DELETE FROM cases WHERE case_id = $1", case.id)
		if case.active:
			case.active = False
			await case.after_deletion()

	async def edit(
		self,
		case: Case,
		*,
		reason: str | None = MISSING,
		expires: datetime.datetime | None = MISSING,
		message: str | None = MISSING,
	) -> Case:
		"""Change a case's reason, expiry or message. Omitted fields keep their value; the expiry is rescheduled."""
		if reason is not MISSING:
			case.reason = reason
		if expires is not MISSING:
			case.expires = expires
		if message is not MISSING:
			case.message = message
		await self._db.execute(
			"UPDATE cases SET reason = $1, expires = $2, message = $3 WHERE case_id = $4",
			case.reason,
			case.expires,
			case.message,
			case.id,
		)
		self._scheduler.cancel(case.id)
		if case.active and case.expires:
			self._scheduler.schedule_at(case.id, case._guild.id, case.expires)
		return case

	async def pending(self) -> list[tuple[int, int, datetime.datetime]]:
		"""Return ``(case_id, guild_id, expires)`` for every active case that expires."""
		rows = await self._db.fetch(
			"SELECT case_id, guild_id, expires FROM cases WHERE active = true AND expires IS NOT NULL"
		)
		return [(int(row["case_id"]), int(row["guild_id"]), row["expires"]) for row in rows]

	async def expire(self, case_id: int) -> None:
		"""Close an expired case. Cases from guilds the bot has left are deleted outright."""
		row = await self._db.fetchrow("SELECT * FROM cases WHERE case_id = $1 AND active = true", case_id)
		if not row:
			return
		guild = self._bot.get_guild(int(row["guild_id"]))
		if guild is None:
			await self._db.execute("DELETE FROM cases WHERE case_id = $1", case_id)
			return
		await self.close(await self._from_row(row, guild))

	async def _from_row(
		self, row: asyncpg.Record, guild: discord.Guild, user: discord.Member | discord.User | None = None
	) -> Case:
		"""Build the `Case` subclass matching the row's type, resolving users from cache or the API."""
		active = row["active"]
		return CASE_CLASSES[CaseType(row["type"])](
			_id=int(row["case_id"]),
			bot=self._bot,
			guild=guild,
			user=user or await self._resolve_user(int(row["user_id"])),
			moderator=await self._resolve_user(int(row["moderator_id"])),
			reason=row["reason"],
			expires=row["expires"],
			message=row["message"],
			created=row["created"],
			active=True if active is None else active,
		)

	async def _resolve_user(self, user_id: int) -> discord.User:
		return self._bot.get_user(user_id) or await self._bot.fetch_user(user_id)


class CaseExpirationManager(ExpiryScheduler[int]):
	"""Shard-aware scheduler that expires cases through a `CaseStore`."""

	def __init__(self, bot: Bot, store: CaseStore) -> None:
		super().__init__(bot)
		self._store = store

	async def fetch_pending(self) -> list[tuple[int, int, datetime.datetime]]:
		"""Return every active case that has an expiry date."""
		return await self._store.pending()

	async def process_expired(self, key: int, guild_id: int) -> None:
		"""Close the expired case."""
		await self._store.expire(key)
