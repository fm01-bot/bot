from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

import discord
from cogs.ticket import ticket_config_setting
from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_category, resolve_channel, resolve_role

if TYPE_CHECKING:
	from core import Context


async def _write(ctx: Context, query: str, *args: Any) -> None:
	"""Run a ticket_config write and report it, so cached ticket configs (here and on other instances) refresh."""
	assert ctx.guild is not None
	await ctx.bot.db.execute(query, *args)
	await ticket_config_setting(ctx.bot.settings).changed(ctx.guild.id)


def setup_ticket_subcommands(parent_node: CLINode) -> CLINode:
	ticket_node = parent_node.create_subcommand("ticket", description="Configure support ticket system.")

	# enable subcommand
	enable_node = ticket_node.create_subcommand("enable", description="Enable support ticket system.")

	async def ticket_enable(ctx: Context, **kwargs: Any):
		assert ctx.guild is not None
		await _write(
			ctx,
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
		await _write(
			ctx,
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

		# Build view
		ticket_cog: Any = ctx.bot.get_cog("Ticket")
		if ticket_cog and hasattr(ticket_cog, "create_launcher_view"):
			view = await ticket_cog.create_launcher_view(ctx.guild, button_label=button)
		else:
			btn_label = button
			if not btn_label:
				panel_data = await ctx.bot.custom_response.get_message("ticket.panel", ctx.guild)
				if isinstance(panel_data, dict) and "button" in panel_data:
					btn_label = str(panel_data["button"])
			if not btn_label:
				btn_label = "Open Ticket"
			from cogs.ticket import TicketLauncherView

			view = TicketLauncherView(button_label=btn_label)

		# Build message payload with localized defaults or custom overrides
		send_kwargs: dict[str, Any] = {"view": view}
		if title or description:
			panel_title = title or "Support Tickets"
			panel_desc = description or "Need assistance? Click the button below to open a support ticket."
			custom_layout = {
				"components": [
					{
						"type": "container",
						"accent_color": 6656243,
						"components": [
							{
								"type": "text_display",
								"content": f"# 🎫 {panel_title}\n{panel_desc}",
							},
							{
								"type": "separator",
							},
							{
								"type": "text_display",
								"content": "*FightMan01 bot — Ticket System*",
							},
						],
					}
				]
			}
			converted = ctx.bot.custom_response.convert_components(custom_layout)
			if "view" in converted:
				send_kwargs["view"] = ctx.bot.custom_response.merge_views(converted["view"], view)
		else:
			payload = await ctx.bot.custom_response.get_message("ticket.panel", ctx.guild)
			if isinstance(payload, dict):
				payload.pop("button", None)
				if "view" in payload and "view" in send_kwargs:
					send_kwargs["view"] = ctx.bot.custom_response.merge_views(send_kwargs["view"], payload.pop("view"))
				send_kwargs.update(payload)
			elif isinstance(payload, str):
				send_kwargs["content"] = payload

		valid_send_kwargs = frozenset(
			{
				"content",
				"tts",
				"embed",
				"embeds",
				"file",
				"files",
				"stickers",
				"delete_after",
				"nonce",
				"allowed_mentions",
				"reference",
				"mention_author",
				"view",
				"suppress_embeds",
				"silent",
				"poll",
			}
		)
		filtered_kwargs = {k: v for k, v in send_kwargs.items() if k in valid_send_kwargs}

		await target_channel.send(**filtered_kwargs)
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
			await _write(
				ctx,
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

		await _write(
			ctx,
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
			await _write(
				ctx,
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

		await _write(
			ctx,
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
			await _write(
				ctx,
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

		await _write(
			ctx,
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

		await _write(
			ctx,
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
		await _write(
			ctx,
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

	# length / modal subcommand
	length_node = ticket_node.create_subcommand("length", description="Configure modal input min/max lengths.")
	length_node.add_option("topic-min", "tn", help="Minimum length for topic (1-4000, default 3)")
	length_node.add_option("topic-max", "tx", help="Maximum length for topic (1-4000, default 100)")
	length_node.add_option("desc-min", "dn", help="Minimum length for description (1-4000, default 10)")
	length_node.add_option("desc-max", "dx", help="Maximum length for description (1-4000, default 1800)")
	length_node.add_argument("--description-min", dest="desc_min", help=argparse.SUPPRESS)
	length_node.add_argument("--description-max", dest="desc_max", help=argparse.SUPPRESS)

	modal_node = ticket_node.create_subcommand("modal", description="Configure modal input min/max lengths.")
	modal_node.add_option("topic-min", "tn", help="Minimum length for topic (1-4000, default 3)")
	modal_node.add_option("topic-max", "tx", help="Maximum length for topic (1-4000, default 100)")
	modal_node.add_option("desc-min", "dn", help="Minimum length for description (1-4000, default 10)")
	modal_node.add_option("desc-max", "dx", help="Maximum length for description (1-4000, default 1800)")
	modal_node.add_argument("--description-min", dest="desc_min", help=argparse.SUPPRESS)
	modal_node.add_argument("--description-max", dest="desc_max", help=argparse.SUPPRESS)

	async def ticket_length(
		ctx: Context,
		topic_min: str | None = None,
		topic_max: str | None = None,
		desc_min: str | None = None,
		desc_max: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		if topic_min is None and topic_max is None and desc_min is None and desc_max is None:
			row = await ctx.bot.db.fetchrow(
				"SELECT topic_min_length, topic_max_length, description_min_length, description_max_length "
				"FROM ticket_config WHERE guild_id = $1",
				ctx.guild.id,
			)
			t_min = (
				row["topic_min_length"]
				if row and "topic_min_length" in row and row["topic_min_length"] is not None
				else 3
			)
			t_max = (
				row["topic_max_length"]
				if row and "topic_max_length" in row and row["topic_max_length"] is not None
				else 100
			)
			d_min = (
				row["description_min_length"]
				if row and "description_min_length" in row and row["description_min_length"] is not None
				else 10
			)
			d_max = (
				row["description_max_length"]
				if row and "description_max_length" in row and row["description_max_length"] is not None
				else 1800
			)
			return await ctx.send(
				content=(
					f"```ansi\n"
					f"Ticket Modal Length Limits ({ctx.guild.name})\n\n"
					f"Topic:       Min {t_min} / Max {t_max}\n"
					f"Description: Min {d_min} / Max {d_max}\n"
					f"```"
				)
			)

		t_min_val: int | None = None
		t_max_val: int | None = None
		d_min_val: int | None = None
		d_max_val: int | None = None

		if topic_min is not None:
			try:
				t_min_val = int(topic_min)
				if t_min_val < 1 or t_min_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--topic-min` must be an integer between 1 and 4000.", length_node)

		if topic_max is not None:
			try:
				t_max_val = int(topic_max)
				if t_max_val < 1 or t_max_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--topic-max` must be an integer between 1 and 4000.", length_node)

		if desc_min is not None:
			try:
				d_min_val = int(desc_min)
				if d_min_val < 1 or d_min_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--desc-min` must be an integer between 1 and 4000.", length_node)

		if desc_max is not None:
			try:
				d_max_val = int(desc_max)
				if d_max_val < 1 or d_max_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("`--desc-max` must be an integer between 1 and 4000.", length_node)

		row = await ctx.bot.db.fetchrow(
			"SELECT topic_min_length, topic_max_length, description_min_length, description_max_length "
			"FROM ticket_config WHERE guild_id = $1",
			ctx.guild.id,
		)
		cur_t_min = (
			row["topic_min_length"] if row and "topic_min_length" in row and row["topic_min_length"] is not None else 3
		)
		cur_t_max = (
			row["topic_max_length"]
			if row and "topic_max_length" in row and row["topic_max_length"] is not None
			else 100
		)
		cur_d_min = (
			row["description_min_length"]
			if row and "description_min_length" in row and row["description_min_length"] is not None
			else 10
		)
		cur_d_max = (
			row["description_max_length"]
			if row and "description_max_length" in row and row["description_max_length"] is not None
			else 1800
		)

		final_t_min = t_min_val if t_min_val is not None else cur_t_min
		final_t_max = t_max_val if t_max_val is not None else cur_t_max
		if final_t_min > final_t_max:
			raise CLIParseError(
				f"Topic minimum length ({final_t_min}) cannot exceed maximum length ({final_t_max}).",
				length_node,
			)

		final_d_min = d_min_val if d_min_val is not None else cur_d_min
		final_d_max = d_max_val if d_max_val is not None else cur_d_max
		if final_d_min > final_d_max:
			raise CLIParseError(
				f"Description minimum length ({final_d_min}) cannot exceed maximum length ({final_d_max}).",
				length_node,
			)

		await _write(
			ctx,
			"""
			INSERT INTO ticket_config (
				guild_id,
				topic_min_length,
				topic_max_length,
				description_min_length,
				description_max_length
			)
			VALUES ($1, $2, $3, $4, $5)
			ON CONFLICT (guild_id) DO UPDATE SET
				topic_min_length = $2,
				topic_max_length = $3,
				description_min_length = $4,
				description_max_length = $5
			""",
			ctx.guild.id,
			final_t_min,
			final_t_max,
			final_d_min,
			final_d_max,
		)

		updates: list[str] = []
		if t_min_val is not None or t_max_val is not None:
			updates.append(f"Topic: Min {final_t_min} / Max {final_t_max}")
		if d_min_val is not None or d_max_val is not None:
			updates.append(f"Description: Min {final_d_min} / Max {final_d_max}")

		return await ctx.send(content="```ansi\n[+] Ticket modal lengths updated:\n- " + "\n- ".join(updates) + "\n```")

	length_node.callback = ticket_length
	modal_node.callback = ticket_length

	# topic subcommand
	topic_node = ticket_node.create_subcommand("topic", description="Configure topic/subject min/max length.")
	topic_node.add_option("min", "n", help="Minimum length for topic (1-4000, default 3)")
	topic_node.add_option("max", "x", help="Maximum length for topic (1-4000, default 100)")
	topic_node.add_argument("min_pos", required=False, help="Minimum length positional argument")
	topic_node.add_argument("max_pos", required=False, help="Maximum length positional argument")

	async def ticket_topic(
		ctx: Context,
		min: str | None = None,
		max: str | None = None,
		min_pos: str | None = None,
		max_pos: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		raw_min = min or min_pos
		raw_max = max or max_pos

		if raw_min is None and raw_max is None:
			row = await ctx.bot.db.fetchrow(
				"SELECT topic_min_length, topic_max_length FROM ticket_config WHERE guild_id = $1",
				ctx.guild.id,
			)
			t_min = (
				row["topic_min_length"]
				if row and "topic_min_length" in row and row["topic_min_length"] is not None
				else 3
			)
			t_max = (
				row["topic_max_length"]
				if row and "topic_max_length" in row and row["topic_max_length"] is not None
				else 100
			)
			return await ctx.send(content=f"```ansi\nTicket Topic Length: Min {t_min} / Max {t_max}\n```")

		t_min_val: int | None = None
		t_max_val: int | None = None

		if raw_min is not None:
			try:
				t_min_val = int(raw_min)
				if t_min_val < 1 or t_min_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("Minimum length must be an integer between 1 and 4000.", topic_node)

		if raw_max is not None:
			try:
				t_max_val = int(raw_max)
				if t_max_val < 1 or t_max_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("Maximum length must be an integer between 1 and 4000.", topic_node)

		row = await ctx.bot.db.fetchrow(
			"SELECT topic_min_length, topic_max_length FROM ticket_config WHERE guild_id = $1",
			ctx.guild.id,
		)
		cur_min = (
			row["topic_min_length"] if row and "topic_min_length" in row and row["topic_min_length"] is not None else 3
		)
		cur_max = (
			row["topic_max_length"]
			if row and "topic_max_length" in row and row["topic_max_length"] is not None
			else 100
		)

		final_min = t_min_val if t_min_val is not None else cur_min
		final_max = t_max_val if t_max_val is not None else cur_max

		if final_min > final_max:
			raise CLIParseError(f"Minimum length ({final_min}) cannot exceed maximum length ({final_max}).", topic_node)

		await _write(
			ctx,
			"""
			INSERT INTO ticket_config (guild_id, topic_min_length, topic_max_length)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id) DO UPDATE SET
				topic_min_length = $2,
				topic_max_length = $3
			""",
			ctx.guild.id,
			final_min,
			final_max,
		)
		return await ctx.send(
			content=f"```ansi\n[+] Ticket topic length set to: Min {final_min} / Max {final_max}\n```"
		)

	topic_node.callback = ticket_topic

	# description subcommand
	desc_node = ticket_node.create_subcommand("description", description="Configure description min/max length.")
	desc_node.add_option("min", "n", help="Minimum length for description (1-4000, default 10)")
	desc_node.add_option("max", "x", help="Maximum length for description (1-4000, default 1800)")
	desc_node.add_argument("min_pos", required=False, help="Minimum length positional argument")
	desc_node.add_argument("max_pos", required=False, help="Maximum length positional argument")

	desc_alias_node = ticket_node.create_subcommand("desc", description="Configure description min/max length.")
	desc_alias_node.add_option("min", "n", help="Minimum length for description (1-4000, default 10)")
	desc_alias_node.add_option("max", "x", help="Maximum length for description (1-4000, default 1800)")
	desc_alias_node.add_argument("min_pos", required=False, help="Minimum length positional argument")
	desc_alias_node.add_argument("max_pos", required=False, help="Maximum length positional argument")

	async def ticket_description(
		ctx: Context,
		min: str | None = None,
		max: str | None = None,
		min_pos: str | None = None,
		max_pos: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		raw_min = min or min_pos
		raw_max = max or max_pos

		if raw_min is None and raw_max is None:
			row = await ctx.bot.db.fetchrow(
				"SELECT description_min_length, description_max_length FROM ticket_config WHERE guild_id = $1",
				ctx.guild.id,
			)
			d_min = (
				row["description_min_length"]
				if row and "description_min_length" in row and row["description_min_length"] is not None
				else 10
			)
			d_max = (
				row["description_max_length"]
				if row and "description_max_length" in row and row["description_max_length"] is not None
				else 1800
			)
			return await ctx.send(content=f"```ansi\nTicket Description Length: Min {d_min} / Max {d_max}\n```")

		d_min_val: int | None = None
		d_max_val: int | None = None

		if raw_min is not None:
			try:
				d_min_val = int(raw_min)
				if d_min_val < 1 or d_min_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("Minimum length must be an integer between 1 and 4000.", desc_node)

		if raw_max is not None:
			try:
				d_max_val = int(raw_max)
				if d_max_val < 1 or d_max_val > 4000:
					raise ValueError
			except ValueError:
				raise CLIParseError("Maximum length must be an integer between 1 and 4000.", desc_node)

		row = await ctx.bot.db.fetchrow(
			"SELECT description_min_length, description_max_length FROM ticket_config WHERE guild_id = $1",
			ctx.guild.id,
		)
		cur_min = (
			row["description_min_length"]
			if row and "description_min_length" in row and row["description_min_length"] is not None
			else 10
		)
		cur_max = (
			row["description_max_length"]
			if row and "description_max_length" in row and row["description_max_length"] is not None
			else 1800
		)

		final_min = d_min_val if d_min_val is not None else cur_min
		final_max = d_max_val if d_max_val is not None else cur_max

		if final_min > final_max:
			raise CLIParseError(f"Minimum length ({final_min}) cannot exceed maximum length ({final_max}).", desc_node)

		await _write(
			ctx,
			"""
			INSERT INTO ticket_config (guild_id, description_min_length, description_max_length)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id) DO UPDATE SET
				description_min_length = $2,
				description_max_length = $3
			""",
			ctx.guild.id,
			final_min,
			final_max,
		)
		return await ctx.send(
			content=f"```ansi\n[+] Ticket description length set to: Min {final_min} / Max {final_max}\n```"
		)

	desc_node.callback = ticket_description
	desc_alias_node.callback = ticket_description

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
			topic_len_str = "Min 3 / Max 100"
			desc_len_str = "Min 10 / Max 1800"
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

			t_min = row["topic_min_length"] if "topic_min_length" in row and row["topic_min_length"] is not None else 3
			t_max = (
				row["topic_max_length"] if "topic_max_length" in row and row["topic_max_length"] is not None else 100
			)
			d_min = (
				row["description_min_length"]
				if "description_min_length" in row and row["description_min_length"] is not None
				else 10
			)
			d_max = (
				row["description_max_length"]
				if "description_max_length" in row and row["description_max_length"] is not None
				else 1800
			)
			topic_len_str = f"Min {t_min} / Max {t_max}"
			desc_len_str = f"Min {d_min} / Max {d_max}"

		content = (
			f"```ansi\n"
			f"Ticket Configuration ({ctx.guild.name})\n\n"
			f"Status:        {'Enabled' if is_on else 'Disabled'}\n"
			f"Category:      {category_str}\n"
			f"Log Channel:   {log_str}\n"
			f"Support Role:  {role_str}\n"
			f"Max Tickets:   {limit_str}\n"
			f"DM Transcript: {dm_str}\n"
			f"Modal Topic:   {topic_len_str}\n"
			f"Modal Desc:    {desc_len_str}\n"
			f"```"
		)
		return await ctx.send(content=content)

	status_node.callback = ticket_status
	ticket_node.callback = ticket_status

	return ticket_node
