"""CLI subcommands for configuring the server leveling system."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_channel, resolve_role

if TYPE_CHECKING:
	from core import Context


def setup_level_subcommands(parent_node: CLINode) -> CLINode:
	"""Set up leveling configuration subcommands on the CLI parser root.

	Args:
		parent_node: The parent CLINode to attach the 'level' subcommand to.

	Returns:
		CLINode: The configured level CLINode.
	"""
	level_node = parent_node.create_subcommand("level", description="Configure server leveling system.")

	# --- Enable ---
	enable_node = level_node.create_subcommand("enable", description="Enable leveling system.")

	async def level_enable(ctx: Context, **kwargs: Any):
		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.enable_leveling(ctx.guild.id)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_config (guild_id, is_on)
				VALUES ($1, true)
				ON CONFLICT (guild_id) DO UPDATE SET is_on = true
				""",
				ctx.guild.id,
			)
		return await ctx.send(content="```ansi\n[+] Leveling system enabled\n```")

	enable_node.callback = level_enable

	# --- Disable ---
	disable_node = level_node.create_subcommand("disable", description="Disable leveling system.")

	async def level_disable(ctx: Context, **kwargs: Any):
		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.disable_leveling(ctx.guild.id)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_config (guild_id, is_on)
				VALUES ($1, false)
				ON CONFLICT (guild_id) DO UPDATE SET is_on = false
				""",
				ctx.guild.id,
			)
		return await ctx.send(content="```ansi\n[-] Leveling system disabled\n```")

	disable_node.callback = level_disable

	# --- XP Settings ---
	xp_node = level_node.create_subcommand("xp", description="Configure XP gain rates, limits, and cooldown.")
	xp_node.add_option("min", "n", help="Minimum XP per message (e.g. 15)")
	xp_node.add_option("max", "x", help="Maximum XP per message (e.g. 25)")
	xp_node.add_option("multiplier", "m", help="Global guild XP multiplier (e.g. 1.0, 1.5, 2.0)")
	xp_node.add_option("cooldown", "c", help="Cooldown in seconds between XP gain (e.g. 60)")

	async def level_xp(
		ctx: Context,
		min: str | None = None,
		max: str | None = None,
		multiplier: str | None = None,
		cooldown: str | None = None,
		**kwargs: Any,
	):
		if min is None and max is None and multiplier is None and cooldown is None:
			raise CLIParseError(
				"Please specify at least one option: `--min`, `--max`, `--multiplier`, or `--cooldown`.", xp_node
			)

		min_val: int | None = None
		max_val: int | None = None
		mult_val: float | None = None
		cd_val: int | None = None

		if min is not None:
			try:
				min_val = int(min)
				if min_val < 1:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--min` must be a positive integer greater than 0.", xp_node)

		if max is not None:
			try:
				max_val = int(max)
				if max_val < 1:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--max` must be a positive integer greater than 0.", xp_node)

		if multiplier is not None:
			try:
				mult_val = float(multiplier)
				if mult_val <= 0:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--multiplier` must be a positive number greater than 0.", xp_node)

		if cooldown is not None:
			try:
				cd_val = int(cooldown)
				if cd_val < 0:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--cooldown` must be a non-negative integer.", xp_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			cfg = await cog.get_guild_config(ctx.guild.id)
			cur_min = min_val if min_val is not None else cfg.min_xp
			cur_max = max_val if max_val is not None else cfg.max_xp
			if cur_min > cur_max:
				raise CLIParseError(f"Minimum XP ({cur_min}) cannot be greater than Maximum XP ({cur_max}).", xp_node)

			await cog.update_xp_config(
				ctx.guild.id, min_xp=min_val, max_xp=max_val, multiplier=mult_val, cooldown=cd_val
			)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_config (guild_id, min_xp, max_xp, multiplier, cooldown)
				VALUES ($1, COALESCE($2, 15), COALESCE($3, 25), COALESCE($4, 1.0), COALESCE($5, 60))
				ON CONFLICT (guild_id) DO UPDATE SET
					min_xp = COALESCE($2, level_config.min_xp),
					max_xp = COALESCE($3, level_config.max_xp),
					multiplier = COALESCE($4, level_config.multiplier),
					cooldown = COALESCE($5, level_config.cooldown)
				""",
				ctx.guild.id,
				min_val,
				max_val,
				mult_val,
				cd_val,
			)

		lines = ["[+] Leveling XP configuration updated:"]
		if min_val is not None:
			lines.append(f"  Minimum XP: {min_val}")
		if max_val is not None:
			lines.append(f"  Maximum XP: {max_val}")
		if mult_val is not None:
			lines.append(f"  Multiplier: {mult_val}x")
		if cd_val is not None:
			lines.append(f"  Cooldown: {cd_val}s")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	xp_node.callback = level_xp

	# --- Level-up Message ---
	msg_node = level_node.create_subcommand("message", description="Configure level-up announcements.")
	msg_node.add_option("mode", "m", help="Delivery mode: `current`, `channel`, or `disabled`")
	msg_node.add_option("channel", "c", help="Target channel when mode is `channel`")
	msg_node.add_option(
		"template", "t", help="Level-up message template (e.g. 'GG {user}, you reached level {level}!')"
	)
	msg_node.add_argument("template_pos", nargs="*", required=False, help="Message template positional argument")

	async def level_message(
		ctx: Context,
		mode: str | None = None,
		channel: str | None = None,
		template: str | None = None,
		template_pos: list[str] | None = None,
		**kwargs: Any,
	):
		tmpl_text = template or (" ".join(template_pos) if template_pos else None)

		if mode is None and channel is None and tmpl_text is None:
			raise CLIParseError("Please specify at least one option: `--mode`, `--channel`, or `--template`.", msg_node)

		mode_clean = mode.lower().strip() if mode else None
		if mode_clean and mode_clean not in {"current", "channel", "disabled"}:
			raise CLIParseError("Invalid mode. Choose `current`, `channel`, or `disabled`.", msg_node)

		target_channel: discord.abc.GuildChannel | discord.Thread | None = None
		if channel:
			target_channel = resolve_channel(ctx.guild, channel)
			if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
				raise CLIParseError(f"Channel `{channel}` was not found or is not a valid text channel.", msg_node)
			if mode_clean is None:
				mode_clean = "channel"

		cog: Any = ctx.bot.get_cog("Level")
		ch_id = target_channel.id if target_channel else None
		if cog:
			await cog.update_message_config(ctx.guild.id, mode=mode_clean, channel_id=ch_id, template=tmpl_text)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_config (guild_id, message_mode, message_channel, levelup_message)
				VALUES ($1, COALESCE($2, 'current'), $3, $4)
				ON CONFLICT (guild_id) DO UPDATE SET
					message_mode = COALESCE($2, level_config.message_mode),
					message_channel = COALESCE($3, level_config.message_channel),
					levelup_message = COALESCE($4, level_config.levelup_message)
				""",
				ctx.guild.id,
				mode_clean,
				ch_id,
				tmpl_text,
			)

		lines = ["[+] Level-up message configuration updated:"]
		if mode_clean:
			lines.append(f"  Mode: {mode_clean}")
		if target_channel:
			lines.append(f"  Channel: #{target_channel.name}")
		if tmpl_text:
			lines.append(f"  Template: {tmpl_text}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	msg_node.callback = level_message

	# --- Rewards ---
	rewards_node = level_node.create_subcommand("rewards", description="Configure role rewards for reaching levels.")

	# rewards add <level> <role>
	rewards_add_node = rewards_node.create_subcommand("add", description="Add a role reward for a level.")
	rewards_add_node.add_argument("level", required=True, help="Level required for the role reward")
	rewards_add_node.add_argument("role", required=True, help="Target role mention, ID, or name")

	async def rewards_add(ctx: Context, level: str | None = None, role: str | None = None, **kwargs: Any):
		if not level or not role:
			raise CLIParseError("Usage: `config level rewards add <level> <role>`", rewards_add_node)

		try:
			lvl_int = int(level)
			if lvl_int < 1:
				raise ValueError
		except ValueError:
			raise CLIParseError("Level must be a positive integer greater than 0.", rewards_add_node)

		target_role = resolve_role(ctx.guild, role)
		if not target_role:
			raise CLIParseError(f"Role `{role}` was not found.", rewards_add_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.add_role_reward(ctx.guild.id, lvl_int, target_role.id)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_roles (guild_id, level, role_id)
				VALUES ($1, $2, $3)
				ON CONFLICT (guild_id, level, role_id) DO NOTHING
				""",
				ctx.guild.id,
				lvl_int,
				target_role.id,
			)

		return await ctx.send(content=f"```ansi\n[+] Added reward: @{target_role.name} at Level {lvl_int}\n```")

	rewards_add_node.callback = rewards_add

	# rewards remove <level> [role]
	rewards_rm_node = rewards_node.create_subcommand("remove", description="Remove a role reward for a level.")
	rewards_rm_node.add_argument("level", required=True, help="Level to remove role reward for")
	rewards_rm_node.add_argument("role", required=False, help="Optional specific role to remove")

	async def rewards_remove(ctx: Context, level: str | None = None, role: str | None = None, **kwargs: Any):
		if not level:
			raise CLIParseError("Usage: `config level rewards remove <level> [role]`", rewards_rm_node)

		try:
			lvl_int = int(level)
		except ValueError:
			raise CLIParseError("Level must be a valid integer.", rewards_rm_node)

		target_role = resolve_role(ctx.guild, role) if role else None
		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.remove_role_reward(ctx.guild.id, lvl_int, target_role.id if target_role else None)
		else:
			if target_role:
				await ctx.bot.db.execute(
					"DELETE FROM level_roles WHERE guild_id = $1 AND level = $2 AND role_id = $3",
					ctx.guild.id,
					lvl_int,
					target_role.id,
				)
			else:
				await ctx.bot.db.execute(
					"DELETE FROM level_roles WHERE guild_id = $1 AND level = $2", ctx.guild.id, lvl_int
				)

		return await ctx.send(content=f"```ansi\n[-] Removed role reward(s) for Level {lvl_int}\n```")

	rewards_rm_node.callback = rewards_remove

	# rewards stack <true|false>
	rewards_stack_node = rewards_node.create_subcommand(
		"stack", description="Set whether role rewards stack or replace previous rewards."
	)
	rewards_stack_node.add_argument("stack", required=True, help="`true` (stack rewards) or `false` (replace previous)")

	async def rewards_stack(ctx: Context, stack: str | None = None, **kwargs: Any):
		if stack is None or stack.lower() not in {"true", "false", "yes", "no", "1", "0"}:
			raise CLIParseError("Please specify `true` (stack) or `false` (replace previous).", rewards_stack_node)

		is_stack = stack.lower() in {"true", "yes", "1"}
		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_stack_roles(ctx.guild.id, is_stack)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_config (guild_id, stack_roles)
				VALUES ($1, $2)
				ON CONFLICT (guild_id) DO UPDATE SET stack_roles = $2
				""",
				ctx.guild.id,
				is_stack,
			)

		mode_str = (
			"Stackable (keep all previous unlocked roles)"
			if is_stack
			else "Replace previous (keep only highest unlocked role)"
		)
		return await ctx.send(content=f"```ansi\n[+] Role reward mode set to: {mode_str}\n```")

	rewards_stack_node.callback = rewards_stack

	# rewards list
	rewards_list_node = rewards_node.create_subcommand("list", description="List all configured role rewards.")

	async def rewards_list(ctx: Context, **kwargs: Any):
		rows = await ctx.bot.db.fetch(
			"SELECT level, role_id FROM level_roles WHERE guild_id = $1 ORDER BY level ASC", ctx.guild.id
		)
		if not rows:
			return await ctx.send(content="```ansi\n[!] No role rewards configured for this server.\n```")

		lines = ["[+] Level Role Rewards:"]
		for r in rows:
			role_obj = ctx.guild.get_role(int(r["role_id"]))
			role_name = f"@{role_obj.name}" if role_obj else f"(Deleted role ID: {r['role_id']})"
			lines.append(f"  Level {r['level']}: {role_name}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	rewards_list_node.callback = rewards_list

	# --- Channel Overrides (Ignore / Multiplier) ---
	channel_node = level_node.create_subcommand("channel", description="Configure channel XP ignores and multipliers.")

	# channel ignore <channel>
	ch_ignore_node = channel_node.create_subcommand("ignore", description="Ignore a channel from earning XP.")
	ch_ignore_node.add_argument("channel", required=True, help="Target channel to ignore")

	async def channel_ignore(ctx: Context, channel: str | None = None, **kwargs: Any):
		if not channel:
			raise CLIParseError("Usage: `config level channel ignore <channel>`", ch_ignore_node)
		target_channel = resolve_channel(ctx.guild, channel)
		if not target_channel:
			raise CLIParseError(f"Channel `{channel}` was not found.", ch_ignore_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_channel_ignored(ctx.guild.id, target_channel.id, True)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_channel_overrides (guild_id, channel_id, is_ignored)
				VALUES ($1, $2, true)
				ON CONFLICT (guild_id, channel_id) DO UPDATE SET is_ignored = true
				""",
				ctx.guild.id,
				target_channel.id,
			)

		return await ctx.send(content=f"```ansi\n[-] Ignored channel #{target_channel.name} from earning XP\n```")

	ch_ignore_node.callback = channel_ignore

	# channel unignore <channel>
	ch_unignore_node = channel_node.create_subcommand("unignore", description="Allow a channel to earn XP again.")
	ch_unignore_node.add_argument("channel", required=True, help="Target channel to unignore")

	async def channel_unignore(ctx: Context, channel: str | None = None, **kwargs: Any):
		if not channel:
			raise CLIParseError("Usage: `config level channel unignore <channel>`", ch_unignore_node)
		target_channel = resolve_channel(ctx.guild, channel)
		if not target_channel:
			raise CLIParseError(f"Channel `{channel}` was not found.", ch_unignore_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_channel_ignored(ctx.guild.id, target_channel.id, False)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_channel_overrides (guild_id, channel_id, is_ignored)
				VALUES ($1, $2, false)
				ON CONFLICT (guild_id, channel_id) DO UPDATE SET is_ignored = false
				""",
				ctx.guild.id,
				target_channel.id,
			)

		return await ctx.send(content=f"```ansi\n[+] Unignored channel #{target_channel.name}\n```")

	ch_unignore_node.callback = channel_unignore

	# channel multiplier <channel> <multiplier>
	ch_mult_node = channel_node.create_subcommand("multiplier", description="Set a custom XP multiplier for a channel.")
	ch_mult_node.add_argument("channel", required=True, help="Target channel")
	ch_mult_node.add_argument("multiplier", required=True, help="XP multiplier for this channel (e.g. 1.5, 2.0)")

	async def channel_multiplier(
		ctx: Context, channel: str | None = None, multiplier: str | None = None, **kwargs: Any
	):
		if not channel or not multiplier:
			raise CLIParseError("Usage: `config level channel multiplier <channel> <multiplier>`", ch_mult_node)
		target_channel = resolve_channel(ctx.guild, channel)
		if not target_channel:
			raise CLIParseError(f"Channel `{channel}` was not found.", ch_mult_node)

		try:
			mult_val = float(multiplier)
			if mult_val <= 0:
				raise ValueError
		except ValueError:
			raise CLIParseError("Multiplier must be a positive number.", ch_mult_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_channel_multiplier(ctx.guild.id, target_channel.id, mult_val)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_channel_overrides (guild_id, channel_id, multiplier)
				VALUES ($1, $2, $3)
				ON CONFLICT (guild_id, channel_id) DO UPDATE SET multiplier = $3
				""",
				ctx.guild.id,
				target_channel.id,
				mult_val,
			)

		return await ctx.send(content=f"```ansi\n[+] XP multiplier in #{target_channel.name} set to {mult_val}x\n```")

	ch_mult_node.callback = channel_multiplier

	# channel list
	ch_list_node = channel_node.create_subcommand("list", description="List channel XP overrides.")

	async def channel_list(ctx: Context, **kwargs: Any):
		rows = await ctx.bot.db.fetch(
			"SELECT channel_id, multiplier, is_ignored FROM level_channel_overrides WHERE guild_id = $1", ctx.guild.id
		)
		if not rows:
			return await ctx.send(content="```ansi\n[!] No channel overrides configured for this server.\n```")

		lines = ["[+] Channel Overrides:"]
		for r in rows:
			ch_obj = ctx.guild.get_channel_or_thread(int(r["channel_id"]))
			ch_name = f"#{ch_obj.name}" if ch_obj else f"(Unknown channel ID: {r['channel_id']})"
			status_parts = []
			if r["is_ignored"]:
				status_parts.append("IGNORED")
			if float(r["multiplier"]) != 1.0:
				status_parts.append(f"{float(r['multiplier'])}x multiplier")
			lines.append(f"  {ch_name}: {', '.join(status_parts) if status_parts else 'Normal'}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	ch_list_node.callback = channel_list

	# --- Role Overrides (Ignore / Multiplier) ---
	role_node = level_node.create_subcommand("role", description="Configure role XP ignores and multipliers.")

	# role ignore <role>
	role_ignore_node = role_node.create_subcommand("ignore", description="Ignore members with a role from earning XP.")
	role_ignore_node.add_argument("role", required=True, help="Target role")

	async def role_ignore(ctx: Context, role: str | None = None, **kwargs: Any):
		if not role:
			raise CLIParseError("Usage: `config level role ignore <role>`", role_ignore_node)
		target_role = resolve_role(ctx.guild, role)
		if not target_role:
			raise CLIParseError(f"Role `{role}` was not found.", role_ignore_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_role_ignored(ctx.guild.id, target_role.id, True)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_role_overrides (guild_id, role_id, is_ignored)
				VALUES ($1, $2, true)
				ON CONFLICT (guild_id, role_id) DO UPDATE SET is_ignored = true
				""",
				ctx.guild.id,
				target_role.id,
			)

		return await ctx.send(content=f"```ansi\n[-] Ignored role @{target_role.name} from earning XP\n```")

	role_ignore_node.callback = role_ignore

	# role unignore <role>
	role_unignore_node = role_node.create_subcommand("unignore", description="Allow members with a role to earn XP.")
	role_unignore_node.add_argument("role", required=True, help="Target role")

	async def role_unignore(ctx: Context, role: str | None = None, **kwargs: Any):
		if not role:
			raise CLIParseError("Usage: `config level role unignore <role>`", role_unignore_node)
		target_role = resolve_role(ctx.guild, role)
		if not target_role:
			raise CLIParseError(f"Role `{role}` was not found.", role_unignore_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_role_ignored(ctx.guild.id, target_role.id, False)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_role_overrides (guild_id, role_id, is_ignored)
				VALUES ($1, $2, false)
				ON CONFLICT (guild_id, role_id) DO UPDATE SET is_ignored = false
				""",
				ctx.guild.id,
				target_role.id,
			)

		return await ctx.send(content=f"```ansi\n[+] Unignored role @{target_role.name}\n```")

	role_unignore_node.callback = role_unignore

	# role multiplier <role> <multiplier>
	role_mult_node = role_node.create_subcommand("multiplier", description="Set a custom XP multiplier for a role.")
	role_mult_node.add_argument("role", required=True, help="Target role")
	role_mult_node.add_argument("multiplier", required=True, help="XP multiplier for this role (e.g. 1.5, 2.0)")

	async def role_multiplier(ctx: Context, role: str | None = None, multiplier: str | None = None, **kwargs: Any):
		if not role or not multiplier:
			raise CLIParseError("Usage: `config level role multiplier <role> <multiplier>`", role_mult_node)
		target_role = resolve_role(ctx.guild, role)
		if not target_role:
			raise CLIParseError(f"Role `{role}` was not found.", role_mult_node)

		try:
			mult_val = float(multiplier)
			if mult_val <= 0:
				raise ValueError
		except ValueError:
			raise CLIParseError("Multiplier must be a positive number.", role_mult_node)

		cog: Any = ctx.bot.get_cog("Level")
		if cog:
			await cog.set_role_multiplier(ctx.guild.id, target_role.id, mult_val)
		else:
			await ctx.bot.db.execute(
				"""
				INSERT INTO level_role_overrides (guild_id, role_id, multiplier)
				VALUES ($1, $2, $3)
				ON CONFLICT (guild_id, role_id) DO UPDATE SET multiplier = $3
				""",
				ctx.guild.id,
				target_role.id,
				mult_val,
			)

		return await ctx.send(content=f"```ansi\n[+] XP multiplier for @{target_role.name} set to {mult_val}x\n```")

	role_mult_node.callback = role_multiplier

	# role list
	role_list_node = role_node.create_subcommand("list", description="List role XP overrides.")

	async def role_list(ctx: Context, **kwargs: Any):
		rows = await ctx.bot.db.fetch(
			"SELECT role_id, multiplier, is_ignored FROM level_role_overrides WHERE guild_id = $1", ctx.guild.id
		)
		if not rows:
			return await ctx.send(content="```ansi\n[!] No role overrides configured for this server.\n```")

		lines = ["[+] Role Overrides:"]
		for r in rows:
			role_obj = ctx.guild.get_role(int(r["role_id"]))
			role_name = f"@{role_obj.name}" if role_obj else f"(Unknown role ID: {r['role_id']})"
			status_parts = []
			if r["is_ignored"]:
				status_parts.append("IGNORED")
			if float(r["multiplier"]) != 1.0:
				status_parts.append(f"{float(r['multiplier'])}x multiplier")
			lines.append(f"  {role_name}: {', '.join(status_parts) if status_parts else 'Normal'}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	role_list_node.callback = role_list

	# --- Show Full Config ---
	show_node = level_node.create_subcommand("show", description="Show full leveling configuration for this server.")

	async def level_show(ctx: Context, **kwargs: Any):
		cog: Any = ctx.bot.get_cog("Level")
		cfg = await cog.get_guild_config(ctx.guild.id) if cog else None

		if not cfg:
			row = await ctx.bot.db.fetchrow("SELECT * FROM level_config WHERE guild_id = $1", ctx.guild.id)
			is_on = row["is_on"] if row else True
			mult = float(row["multiplier"]) if row else 1.0
			min_xp = int(row["min_xp"]) if row else 15
			max_xp = int(row["max_xp"]) if row else 25
			cooldown = int(row["cooldown"]) if row else 60
			mode = row["message_mode"] if row else "current"
			ch_id = int(row["message_channel"]) if row and row["message_channel"] else None
			msg_tmpl = row["levelup_message"] if row and row["levelup_message"] else "(Default: localized)"
			stack = row["stack_roles"] if row else True
		else:
			is_on = cfg.is_on
			mult = cfg.multiplier
			min_xp = cfg.min_xp
			max_xp = cfg.max_xp
			cooldown = cfg.cooldown
			mode = cfg.message_mode
			ch_id = cfg.message_channel
			msg_tmpl = cfg.levelup_message if cfg.levelup_message else "(Default: localized)"
			stack = cfg.stack_roles

		ch_obj = ctx.guild.get_channel(ch_id) if ch_id else None
		ch_str = f"#{ch_obj.name}" if ch_obj else "(None)"
		mode_str = mode.value if hasattr(mode, "value") else str(mode)

		lines = [
			"=== Leveling System Configuration ===",
			f"Status:          {'Enabled' if is_on else 'Disabled'}",
			f"XP Range:        {min_xp} - {max_xp} XP",
			f"Global Mult:     {mult}x",
			f"Cooldown:        {cooldown}s",
			f"Level-up Mode:   {mode_str}",
			f"Target Channel:  {ch_str}",
			f"Message:         {msg_tmpl}",
			f"Role Stacking:   {'Enabled (stack)' if stack else 'Disabled (replace previous)'}",
		]
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	show_node.callback = level_show

	return level_node
