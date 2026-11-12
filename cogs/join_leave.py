from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

import discord
from args.channel import convert_to_custom_channel
from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.member import Member
from discord.ext import commands
from discord.ext.localization import CustomFormatter
from helpers.custom_response import KWARG_MAPPING

if TYPE_CHECKING:
	import asyncpg
	from core import Bot
	from core.settings import GuildSetting

logger = logging.getLogger(__name__)


async def _load_join_config(db: asyncpg.Pool, guild_id: int) -> dict[str, Any] | None:
	row = await db.fetchrow("SELECT * FROM join_config WHERE guild_id = $1", guild_id)
	return dict(row) if row else None


async def _load_leave_config(db: asyncpg.Pool, guild_id: int) -> dict[str, Any] | None:
	row = await db.fetchrow("SELECT * FROM leave_config WHERE guild_id = $1", guild_id)
	return dict(row) if row else None


class JoinLeave(commands.Cog, name="JoinLeave"):
	def __init__(self, client: Bot):
		self.client = client
		self.join: GuildSetting[dict[str, Any] | None] = client.settings.add("join", _load_join_config)
		self.leave: GuildSetting[dict[str, Any] | None] = client.settings.add("leave", _load_leave_config)

	async def get_join_config(self, guild_id: int) -> dict[str, Any] | None:
		return await self.join.get(guild_id)

	async def get_leave_config(self, guild_id: int) -> dict[str, Any] | None:
		return await self.leave.get(guild_id)

	async def set_join(self, guild_id: int, channel_id: int | None, message: str | None = None) -> None:
		if message:
			await self.client.db.execute(
				"""
				INSERT INTO join_config (guild_id, is_on, channel, message)
				VALUES ($1, true, $2, $3)
				ON CONFLICT (guild_id) DO UPDATE
				SET is_on = true, channel = COALESCE($2, join_config.channel), message = $3
				""",
				guild_id,
				channel_id,
				message,
			)
		else:
			await self.client.db.execute(
				"""
				INSERT INTO join_config (guild_id, is_on, channel)
				VALUES ($1, true, $2)
				ON CONFLICT (guild_id) DO UPDATE
				SET is_on = true, channel = COALESCE($2, join_config.channel)
				""",
				guild_id,
				channel_id,
			)
		await self.join.changed(guild_id)

	async def set_leave(self, guild_id: int, channel_id: int | None, message: str | None = None) -> None:
		if message:
			await self.client.db.execute(
				"""
				INSERT INTO leave_config (guild_id, is_on, channel, message)
				VALUES ($1, true, $2, $3)
				ON CONFLICT (guild_id) DO UPDATE
				SET is_on = true, channel = COALESCE($2, leave_config.channel), message = $3
				""",
				guild_id,
				channel_id,
				message,
			)
		else:
			await self.client.db.execute(
				"""
				INSERT INTO leave_config (guild_id, is_on, channel)
				VALUES ($1, true, $2)
				ON CONFLICT (guild_id) DO UPDATE
				SET is_on = true, channel = COALESCE($2, leave_config.channel)
				""",
				guild_id,
				channel_id,
			)
		await self.leave.changed(guild_id)

	async def disable_join(self, guild_id: int) -> None:
		await self.client.db.execute("UPDATE join_config SET is_on = false WHERE guild_id = $1", guild_id)
		await self.join.changed(guild_id)

	async def disable_leave(self, guild_id: int) -> None:
		await self.client.db.execute("UPDATE leave_config SET is_on = false WHERE guild_id = $1", guild_id)
		await self.leave.changed(guild_id)

	async def set_join_message(self, guild_id: int, channel_id: int, message: str) -> None:
		await self.client.db.execute(
			"""
			INSERT INTO join_config (guild_id, is_on, channel, message)
			VALUES ($1, true, $2, $3)
			ON CONFLICT (guild_id) DO UPDATE SET message = $3
			""",
			guild_id,
			channel_id,
			message,
		)
		await self.join.changed(guild_id)

	async def set_leave_message(self, guild_id: int, channel_id: int, message: str) -> None:
		await self.client.db.execute(
			"""
			INSERT INTO leave_config (guild_id, is_on, channel, message)
			VALUES ($1, true, $2, $3)
			ON CONFLICT (guild_id) DO UPDATE SET message = $3
			""",
			guild_id,
			channel_id,
			message,
		)
		await self.leave.changed(guild_id)

	def format_message(
		self, template: str, member: discord.Member, channel: discord.abc.Messageable | None = None, **extra: Any
	) -> str:
		try:
			formatter = CustomFormatter()
			member_arg = Member.from_member(member)
			guild_arg = Guild.from_guild(member.guild) if member.guild else None
			channel_arg = (
				convert_to_custom_channel(channel)
				if isinstance(channel, (discord.abc.GuildChannel, discord.Thread))
				else None
			)

			format_kwargs: dict[str, Any] = {
				"member": member_arg,
				"user": member_arg,
				"author": member_arg,
				"guild": guild_arg,
				"server": guild_arg,
				"channel": channel_arg,
				"now": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
				"username": member.name,
				"member_count": member.guild.member_count if member.guild else 1,
			}
			for k, v in extra.items():
				for _type, converter in KWARG_MAPPING.items():
					if isinstance(v, _type):
						format_kwargs[k] = converter(v)
						break
				else:
					if isinstance(v, datetime.datetime):
						format_kwargs[k] = FormatDateTime(v, default_style="F")
					elif isinstance(v, (discord.abc.GuildChannel, discord.Thread)):
						format_kwargs[k] = convert_to_custom_channel(v)
					else:
						format_kwargs[k] = v

			return formatter.format(template, **format_kwargs)
		except Exception as e:  # noqa: BLE001
			logger.warning(f"Failed to format member event template '{template}': {e}")
			return template

	@commands.Cog.listener()
	async def on_member_join(self, member: discord.Member):
		if member.bot:
			return

		cfg = await self.get_join_config(member.guild.id)
		if not cfg or not cfg.get("is_on") or not cfg.get("channel") or not cfg.get("message"):
			return

		channel_id = int(cfg["channel"])
		channel = member.guild.get_channel(channel_id)
		if not channel or not isinstance(channel, discord.abc.Messageable):
			return

		content = self.format_message(str(cfg["message"]), member, channel=channel)

		try:
			await channel.send(content)
		except (discord.Forbidden, discord.HTTPException):
			logger.debug(f"Failed to send join message in {channel_id} for guild {member.guild.id}")

	@commands.Cog.listener()
	async def on_member_remove(self, member: discord.Member):
		if member.bot:
			return

		cfg = await self.get_leave_config(member.guild.id)
		if not cfg or not cfg.get("is_on") or not cfg.get("channel") or not cfg.get("message"):
			return

		channel_id = int(cfg["channel"])
		channel = member.guild.get_channel(channel_id)
		if not channel or not isinstance(channel, discord.abc.Messageable):
			return

		content = self.format_message(str(cfg["message"]), member, channel=channel)

		try:
			await channel.send(content)
		except (discord.Forbidden, discord.HTTPException):
			logger.debug(f"Failed to send leave message in {channel_id} for guild {member.guild.id}")


async def setup(client: Bot):
	await client.add_cog(JoinLeave(client))
