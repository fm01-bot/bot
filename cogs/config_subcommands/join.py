from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_channel

if TYPE_CHECKING:
	from core import Context


def setup_join_subcommands(parent_node: CLINode) -> CLINode:
	join_node = parent_node.create_subcommand("join", description="Configure member join messages.")

	enable_node = join_node.create_subcommand("enable", description="Enable member join messages.")
	enable_node.add_option("channel", "c", help="Target channel for join messages (e.g. #welcome)")
	enable_node.add_option("message", "m", help='Join message template (e.g. "Welcome {user} to {guild}!")')
	enable_node.add_argument("channel_pos", required=False, help="Target channel positional argument")

	async def join_enable(
		ctx: Context,
		channel: str | None = None,
		message: str | None = None,
		channel_pos: str | None = None,
		**kwargs: Any,
	):
		ch_raw = channel or channel_pos
		target_channel: discord.abc.GuildChannel | discord.Thread | None = None

		if ch_raw:
			target_channel = resolve_channel(ctx.guild, ch_raw)
			if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
				raise CLIParseError(f"Channel `{ch_raw}` was not found or is not a valid text channel.", enable_node)
		else:
			row = await ctx.bot.db.fetchrow("SELECT channel FROM join_config WHERE guild_id = $1", ctx.guild.id)
			if row and row["channel"]:
				target_channel = ctx.guild.get_channel(int(row["channel"]))
			if not target_channel:
				target_channel = ctx.channel

		channel_id = target_channel.id if target_channel else None

		join_leave_cog: Any = ctx.bot.get_cog("JoinLeave")
		if join_leave_cog:
			await join_leave_cog.set_join(ctx.guild.id, channel_id, message)
		else:
			if message:
				await ctx.bot.db.execute(
					"""
					INSERT INTO join_config (guild_id, is_on, channel, message)
					VALUES ($1, true, $2, $3)
					ON CONFLICT (guild_id) DO UPDATE
					SET is_on = true, channel = COALESCE($2, join_config.channel), message = $3
					""",
					ctx.guild.id,
					channel_id,
					message,
				)
			else:
				await ctx.bot.db.execute(
					"""
					INSERT INTO join_config (guild_id, is_on, channel)
					VALUES ($1, true, $2)
					ON CONFLICT (guild_id) DO UPDATE
					SET is_on = true, channel = COALESCE($2, join_config.channel)
					""",
					ctx.guild.id,
					channel_id,
				)

		ch_name = f"#{target_channel.name}" if target_channel else "(unknown)"
		lines = [f"[+] Join messages enabled in {ch_name}"]
		if message:
			lines.append(f"Message: {message}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	enable_node.callback = join_enable

	disable_node = join_node.create_subcommand("disable", description="Disable member join messages.")

	async def join_disable(ctx: Context, **kwargs: Any):
		join_leave_cog: Any = ctx.bot.get_cog("JoinLeave")
		if join_leave_cog:
			await join_leave_cog.disable_join(ctx.guild.id)
		else:
			await ctx.bot.db.execute("UPDATE join_config SET is_on = false WHERE guild_id = $1", ctx.guild.id)
		return await ctx.send(content="```ansi\n[-] Join messages disabled\n```")

	disable_node.callback = join_disable

	msg_node = join_node.create_subcommand("message", description="Set the join message template.")
	msg_node.add_option("message", "m", help="Join message template")
	msg_node.add_argument("message_pos", nargs="*", required=False, help="Join message positional tokens")

	async def join_message(
		ctx: Context, message: str | None = None, message_pos: list[str] | None = None, **kwargs: Any
	):
		text = message or (" ".join(message_pos) if message_pos else None)
		if not text:
			raise CLIParseError('Please provide a message template via `--message "..."` or as arguments.', msg_node)

		join_leave_cog: Any = ctx.bot.get_cog("JoinLeave")
		if join_leave_cog:
			await join_leave_cog.set_join_message(ctx.guild.id, ctx.channel.id, text)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO join_config (guild_id, is_on, channel, message)
				VALUES ($1, true, $2, $3)
				ON CONFLICT (guild_id) DO UPDATE SET message = $3
				""",
				ctx.guild.id,
				ctx.channel.id,
				text,
			)

		return await ctx.send(content=f"```ansi\nJoin message template updated:\n{text}\n```")

	msg_node.callback = join_message

	status_node = join_node.create_subcommand("status", description="Show the current join configuration.")

	async def join_status(ctx: Context, **kwargs: Any):
		row = await ctx.bot.db.fetchrow("SELECT * FROM join_config WHERE guild_id = $1", ctx.guild.id)
		if not row:
			return await ctx.send(content="```ansi\nJoin messages are not configured for this server.\n```")

		is_on = bool(row["is_on"])
		ch_id = int(row["channel"]) if row["channel"] else None
		channel = ctx.guild.get_channel(ch_id) if ch_id else None
		ch_str = f"#{channel.name}" if channel else "(None)"
		msg_template = row["message"] or "(None)"

		content = (
			f"```ansi\n"
			f"Join Configuration ({ctx.guild.name})\n\n"
			f"Status: {'Enabled' if is_on else 'Disabled'}\n"
			f"Channel: {ch_str}\n"
			f"Template: {msg_template}\n"
			f"```"
		)
		return await ctx.send(content=content)

	status_node.callback = join_status

	return join_node
