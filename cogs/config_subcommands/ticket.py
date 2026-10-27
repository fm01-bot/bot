from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_category, resolve_channel, resolve_role

if TYPE_CHECKING:
	from core import Context


def setup_ticket_subcommands(parent_node: CLINode) -> CLINode:
	ticket_node = parent_node.create_subcommand("ticket", description="Configure support ticket system.")

	# enable subcommand
	enable_node = ticket_node.create_subcommand("enable", description="Enable support ticket system.")

	async def ticket_enable(ctx: Context, **kwargs: Any):
		assert ctx.guild is not None
		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, is_on)
			VALUES ($1, true)
			ON CONFLICT (guild_id) DO UPDATE SET is_on = true
			""",
			ctx.guild.id,
		)
		return await ctx.send(content="```ansi\n[+] Ticket system enabled\n```")

	enable_node.callback = ticket_enable

	# disable subcommand
	disable_node = ticket_node.create_subcommand("disable", description="Disable support ticket system.")

	async def ticket_disable(ctx: Context, **kwargs: Any):
		assert ctx.guild is not None
		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, is_on)
			VALUES ($1, false)
			ON CONFLICT (guild_id) DO UPDATE SET is_on = false
			""",
			ctx.guild.id,
		)
		return await ctx.send(content="```ansi\n[-] Ticket system disabled\n```")

	disable_node.callback = ticket_disable

	# panel subcommand
	panel_node = ticket_node.create_subcommand("panel", description="Deploy the ticket launcher button panel.")
	panel_node.add_option("channel", "c", help="Target channel for the panel (e.g. #tickets)")
	panel_node.add_option("title", "t", help="Custom panel embed title")
	panel_node.add_option("description", "d", help="Custom panel embed description")
	panel_node.add_option("button", "b", help="Custom button label text")
	panel_node.add_argument("channel_pos", required=False, help="Target channel positional argument")

	async def ticket_panel(
		ctx: Context,
		channel: str | None = None,
		title: str | None = None,
		description: str | None = None,
		button: str | None = None,
		channel_pos: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		ch_raw = channel or channel_pos
		target_channel: discord.abc.GuildChannel | discord.Thread | None = None

		if ch_raw:
			target_channel = resolve_channel(ctx.guild, ch_raw)
			if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
				raise CLIParseError(f"Channel `{ch_raw}` was not found or is not a valid text channel.", panel_node)
		else:
			if isinstance(ctx.channel, (discord.abc.GuildChannel, discord.Thread)) and isinstance(
				ctx.channel, discord.abc.Messageable
			):
				target_channel = ctx.channel

		if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
			raise CLIParseError("Target channel could not be resolved.", panel_node)

		# Check bot permissions in target channel
		if isinstance(target_channel, discord.TextChannel) and ctx.guild.me:
			perms = target_channel.permissions_for(ctx.guild.me)
			if not perms.send_messages or not perms.embed_links:
				raise CLIParseError(
					f"The bot is missing Send Messages or Embed Links permissions in #{target_channel.name}.",
					panel_node,
				)

		# Build embed and button
		ticket_cog: Any = ctx.bot.get_cog("Ticket")
		embed_title = title or "Support Tickets"
		embed_desc = description or "Need assistance? Click the button below to open a support ticket."
		button_label = button or "Open Ticket"

		embed = discord.Embed(
			title=embed_title,
			description=embed_desc,
			color=6656243,
			timestamp=discord.utils.utcnow(),
		)
		embed.set_footer(text="FightMan01 bot - Ticket System")

		if ticket_cog and hasattr(ticket_cog, "create_launcher_view"):
			view = ticket_cog.create_launcher_view(button_label=button_label)
		else:
			# Fallback import
			from cogs.ticket import TicketLauncherView

			view = TicketLauncherView(ctx.bot, button_label=button_label)

		await target_channel.send(embed=embed, view=view)
		ch_name = getattr(target_channel, "name", str(target_channel.id))
		return await ctx.send(content=f"```ansi\n[+] Ticket panel deployed in #{ch_name}\n```")

	panel_node.callback = ticket_panel

	# category subcommand
	cat_node = ticket_node.create_subcommand("category", description="Set or clear the category for ticket channels.")
	cat_node.add_option("category", "c", help="Category name or ID")
	cat_node.add_option("clear", is_flag=True, help="Clear custom category to use default 'Tickets' category")
	cat_node.add_argument("category_pos", required=False, help="Category positional argument")

	async def ticket_category(
		ctx: Context,
		category: str | None = None,
		category_pos: str | None = None,
		clear: bool = False,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		if clear:
			await ctx.bot.db.execute(
				"""
				INSERT INTO ticket_config (guild_id, category_id)
				VALUES ($1, NULL)
				ON CONFLICT (guild_id) DO UPDATE SET category_id = NULL
				""",
				ctx.guild.id,
			)
			return await ctx.send(
				content="```ansi\n[-] Ticket category cleared (will use default 'Tickets' category)\n```"
			)

		cat_raw = category or category_pos
		if not cat_raw:
			raise CLIParseError("Please specify a category via `--category <name|id>` or `--clear`.", cat_node)

		resolved = resolve_category(ctx.guild, cat_raw)
		if not resolved:
			raise CLIParseError(f"Category `{cat_raw}` was not found.", cat_node)

		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, category_id)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE SET category_id = $2
			""",
			ctx.guild.id,
			resolved.id,
		)
		return await ctx.send(content=f"```ansi\n[+] Ticket category set to '{resolved.name}'\n```")

	cat_node.callback = ticket_category

	# log subcommand
	log_node = ticket_node.create_subcommand("log", description="Set or disable the ticket log channel.")
	log_node.add_option("channel", "c", help="Channel name, mention, or ID for ticket logs")
	log_node.add_option("disable", is_flag=True, help="Disable ticket logging")
	log_node.add_argument("channel_pos", required=False, help="Channel positional argument")

	async def ticket_log(
		ctx: Context,
		channel: str | None = None,
		channel_pos: str | None = None,
		disable: bool = False,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		if disable:
			await ctx.bot.db.execute(
				"""
				INSERT INTO ticket_config (guild_id, log_channel_id)
				VALUES ($1, NULL)
				ON CONFLICT (guild_id) DO UPDATE SET log_channel_id = NULL
				""",
				ctx.guild.id,
			)
			return await ctx.send(content="```ansi\n[-] Ticket logging disabled\n```")

		ch_raw = channel or channel_pos
		if not ch_raw:
			raise CLIParseError("Please specify a channel via `--channel #log` or `--disable`.", log_node)

		resolved = resolve_channel(ctx.guild, ch_raw)
		if not resolved or not isinstance(resolved, discord.abc.Messageable):
			raise CLIParseError(f"Channel `{ch_raw}` was not found or is not a valid text channel.", log_node)

		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, log_channel_id)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE SET log_channel_id = $2
			""",
			ctx.guild.id,
			resolved.id,
		)
		ch_name = getattr(resolved, "name", str(resolved.id))
		return await ctx.send(content=f"```ansi\n[+] Ticket log channel set to #{ch_name}\n```")

	log_node.callback = ticket_log

	# role subcommand
	role_node = ticket_node.create_subcommand("role", description="Set or clear the support staff role.")
	role_node.add_option("role", "r", help="Role mention, name, or ID")
	role_node.add_option("clear", is_flag=True, help="Clear support staff role")
	role_node.add_argument("role_pos", required=False, help="Role positional argument")

	async def ticket_role(
		ctx: Context,
		role: str | None = None,
		role_pos: str | None = None,
		clear: bool = False,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		if clear:
			await ctx.bot.db.execute(
				"""
				INSERT INTO ticket_config (guild_id, support_role_id)
				VALUES ($1, NULL)
				ON CONFLICT (guild_id) DO UPDATE SET support_role_id = NULL
				""",
				ctx.guild.id,
			)
			return await ctx.send(content="```ansi\n[-] Support role cleared\n```")

		r_raw = role or role_pos
		if not r_raw:
			raise CLIParseError("Please specify a role via `--role @Role` or `--clear`.", role_node)

		resolved = resolve_role(ctx.guild, r_raw)
		if not resolved:
			raise CLIParseError(f"Role `{r_raw}` was not found.", role_node)

		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, support_role_id)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE SET support_role_id = $2
			""",
			ctx.guild.id,
			resolved.id,
		)
		return await ctx.send(content=f"```ansi\n[+] Support role set to @{resolved.name}\n```")

	role_node.callback = ticket_role

	# limit subcommand
	limit_node = ticket_node.create_subcommand("limit", description="Set max concurrent open tickets per user.")
	limit_node.add_option("max", "m", help="Max tickets (0 for unlimited, default 1)")
	limit_node.add_argument("max_pos", required=False, help="Max tickets positional argument")

	async def ticket_limit(
		ctx: Context,
		max: str | None = None,
		max_pos: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		val_raw = max or max_pos
		if val_raw is None:
			raise CLIParseError(
				"Please specify the maximum tickets allowed (e.g. `config ticket limit 2`).", limit_node
			)

		try:
			val = int(val_raw)
			if val < 0:
				raise ValueError
		except ValueError:
			raise CLIParseError("Maximum tickets must be a non-negative integer (0 for unlimited).", limit_node)

		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, max_tickets)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE SET max_tickets = $2
			""",
			ctx.guild.id,
			val,
		)
		limit_str = f"{val} ticket(s) per user" if val > 0 else "Unlimited"
		return await ctx.send(content=f"```ansi\n[+] Max concurrent tickets set to: {limit_str}\n```")

	limit_node.callback = ticket_limit

	# dm subcommand
	dm_node = ticket_node.create_subcommand("dm", description="Toggle sending DM transcripts to users upon close.")
	dm_node.add_option("enable", is_flag=True, help="Enable DM transcripts")
	dm_node.add_option("disable", is_flag=True, help="Disable DM transcripts")

	async def ticket_dm(ctx: Context, enable: bool = False, disable: bool = False, **kwargs: Any):
		assert ctx.guild is not None
		if enable and disable:
			raise CLIParseError("Cannot specify both `--enable` and `--disable`.", dm_node)
		if not enable and not disable:
			raise CLIParseError("Please specify `--enable` or `--disable`.", dm_node)

		new_val = bool(enable)
		await ctx.bot.db.execute(
			"""
			INSERT INTO ticket_config (guild_id, dm_transcript)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE SET dm_transcript = $2
			""",
			ctx.guild.id,
			new_val,
		)
		status_str = "enabled" if new_val else "disabled"
		return await ctx.send(content=f"```ansi\n[+] DM transcripts {status_str}\n```")

	dm_node.callback = ticket_dm

	# status subcommand
	status_node = ticket_node.create_subcommand("status", description="Show the current ticket configuration.")

	async def ticket_status(ctx: Context, **kwargs: Any):
		assert ctx.guild is not None
		row = await ctx.bot.db.fetchrow("SELECT * FROM ticket_config WHERE guild_id = $1", ctx.guild.id)
		if not row:
			is_on = True
			category_str = "(Default 'Tickets')"
			log_str = "(Disabled)"
			role_str = "(None - Administrators only)"
			limit_str = "1 per user"
			dm_str = "Enabled"
		else:
			is_on = bool(row["is_on"])
			cat_id = int(row["category_id"]) if row["category_id"] else None
			cat = ctx.guild.get_channel(cat_id) if cat_id else None
			category_str = cat.name if cat else "(Default 'Tickets')"

			log_id = int(row["log_channel_id"]) if row["log_channel_id"] else None
			log_ch = ctx.guild.get_channel(log_id) if log_id else None
			log_str = f"#{log_ch.name}" if log_ch else "(Disabled)"

			role_id = int(row["support_role_id"]) if row["support_role_id"] else None
			role = ctx.guild.get_role(role_id) if role_id else None
			role_str = f"@{role.name}" if role else "(None - Administrators only)"

			max_t = row["max_tickets"] if row["max_tickets"] is not None else 1
			limit_str = f"{max_t} per user" if max_t > 0 else "Unlimited"

			dm_t = bool(row["dm_transcript"]) if row["dm_transcript"] is not None else True
			dm_str = "Enabled" if dm_t else "Disabled"

		content = (
			f"```ansi\n"
			f"Ticket Configuration ({ctx.guild.name})\n\n"
			f"Status:        {'Enabled' if is_on else 'Disabled'}\n"
			f"Category:      {category_str}\n"
			f"Log Channel:   {log_str}\n"
			f"Support Role:  {role_str}\n"
			f"Max Tickets:   {limit_str}\n"
			f"DM Transcript: {dm_str}\n"
			f"```"
		)
		return await ctx.send(content=content)

	status_node.callback = ticket_status
	ticket_node.callback = ticket_status

	return ticket_node
