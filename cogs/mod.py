import datetime
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
from helpers import convert_to_query, custom_response, seconds_to_text, text_to_seconds


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
		moderator: discord.User,
		created: datetime.datetime | None = None,
		reason: str | None = None,
		expires: datetime.datetime | None = None,
		message: str | None = None,
	):
		self.bot: Bot = bot
		self.type: CaseType = _type
		self.id: int = _id
		self._guild: discord.Guild = guild
		self._user: discord.Member | discord.User = user
		self._reason: str | None = reason
		self._moderator: discord.User = moderator
		self.expires: datetime.datetime | None = expires
		self.message: str | None = message
		self.length: str | None = discord.utils.format_dt(self.expires, "R") if self.expires else self.expires
		self._created: datetime.datetime = created or datetime.datetime.now()

	def __repr__(self):
		return f"Case(type={self.type} user={self._user} reason={self.reason} moderator={self._moderator} duration={self.expires} message={self.message} id={self.id})"

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
		if self.expires is None:
			return True
		return self.expires > datetime.datetime.now()

	def __len__(self):
		if self.expires is None:
			return 0
		return datetime.datetime.now() - self.expires

	@classmethod
	def from_dict(cls, data: dict, client: discord.Client, get_type: bool = False) -> Self:
		"""Create a `Case` from a dictionary.

		Parameters
		----------
		data: `dict`
		        The dictionary to create the `Case` from.
		client: `discord.Client`
		        The client to get the guilds with.
		get_type: `bool`
		        Whether to return the type of the case in the dictionary.
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
	) -> list[Self]:
		"""Generate a list of `Case`s from a user.

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool
		user: Union[`discord.Member`, `discord.User`]
		        The user to get the cases from
		client: `discord.Client`
		        The client to get the guilds with
		guild: `discord.Guild`
		        The guild to get the cases from
		limit: `int`
		        The limit of cases to get. If None, it will get all cases
		get_type: `bool`
		        Whether to return the type of the case in the result dictionary

		Returns
		-------
		list[`Case`]
		        The list of cases.
		"""
		return await cls.from_db(db, client, guild, limit=limit, get_type=get_type, user=user)

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

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool.
		moderator: `discord.User`
		        The moderator to get the cases from.
		client: `discord.Client`
		        The client to get the guilds with.
		guild: `discord.Guild`
		        The guild to get the cases from.
		limit: `int`
		        The limit of cases to get. If None, it will get all cases.

		Returns
		-------
		list[`Case`]
		        The list of cases.
		"""
		return await cls.from_db(db, client, guild, limit=limit, moderator=moderator)

	@classmethod
	async def from_id(
		cls, db: asyncpg.Pool, client: discord.Client, guild: discord.Guild, case_id: int, get_type: bool = False
	) -> Self | None:
		"""Get a `Case` from an ID.

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool.
		client: `discord.Client`
		        The client to get the guilds with.
		guild: `discord.Guild`
		        The guild to get the case from.
		case_id: `int`
		        The ID of the case.
		get_type: `bool`
		        Whether to return the type of the case in the result dictionary.

		Returns
		-------
		Optional[`Case`]
		        The case.
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
		"""
		Retrieve cases from the database based on the provided attributes.

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool.
		client: `discord.Client`
		        The client instance.
		guild: `discord.Guild`
		        The guild to get the cases for. Defaults to None.
		limit: `int`
		        The limit of cases to retrieve. If None, retrieves all cases.
		get_type: `bool`
		        Set to true if you want a Case object. Set to false if you want a corresponding mod action object.
		**filters: Any
		        Additional filters for querying cases (e.g., user=..., moderator=...).

		Returns
		-------
		list[`Case`]
		        A list of cases matching the filters.
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
				cases.append(case_class(**as_dict))
		return cases

	def to_dict(
		self,
	) -> dict[
		str, CaseType | int | discord.Guild | discord.Member | discord.User | str | datetime.datetime | None | Bot
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
		}

	async def before_deletion(self):
		"""An overrideable method that is called before a case is deleted. The default implementation does nothing.

		Example usage: when deleting a Case(type=CaseType.MUTE), you want to remove the timeout from the user.
		"""
		pass

	async def after_deletion(self):
		"""An overrideable method that is called after a case is deleted. The default implementation does nothing.

		Example usage: when deleting a Case(type=CaseType.MUTE), you want to remove the timeout from the user.
		"""
		pass

	async def delete(self, db: asyncpg.Pool) -> None:
		"""Delete the case from the database. This will also call `before_deletion` and `after_deletion`.

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool.
		"""
		await self.before_deletion()
		await db.execute("DELETE FROM cases WHERE case_id = $1", self.id)
		await self.after_deletion()

	async def before_creation(self) -> None:
		"""An overrideable method that is called before a case is created. The default implementation does nothing."""
		pass

	async def after_creation(self) -> None:
		"""An overrideable method that is called after a case is created. The default implementation does nothing."""
		pass

	async def create(self, db: asyncpg.Pool) -> Self | None:
		"""Create the case in the database.

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool.

		Returns
		-------
		`Case`
		        The created case.
		"""
		if self._user not in self._guild.members:
			return None

		await self.before_creation()
		await db.execute(
			"INSERT INTO cases (type, guild_id, case_id, user_id, moderator_id, reason, expires, message) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
			self.type.value,
			self._guild.id,
			self.id,
			self._user.id,
			self._moderator.id,
			self.reason,
			self.expires,
			self.message,
		)
		await self.after_creation()
		return self

	@staticmethod
	def generate_id(message: discord.Message) -> int:
		"""Generate a case ID from a message."""
		return message.id

	async def edit(self, db: asyncpg.Pool, case: Self) -> None:
		"""Edit the case in the database.

		Parameters
		----------
		db: `asyncpg.Pool`
		        The database connection pool.
		case: `Case`
		        The new case data; if something is not set in the new case, it will be set to the old case's data.
		"""
		await db.execute(
			"UPDATE cases SET user_id = $1, reason = $2, expires = $3, message = $4 WHERE case_id = $5",
			case._user.id,
			case.reason,
			case.expires,
			case.message,
			self.id,
		)

	def copy(self) -> Self:
		"""Copy the case."""
		return deepcopy(self)

	@property
	def created(self) -> FormatDateTime:
		"""The creation date of the case."""
		return FormatDateTime(self._created, "R")

	@property
	def reason(self) -> str | None:
		return self._reason

	@reason.setter
	def reason(self, value: str) -> None:
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
		moderator: discord.User,
		reason: str | None = None,
		expires: datetime.datetime | None = None,
		message: str | None = None,
		created: datetime.datetime = datetime.datetime.now(),
	):
		self._user = user
		self._guild = guild
		super().__init__(CaseType.WARN, _id, bot, guild, user, moderator, created, reason, expires, message)

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
		moderator: discord.User,
		reason: str | None = None,
		message: str | None = None,
		created: datetime.datetime = datetime.datetime.now(),
		expires=None,
	):
		super().__init__(CaseType.KICK, _id, bot, guild, user, moderator, created, reason, expires, message)

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
		moderator: discord.User,
		expires: datetime.datetime,
		reason: str | None = None,
		message: str | None = None,
		created: datetime.datetime = datetime.datetime.now(),
	):
		super().__init__(CaseType.MUTE, _id, bot, guild, user, moderator, created, reason, expires, message)

	async def before_creation(self) -> None:
		"""Mutes the user."""
		self._custom_response = custom_response.CustomResponse(self.bot, "mod")
		reason = await self._custom_response("mod.mute.reason", self._guild, mute=self)
		if isinstance(self._user, discord.Member) and self.expires is not None:
			await self._user.timeout(
				self.expires.astimezone(datetime.timezone.utc), reason=reason if isinstance(reason, str) else None
			)

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
		moderator: discord.User,
		reason: str | None = None,
		expires: datetime.datetime | None = None,
		message: str | None = None,
		created: datetime.datetime = datetime.datetime.now(),
	):
		super().__init__(CaseType.BAN, _id, bot, guild, user, moderator, created, reason, expires, message)

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
		await self._guild.ban(self._user, reason=f"Banned by {self._moderator}", delete_message_days=0)

	async def before_deletion(self) -> None:
		"""Unbans the user."""
		try:
			await self._guild.unban(self._user, reason="Ban removed")
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


@commands.guild_only()
@app_commands.guild_only()
class Moderation(commands.GroupCog, name="Moderation", group_name="mod"):
	def __init__(self, client: Bot) -> None:
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "mod")

	async def case_removal(self):
		await self.client.wait_until_ready()

		case_rows = await self.client.db.fetch(
			"SELECT * FROM cases WHERE expires IS NOT NULL AND expires <= $1", datetime.datetime.now()
		)
		for row in case_rows:
			case = Case.from_dict(row, self.client, get_type=True)

			if not case._guild:
				continue

			if not case._guild.chunked:
				await case._guild.chunk()

			match case.type:
				case CaseType.WARN:
					case = Warn.from_dict(row, self.client)
				case CaseType.MUTE:
					case = Mute.from_dict(row, self.client)
				case CaseType.KICK:
					case = Kick.from_dict(row, self.client)
				case CaseType.BAN:
					case = Ban.from_dict(row, self.client)
			await case.delete(self.client.db)

	async def cog_load(self):
		self.client.loop.create_task(self.case_removal())

	@command(user=False, permissions=["moderate_members"])
	async def warn(
		self, ctx: Context, member: discord.Member, expires: str | None = None, *, reason: str | None = None
	):
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
				datetime.datetime.now() + datetime.timedelta(seconds=text_to_seconds(expires)) if expires else None
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
			ctx.message.reference.resolved.content if ctx.message.reference else None,
		)
		await warn.create(self.client.db)

		await ctx.send("mod.warn.response", warn=warn)

	@command(user=False, permissions=["moderate_members"])
	async def mute(self, ctx: Context, member: discord.Member, expires: str, *, reason: str | None = None):
		try:
			expiry_date = datetime.datetime.now() + datetime.timedelta(seconds=text_to_seconds(expires))
		except (ValueError, TypeError):
			raise commands.BadArgument
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
			ctx.message.reference.resolved.content if ctx.message.reference else None,
		)
		await mute.create(self.client.db)

		await ctx.send("mod.mute.response", mute=mute)

	@command(user=False, permissions=["moderate_members"])
	async def unmute(self, ctx: Context, member: discord.Member):
		if member.timed_out_until:
			cases = await Mute.from_db(
				self.client.db,
				self.client,
				ctx.guild,
				user=member,
				expires=member.timed_out_until.astimezone(datetime.timezone.utc).replace(tzinfo=None),
			)
			if cases:
				for case in cases:
					await case.delete(self.client.db)
			else:
				await member.edit(timed_out_until=None)
		await member.edit(timed_out_until=None)

		await ctx.send("mod.unmute.response", member=member)

	@command(user=False, permissions=["kick_members"])
	async def kick(self, ctx: Context, member: discord.Member, *, reason: str | None = None):
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
			ctx.message.reference.resolved.content if ctx.message.reference else None,
		)
		await kick.create(self.client.db)

		await ctx.send("mod.kick.response", kick=kick)

	@command(user=False, permissions=["ban_members"])
	async def ban(self, ctx: Context, user: discord.User, expires: str | None = None, *, reason: str | None = None):
		try:
			expiry_date = (
				datetime.datetime.now() + datetime.timedelta(seconds=text_to_seconds(expires)) if expires else None
			)
		except (ValueError, TypeError):
			raise commands.BadArgument
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
			ctx.message.reference.resolved.content if ctx.message.reference else None,
		)
		await ban.create(self.client.db)

		await ctx.send("mod.ban.response", ban=ban)

	@command(user=False, permissions=["ban_members"])
	async def unban(self, ctx: Context, user: discord.User):
		cases = await Ban.from_db(self.client.db, self.client, ctx.guild, user=user)
		if cases:
			for case in cases:
				case._custom_response = self.custom_response
				await case.delete(self.client.db)
		else:
			try:
				await ctx.guild.unban(user, reason=f"Ban removed by {ctx.author}")
			except discord.NotFound:
				pass

		await ctx.send("mod.unban.response", user=user)

	@command(user=False, permissions=["manage_channels"], l10n_key="sm")
	async def slowmode(self, ctx: Context, duration: str | None = None, channel: discord.TextChannel | None = None):
		if not duration:
			await ctx.send("mod.slowmode.current_slowmode", channel=TextChannel.from_channel(ctx.channel))
			return
		if duration.lower() == "off":
			duration = "0s"
		channel = channel or ctx.channel
		max_slowmode_delay = 60 * 60 * 6  # 6 hours
		slowmode_before = channel.slowmode_delay
		try:
			seconds = text_to_seconds(duration, channel.slowmode_delay)
		except ValueError:
			raise commands.BadArgument
		seconds = max(
			0, min(seconds, max_slowmode_delay)
		)  # clamp between 0 and 6hrs (silently, but whatever, its easier for the user)
		reason: str = await self.custom_response("mod.slowmode.reason", ctx, moderator=ctx.author)  # type: ignore
		await channel.edit(slowmode_delay=seconds, reason=reason)
		await ctx.send(
			"mod.slowmode.response",
			channel=channel,
			time_before=seconds_to_text(slowmode_before),
			time=seconds_to_text(seconds),
		)


class Cases(commands.Cog, name="Cases"):
	def __init__(self, client: Bot) -> None:
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "mod")

	@group(user=False, l10n_key="caseinfo")
	async def case(self, ctx: Context, case_id: str):
		try:
			fetched_case_id = int(case_id)
		except ValueError:
			raise commands.BadArgument

		case = await Case.from_id(self.client.db, self.client, ctx.guild, fetched_case_id, get_type=True)
		if not case:
			await ctx.send("mod.info.errors.not_found", case_id=fetched_case_id)
			return

		# since we need the case's information but we don't want to duplicate db calls,
		# we check inside the actual command
		if case._user.id != ctx.author.id and not ctx.author.guild_permissions.moderate_members:
			raise commands.MissingPermissions(["moderate_members"])

		await ctx.send("mod.info.response", case=case)

	@case.command(user=False, permissions=["moderate_members"], l10n_key="casedel")
	async def delete(self, ctx: Context, case_id: str):
		try:
			# because discord's app commands only support int up to 2^54, but discord snowflakes are 2^64,
			# we need to convert the case id to an int ourselves :(
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

	@case.command(user=False, permissions=["moderate_members"], l10n_key="caseedit")
	@app_commands.choices(
		value=[
			app_commands.Choice(name="caseedit-args-value-expires", value="expires"),
			app_commands.Choice(name="caseedit-args-value-reason", value="reason"),
			app_commands.Choice(name="caseedit-args-value-message", value="message"),
		]
	)
	async def edit(self, ctx: Context, case_id: str, value: Literal["expires", "reason", "message"], *, new_value: str):
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
				final_value = datetime.datetime.now() + datetime.timedelta(seconds=text_to_seconds(new_value))
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
	async def list(self, ctx: Context, user: discord.Member | None = None):
		user = user or ctx.author

		cases = await Case.from_user(self.client.db, user, self.client, ctx.guild, 10)

		# since we need the case's information but we don't want to duplicate db calls,
		# we check inside the actual command
		if user.id != ctx.author.id and not ctx.author.guild_permissions.moderate_members:
			raise commands.MissingPermissions(["moderate_members"])

		message: dict | str | list | int | float = await self.custom_response.get_message(
			"mod.list.response", ctx, cases=cases
		)
		if not isinstance(message, dict):
			await ctx.send(content=message)
			return

		embeds: list[discord.Embed] = message.get("embeds")  # type: ignore
		if not cases:
			if embeds:
				embeds[0].remove_field(0)
			await ctx.send(**message)
			return

		if embeds:
			template = embeds[0].to_dict().get("fields", [None])[0]
			if not template:
				await ctx.send(**message)
				return
			embeds[0].clear_fields()
			for case in cases:
				formatted = localization.Localization.format_strings(template, case=case)
				embeds[0].add_field(**formatted)

		await ctx.send(**message)


async def setup(client: Bot):
	await client.add_cog(Moderation(client))
	await client.add_cog(Cases(client))
