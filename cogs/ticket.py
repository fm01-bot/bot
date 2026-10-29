from __future__ import annotations

import base64
import io
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
import chat_exporter
import discord
from chat_exporter.construct.attachment_handler import AttachmentHandler
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
	TICKET_OPEN_ID: TICKET_OPEN_ID,
	TICKET_ARCHIVE_ID: TICKET_ARCHIVE_ID,
	TICKET_CLOSE_ID: TICKET_CLOSE_ID,
	TICKET_SAVE_ID: TICKET_SAVE_ID,
	TICKET_REOPEN_ID: TICKET_REOPEN_ID,
}


class CompactTranscriptAttachmentHandler(AttachmentHandler):
	"""Attachment handler that saves up to max_images in base64 data URLs in the HTML transcript."""

	def __init__(self, max_images: int = 5):
		self.max_images = max_images
		self.saved_images = 0

	async def process_asset(self, attachment: discord.Attachment) -> discord.Attachment:
		ct = getattr(attachment, "content_type", "") or ""
		fn = getattr(attachment, "filename", "") or ""
		is_image = ct.startswith("image/") or fn.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))

		if is_image and self.saved_images < self.max_images:
			try:
				data = None
				if hasattr(attachment, "read") and callable(attachment.read):
					data = await attachment.read()
				elif getattr(attachment, "url", None):
					async with (
						aiohttp.ClientSession() as session,
						session.get(attachment.url) as resp,
					):
						if resp.status == 200:
							data = await resp.read()
				if data and len(data) <= 4 * 1024 * 1024:
					self.saved_images += 1
					mime = ct or "image/png"
					b64 = base64.b64encode(data).decode("ascii")
					data_url = f"data:{mime};base64,{b64}"
					attachment.url = data_url
					attachment.proxy_url = data_url
					return attachment
			except (discord.DiscordException, OSError, ValueError, aiohttp.ClientError) as e:
				logger.debug(f"Failed to embed image asset {fn} in compact transcript: {e}")

		if is_image and self.saved_images >= self.max_images:
			attachment.content_type = "application/octet-stream"

		return attachment


def process_compact_transcript(html: str, max_images: int = 5) -> str:
	"""Apply compact mode to ticket transcript HTML, strip user avatars, and enforce maximum image limit."""
	# 1. Strip avatars of Discord users
	html = re.sub(r"<img[^>]*chatlog__(?:followup-)?avatar[^>]*>", "", html)
	html = re.sub(r'<img[^>]*alt="Avatar"[^>]*>', "", html)
	html = re.sub(r"https://cdn\.discordapp\.com/avatars/[^\s\"'<>]+", "", html)

	# 2. Inject compact layout CSS (IRC-style compact messages, no 72px avatar spacing)
	compact_css = (
		'\n<style id="compact-transcript-style">\n'
		"  .chatlog__message-aside { display: none !important; width: 0 !important; }\n"
		"  .chatlog__message { grid-template-columns: 1fr !important; padding: 0.15rem 1rem !important; }\n"
		"  .chatlog__avatar, .chatlog__followup-avatar, .chatlog__pin-avatar { display: none !important; }\n"
		"  .meta-popout .meta__header img { display: none !important; }\n"
		"</style>\n"
	)
	if "</head>" in html:
		html = html.replace("</head>", f"{compact_css}</head>", 1)
	else:
		html = f"{compact_css}{html}"

	# 3. Enforce maximum image limit (only saving up to max_images in the HTML)
	img_count = 0

	def replace_excess_images(match: re.Match) -> str:
		nonlocal img_count
		tag = match.group(0)
		if "discord-hashtag" in tag or "discord-logo" in tag or ("icon" in tag and "attachment" not in tag):
			return tag
		img_count += 1
		if img_count > max_images:
			return '<span class="chatlog__attachment-omitted">[Image not saved in compact mode]</span>'
		return tag

	html = re.sub(r"<img[^>]+>", replace_excess_images, html)
	return html


class TicketModal(discord.ui.Modal):
	def __init__(
		self,
		cog: Ticket,
		title: str = "Open a Ticket",
		topic_label: str = "Topic / Subject",
		topic_placeholder: str = "Brief summary of the issue",
		desc_label: str = "Description",
		desc_placeholder: str = "Please provide a detailed explanation of your issue...",
	):
		super().__init__(title=title[:45], timeout=300)
		self.cog = cog

		self.topic = discord.ui.TextInput(
			label=topic_label[:45],
			placeholder=topic_placeholder[:100],
			min_length=3,
			max_length=100,
			required=True,
		)
		self.add_item(self.topic)

		self.description = discord.ui.TextInput(
			label=desc_label[:45],
			style=discord.TextStyle.paragraph,
			placeholder=desc_placeholder[:100],
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
		await self.cog.send_response("ticket.modal.error", interaction, ephemeral=True)


class TicketLauncherView(discord.ui.View):
	def __init__(self, button_label: str = "Open Ticket"):
		super().__init__(timeout=None)
		self.open_button.label = button_label

	@discord.ui.button(
		style=discord.ButtonStyle.primary,
		label="Open Ticket",
		custom_id=TICKET_OPEN_ID,
		emoji="🎫",
	)
	async def open_button(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if not cog:
			payload = await interaction.client.custom_response.get_message(  # type: ignore
				"ticket.errors.unavailable", interaction
			)
			if isinstance(payload, dict):
				return await interaction.response.send_message(**payload, ephemeral=True)
			return await interaction.response.send_message(content=str(payload), ephemeral=True)
		modal = await cog.create_ticket_modal(interaction)
		await interaction.response.send_modal(modal)


class ActiveTicketControlsView(discord.ui.View):
	def __init__(
		self,
		*,
		archive_label: str = "Archive",
		close_label: str = "Close",
		save_label: str = "Save Transcript",
	):
		super().__init__(timeout=None)
		self.archive_btn.label = archive_label
		self.close_btn.label = close_label
		self.save_btn.label = save_label

	@discord.ui.button(
		label="Archive",
		style=discord.ButtonStyle.blurple,
		custom_id=TICKET_ARCHIVE_ID,
		emoji="📦",
	)
	async def archive_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_archive_action(interaction)

	@discord.ui.button(
		label="Close",
		style=discord.ButtonStyle.danger,
		custom_id=TICKET_CLOSE_ID,
		emoji="📪",
	)
	async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_close_action(interaction)

	@discord.ui.button(
		label="Save Transcript",
		style=discord.ButtonStyle.secondary,
		custom_id=TICKET_SAVE_ID,
		emoji="💾",
	)
	async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_save_action(interaction)


class ArchivedTicketControlsView(discord.ui.View):
	def __init__(
		self,
		*,
		close_label: str = "Close",
		reopen_label: str = "Reopen",
		save_label: str = "Save Transcript",
	):
		super().__init__(timeout=None)
		self.close_btn.label = close_label
		self.reopen_btn.label = reopen_label
		self.save_btn.label = save_label

	@discord.ui.button(
		label="Close",
		style=discord.ButtonStyle.danger,
		custom_id=TICKET_CLOSE_ID,
		emoji="📪",
	)
	async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_close_action(interaction)

	@discord.ui.button(
		label="Reopen",
		style=discord.ButtonStyle.success,
		custom_id=TICKET_REOPEN_ID,
		emoji="🔁",
	)
	async def reopen_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_reopen_action(interaction)

	@discord.ui.button(
		label="Save Transcript",
		style=discord.ButtonStyle.secondary,
		custom_id=TICKET_SAVE_ID,
		emoji="💾",
	)
	async def save_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		cog: Ticket | None = interaction.client.get_cog("Ticket")  # type: ignore
		if cog:
			await cog.handle_save_action(interaction)


class DisabledControlsView(discord.ui.View):
	def __init__(
		self,
		*,
		close_label: str = "Close",
		save_label: str = "Save Transcript",
		archive_label: str | None = None,
		reopen_label: str | None = None,
	):
		super().__init__(timeout=None)
		if archive_label:
			self.add_item(
				discord.ui.Button(
					label=archive_label,
					style=discord.ButtonStyle.blurple,
					emoji="📦",
					disabled=True,
					custom_id="dis_arch",
				)
			)
		self.add_item(
			discord.ui.Button(
				label=close_label,
				style=discord.ButtonStyle.danger,
				emoji="📪",
				disabled=True,
				custom_id="dis_close",
			)
		)
		if reopen_label:
			self.add_item(
				discord.ui.Button(
					label=reopen_label,
					style=discord.ButtonStyle.success,
					emoji="🔁",
					disabled=True,
					custom_id="dis_reopen",
				)
			)
		self.add_item(
			discord.ui.Button(
				label=save_label,
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
		self.bot.add_view(TicketLauncherView())
		self.bot.add_view(ActiveTicketControlsView())
		self.bot.add_view(ArchivedTicketControlsView())

	async def create_launcher_view(
		self, guild: discord.Guild | None = None, button_label: str | None = None
	) -> TicketLauncherView:
		if not button_label:
			panel_data = await self.bot.custom_response.get_message("ticket.panel", guild)
			if isinstance(panel_data, dict) and "button" in panel_data:
				button_label = str(panel_data["button"])
			if not button_label:
				lbl = await self.bot.custom_response.get_message("ticket.buttons.open", guild)
				button_label = str(lbl) if lbl and not str(lbl).startswith("localizer") else "Open Ticket"
		return TicketLauncherView(button_label=button_label)

	async def create_controls_view(
		self, guild: discord.Guild | None = None, is_archived: bool = False
	) -> discord.ui.View:
		if is_archived:
			close_lbl = await self.bot.custom_response.get_message("ticket.buttons.close", guild)
			reopen_lbl = await self.bot.custom_response.get_message("ticket.buttons.reopen", guild)
			save_lbl = await self.bot.custom_response.get_message("ticket.buttons.save", guild)
			return ArchivedTicketControlsView(
				close_label=str(close_lbl) if close_lbl and not str(close_lbl).startswith("localizer") else "Close",
				reopen_label=str(reopen_lbl)
				if reopen_lbl and not str(reopen_lbl).startswith("localizer")
				else "Reopen",
				save_label=str(save_lbl)
				if save_lbl and not str(save_lbl).startswith("localizer")
				else "Save Transcript",
			)
		arch_lbl = await self.bot.custom_response.get_message("ticket.buttons.archive", guild)
		close_lbl = await self.bot.custom_response.get_message("ticket.buttons.close", guild)
		save_lbl = await self.bot.custom_response.get_message("ticket.buttons.save", guild)
		return ActiveTicketControlsView(
			archive_label=str(arch_lbl) if arch_lbl and not str(arch_lbl).startswith("localizer") else "Archive",
			close_label=str(close_lbl) if close_lbl and not str(close_lbl).startswith("localizer") else "Close",
			save_label=str(save_lbl) if save_lbl and not str(save_lbl).startswith("localizer") else "Save Transcript",
		)

	async def create_disabled_controls_view(
		self, guild: discord.Guild | None = None, is_archived: bool = False
	) -> DisabledControlsView:
		close_lbl = await self.bot.custom_response.get_message("ticket.buttons.close", guild)
		save_lbl = await self.bot.custom_response.get_message("ticket.buttons.save", guild)
		if is_archived:
			reopen_lbl = await self.bot.custom_response.get_message("ticket.buttons.reopen", guild)
			return DisabledControlsView(
				close_label=str(close_lbl) if close_lbl and not str(close_lbl).startswith("localizer") else "Close",
				reopen_label=str(reopen_lbl)
				if reopen_lbl and not str(reopen_lbl).startswith("localizer")
				else "Reopen",
				save_label=str(save_lbl)
				if save_lbl and not str(save_lbl).startswith("localizer")
				else "Save Transcript",
			)
		arch_lbl = await self.bot.custom_response.get_message("ticket.buttons.archive", guild)
		return DisabledControlsView(
			archive_label=str(arch_lbl) if arch_lbl and not str(arch_lbl).startswith("localizer") else "Archive",
			close_label=str(close_lbl) if close_lbl and not str(close_lbl).startswith("localizer") else "Close",
			save_label=str(save_lbl) if save_lbl and not str(save_lbl).startswith("localizer") else "Save Transcript",
		)

	async def send_response(
		self,
		key: str,
		target: discord.Interaction | discord.abc.Messageable,
		*,
		ephemeral: bool = False,
		file: discord.File | None = None,
		view: discord.ui.View | None = None,
		**kwargs: Any,
	) -> discord.Message | None:
		context: Any = (
			target.guild
			if isinstance(target, (discord.Interaction, discord.abc.GuildChannel)) and target.guild
			else target
		)
		payload = await self.bot.custom_response.get_message(key, context, **kwargs)

		send_kwargs: dict[str, Any] = {}
		if file is not None:
			send_kwargs["file"] = file
		if view is not None:
			send_kwargs["view"] = view

		if isinstance(payload, dict):
			send_kwargs.update(payload)
		elif isinstance(payload, str):
			send_kwargs["content"] = payload

		if isinstance(target, discord.Interaction):
			if target.response.is_done():
				return await target.followup.send(**send_kwargs, ephemeral=ephemeral)
			return await target.response.send_message(**send_kwargs, ephemeral=ephemeral)
		elif hasattr(target, "response") and hasattr(target, "followup"):
			target_any: Any = target
			if target_any.response.is_done():
				return await target_any.followup.send(**send_kwargs, ephemeral=ephemeral)
			return await target_any.response.send_message(**send_kwargs, ephemeral=ephemeral)
		elif isinstance(target, discord.abc.Messageable):
			return await target.send(**send_kwargs)
		elif hasattr(target, "send"):
			msg_any: Any = target
			return await msg_any.send(**send_kwargs)
		return None

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
		context: Any = interaction.guild or interaction
		title = await self.bot.custom_response.get_message("ticket.modal.title", context)
		topic_label = await self.bot.custom_response.get_message("ticket.modal.topic_label", context)
		topic_placeholder = await self.bot.custom_response.get_message("ticket.modal.topic_placeholder", context)
		desc_label = await self.bot.custom_response.get_message("ticket.modal.desc_label", context)
		desc_placeholder = await self.bot.custom_response.get_message("ticket.modal.desc_placeholder", context)

		return TicketModal(
			cog=self,
			title=str(title) if title and not str(title).startswith("localizer") else "Open a Ticket",
			topic_label=str(topic_label)
			if topic_label and not str(topic_label).startswith("localizer")
			else "Topic / Subject",
			topic_placeholder=str(topic_placeholder)
			if topic_placeholder and not str(topic_placeholder).startswith("localizer")
			else "Brief summary of the issue",
			desc_label=str(desc_label) if desc_label and not str(desc_label).startswith("localizer") else "Description",
			desc_placeholder=str(desc_placeholder)
			if desc_placeholder and not str(desc_placeholder).startswith("localizer")
			else "Please provide a detailed explanation of your issue...",
		)

	async def export_transcript(self, channel: discord.abc.GuildChannel | discord.Thread, ticket_id: int) -> str:
		transcript_str = ""
		handler = CompactTranscriptAttachmentHandler(max_images=5)
		if isinstance(channel, discord.TextChannel):
			try:
				res = await chat_exporter.export(
					channel=channel,
					tz_info="UTC",
					bot=self.bot,
					attachment_handler=handler,
				)
				if isinstance(res, str):
					transcript_str = res
			except (discord.DiscordException, OSError, ValueError) as e:
				logger.warning(f"chat_exporter failed for #{channel.name}: {e}")

		if not transcript_str:
			lines = [
				f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Ticket #{ticket_id}</title></head>",
				f"<body><h1>Ticket #{ticket_id} - #{getattr(channel, 'name', 'ticket')}</h1><ul>",
			]
			if isinstance(channel, discord.TextChannel):
				try:
					fallback_images = 0
					async for msg in channel.history(limit=500, oldest_first=True):
						author_str = f"{msg.author.display_name} ({msg.author.id})"
						content_str = msg.clean_content.replace("<", "&lt;").replace(">", "&gt;")
						att_parts: list[str] = []
						for att in msg.attachments:
							ct = getattr(att, "content_type", "") or ""
							fn = getattr(att, "filename", "") or ""
							is_img = ct.startswith("image/") or fn.lower().endswith(
								(".png", ".jpg", ".jpeg", ".gif", ".webp")
							)
							if is_img and fallback_images < 5:
								try:
									data = await att.read()
									if len(data) <= 4 * 1024 * 1024:
										fallback_images += 1
										mime = ct or "image/png"
										b64 = base64.b64encode(data).decode("ascii")
										att_parts.append(
											f"<br><img src='data:{mime};base64,{b64}' style='max-width:400px;' alt='{fn}' />"
										)
									else:
										att_parts.append(f"<br>[Attachment: {fn}]")
								except (discord.DiscordException, OSError, ValueError):
									att_parts.append(f"<br>[Attachment: {fn}]")
							else:
								att_parts.append(f"<br>[Attachment: {fn}]")
						att_str = "".join(att_parts)
						lines.append(
							f"<li><strong>{author_str}</strong> [{msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}]: {content_str}{att_str}</li>"
						)
				except (discord.DiscordException, OSError) as e:
					logger.debug("Failed reading message history for fallback transcript: %s", e)
			lines.append("</ul></body></html>")
			transcript_str = "\n".join(lines)

		return process_compact_transcript(transcript_str, max_images=5)

	async def handle_ticket_create(self, interaction: discord.Interaction, topic: str, description: str):
		assert interaction.guild is not None
		assert isinstance(interaction.user, discord.Member)
		await interaction.response.defer(thinking=True, ephemeral=True)

		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and not cfg.get("is_on", True):
			return await self.send_response("ticket.errors.disabled", interaction, ephemeral=True)

		max_tickets = cfg.get("max_tickets", 1) if cfg else 1
		if max_tickets > 0:
			count = await self.get_active_ticket_count(interaction.guild.id, interaction.user.id)
			if count >= max_tickets:
				return await self.send_response(
					"ticket.errors.already_open", interaction, count=count, limit=max_tickets, ephemeral=True
				)

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
					return await self.send_response("ticket.errors.bot_perms", interaction, ephemeral=True)

		clean_username = re.sub(r"[^a-zA-Z0-9_-]", "", interaction.user.name.lower().replace(" ", "-"))[:20] or "user"
		channel_name = f"ticket-{clean_username}"

		opener_target: discord.Role | discord.Member | discord.Object = interaction.user

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
			return await self.send_response("ticket.errors.bot_perms", interaction, ephemeral=True)

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

		controls_view = await self.create_controls_view(interaction.guild, is_archived=False)
		await self.send_response(
			"ticket.created.message",
			ticket_channel,
			member=interaction.user,
			channel=ticket_channel,
			topic=topic,
			description=description,
			ticket_id=ticket_id,
			view=controls_view,
		)

		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				try:
					await self.send_response(
						"ticket.logs.created",
						log_ch,
						member=interaction.user,
						channel=ticket_channel,
						topic=topic,
						ticket_id=ticket_id,
					)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send ticket create log: {e}")

		await self.send_response(
			"ticket.created.ephemeral",
			interaction,
			channel=ticket_channel,
			ephemeral=True,
		)

	async def handle_archive_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			return await self.send_response("ticket.errors.not_ticket", interaction, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			return await self.send_response("ticket.errors.no_permission", interaction, ephemeral=True)

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

		if isinstance(interaction.channel, discord.abc.Messageable):
			controls_view = await self.create_controls_view(interaction.guild, is_archived=True)
			await self.send_response(
				"ticket.actions.archived",
				interaction.channel,
				author=interaction.user,
				ticket_id=ticket["id"],
				view=controls_view,
			)

		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				try:
					await self.send_response(
						"ticket.logs.archived",
						log_ch,
						actor=interaction.user,
						ticket_user_id=ticket["user_id"],
						channel=interaction.channel,
						ticket_id=ticket["id"],
					)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send archive log: {e}")

	async def handle_reopen_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			return await self.send_response("ticket.errors.not_ticket", interaction, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			return await self.send_response("ticket.errors.no_permission", interaction, ephemeral=True)

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

		if isinstance(interaction.channel, discord.abc.Messageable):
			controls_view = await self.create_controls_view(interaction.guild, is_archived=False)
			await self.send_response(
				"ticket.actions.reopened",
				interaction.channel,
				author=interaction.user,
				ticket_id=ticket["id"],
				view=controls_view,
			)

		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				try:
					await self.send_response(
						"ticket.logs.reopened",
						log_ch,
						actor=interaction.user,
						ticket_user_id=ticket["user_id"],
						channel=interaction.channel,
						ticket_id=ticket["id"],
					)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send reopen log: {e}")

	async def handle_save_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			return await self.send_response("ticket.errors.not_ticket", interaction, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			return await self.send_response("ticket.errors.no_permission", interaction, ephemeral=True)

		await interaction.response.defer()

		transcript = await self.export_transcript(interaction.channel, ticket["id"])  # type: ignore

		ch_name = getattr(interaction.channel, "name", "ticket")
		file_to_send = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")

		cfg = await self.get_ticket_config(interaction.guild.id)
		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")
				try:
					await self.send_response(
						"ticket.logs.saved",
						log_ch,
						actor=interaction.user,
						ticket_user_id=ticket["user_id"],
						channel=interaction.channel,
						ticket_id=ticket["id"],
						file=log_file,
					)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send save transcript log: {e}")

		await self.send_response(
			"ticket.actions.saved",
			interaction,
			file=file_to_send,
		)

	async def handle_close_action(self, interaction: discord.Interaction):
		assert interaction.guild is not None
		if not interaction.channel:
			return

		ticket = await self.get_ticket(interaction.channel.id)
		if not ticket:
			return await self.send_response("ticket.errors.not_ticket", interaction, ephemeral=True)

		if not await self.can_manage_ticket(interaction, ticket):
			return await self.send_response("ticket.errors.no_permission", interaction, ephemeral=True)

		await interaction.response.defer()

		if interaction.message:
			try:
				disabled_view = await self.create_disabled_controls_view(
					interaction.guild, is_archived=bool(ticket.get("is_archived", False))
				)
				await interaction.message.edit(view=disabled_view)
			except discord.HTTPException as e:
				logger.debug("Failed to disable buttons on close message: %s", e)

		await self.send_response(
			"ticket.actions.closed.generating",
			interaction,
		)

		transcript = await self.export_transcript(interaction.channel, ticket["id"])  # type: ignore

		await self.bot.db.execute(
			"""
			UPDATE tickets
			SET is_closed = true, is_archived = true, closed_at = now(), closed_by = $1
			WHERE id = $2
			""",
			interaction.user.id,
			ticket["id"],
		)

		ch_name = getattr(interaction.channel, "name", "ticket")
		cfg = await self.get_ticket_config(interaction.guild.id)

		if cfg and cfg.get("log_channel_id"):
			log_ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
			if log_ch and isinstance(log_ch, discord.abc.Messageable):
				log_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")
				try:
					await self.send_response(
						"ticket.logs.closed",
						log_ch,
						actor=interaction.user,
						ticket_user_id=ticket["user_id"],
						channel=interaction.channel,
						topic=ticket["title"],
						ticket_id=ticket["id"],
						file=log_file,
					)
				except discord.HTTPException as e:
					logger.warning(f"Failed to send close log: {e}")

		if cfg is None or cfg.get("dm_transcript", True):
			opener = interaction.guild.get_member(int(ticket["user_id"]))
			if not opener:
				try:
					opener = await self.bot.fetch_user(int(ticket["user_id"]))
				except (discord.HTTPException, discord.NotFound):
					opener = None
			if opener:
				dm_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"transcript-{ch_name}.html")
				try:
					await self.send_response(
						"ticket.dm.closed",
						opener,
						guild=interaction.guild,
						channel_name=ch_name,
						file=dm_file,
					)
				except (discord.Forbidden, discord.HTTPException) as e:
					logger.debug(f"Could not DM user {ticket['user_id']}: {e}")

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
