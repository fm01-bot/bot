from __future__ import annotations

import datetime
import logging
from copy import deepcopy
from enum import Enum
from typing import Any, Literal, Self

import asyncpg
import discord
from args import FormatDateTime, Guild, Member, TextChannel, User
from core import Bot, Context
from core.hybrid import command, group
from discord import app_commands
from discord.ext import commands, localization
from discord.utils import MISSING
from helpers import convert_to_query, custom_response, seconds_to_text, text_to_seconds
from helpers.pagination import PaginationView
from helpers.scheduler import ExpiryScheduler

logger = logging.getLogger(__name__)


class CaseType(Enum):
	WARN = 1
	MUTE = 2
	KICK = 3
	BAN = 4


class Case:
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
		if created is MISSING:
			created = datetime.datetime.now(tz=datetime.UTC)
		elif created and created.tzinfo is None:
			created = created.replace(tzinfo=datetime.UTC)
		if expires and expires.tzinfo is None:
			expires = expires.replace(tzinfo=datetime.UTC)
		self.bot: Bot = bot
		self.type: CaseType = _type
		self.id: int = _id
		self._guild: discord.Guild = guild
		self._user: discord.Member | discord.User = user
		self._reason: str | None = reason
		self._moderator: discord.User | discord.Member = moderator
		self.expires: datetime.datetime | None = expires
		self.message: str | None = message
		self.active: bool = active
		self.length: str | None = discord.utils.format_dt(self.expires, "R") if self.expires else None
		self._created: datetime.datetime = created or datetime.datetime.now(tz=datetime.UTC)

	def __repr__(self):
		return (
			f"Case(type={self.type} user={self._user} reason={self.reason} moderator={self._moderator} "
			f"duration={self.expires} message={self.message} id={self.id} active={self.active})"
		)

	def __eq__(self, other):
		return self.id == other.id

	def __ne__(self, other):
		return self.id != other.id

	def __lt__(self, other):
		return self.expires < other.expires

	def __le__(self, other):
		return self.expires <= other.expires

	def __gt__(self, other):
		return self.expires > other.expires

	def __ge__(self, other):
		return self.expires >= other.expires

	def __int__(self):
		return self.id

	def __bool__(self):
		if not self.active:
			return False
		if self.expires is None:
			return True
		return self.expires > datetime.datetime.now(tz=datetime.UTC)

	def __len__(self):
		if self.expires is None:
			return 0
		return datetime.datetime.now(tz=datetime.UTC) - self.expires

	@property
	def status(self) -> str:
		"""Returns the status text: 'Active', 'Expired', or 'Inactive'."""
		if not self.active:
			return "Inactive"
		if self.expires and self.expires <= datetime.datetime.now(tz=datetime.UTC):
			return "Expired"
		return "Active"

	@classmethod
	def from_dict(cls, data: dict, client: discord.Client, get_type: bool = False) -> Self:
		"""Create a `Case` from a dictionary.

		Args:
			data (dict): The dictionary to create the `Case` from.
			client (discord.Client): The client to get the guilds with.
			get_type (bool): Whether to return the type of the case in the dictionary.

		"""
		data = dict(data)
		data.pop("id", None)
		case_type = CaseType(data.pop("type"))
		data["_type"] = case_type
		data["_id"] = data.pop("case_id")
		data["bot"] = client
		data["guild"] = client.get_guild(data.pop("guild_id"))
		data["user"] = client.get_user(data.pop("user_id"))
		data["moderator"] = client.get_user(data.pop("moderator_id"))

		active = data.pop("active", True)
		if active is None:
			active = True
		data["active"] = active

		if not get_type:
			data.pop("_type", None)
		return cls(**data)

	@classmethod
	async def from_user(
		cls,
		db: asyncpg.Pool,
		user: discord.Member | discord.User,
		client: discord.Client,
		guild: discord.Guild,
		limit: int | None = None,
		get_type: bool = True,
		status_filter: str | None = None,
	) -> list[Self]:
		"""Generate a list of `Case`s from a user with optional status filtering.

		Args:
			db (asyncpg.Pool): The database connection pool.
			user (Union[discord.Member, discord.User]): The user to get the cases from.
			client (discord.Client): The client to get the guilds with.
			guild (discord.Guild): The guild to get the cases from.
			limit (int, optional): The limit of cases to get. If None, it will get all cases.
			get_type (bool): Whether to return the type of the case in the result dictionary.
			status_filter (str, optional): Filter by 'active', 'expired', or 'all'.

		Returns:
			list[Case]: The list of cases.

		"""
		now = datetime.datetime.now(tz=datetime.UTC)
		if status_filter == "active":
			query = (
				"SELECT * FROM cases WHERE guild_id = $1 AND user_id = $2 "
				"AND active = true AND (expires IS NULL OR expires > $3) ORDER BY created DESC"
			)
			params: list[Any] = [guild.id, user.id, now]
		elif status_filter == "expired":
			query = (
				"SELECT * FROM cases WHERE guild_id = $1 AND user_id = $2 "
				"AND (active = false OR (expires IS NOT NULL AND expires <= $3)) ORDER BY created DESC"
			)
			params = [guild.id, user.id, now]
		else:
			query = "SELECT * FROM cases WHERE guild_id = $1 AND user_id = $2 ORDER BY created DESC"
			params = [guild.id, user.id]

		if limit is not None:
			query += f" LIMIT ${len(params) + 1}"
			params.append(limit)

		result = await db.fetch(query, *params)
		case_mapping = {CaseType.WARN: Warn, CaseType.MUTE: Mute, CaseType.KICK: Kick, CaseType.BAN: Ban}

		cases = []
		for case_data in result:
			base_case = cls.from_dict(case_data, client, get_type)
			case_class = case_mapping.get(base_case.type, cls)
			as_dict = base_case.to_dict()
			if as_dict.get("_type") is None:
				cases.append(cls(**as_dict))  # type: ignore
			else:
				as_dict.pop("_type", None)
				cases.append(case_class(**as_dict))  # type: ignore
		return cases

	@classmethod
	async def from_moderator(
		cls,
		db: asyncpg.Pool,
		moderator: discord.User,
		client: discord.Client,
		guild: discord.Guild,
		limit: int | None = None,
	) -> list[Self]:
		"""Generate a list of `Case`s given by a moderator.

		Args:
			db (asyncpg.Pool): The database connection pool.
			moderator (discord.User): The moderator to get the cases from.
			client (discord.Client): The client to get the guilds with.
			guild (discord.Guild): The guild to get the cases from.
			limit (int, optional): The limit of cases to get. If None, it will get all cases.

		Returns:
			list[Case]: The list of cases.

		"""
		return await cls.from_db(db, client, guild, limit=limit, moderator=moderator)

	@classmethod
	async def from_id(
		cls, db: asyncpg.Pool, client: discord.Client, guild: discord.Guild, case_id: int, get_type: bool = False
	) -> Self | None:
		"""Get a `Case` from an ID.

		Args:
			db (asyncpg.Pool): The database connection pool.
			client (discord.Client): The client to get the guilds with.
			guild (discord.Guild): The guild to get the case from.
			case_id (int): The ID of the case.
			get_type (bool): Whether to return the type of the case in the result dictionary.

		Returns:
			Optional[Case]: The case.

		"""
		result = await db.fetch("SELECT * FROM cases WHERE case_id = $1 AND guild_id = $2", case_id, guild.id)
		if not result:
			return None
		return cls.from_dict(result[0], client, get_type)

	@classmethod
	async def from_db(
		cls,
		db: asyncpg.Pool,
		client: discord.Client,
		guild: discord.Guild | None = None,
		*,
		limit: int | None = None,
		get_type: bool = False,
		**filters: Any,
	) -> list[Any]:
		"""Retrieve cases from the database based on the provided attributes.

		Args:
			db (asyncpg.Pool): The database connection pool.
			client (discord.Client): The client instance.
			guild (discord.Guild, optional): The guild to get the cases for. Defaults to None.
			limit (int, optional): The limit of cases to retrieve. If None, retrieves all cases.
			get_type (bool): Set to true if you want a Case object. Set to false if you want a corresponding mod action object.
			**filters: Additional filters for querying cases (e.g., user=..., moderator=...).

		Returns:
			list[Case]: A list of cases matching the filters.

		"""
		query, query_parameters = convert_to_query("cases", guild, limit, **filters)

		result = await db.fetch(query, *query_parameters)

		case_mapping = {CaseType.WARN: Warn, CaseType.MUTE: Mute, CaseType.KICK: Kick, CaseType.BAN: Ban}

		cases = []
		for case_data in result:
			base_case = cls.from_dict(case_data, client, get_type)
			case_class = case_mapping.get(base_case.type, cls)
			as_dict = base_case.to_dict()
			if as_dict.get("_type") is None:
				cases.append(cls(**as_dict))  # type: ignore
			else:
				as_dict.pop("_type", None)
				cases.append(case_class(**as_dict))  # type: ignore
		return cases

	def to_dict(
		self,
	) -> dict[
		str,
		CaseType | int | discord.Guild | discord.Member | discord.User | str | datetime.datetime | None | Bot | bool,
	]:
		"""Convert the `Case` to a dictionary."""
		return {
			"_type": self.type,
			"_id": self.id,
			"bot": self.bot,
			"guild": self._guild,
			"user": self._user,
			"moderator": self._moderator,
			"reason": self.reason,
			"expires": self.expires,
			"message": self.message,
			"active": self.active,
		}

	async def before_deletion(self):
		"""An overrideable method that is called before a case is deleted or deactivated."""

	async def after_deletion(self):
		"""An overrideable method that is called after a case is deleted or deactivated."""

	async def delete(self, db: asyncpg.Pool) -> None:
		"""Delete the case from the database. This will also call `before_deletion` and `after_deletion`.

		Args:
			db (asyncpg.Pool): The database connection pool.

		"""
		mod_cog: Any = self.bot.get_cog("Moderation")
		if mod_cog and hasattr(mod_cog, "manager"):
			mod_cog.manager.cancel(self.id)
		await self.before_deletion()
		await db.execute("DELETE FROM cases WHERE case_id = $1", self.id)
		await self.after_deletion()

	async def deactivate(self, db: asyncpg.Pool) -> None:
		"""Mark the case as inactive in the database. This will also call `before_deletion` and `after_deletion`.

		Args:
			db (asyncpg.Pool): The database connection pool.

		"""
		mod_cog: Any = self.bot.get_cog("Moderation")
		if mod_cog and hasattr(mod_cog, "manager"):
			mod_cog.manager.cancel(self.id)
		await self.before_deletion()
		self.active = False
		await db.execute("UPDATE cases SET active = false WHERE case_id = $1", self.id)
		await self.after_deletion()

	async def before_creation(self) -> None:
		"""An overrideable method that is called before a case is created. The default implementation does nothing."""

	async def after_creation(self) -> None:
		"""An overrideable method that is called after a case is created. The default implementation does nothing."""

	async def create(self, db: asyncpg.Pool) -> Self | None:
		"""Create the case in the database.

		Args:
			db (asyncpg.Pool): The database connection pool.

		Returns:
			Case: The created case.

		"""
		if self.type != CaseType.BAN and self._user not in self._guild.members:
			return None

		await self.before_creation()
		await db.execute(
			"""
			INSERT INTO cases (type, guild_id, case_id, user_id, moderator_id, reason, expires, message, active)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
			""",
			self.type.value,
			self._guild.id,
			self.id,
			self._user.id,
			self._moderator.id,
			self.reason,
			self.expires,
			self.message,
			self.active,
		)
		try:
			await self.after_creation()
		except Exception:
			await db.execute("DELETE FROM cases WHERE case_id = $1", self.id)
			raise

		mod_cog: Any = self.bot.get_cog("Moderation")
		if mod_cog and hasattr(mod_cog, "manager"):
			mod_cog.manager.schedule(self)

		return self

	@staticmethod
	def generate_id(message: discord.Message) -> int:
		"""Generate a case ID from a message."""
		return message.id

	async def edit(self, db: asyncpg.Pool, case: Self) -> None:
		"""Edit the case in the database.

		Args:
			db (asyncpg.Pool): The database connection pool.
			case (Case): The new case data; if something is not set in the new case, it will be set to the old case's data.

		"""
		self.active = case.active
		self.reason = case.reason
		self.expires = case.expires
		self.message = case.message
		self._user = case._user
		await db.execute(
			"UPDATE cases SET user_id = $1, reason = $2, expires = $3, message = $4, active = $5 WHERE case_id = $6",
			case._user.id,
			case.reason,
			case.expires,
			case.message,
			case.active,
			self.id,
		)
		mod_cog: Any = self.bot.get_cog("Moderation")
		if mod_cog and hasattr(mod_cog, "manager"):
			mod_cog.manager.reschedule(self.id, self._guild.id, case.expires)

	def copy(self) -> Self:
		"""Copy the case."""
		new_case = object.__new__(self.__class__)
		new_case.__dict__.update(self.__dict__)
		return new_case

	@property
	def created(self) -> FormatDateTime:
		"""The creation date of the case."""
		return FormatDateTime(self._created, "R")

	@property
	def reason(self) -> str | None:
		return self._reason

	@reason.setter
	def reason(self, value: str | None) -> None:
		self._reason = value

	@property
	def guild(self) -> Guild:
		return Guild.from_guild(self._guild)

	@property
	def user(self) -> User:
		return User.from_user(self._user) if isinstance(self._user, discord.User) else Member.from_member(self._user)

	@property
	def moderator(self) -> User:
		return User.from_user(self._moderator)


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
		self._user = user
		self._guild = guild
		super().__init__(
			CaseType.WARN, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def after_creation(self) -> None:
		"""Notifies the user about the warning."""
		_custom_response = custom_response.CustomResponse(self.bot, "mod")
		message = await _custom_response.get_message("mod.warn.notify", self._guild, warn=self)

		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass

	async def after_deletion(self) -> None:
		"""Notifies the user about the removal of the warning."""
		_custom_response = custom_response.CustomResponse(self.bot, "mod")
		message = await _custom_response.get_message("mod.warn.unwarned", self._guild, warn=self)

		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass


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
		expires=None,
		active: bool = True,
	):
		super().__init__(
			CaseType.KICK, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def before_creation(self) -> None:
		"""Notifies the user about the kick."""
		self._custom_response = custom_response.CustomResponse(self.bot, "mod")
		message = await self._custom_response.get_message("mod.kick.notify", self._guild, kick=self)

		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass

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
		expires: datetime.datetime,
		reason: str | None = None,
		message: str | None = None,
		created: datetime.datetime = MISSING,
		active: bool = True,
	):
		super().__init__(
			CaseType.MUTE, _id, bot, guild, user, moderator, created, reason, expires, message, active=active
		)

	async def before_creation(self) -> None:
		"""Mutes the user."""
		self._custom_response = custom_response.CustomResponse(self.bot, "mod")
		reason = await self._custom_response("mod.mute.reason", self._guild, mute=self)
		if isinstance(self._user, discord.Member) and self.expires is not None:
			now = datetime.datetime.now(tz=datetime.UTC)
			expires_utc = self.expires.astimezone(datetime.UTC)
			max_timeout = now + datetime.timedelta(days=28)
			expires_utc = min(expires_utc, max_timeout)
			if expires_utc <= now:
				return
			await self._user.timeout(expires_utc, reason=reason if isinstance(reason, str) else None)

	async def after_creation(self) -> None:
		"""Notifies the user about the mute."""
		self._custom_response = custom_response.CustomResponse(self.bot, "mod")
		message = await self._custom_response.get_message("mod.mute.notify", self._guild, mute=self)

		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass

	async def before_deletion(self) -> None:
		"""Unmutes the user."""
		as_member: discord.Member | None = self._guild.get_member(self._user.id)
		if not as_member or not as_member.timed_out_until:
			return

		await as_member.edit(timed_out_until=None, reason=self.reason)

	async def after_deletion(self) -> None:
		"""Notifies the user about the unmute."""
		self._custom_response = custom_response.CustomResponse(self.bot, "mod")
		message = await self._custom_response.get_message("mod.unmute.notify", self._guild, mute=self)

		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass


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
		self._custom_response = custom_response.CustomResponse(self.bot, "mod")
		message = await self._custom_response.get_message("mod.ban.notify", self._guild, ban=self)

		try:
			if isinstance(message, dict):
				await self._user.send(**message)
		except discord.Forbidden:
			pass

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
		"""Notifies the user about the unban."""
		if self._guild.get_member(self._user.id):  # to avoid spamming non-members
			self._custom_response = custom_response.CustomResponse(self.bot, "mod")
			message = await self._custom_response.get_message("mod.unban.notify", self._guild, ban=self)

			try:
				if isinstance(message, dict):
					await self._user.send(**message)
			except discord.Forbidden:
				pass


class CaseExpirationManager(ExpiryScheduler[int]):
	"""Event-driven priority queue manager for case expirations across shards."""

	def __init__(self, bot: Bot):
		super().__init__(bot)
		self._retention_cache: dict[int, str] = {}

	async def get_guild_retention(self, guild_id: int) -> str:
		"""Fetch the case retention setting ('keep' or 'delete') for a guild."""
		if guild_id in self._retention_cache:
			return self._retention_cache[guild_id]

		row = await self.bot.db.fetchrow("SELECT case_retention FROM mod_config WHERE guild_id = $1", guild_id)
		retention = row["case_retention"] if row else "keep"
		self._retention_cache[guild_id] = retention
		return retention

	def set_guild_retention(self, guild_id: int, retention: str) -> None:
		"""Update local retention cache for a guild."""
		self._retention_cache[guild_id] = retention

	def schedule(self, case: Case) -> None:
		"""Schedule a case for expiration if it has an expiry date."""
		if not case.expires or not case.active:
			return
		self.schedule_at(case.id, case._guild.id, case.expires)

	def reschedule(self, case_id: int, guild_id: int, new_expires: datetime.datetime | None) -> None:
		"""Reschedule an existing case expiration."""
		self.cancel(case_id)
		if new_expires:
			self.schedule_at(case_id, guild_id, new_expires)

	async def fetch_pending(self) -> list[tuple[int, int, datetime.datetime]]:
		"""Return every active case that has an expiry date."""
		rows = await self.bot.db.fetch("SELECT * FROM cases WHERE active = true AND expires IS NOT NULL")
		return [(int(row["case_id"]), int(row["guild_id"]), row["expires"]) for row in rows if row["expires"]]

	async def process_expired(self, key: int, guild_id: int) -> None:
		"""Process an expired case."""
		await self._process_expiration(key, guild_id)

	async def _process_expiration(self, case_id: int, guild_id: int) -> None:
		"""Process an expired case: execute side effects and deactivate or delete."""
		row = await self.bot.db.fetchrow("SELECT * FROM cases WHERE case_id = $1 AND active = true", case_id)
		if not row:
			return

		base_case = Case.from_dict(row, self.bot, get_type=True)
		if not base_case._guild:
			await self.bot.db.execute("DELETE FROM cases WHERE case_id = $1", case_id)
			return

		case_mapping = {
			CaseType.WARN: Warn,
			CaseType.MUTE: Mute,
			CaseType.KICK: Kick,
			CaseType.BAN: Ban,
		}
		case_cls = case_mapping.get(base_case.type, Case)
		as_dict = base_case.to_dict()
		as_dict.pop("_type", None)
		case: Case = case_cls(**as_dict)  # type: ignore

		retention = await self.get_guild_retention(guild_id)
		if retention == "delete":
			await case.delete(self.bot.db)
		else:
			await case.deactivate(self.bot.db)


@commands.guild_only()
@app_commands.guild_only()
class Moderation(commands.GroupCog, name="Moderation", group_name="mod"):
	def __init__(self, client: Bot):
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "mod")
		self.manager = CaseExpirationManager(client)

	def set_guild_retention(self, guild_id: int, retention: str) -> None:
		"""Update retention setting in the expiration manager."""
		self.manager.set_guild_retention(guild_id, retention)

	async def cog_load(self):
		self.manager.start()

	async def cog_unload(self):
		self.manager.stop()

	@command(user=False, permissions=["moderate_members"])
	async def warn(
		self, ctx: Context, member: discord.Member, expires: str | None = None, *, reason: str | None = None
	):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		try:
			member = await commands.MemberConverter().convert(
				ctx, str(member.name) if isinstance(member, discord.Member) else member
			)
		except commands.MemberNotFound:
			if not ctx.message.reference:
				reason = " ".join(
					[str(member), expires or "", reason or ""] if reason else [str(member), expires or ""]
				)
			else:
				raise commands.MemberNotFound(str(member))
		try:
			expiry_date = (
				datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=text_to_seconds(expires))
				if expires
				else None
			)
		except (ValueError, TypeError):
			reason = " ".join([expires or "", reason or ""] if reason else [expires or ""])
			expiry_date = None

		if member == ctx.me:
			await ctx.send("mod.warn.errors.bot")
			return

		if member.top_role >= ctx.author.top_role:
			await ctx.send("mod.warn.errors.hierarchy")
			return

		warn = Warn(
			Case.generate_id(ctx.message),
			self.client,
			ctx.guild,
			member,
			ctx.author,
			reason,
			expiry_date,
			ctx.message.reference.resolved.content if ctx.message.reference else None,  # type: ignore
		)
		await warn.create(self.client.db)

		await ctx.send("mod.warn.response", warn=warn)

	@command(user=False, permissions=["moderate_members"])
	async def mute(self, ctx: Context, member: discord.Member, expires: str, *, reason: str | None = None):
		assert ctx.guild is not None
		try:
			seconds = text_to_seconds(expires)
		except (ValueError, TypeError):
			raise commands.BadArgument
		max_timeout = 28 * 24 * 60 * 60  # 28 days
		if seconds <= 0 or seconds > max_timeout:
			raise commands.BadArgument("Mute duration must be between 1 second and 28 days.")
		expiry_date = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=seconds)
		if member == ctx.me:
			await ctx.send("mod.mute.errors.bot")
			return
		mute = Mute(
			Case.generate_id(ctx.message),
			self.client,
			ctx.guild,
			member,
			ctx.author,
			expiry_date,
			reason,
			ctx.message.reference.resolved.content if ctx.message.reference else None,  # type: ignore
		)
		await mute.create(self.client.db)

		await ctx.send("mod.mute.response", mute=mute)

	@command(user=False, permissions=["moderate_members"])
	async def unmute(self, ctx: Context, member: discord.Member):
		assert ctx.guild is not None
		if member.timed_out_until:
			cases = await Mute.from_db(
				self.client.db,
				self.client,
				ctx.guild,
				user=member,
				expires=member.timed_out_until.astimezone(datetime.UTC),
			)
			if cases:
				retention = await self.manager.get_guild_retention(ctx.guild.id)
				for case in cases:
					if retention == "delete":
						await case.delete(self.client.db)
					else:
						await case.deactivate(self.client.db)
			else:
				await member.edit(timed_out_until=None)
		await member.edit(timed_out_until=None)

		await ctx.send("mod.unmute.response", member=member)

	@command(user=False, permissions=["kick_members"])
	async def kick(self, ctx: Context, member: discord.Member, *, reason: str | None = None):
		assert ctx.guild is not None
		if member == ctx.me:
			await ctx.send("mod.kick.errors.bot")
			return
		kick = Kick(
			Case.generate_id(ctx.message),
			self.client,
			ctx.guild,
			member,
			ctx.author,
			reason,
			ctx.message.reference.resolved.content if ctx.message.reference else None,  # type: ignore
		)
		await kick.create(self.client.db)

		await ctx.send("mod.kick.response", kick=kick)

	@command(user=False, permissions=["ban_members"])
	async def ban(self, ctx: Context, user: discord.User, expires: str | None = None, *, reason: str | None = None):
		assert ctx.guild is not None
		try:
			expiry_date = (
				datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=text_to_seconds(expires))
				if expires
				else None
			)
		except (ValueError, TypeError):
			if ctx.interaction:
				raise commands.BadArgument
			reason = f"{expires} {reason}" if reason else expires
			expiry_date = None
		if user == ctx.me:
			await ctx.send("mod.ban.errors.bot")
			return
		ban = Ban(
			Case.generate_id(ctx.message),
			self.client,
			ctx.guild,
			user,
			ctx.author,
			reason,
			expiry_date,
			ctx.message.reference.resolved.content if ctx.message.reference else None,  # type: ignore
		)
		await ban.create(self.client.db)

		await ctx.send("mod.ban.response", ban=ban)

	@command(user=False, permissions=["ban_members"])
	async def unban(self, ctx: Context, user: discord.User):
		assert ctx.guild is not None
		cases = await Ban.from_db(
			self.client.db, self.client, ctx.guild, user=user, type=CaseType.BAN.value, active=True
		)
		if cases:
			retention = await self.manager.get_guild_retention(ctx.guild.id)
			for case in cases:
				case._custom_response = self.custom_response
				if retention == "delete":
					await case.delete(self.client.db)
				else:
					await case.deactivate(self.client.db)
		else:
			try:
				await ctx.guild.unban(user, reason=f"Ban removed by {ctx.author}")
			except discord.NotFound:
				pass

		await ctx.send("mod.unban.response", user=user)

	@command(user=False, permissions=["manage_channels"], l10n_key="sm")
	async def slowmode(self, ctx: Context, duration: str | None = None, channel: discord.TextChannel | None = None):
		target_channel = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
		if not target_channel:
			raise commands.BadArgument("Channel is not a text channel")
		if not duration:
			await ctx.send("mod.slowmode.current_slowmode", channel=TextChannel.from_channel(target_channel))
			return
		if duration.lower() == "off":
			duration = "0s"
		max_slowmode_delay = 60 * 60 * 6  # 6 hours
		slowmode_before = target_channel.slowmode_delay
		try:
			seconds = text_to_seconds(duration, target_channel.slowmode_delay)
		except ValueError:
			raise commands.BadArgument
		seconds = max(
			0, min(seconds, max_slowmode_delay)
		)  # clamp between 0 and 6hrs (silently, but whatever, its easier for the user)
		reason: str = await self.custom_response("mod.slowmode.reason", ctx, moderator=ctx.author)
		await target_channel.edit(slowmode_delay=seconds, reason=reason)
		await ctx.send(
			"mod.slowmode.response",
			channel=target_channel,
			time_before=seconds_to_text(slowmode_before),
			time=seconds_to_text(seconds),
		)


class Cases(commands.Cog, name="Cases"):
	def __init__(self, client: Bot) -> None:
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "mod")

	@group(user=False, l10n_key="caseinfo", name="case")
	async def case(self, ctx: Context, case_id: str):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		try:
			fetched_case_id = int(case_id)
		except ValueError:
			raise commands.BadArgument

		case = await Case.from_id(self.client.db, self.client, ctx.guild, fetched_case_id, get_type=True)
		if not case:
			await ctx.send("mod.info.errors.not_found", case_id=fetched_case_id)
			return

		if case._user.id != ctx.author.id and not ctx.author.guild_permissions.moderate_members:
			raise commands.MissingPermissions(["moderate_members"])

		await ctx.send("mod.info.response", case=case)

	@case.command(user=False, permissions=["moderate_members"], l10n_key="casedel")
	async def delete(self, ctx: Context, case_id: str):
		assert ctx.guild is not None
		try:
			fetched_case_id = int(case_id)
		except ValueError:
			raise commands.BadArgument("case_id")
		case = await Case.from_id(self.client.db, self.client, ctx.guild, fetched_case_id, get_type=True)
		if not case:
			await ctx.send("mod.delete.errors.not_found", case_id=fetched_case_id)
			return

		match case.type:
			case CaseType.WARN:
				case = await Warn.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)
			case CaseType.MUTE:
				case = await Mute.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)
			case CaseType.KICK:
				case = await Kick.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)
			case CaseType.BAN:
				case = await Ban.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)

		await case.delete(self.client.db)  # type: ignore

		await ctx.send("mod.delete.response", case=case)

	@case.command(user=False, permissions=["moderate_members"], l10n_key="caserem")
	async def remove(self, ctx: Context, case_id: str):
		assert ctx.guild is not None
		try:
			fetched_case_id = int(case_id)
		except ValueError:
			raise commands.BadArgument("case_id")
		case = await Case.from_id(self.client.db, self.client, ctx.guild, fetched_case_id, get_type=True)
		if not case:
			await ctx.send("mod.remove.errors.not_found", case_id=fetched_case_id)
			return

		mod_cog: Any = self.client.get_cog("Moderation")
		retention = "keep"
		if mod_cog and hasattr(mod_cog, "manager"):
			retention = await mod_cog.manager.get_guild_retention(ctx.guild.id)

		match case.type:
			case CaseType.WARN:
				case = await Warn.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)
			case CaseType.MUTE:
				case = await Mute.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)
			case CaseType.KICK:
				case = await Kick.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)
			case CaseType.BAN:
				case = await Ban.from_id(self.client.db, self.client, ctx.guild, fetched_case_id)

		if retention == "delete":
			await case.delete(self.client.db)  # type: ignore
			await ctx.send("mod.delete.response", case=case)
		else:
			await case.deactivate(self.client.db)  # type: ignore
			await ctx.send("mod.remove.response", case=case)

	@case.command(user=False, permissions=["moderate_members"], l10n_key="caseedit")
	@app_commands.choices(
		value=[
			app_commands.Choice(name="caseedit-args-value-expires", value="expires"),
			app_commands.Choice(name="caseedit-args-value-reason", value="reason"),
			app_commands.Choice(name="caseedit-args-value-message", value="message"),
		]
	)
	async def edit(self, ctx: Context, case_id: str, value: Literal["expires", "reason", "message"], *, new_value: str):
		assert ctx.guild is not None
		try:
			fetched_case_id = int(case_id)
		except ValueError:
			raise commands.BadArgument("case_id")
		case = await Case.from_id(self.client.db, self.client, ctx.guild, fetched_case_id, get_type=True)
		if case is None:
			await ctx.send("mod.edit.errors.not_found", case_id=fetched_case_id)
			return

		if value == "expires":
			try:
				final_value = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(
					seconds=text_to_seconds(new_value)
				)
			except (ValueError, TypeError):
				await ctx.send("mod.edit.errors.invalid_time", case_id=fetched_case_id)
				return
		else:
			final_value = new_value

		new_case = case.copy()
		setattr(new_case, value, final_value)
		await case.edit(self.client.db, new_case)

		await ctx.send("mod.edit.response", case=case)

	@case.command(user=False, l10n_key="caselist")
	@app_commands.choices(
		filter=[
			app_commands.Choice(name="caselist-args-filter-active", value="active"),
			app_commands.Choice(name="caselist-args-filter-expired", value="expired"),
			app_commands.Choice(name="caselist-args-filter-all", value="all"),
		]
	)
	async def list(
		self,
		ctx: Context,
		user: discord.Member | None = None,
		filter: Literal["active", "expired", "all"] | None = None,
	):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		target_user: discord.Member | discord.User = user or ctx.author

		is_moderator = ctx.author.guild_permissions.moderate_members
		if target_user.id != ctx.author.id and not is_moderator:
			raise commands.MissingPermissions(["moderate_members"])

		effective_filter = filter or ("all" if is_moderator else "active")
		if effective_filter not in ("active", "expired", "all"):
			raise commands.BadArgument("Filter must be 'active', 'expired', or 'all'.")

		cases = await Case.from_user(
			self.client.db, target_user, self.client, ctx.guild, get_type=True, status_filter=effective_filter
		)

		message: dict | str = await self.custom_response.get_message("mod.list.response", ctx, cases=cases)
		if isinstance(message, str):
			await ctx.send(content=message)
			return

		embeds: list[discord.Embed] = message.get("embeds", [])
		if not cases and isinstance(message, dict):
			if embeds:
				embeds[0].remove_field(0)
			await ctx.send(**message)
			return

		if not embeds:
			await ctx.send(**message)
			return

		base_embed_dict = embeds[0].to_dict()
		fields = base_embed_dict.get("fields", [])
		template = fields[0] if fields else None
		if not template:
			await ctx.send(**message)
			return

		page_size = 5
		total_pages = max(1, (len(cases) + page_size - 1) // page_size)
		pages: list[discord.Embed] = []

		for p in range(total_pages):
			page_cases = cases[p * page_size : (p + 1) * page_size]
			page_dict = deepcopy(base_embed_dict)
			page_dict["fields"] = []
			embed_page = discord.Embed.from_dict(page_dict)
			for case in page_cases:
				formatted = localization.Localization.format_strings(template, case=case)
				embed_page.add_field(**formatted)
			pages.append(embed_page)

		if len(pages) > 1:
			view = PaginationView(pages, author_id=ctx.author.id)
			msg = await ctx.send(embed=pages[0], view=view)
			view.message = msg
		else:
			await ctx.send(embed=pages[0])


async def setup(client: Bot):
	await client.add_cog(Moderation(client))
	await client.add_cog(Cases(client))
