from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from typing import TYPE_CHECKING

import chat_exporter
import discord
from discord.ext import commands

if TYPE_CHECKING:
	from core import Bot

logger = logging.getLogger(__name__)

TICKET_OPEN_ID = "ticket:open"
TICKET_ARCHIVE_ID = "ticket:archive"
TICKET_CLOSE_ID = "ticket:close"
TICKET_SAVE_ID = "ticket:save"
TICKET_REOPEN_ID = "ticket:reopen"

LEGACY_MAP = {
	"ticketbtn": TICKET_OPEN_ID,
	"archivebtn": TICKET_ARCHIVE_ID,
	"closebtn": TICKET_CLOSE_ID,
	"savebtn": TICKET_SAVE_ID,
	"reopenbtn": TICKET_REOPEN_ID,
}


def _write_file_sync(filepath: str, content: str) -> None:
	with open(filepath, "w", encoding="utf-8") as f:
		f.write(content)


class TicketModal(discord.ui.Modal):
	def __init__(self, cog: Ticket, title: str = "Open a Ticket"):
		super().__init__(title=title[:45], timeout=300)
		self.cog = cog

		self.topic = discord.ui.TextInput(
			label="Topic / Subject",
			placeholder="Brief summary of the issue",
			min_length=3,
			max_length=100,
			required=True,
		)
		self.add_item(self.topic)

		self.description = discord.ui.TextInput(
			label="Description",
			style=discord.TextStyle.paragraph,
			placeholder="Please provide a detailed explanation of your issue...",
			min_length=10,
			max_length=1800,
			required=True,
		)
		self.add_item(self.description)

	async def on_submit(self, interaction: discord.Interaction):
		await self.cog.handle_ticket_create(
			interaction=interaction,
			topic=self.topic.value.strip(),
			description=self.description.value.strip(),
		)

	async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
		logger.exception("Error in TicketModal on_submit", exc_info=error)
		err_msg = "An unexpected error occurred while creating your ticket."
		if interaction.response.is_done():
			await interaction.followup.send(err_msg, ephemeral=True)
		else:
			await interaction.response.send_message(err_msg, ephemeral=True)


class TicketLauncherView(discord.ui.View):
	def __init__(self, bot: Bot, button_label: str = "Open Ticket"):
		super().__init__(timeout=None)
		self.bot = bot
		self.open_button.label = button_label

	@discord.ui.button(
		style=discord.ButtonStyle.primary,
		label="Open Ticket",
		custom_id=TICKET_OPEN_ID,
		emoji="🎫",
	)
	async def open_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if not cog:
			return await interaction.response.send_message("Ticket system is currently unavailable.", ephemeral=True)
		modal = await cog.create_ticket_modal(interaction)
		await interaction.response.send_modal(modal)


class ActiveTicketControlsView(discord.ui.View):
	def __init__(self, bot: Bot):
		super().__init__(timeout=None)
		self.bot = bot

	@discord.ui.button(
		label="Archive",
		style=discord.ButtonStyle.blurple,
		custom_id=TICKET_ARCHIVE_ID,
		emoji="📦",
	)
	async def archive_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_archive_action(interaction)

	@discord.ui.button(
		label="Close",
		style=discord.ButtonStyle.danger,
		custom_id=TICKET_CLOSE_ID,
		emoji="📪",
	)
	async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_close_action(interaction)

	@discord.ui.button(
		label="Save Transcript",
		style=discord.ButtonStyle.secondary,
		custom_id=TICKET_SAVE_ID,
		emoji="💾",
	)
	async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_save_action(interaction)


class ArchivedTicketControlsView(discord.ui.View):
	def __init__(self, bot: Bot):
		super().__init__(timeout=None)
		self.bot = bot

	@discord.ui.button(
		label="Close",
		style=discord.ButtonStyle.danger,
		custom_id=TICKET_CLOSE_ID,
		emoji="📪",
	)
	async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_close_action(interaction)

	@discord.ui.button(
		label="Reopen",
		style=discord.ButtonStyle.success,
		custom_id=TICKET_REOPEN_ID,
		emoji="🔁",
	)
	async def reopen_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_reopen_action(interaction)

	@discord.ui.button(
		label="Save Transcript",
		style=discord.ButtonStyle.secondary,
		custom_id=TICKET_SAVE_ID,
		emoji="💾",
	)
	async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = self.bot.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_save_action(interaction)


class DisabledControlsView(discord.ui.View):
	def __init__(self):
		super().__init__(timeout=None)
		self.add_item(
			discord.ui.Button(
				label="Archive", style=discord.ButtonStyle.blurple, emoji="📦", disabled=True, custom_id="dis_arch"
			)
		)
		self.add_item(
			discord.ui.Button(
				label="Close", style=discord.ButtonStyle.danger, emoji="📪", disabled=True, custom_id="dis_close"
			)
		)
		self.add_item(
			discord.ui.Button(
				label="Save Transcript",
				style=discord.ButtonStyle.secondary,
				emoji="💾",
				disabled=True,
				custom_id="dis_save",
			)
		)


class Ticket(commands.Cog, name="Ticket"):
	def __init__(self, bot: Bot):
		self.bot = bot

	async def cog_load(self):
		self.bot.add_view(TicketLauncherView(self.bot))
		self.bot.add_view(ActiveTicketControlsView(self.bot))
		self.bot.add_view(ArchivedTicketControlsView(self.bot))

	def create_launcher_view(self, button_label: str = "Open Ticket") -> TicketLauncherView:
		return TicketLauncherView(self.bot, button_label=button_label)

	def create_controls_view(self, is_archived: bool = False) -> discord.ui.View:
		if is_archived:
			return ArchivedTicketControlsView(self.bot)
		return ActiveTicketControlsView(self.bot)

	async def get_ticket_config(self, guild_id: int) -> dict | None:
		if not self.bot.db:
			return None
		row = await self.bot.db.fetchrow("SELECT * FROM ticket_config WHERE guild_id = $1", guild_id)
		return dict(row) if row else None

	async def get_ticket(self, channel_id: int) -> dict | None:
		if not self.bot.db:
			return None
		row = await self.bot.db.fetchrow(
			"SELECT * FROM tickets WHERE channel_id = $1 AND is_closed = false", channel_id
		)
		return dict(row) if row else None

	async def get_active_ticket_count(self, guild_id: int, user_id: int) -> int:
		if not self.bot.db:
			return 0
		val = await self.bot.db.fetchval(
			"SELECT count(*) FROM tickets WHERE guild_id = $1 AND user_id = $2 AND is_closed = false",
			guild_id,
			user_id,
		)
		return int(val) if val is not None else 0

	async def can_manage_ticket(self, interaction: discord.Interaction, ticket_row: dict) -> bool:
		if not interaction.guild or not isinstance(interaction.user, discord.Member):
			return False
		if interaction.user.id == int(ticket_row["user_id"]):
			return True
		if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_channels:
			return True
		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("support_role_id"):
			role_id = int(cfg["support_role_id"])
			if any(r.id == role_id for r in interaction.user.roles):
				return True
		return False

	async def create_ticket_modal(self, interaction: discord.Interaction) -> TicketModal:
		modal_title = "Open a Ticket"
		try:
			loc = await self.bot.custom_response.get_message("ticket.modal.title", interaction)
			if isinstance(loc, str) and loc and not loc.startswith("localizer"):
				modal_title = loc
		except (discord.DiscordException, KeyError, AttributeError) as e:
			logger.debug("Could not resolve localized modal title: %s", e)
		return TicketModal(self, title=modal_title)

	async def export_transcript(
		self, channel: discord.abc.GuildChannel | discord.Thread, ticket_id: int
	) -> tuple[str, str]:
		transcript_str = ""
		if isinstance(channel, discord.TextChannel):
			try:
				res = await chat_exporter.export(
					channel=channel,
					tz_info="UTC",
					bot=self.bot,
				)
				if isinstance(res, str):
					transcript_str = res
			except (discord.DiscordException, OSError, ValueError) as e:
				logger.warning(f"chat_exporter failed for #{channel.name}: {e}")

		if not transcript_str:
			# Fallback clean transcript
			lines = [
				f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Ticket #{ticket_id}</title></head>",
				f"<body><h1>Ticket #{ticket_id} - #{getattr(channel, 'name', 'ticket')}</h1><ul>",
			]
			if isinstance(channel, discord.TextChannel):
				try:
					async for msg in channel.history(limit=500, oldest_first=True):
						author_str = f"{msg.author.display_name} ({msg.author.id})"
						content_str = msg.clean_content.replace("<", "&lt;").replace(">", "&gt;")
						lines.append(
							f"<li><strong>{author_str}</strong> [{msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}]: {content_str}</li>"
						)
				except (discord.DiscordException, OSError) as e:
					logger.debug("Failed reading message history for fallback transcript: %s", e)
			lines.append("</ul></body></html>")
			transcript_str = "\n".join(lines)

		os.makedirs("transcript", exist_ok=True)
		channel_name = getattr(channel, "name", str(channel.id))
		clean_name = re.sub(r"[^a-zA-Z0-9_-]", "", channel_name)
		filename = f"ticket-{clean_name}_{ticket_id}.html"
		filepath = os.path.join("transcript", filename)
		try:
			await asyncio.to_thread(_write_file_sync, filepath, transcript_str)
		except OSError as e:
			logger.warning(f"Failed to write local transcript: {e}")

		return transcript_str, filepath

	async def handle_ticket_create(self, interaction: discord.Interaction, topic: str, description: str):
		assert interaction.guild is not None
		await interaction.response.defer(thinking=True, ephemeral=True)

		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and not cfg.get("is_on", True):
			msg = await self.bot.custom_response.get_message("ticket.errors.disabled", interaction)
			return await interaction.followup.send(msg, ephemeral=True)

		max_tickets = cfg.get("max_tickets", 1) if cfg else 1
		if max_tickets > 0:
			count = await self.get_active_ticket_count(interaction.guild.id, interaction.user.id)
			if count >= max_tickets:
				msg = await self.bot.custom_response.get_message(
					"ticket.errors.already_open", interaction, count=count, limit=max_tickets
				)
				return await interaction.followup.send(msg, ephemeral=True)

		# Determine category
		category: discord.CategoryChannel | None = None
		if cfg and cfg.get("category_id"):
			cat = interaction.guild.get_channel(int(cfg["category_id"]))
			if isinstance(cat, discord.CategoryChannel):
				category = cat

		if not category:
			category = discord.utils.get(interaction.guild.categories, name="Tickets")
			if not category and interaction.guild.me:
				try:
					cat_overwrites: dict[
						discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite
					] = {
						interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
						interaction.guild.me: discord.PermissionOverwrite(
							view_channel=True,
							send_messages=True,
							manage_channels=True,
							manage_permissions=True,
							read_message_history=True,
							attach_files=True,
							embed_links=True,
						),
					}
					category = await interaction.guild.create_category(
						name="Tickets", overwrites=cat_overwrites, reason="Ticket system category"
					)
				except discord.Forbidden:
					msg = await self.bot.custom_response.get_message("ticket.errors.bot_perms", interaction)
					return await interaction.followup.send(msg, ephemeral=True)

		# Build overwrites
		clean_username = re.sub(r"[^a-zA-Z0-9_-]", "", interaction.user.name.lower().replace(" ", "-"))[:20] or "user"
		channel_name = f"ticket-{clean_username}"

		opener_target: discord.Role | discord.Member | discord.Object = (
			interaction.user
			if isinstance(interaction.user, (discord.Member, discord.Role, discord.Object))
			else discord.Object(id=interaction.user.id)
		)

		ch_overwrites: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite] = {
			interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
			opener_target: discord.PermissionOverwrite(
				view_channel=True,
				send_messages=True,
				read_message_history=True,
				attach_files=True,
				embed_links=True,
			),
		}
		if interaction.guild.me:
			ch_overwrites[interaction.guild.me] = discord.PermissionOverwrite(
				view_channel=True,
				send_messages=True,
				manage_channels=True,
				manage_permissions=True,
				read_message_history=True,
				attach_files=True,
				embed_links=True,
			)

		if cfg and cfg.get("support_role_id"):
			support_role = interaction.guild.get_role(int(cfg["support_role_id"]))
			if support_role:
				ch_overwrites[support_role] = discord.PermissionOverwrite(
					view_channel=True,
					send_messages=True,
					read_message_history=True,
					attach_files=True,
					embed_links=True,
				)

		try:
			ticket_channel = await interaction.guild.create_text_channel(
				name=channel_name,
				category=category,
				overwrites=ch_overwrites,
				reason=f"Ticket opened by {interaction.user} ({interaction.user.id})",
			)
		except discord.Forbidden:
			msg = await self.bot.custom_response.get_message("ticket.errors.bot_perms", interaction)
			return await interaction.followup.send(msg, ephemeral=True)

		# Save to DB
		ticket_id = await self.bot.db.fetchval(
			"""
			INSERT INTO tickets (guild_id, channel_id, user_id, title, description)
			VALUES ($1, $2, $3, $4, $5)
			RETURNING id
			""",
			interaction.guild.id,
			ticket_channel.id,
			interaction.user.id,
			topic,
			description,
		)

		embed = discord.Embed(
			title=topic,
			description=description,
			color=6656243,
			timestamp=discord.utils.utcnow(),
		)
		embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
		embed.set_footer(text=f"FightMan01 bot - Ticket #{ticket_id}")

		await ticket_channel.send(
			content=interaction.user.mention,
			embed=embed,
			view=ActiveTicketControlsView(self.bot),
		)

		# Send log if log channel is set
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_embed = discord.Embed(
					title="Ticket Created",
					color=6656243,
					timestamp=discord.utils.utcnow(),
				)
				log_embed.add_field(
					name="Ticket Creator", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False
				)
				log_embed.add_field(
					name="Ticket Channel", value=f"{ticket_channel.mention} (`#{ticket_channel.name}`)", inline=False
				)
				log_embed.add_field(name="Topic", value=topic, inline=False)
				log_embed.set_footer(text=f"Ticket ID: {ticket_id}")
				try:
					await log_ch.send(embed=log_embed)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send ticket create log: {e}")

		ephemeral_msg = await self.bot.custom_response.get_message(
			"ticket.created.ephemeral", interaction, channel=ticket_channel.mention
		)
		await interaction.followup.send(ephemeral_msg, ephemeral=True)

	async def handle_archive_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			msg = await self.bot.custom_response.get_message("ticket.errors.not_ticket", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			msg = await self.bot.custom_response.get_message("ticket.errors.no_permission", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		await interaction.response.defer()

		opener = interaction.guild.get_member(int(ticket["user_id"]))
		if opener and isinstance(interaction.channel, discord.TextChannel):
			try:
				await interaction.channel.set_permissions(
					opener, send_messages=False, view_channel=True, read_message_history=True
				)
			except discord.HTTPException as e:
				logger.warning(f"Failed to set opener permissions on archive: {e}")

		await self.bot.db.execute("UPDATE tickets SET is_archived = true WHERE id = $1", ticket["id"])

		desc = await self.bot.custom_response.get_message(
			"ticket.actions.archived.description", interaction, author=interaction.user
		)
		title = await self.bot.custom_response.get_message("ticket.actions.archived.title", interaction)
		embed = discord.Embed(
			title=str(title) if title else "Ticket Archived",
			description=str(desc) if desc else "",
			color=6656243,
			timestamp=discord.utils.utcnow(),
		)
		embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
		embed.set_footer(text=f"FightMan01 bot - Ticket #{ticket['id']}")

		if isinstance(interaction.channel, discord.abc.Messageable):
			await interaction.channel.send(embed=embed, view=ArchivedTicketControlsView(self.bot))

		# Log
		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_embed = discord.Embed(
					title="Ticket Archived",
					color=6656243,
					timestamp=discord.utils.utcnow(),
				)
				log_embed.add_field(
					name="Action By", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False
				)
				log_embed.add_field(
					name="Ticket Creator", value=f"<@{ticket['user_id']}> ({ticket['user_id']})", inline=False
				)
				log_embed.add_field(
					name="Ticket Channel",
					value=getattr(interaction.channel, "name", str(interaction.channel.id)),
					inline=False,
				)
				log_embed.set_footer(text=f"Ticket ID: {ticket['id']}")
				try:
					await log_ch.send(embed=log_embed)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send archive log: {e}")

	async def handle_reopen_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			msg = await self.bot.custom_response.get_message("ticket.errors.not_ticket", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			msg = await self.bot.custom_response.get_message("ticket.errors.no_permission", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		await interaction.response.defer()

		opener = interaction.guild.get_member(int(ticket["user_id"]))
		if opener and isinstance(interaction.channel, discord.TextChannel):
			try:
				await interaction.channel.set_permissions(
					opener, send_messages=True, view_channel=True, read_message_history=True
				)
			except discord.HTTPException as e:
				logger.warning(f"Failed to restore opener permissions on reopen: {e}")

		await self.bot.db.execute("UPDATE tickets SET is_archived = false WHERE id = $1", ticket["id"])

		desc = await self.bot.custom_response.get_message(
			"ticket.actions.reopened.description", interaction, author=interaction.user
		)
		title = await self.bot.custom_response.get_message("ticket.actions.reopened.title", interaction)
		embed = discord.Embed(
			title=str(title) if title else "Ticket Reopened",
			description=str(desc) if desc else "",
			color=6656243,
			timestamp=discord.utils.utcnow(),
		)
		embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
		embed.set_footer(text=f"FightMan01 bot - Ticket #{ticket['id']}")

		if isinstance(interaction.channel, discord.abc.Messageable):
			await interaction.channel.send(embed=embed, view=ActiveTicketControlsView(self.bot))

		# Log
		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_embed = discord.Embed(
					title="Ticket Reopened",
					color=6656243,
					timestamp=discord.utils.utcnow(),
				)
				log_embed.add_field(
					name="Action By", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False
				)
				log_embed.add_field(
					name="Ticket Creator", value=f"<@{ticket['user_id']}> ({ticket['user_id']})", inline=False
				)
				log_embed.add_field(
					name="Ticket Channel",
					value=getattr(interaction.channel, "name", str(interaction.channel.id)),
					inline=False,
				)
				log_embed.set_footer(text=f"Ticket ID: {ticket['id']}")
				try:
					await log_ch.send(embed=log_embed)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send reopen log: {e}")

	async def handle_save_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			msg = await self.bot.custom_response.get_message("ticket.errors.not_ticket", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			msg = await self.bot.custom_response.get_message("ticket.errors.no_permission", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		await interaction.response.defer()

		transcript, filepath = await self.export_transcript(interaction.channel, ticket["id"])  # type: ignore
		await self.bot.db.execute("UPDATE tickets SET transcript_path = $1 WHERE id = $2", filepath, ticket["id"])

		ch_name = getattr(interaction.channel, "name", "ticket")
		file_to_send = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")

		# Log
		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_embed = discord.Embed(
					title="Ticket Transcript Saved",
					color=6656243,
					timestamp=discord.utils.utcnow(),
				)
				log_embed.add_field(
					name="Action By", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False
				)
				log_embed.add_field(
					name="Ticket Creator", value=f"<@{ticket['user_id']}> ({ticket['user_id']})", inline=False
				)
				log_embed.add_field(name="Ticket Channel", value=f"#{ch_name}", inline=False)
				log_embed.set_footer(text=f"Ticket ID: {ticket['id']}")
				log_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")
				try:
					await log_ch.send(embed=log_embed, file=log_file)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send save transcript log: {e}")

		saved_msg = await self.bot.custom_response.get_message("ticket.actions.saved.content", interaction)
		await interaction.followup.send(
			content=str(saved_msg) if saved_msg else "Transcript saved successfully!",
			file=file_to_send,
		)

	async def handle_close_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			msg = await self.bot.custom_response.get_message("ticket.errors.not_ticket", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			msg = await self.bot.custom_response.get_message("ticket.errors.no_permission", interaction)
			return await interaction.response.send_message(msg, ephemeral=True)

		await interaction.response.defer()

		if interaction.message:
			try:
				await interaction.message.edit(view=DisabledControlsView())
			except discord.HTTPException as e:
				logger.debug("Failed to disable buttons on close message: %s", e)

		loading_msg = await self.bot.custom_response.get_message("ticket.actions.closed.generating", interaction)
		await interaction.followup.send(
			str(loading_msg) if loading_msg else "Generating transcript and closing ticket..."
		)

		transcript, filepath = await self.export_transcript(interaction.channel, ticket["id"])  # type: ignore

		await self.bot.db.execute(
			"""
			UPDATE tickets
			SET is_closed = true, is_archived = true, closed_at = now(), closed_by = $1, transcript_path = $2
			WHERE id = $3
			""",
			interaction.user.id,
			filepath,
			ticket["id"],
		)

		ch_name = getattr(interaction.channel, "name", "ticket")
		cfg = await self.get_ticket_config(interaction.guild.id)

		# Log to ticket log channel
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_embed = discord.Embed(
					title="Ticket Closed",
					color=6656243,
					timestamp=discord.utils.utcnow(),
				)
				log_embed.add_field(
					name="Closed By", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False
				)
				log_embed.add_field(
					name="Ticket Creator", value=f"<@{ticket['user_id']}> ({ticket['user_id']})", inline=False
				)
				log_embed.add_field(name="Ticket Channel", value=f"#{ch_name}", inline=False)
				log_embed.add_field(name="Topic", value=ticket["title"], inline=False)
				log_embed.set_footer(text=f"Ticket ID: {ticket['id']}")
				log_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")
				try:
					await log_ch.send(embed=log_embed, file=log_file)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send close log: {e}")

		# DM transcript to opener if enabled
		if cfg is None or cfg.get("dm_transcript", True):
			opener = interaction.guild.get_member(int(ticket["user_id"]))
			if not opener:
				try:
					opener = await self.bot.fetch_user(int(ticket["user_id"]))
				except (discord.HTTPException, discord.NotFound):
					opener = None
			if opener:
				dm_text = f"Your ticket in **{interaction.guild.name}** (`#{ch_name}`) has been closed. A transcript is attached below."
				dm_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")
				try:
					await opener.send(content=dm_text, file=dm_file)
				except (discord.Forbidden, discord.HTTPException) as e:
					logger.debug(f"Could not DM user {ticket['user_id']}: {e}")

		# Delete channel
		if isinstance(interaction.channel, discord.abc.GuildChannel):
			try:
				await interaction.channel.delete(reason=f"Ticket closed by {interaction.user} ({interaction.user.id})")
			except discord.HTTPException as e:
				logger.warning(f"Failed to delete ticket channel: {e}")

	@commands.Cog.listener()
	async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
		if not self.bot.db:
			return
		await self.bot.db.execute(
			"""
			UPDATE tickets
			SET is_closed = true, is_archived = true, closed_at = now()
			WHERE channel_id = $1 AND is_closed = false
			""",
			channel.id,
		)

	@commands.Cog.listener()
	async def on_interaction(self, interaction: discord.Interaction):
		if interaction.type != discord.InteractionType.component:
			return
		data = interaction.data
		if not data:
			return
		custom_id = data.get("custom_id")
		if not custom_id or custom_id not in LEGACY_MAP:
			return

		mapped_id = LEGACY_MAP[custom_id]
		if mapped_id == TICKET_OPEN_ID:
			modal = await self.create_ticket_modal(interaction)
			await interaction.response.send_modal(modal)
		elif mapped_id == TICKET_ARCHIVE_ID:
			await self.handle_archive_action(interaction)
		elif mapped_id == TICKET_CLOSE_ID:
			await self.handle_close_action(interaction)
		elif mapped_id == TICKET_SAVE_ID:
			await self.handle_save_action(interaction)
		elif mapped_id == TICKET_REOPEN_ID:
			await self.handle_reopen_action(interaction)


async def setup(bot: Bot):
	await bot.add_cog(Ticket(bot))
