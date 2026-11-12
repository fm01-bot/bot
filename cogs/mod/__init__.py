from __future__ import annotations

import datetime
import logging
from copy import deepcopy
from typing import Literal

import discord
from args import TextChannel
from cogs.mod.cases import (
	Ban,
	Case,
	CaseExpirationManager,
	CaseStatus,
	CaseStore,
	CaseType,
	Kick,
	Mute,
	Retention,
	RetentionCache,
	Warn,
)
from core import Bot, Context
from core.hybrid import command, group
from discord import app_commands
from discord.ext import commands, localization
from helpers import custom_response, seconds_to_text, text_to_seconds
from helpers.pagination import PaginationView

__all__ = (
	"Ban",
	"Case",
	"CaseExpirationManager",
	"CaseStore",
	"CaseType",
	"Cases",
	"Kick",
	"Moderation",
	"Mute",
	"RetentionCache",
	"Warn",
)

logger = logging.getLogger(__name__)


def _parse_case_id(case_id: str) -> int:
	try:
		return int(case_id)
	except ValueError:
		raise commands.BadArgument("case_id")


@commands.guild_only()
@app_commands.guild_only()
class Moderation(commands.GroupCog, name="Moderation", group_name="mod"):
	def __init__(self, client: Bot, cases: CaseStore, retention: RetentionCache):
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "mod")
		self.cases = cases
		self.retention = retention

	def set_guild_retention(self, guild_id: int, retention: Retention) -> None:
		"""Update the cached retention policy after it changed elsewhere."""
		self.retention.set(guild_id, retention)

	async def cog_load(self):
		self.cases.start()

	async def cog_unload(self):
		self.cases.stop()

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
		await self.cases.open(warn)

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
		await self.cases.open(mute)

		await ctx.send("mod.mute.response", mute=mute)

	@command(user=False, permissions=["moderate_members"])
	async def unmute(self, ctx: Context, member: discord.Member):
		assert ctx.guild is not None
		was_timed_out = member.timed_out_until is not None
		cases = await self.cases.active(ctx.guild, member, CaseType.MUTE)
		for case in cases:
			await self.cases.close(case)  # Mute.before_deletion lifts the timeout

		if cases and was_timed_out:
			await ctx.send("mod.unmute.response", member=member, user=member)
		elif cases:
			await ctx.send("mod.unmute.timeout_already_removed", member=member, user=member)
		elif was_timed_out:
			await member.edit(timed_out_until=None, reason=f"Unmuted by {ctx.author}")
			await ctx.send("mod.unmute.no_case", member=member, user=member)
		else:
			await ctx.send("mod.unmute.errors.not_muted", member=member, user=member)

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
		await self.cases.open(kick)

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
		await self.cases.open(ban)

		await ctx.send("mod.ban.response", ban=ban)

	@command(user=False, permissions=["ban_members"])
	async def unban(self, ctx: Context, user: discord.User):
		assert ctx.guild is not None
		cases = await self.cases.active(ctx.guild, user, CaseType.BAN)
		for case in cases:
			await self.cases.close(case)  # Ban.before_deletion lifts the ban
		if not cases:
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
	def __init__(self, client: Bot, cases: CaseStore) -> None:
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "mod")
		self.cases = cases

	@group(user=False, l10n_key="caseinfo", name="case")
	async def case(self, ctx: Context, case_id: str):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		try:
			fetched_case_id = int(case_id)
		except ValueError:
			raise commands.BadArgument

		case = await self.cases.get(ctx.guild, fetched_case_id)
		if case is None:
			await ctx.send("mod.info.errors.not_found", case_id=fetched_case_id)
			return

		if case._user.id != ctx.author.id and not ctx.author.guild_permissions.moderate_members:
			raise commands.MissingPermissions(["moderate_members"])

		await ctx.send("mod.info.response", case=case)

	@case.command(user=False, permissions=["moderate_members"], l10n_key="casedel")
	async def delete(self, ctx: Context, case_id: str):
		assert ctx.guild is not None
		fetched_case_id = _parse_case_id(case_id)
		case = await self.cases.get(ctx.guild, fetched_case_id)
		if case is None:
			await ctx.send("mod.delete.errors.not_found", case_id=fetched_case_id)
			return

		await self.cases.delete(case)
		await ctx.send("mod.delete.response", case=case)

	@case.command(user=False, permissions=["moderate_members"], l10n_key="caserem")
	async def remove(self, ctx: Context, case_id: str):
		assert ctx.guild is not None
		fetched_case_id = _parse_case_id(case_id)
		case = await self.cases.get(ctx.guild, fetched_case_id)
		if case is None:
			await ctx.send("mod.remove.errors.not_found", case_id=fetched_case_id)
			return

		outcome = await self.cases.close(case)
		await ctx.send("mod.delete.response" if outcome == "deleted" else "mod.remove.response", case=case)

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
		fetched_case_id = _parse_case_id(case_id)
		case = await self.cases.get(ctx.guild, fetched_case_id)
		if case is None:
			await ctx.send("mod.edit.errors.not_found", case_id=fetched_case_id)
			return

		if value == "expires":
			try:
				expires = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(
					seconds=text_to_seconds(new_value)
				)
			except (ValueError, TypeError):
				await ctx.send("mod.edit.errors.invalid_time", case_id=fetched_case_id)
				return
			await self.cases.edit(case, expires=expires)
		elif value == "reason":
			await self.cases.edit(case, reason=new_value)
		else:
			await self.cases.edit(case, message=new_value)

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

		effective_filter: CaseStatus = filter or ("all" if is_moderator else "active")
		if effective_filter not in ("active", "expired", "all"):
			raise commands.BadArgument("Filter must be 'active', 'expired', or 'all'.")

		cases = await self.cases.for_user(ctx.guild, target_user, effective_filter)

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
	retention = RetentionCache(client.db)
	cases = CaseStore(client, client.db, retention.get)
	await client.add_cog(Moderation(client, cases, retention))
	await client.add_cog(Cases(client, cases))
