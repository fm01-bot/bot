from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_channel

if TYPE_CHECKING:
	from core import Context


def setup_log_subcommands(parent_node: CLINode) -> CLINode:
	log_node = parent_node.create_subcommand("log", description="Configure server event logging.")

	enable_node = log_node.create_subcommand("enable", description="Enable logging in a channel.")
	enable_node.add_option("channel", "c", help="Target logging channel (e.g. #log or channel ID)")
	enable_node.add_argument("channel_pos", required=False, help="Target channel positional argument")

	async def log_enable(ctx: Context, channel: str | None = None, channel_pos: str | None = None, **kwargs: Any):
		ch_raw = channel or channel_pos
		target_channel: discord.abc.GuildChannel | discord.Thread | None = None

		if ch_raw:
			target_channel = resolve_channel(ctx.guild, ch_raw)
			if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
				raise CLIParseError(f"Channel `{ch_raw}` was not found or is not a valid text channel.", enable_node)
		else:
			logging_cog: Any = ctx.bot.get_cog("Logging")
			existing_cfg = logging_cog.get_config(ctx.guild.id) if logging_cog else None
			if existing_cfg and existing_cfg.channel_id:
				target_channel = ctx.guild.get_channel(existing_cfg.channel_id)
			if not target_channel:
				target_channel = ctx.channel

		channel_id = target_channel.id if target_channel else None

		logging_cog: Any = ctx.bot.get_cog("Logging")
		if logging_cog:
			await logging_cog.enable_log(ctx.guild.id, channel_id)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO log (guild_id, is_on, channel, modules, channels)
				VALUES ($1, true, $2, ARRAY['*'], '{}'::jsonb)
				ON CONFLICT (guild_id) DO UPDATE
				SET is_on = true, channel = COALESCE($2, log.channel)
				""",
				ctx.guild.id,
				channel_id,
			)

		ch_name = getattr(target_channel, "name", str(channel_id))
		return await ctx.send(content=f"```ansi\n[+] Logging enabled in #{ch_name}\n```")

	enable_node.callback = log_enable

	disable_node = log_node.create_subcommand("disable", description="Disable server logging.")

	async def log_disable(ctx: Context, **kwargs: Any):
		logging_cog: Any = ctx.bot.get_cog("Logging")
		if logging_cog:
			await logging_cog.disable_log(ctx.guild.id)
		else:
			await ctx.bot.db.execute("UPDATE log SET is_on = false WHERE guild_id = $1", ctx.guild.id)
		return await ctx.send(content="```ansi\n[-] Logging disabled\n```")

	disable_node.callback = log_disable

	channel_node = log_node.create_subcommand("channel", description="Set the default logging channel.")
	channel_node.add_option("channel", "c", help="Target channel")
	channel_node.add_argument("channel_pos", required=False, help="Target channel positional")

	async def log_channel(ctx: Context, channel: str | None = None, channel_pos: str | None = None, **kwargs: Any):
		ch_raw = channel or channel_pos
		if not ch_raw:
			raise CLIParseError("Please specify a channel via `--channel #name` or `#name`.", channel_node)
		target_channel = resolve_channel(ctx.guild, ch_raw)
		if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
			raise CLIParseError(f"Channel `{ch_raw}` was not found or is not a valid text channel.", channel_node)

		logging_cog: Any = ctx.bot.get_cog("Logging")
		if logging_cog:
			await logging_cog.set_default_channel(ctx.guild.id, target_channel.id)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO log (guild_id, is_on, channel, modules, channels)
				VALUES ($1, true, $2, ARRAY['*'], '{}'::jsonb)
				ON CONFLICT (guild_id) DO UPDATE SET channel = $2
				""",
				ctx.guild.id,
				target_channel.id,
			)
		ch_name = getattr(target_channel, "name", str(target_channel.id))
		return await ctx.send(content=f"```ansi\n[+] Default log channel set to #{ch_name}\n```")

	channel_node.callback = log_channel

	modules_node = log_node.create_subcommand("modules", description="Manage active logging event modules.")

	mod_enable_node = modules_node.create_subcommand("enable", description="Enable one or more event modules.")
	mod_enable_node.add_argument("modules", nargs="+", required=True, help="Names of the modules to enable")

	async def modules_enable(ctx: Context, modules: list[str], **kwargs: Any):
		logging_cog: Any = ctx.bot.get_cog("Logging")
		from cogs.log import LOG_MODULES

		valid_mods: list[str] = [m for m in modules if m in LOG_MODULES]
		invalid_mods: list[str] = [m for m in modules if m not in LOG_MODULES]

		if not valid_mods:
			avail_sample = ", ".join(list(LOG_MODULES)[:5])
			raise CLIParseError(
				f"None of the provided modules are valid: {', '.join(invalid_mods)}.\n"
				f"Example valid modules: {avail_sample} (use `modules list` to see all).",
				mod_enable_node,
			)

		for m in valid_mods:
			if logging_cog:
				await logging_cog.add_module(ctx.guild.id, m)
			else:
				await ctx.bot.db.execute(
					"""
					UPDATE log SET modules = array_append(array_remove(modules, $1), $1)
					WHERE guild_id = $2
					""",
					m,
					ctx.guild.id,
				)

		lines = [f"Enabled modules: {', '.join(valid_mods)}"]
		if invalid_mods:
			lines.append(f"Invalid modules: {', '.join(invalid_mods)}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	mod_enable_node.callback = modules_enable

	mod_disable_node = modules_node.create_subcommand("disable", description="Disable one or more event modules.")
	mod_disable_node.add_argument("modules", nargs="+", required=True, help="Names of the modules to disable")

	async def modules_disable(ctx: Context, modules: list[str], **kwargs: Any):
		logging_cog: Any = ctx.bot.get_cog("Logging")
		for m in modules:
			if logging_cog:
				await logging_cog.remove_module(ctx.guild.id, m)
			else:
				await ctx.bot.db.execute(
					"UPDATE log SET modules = array_remove(modules, $1) WHERE guild_id = $2", m, ctx.guild.id
				)
		return await ctx.send(content=f"```ansi\nDisabled modules: {', '.join(modules)}\n```")

	mod_disable_node.callback = modules_disable

	mod_list_node = modules_node.create_subcommand("list", description="List all available logging modules.")

	async def modules_list(ctx: Context, **kwargs: Any):
		logging_cog: Any = ctx.bot.get_cog("Logging")
		from cogs.log import LOG_MODULES

		cfg = await logging_cog._ensure_config(ctx.guild.id) if logging_cog else None
		enabled = cfg.modules if cfg else set()

		lines = [f"Logging Modules ({ctx.guild.name})\n"]
		for mod_name in sorted(LOG_MODULES):
			status = "[+]" if (mod_name in enabled or "*" in enabled) else "[-]"
			lines.append(f"{status} {mod_name}")

		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	mod_list_node.callback = modules_list

	status_node = log_node.create_subcommand("status", description="Show server logging status.")

	async def log_status(ctx: Context, **kwargs: Any):
		logging_cog: Any = ctx.bot.get_cog("Logging")
		cfg = await logging_cog._ensure_config(ctx.guild.id) if logging_cog else None

		if not cfg or not cfg.is_on:
			return await ctx.send(content="```ansi\nStatus: Disabled\n```")

		channel = ctx.guild.get_channel(cfg.channel_id) if cfg.channel_id else None
		ch_name = f"#{channel.name}" if channel else "None"
		active_count = len(cfg.modules)
		content = (
			f"```ansi\n"
			f"Logging Configuration ({ctx.guild.name})\n\n"
			f"Status:          Enabled\n"
			f"Default Channel: {ch_name}\n"
			f"Active Modules:  {active_count}\n"
			f"```"
		)
		return await ctx.send(content=content)

	status_node.callback = log_status

	return log_node
