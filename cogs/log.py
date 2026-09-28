from __future__ import annotations

import datetime
import json
from logging import getLogger
from typing import TYPE_CHECKING, Any

import discord
from args import AutoModAction, AutoModRule, Invite, Member, Message, User
from args.channel import convert_to_custom_channel
from discord.ext import commands
from helpers import custom_response

if TYPE_CHECKING:
	import asyncpg
	from core import Bot

logger = getLogger(__name__)

AVAILABLE_MODULES: dict[str, str] = {
	# Message events
	"on_message_delete": "Message deletions (includes author and deleter if identifiable)",
	"on_bulk_message_delete": "Bulk message deletions",
	"on_message_edit": "Message content, embed, attachment, and pin edits",
	# Channel events
	"on_guild_channel_create": "Channel creation",
	"on_guild_channel_delete": "Channel deletion",
	"on_guild_channel_update": "Channel updates (name, topic, nsfw, slowmode, overwrites, position)",
	"on_guild_channel_pins_update": "Channel pinned messages updates",
	# Role events
	"on_guild_role_create": "Role creation",
	"on_guild_role_update": "Role updates (name, color, permissions)",
	"on_guild_role_delete": "Role deletion",
	# Member events
	"on_member_join": "Member joins",
	"on_member_remove": "Member leaves and kicks",
	"on_member_update": "Member updates (roles, nicknames, timeouts, server avatars)",
	"on_member_ban": "Member bans",
	"on_member_unban": "Member unbans",
	# Voice events
	"on_voice_state_update": "Voice join, leave, switch, deafen/undeafen, and mute/unmute",
	# AutoMod events
	"on_automod_rule_create": "AutoMod rule creation",
	"on_automod_rule_update": "AutoMod rule updates",
	"on_automod_rule_delete": "AutoMod rule deletion",
	"on_automod_action": "AutoMod action executions",
	# Guild events
	"on_guild_update": "Server name and icon updates",
	"on_guild_emojis_update": "Server emoji additions and removals",
	"on_guild_stickers_update": "Server sticker additions and removals",
	"on_invite_create": "Invite link creations",
	"on_invite_delete": "Invite link deletions",
	"on_webhooks_update": "Webhook updates",
	"on_guild_integrations_update": "Server integration updates",
	"on_raw_integration_delete": "Integration deletions",
	# Thread events
	"on_thread_create": "Thread creations",
	"on_thread_delete": "Thread deletions",
	"on_thread_update": "Thread updates (name, archive, lock)",
	"on_thread_join": "Bot joins a thread",
	"on_thread_remove": "Thread removed from cache",
	"on_thread_member_join": "Thread member joins",
	"on_thread_member_remove": "Thread member leaves",
	# Scheduled events
	"on_scheduled_event_create": "Scheduled event creations",
	"on_scheduled_event_delete": "Scheduled event deletions",
	"on_scheduled_event_update": "Scheduled event updates",
	# Soundboard events
	"on_soundboard_sound_create": "Soundboard sound creations",
	"on_soundboard_sound_delete": "Soundboard sound deletions",
	"on_soundboard_sound_update": "Soundboard sound updates",
	# Stage events
	"on_stage_instance_create": "Stage instance starts",
	"on_stage_instance_delete": "Stage instance ends",
	"on_stage_instance_update": "Stage instance topic updates",
	# Reaction events
	"on_reaction_add": "Reaction additions",
	"on_reaction_remove": "Reaction removals",
	"on_reaction_clear": "Reaction clears",
	"on_reaction_clear_emoji": "Reaction specific emoji clears",
	# Poll events
	"on_poll_vote_add": "Poll vote additions",
	"on_poll_vote_remove": "Poll vote removals",
}


class LogConfig:
	"""Cached per-guild log configuration."""

	__slots__ = ("channel_id", "channels", "guild_id", "is_on", "modules", "webhook_url")

	def __init__(self, row: dict[str, Any] | asyncpg.Record):
		self.guild_id: int = int(row["guild_id"])
		self.is_on: bool = bool(row["is_on"])
		self.webhook_url: str | None = row.get("webhook")
		self.channel_id: int | None = int(row["channel"]) if row.get("channel") else None

		raw_channels = row.get("channels") or {}
		if isinstance(raw_channels, str):
			try:
				raw_channels = json.loads(raw_channels)
			except (json.JSONDecodeError, TypeError, ValueError):
				raw_channels = {}
		self.channels: dict[str, int] = (
			{str(k): int(v) for k, v in raw_channels.items() if v} if isinstance(raw_channels, dict) else {}
		)
		self.modules: set[str] = set(row.get("modules") or [])

	def is_enabled(self, event: str) -> bool:
		return self.is_on and event in self.modules

	def channel_for(self, event: str) -> int | None:
		"""Return the per-event channel ID override, or the default channel."""
		return self.channels.get(event) or self.channel_id


class _UnknownActor:
	"""Fallback actor for when an audit log entry does not resolve to a user."""

	__slots__ = ("avatar", "display_name", "id", "mention", "name")

	def __init__(self, text: str = "Unknown"):
		self.name: str = text
		self.display_name: str = text
		self.mention: str = text
		self.id: int = 0
		self.avatar: str = ""

	def __str__(self) -> str:
		return self.name


async def _find_audit_entry(
	guild: discord.Guild,
	action: discord.AuditLogAction,
	target: discord.abc.Snowflake | None = None,
	*,
	channel: discord.abc.Snowflake | None = None,
	within: float = 5.0,
) -> discord.AuditLogEntry | None:
	"""Search recent audit log for a matching entry."""
	now = discord.utils.utcnow()
	try:
		async for entry in guild.audit_logs(limit=5, action=action):
			if (now - entry.created_at).total_seconds() > within:
				break
			if target and entry.target and entry.target.id != target.id:
				continue
			extra_channel = getattr(entry.extra, "channel", None)
			if channel and extra_channel is not None and getattr(extra_channel, "id", None) != channel.id:
				continue
			return entry
	except (discord.Forbidden, discord.HTTPException):
		pass
	return None


def _user_arg(user: discord.User | discord.Member | None) -> Member | User | _UnknownActor:
	"""Convert a discord user/member to the appropriate args dataclass."""
	if isinstance(user, discord.Member):
		return Member.from_member(user)
	if isinstance(user, discord.User):
		return User.from_user(user)
	return _UnknownActor()


def _format_overwrite_diff(
	before: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite],
	after: dict[discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite],
) -> str:
	"""Build a human-readable diff of permission overwrite changes."""
	lines: list[str] = []

	all_targets = set(before.keys()) | set(after.keys())
	for target in all_targets:
		old = before.get(target)
		new = after.get(target)
		name = target.mention if hasattr(target, "mention") else str(target)

		if old is None and new is not None:
			lines.append(f"**+** Overwrite added for {name}")
		elif old is not None and new is None:
			lines.append(f"**-** Overwrite removed for {name}")
		elif old is not None and new is not None:
			old_pair = old.pair()
			new_pair = new.pair()
			if old_pair != new_pair:
				lines.append(f"**~** Overwrite changed for {name}")

	return "\n".join(lines[:15]) if lines else "No visible changes"


class Logging(commands.Cog, name="Logging"):
	def __init__(self, client: Bot):
		self.client = client
		self.custom_response = custom_response.CustomResponse(client, "log")
		self._config_cache: dict[int, LogConfig | None] = {}

	async def cog_load(self):
		try:
			rows = await self.client.db.fetch("SELECT * FROM log")
			for row in rows:
				cfg = LogConfig(row)
				self._config_cache[cfg.guild_id] = cfg
		except Exception:
			logger.exception("Failed to load log configurations")

	def get_config(self, guild_id: int) -> LogConfig | None:
		"""Return the cached config for a guild, if present."""
		return self._config_cache.get(guild_id)

	async def _ensure_config(self, guild_id: int) -> LogConfig | None:
		if guild_id in self._config_cache:
			return self._config_cache[guild_id]
		row = await self.client.db.fetchrow("SELECT * FROM log WHERE guild_id = $1", guild_id)
		if row:
			cfg = LogConfig(row)
			self._config_cache[guild_id] = cfg
			return cfg
		self._config_cache[guild_id] = None
		return None

	def invalidate_cache(self, guild_id: int):
		"""Remove cached config so it gets re-fetched on next event."""
		self._config_cache.pop(guild_id, None)

	# ── database configuration helpers ────────────────────────

	async def enable_log(self, guild_id: int, channel_id: int | None = None) -> LogConfig:
		"""Enable logging for a guild, creating the DB row if not present."""
		modules = list(AVAILABLE_MODULES.keys())
		row = await self.client.db.fetchrow(
			"""
			INSERT INTO log (guild_id, is_on, channel, modules, channels)
			VALUES ($1, true, $2, $3, '{}'::jsonb)
			ON CONFLICT (guild_id) DO UPDATE
			SET is_on = true,
			    channel = COALESCE($2, log.channel)
			RETURNING *
			""",
			guild_id,
			channel_id,
			modules,
		)
		cfg = LogConfig(row)
		self._config_cache[guild_id] = cfg
		return cfg

	async def disable_log(self, guild_id: int) -> None:
		"""Disable logging for a guild."""
		await self.client.db.execute("UPDATE log SET is_on = false WHERE guild_id = $1", guild_id)
		self.invalidate_cache(guild_id)

	async def add_module(self, guild_id: int, module_name: str) -> bool:
		"""Add an event module to the guild's active logging modules."""
		if module_name not in AVAILABLE_MODULES:
			return False
		await self.client.db.execute(
			"""
			UPDATE log
			SET modules = array_append(array_remove(modules, $1), $1)
			WHERE guild_id = $2
			""",
			module_name,
			guild_id,
		)
		self.invalidate_cache(guild_id)
		return True

	async def remove_module(self, guild_id: int, module_name: str) -> bool:
		"""Remove an event module from the guild's active logging modules."""
		await self.client.db.execute(
			"UPDATE log SET modules = array_remove(modules, $1) WHERE guild_id = $2", module_name, guild_id
		)
		self.invalidate_cache(guild_id)
		return True

	async def set_event_channel(self, guild_id: int, event_name: str, channel_id: int | None) -> None:
		"""Set or clear a per-event channel override."""
		cfg = await self._ensure_config(guild_id)
		channels = dict(cfg.channels) if cfg else {}
		if channel_id is None:
			channels.pop(event_name, None)
		else:
			channels[event_name] = channel_id

		await self.client.db.execute("UPDATE log SET channels = $1 WHERE guild_id = $2", channels, guild_id)
		self.invalidate_cache(guild_id)

	async def set_default_channel(self, guild_id: int, channel_id: int) -> None:
		"""Set the fallback/default log channel for a guild."""
		await self.client.db.execute("UPDATE log SET channel = $1 WHERE guild_id = $2", channel_id, guild_id)
		self.invalidate_cache(guild_id)

	async def set_webhook(self, guild_id: int, webhook_url: str | None) -> None:
		"""Set or clear the webhook URL for a guild."""
		await self.client.db.execute("UPDATE log SET webhook = $1 WHERE guild_id = $2", webhook_url, guild_id)
		self.invalidate_cache(guild_id)

	# ── delivery ──────────────────────────────────────────────

	async def _send(self, guild: discord.Guild, event_name: str, key: str, /, **kwargs: Any):
		"""Resolve the localized payload and send it to the configured log channel.

		Parameters
		----------
		guild
			The guild the event occurred in.
		event_name
			The event name as stored in the ``modules`` column (e.g. ``on_message_delete``).
		key
			The full localization key (e.g. ``log.on_message_delete.delete``).
		**kwargs
			Formatting variables, converted to custom args where applicable.
		"""
		cfg = await self._ensure_config(guild.id)
		if not cfg or not cfg.is_enabled(event_name):
			return

		channel_id = cfg.channel_for(event_name)
		if not channel_id:
			return

		channel = guild.get_channel_or_thread(channel_id)
		if not channel or not isinstance(channel, discord.abc.Messageable):
			return

		payload = await self.custom_response.get_message(key, guild, convert_embeds=True, **kwargs)
		if not isinstance(payload, dict):
			return

		if cfg.webhook_url and self.client.session:
			try:
				webhook = discord.Webhook.from_url(cfg.webhook_url, session=self.client.session)
				bot_user = self.client.user
				await webhook.send(
					**payload,
					username=bot_user.display_name if bot_user else "Log",
					avatar_url=bot_user.display_avatar.url if bot_user else None,
				)
				return
			except (discord.HTTPException, ValueError):
				pass

		try:
			await channel.send(**payload)
		except (discord.Forbidden, discord.HTTPException):
			logger.debug(f"Failed to send log in {channel_id} for guild {guild.id}")

	# ── message events ────────────────────────────────────────

	@commands.Cog.listener()
	async def on_message_delete(self, message: discord.Message):
		if not message.guild or message.author.bot:
			return

		entry = await _find_audit_entry(
			message.guild, discord.AuditLogAction.message_delete, message.author, channel=message.channel, within=4.0
		)
		deleted_by = _user_arg(entry.user) if entry and entry.user else _user_arg(message.author)

		await self._send(
			message.guild,
			"on_message_delete",
			"log.on_message_delete.delete",
			message=Message.from_message(message),
			deleted_by=deleted_by,
		)

	@commands.Cog.listener()
	async def on_bulk_message_delete(self, messages: list[discord.Message]):
		if not messages or not messages[0].guild:
			return

		guild = messages[0].guild
		channel = messages[0].channel

		await self._send(
			guild,
			"on_bulk_message_delete",
			"log.on_bulk_message_delete.delete",
			channel=convert_to_custom_channel(channel),
			count=len(messages),
		)

	@commands.Cog.listener()
	async def on_message_edit(self, before: discord.Message, after: discord.Message):
		if not after.guild or after.author.bot:
			return

		before_msg = Message.from_message(before)
		after_msg = Message.from_message(after)

		if before.content != after.content:
			await self._send(
				after.guild, "on_message_edit", "log.on_message_edit.content", before=before_msg, after=after_msg
			)
		if before.embeds != after.embeds:
			await self._send(
				after.guild, "on_message_edit", "log.on_message_edit.embeds", before=before_msg, after=after_msg
			)
		if before.attachments != after.attachments:
			await self._send(
				after.guild, "on_message_edit", "log.on_message_edit.attachments", before=before_msg, after=after_msg
			)
		if before.pinned != after.pinned:
			await self._send(
				after.guild, "on_message_edit", "log.on_message_edit.pinned", before=before_msg, after=after_msg
			)

	# ── channel events ────────────────────────────────────────

	@commands.Cog.listener()
	async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
		entry = await _find_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel)
		created_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			channel.guild,
			"on_guild_channel_create",
			"log.on_guild_channel_create.create",
			channel=convert_to_custom_channel(channel),
			created_by=created_by,
		)

	@commands.Cog.listener()
	async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
		entry = await _find_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel)
		deleted_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			channel.guild,
			"on_guild_channel_delete",
			"log.on_guild_channel_delete.delete",
			channel=convert_to_custom_channel(channel),
			deleted_by=deleted_by,
		)

	@commands.Cog.listener()
	async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
		entry = await _find_audit_entry(after.guild, discord.AuditLogAction.channel_update, after)
		updated_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		before_arg = convert_to_custom_channel(before)
		after_arg = convert_to_custom_channel(after)
		base_kwargs: dict[str, object] = {"before": before_arg, "after": after_arg, "updated_by": updated_by}

		if getattr(before, "name", None) != getattr(after, "name", None):
			await self._send(after.guild, "on_guild_channel_update", "log.on_guild_channel_update.name", **base_kwargs)
		if getattr(before, "topic", None) != getattr(after, "topic", None):
			await self._send(after.guild, "on_guild_channel_update", "log.on_guild_channel_update.topic", **base_kwargs)
		if getattr(before, "nsfw", None) != getattr(after, "nsfw", None):
			await self._send(after.guild, "on_guild_channel_update", "log.on_guild_channel_update.nsfw", **base_kwargs)
		if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
			await self._send(
				after.guild, "on_guild_channel_update", "log.on_guild_channel_update.slowmode_delay", **base_kwargs
			)
		if before.position != after.position:
			await self._send(
				after.guild, "on_guild_channel_update", "log.on_guild_channel_update.position", **base_kwargs
			)
		if before.overwrites != after.overwrites:
			diff = _format_overwrite_diff(before.overwrites, after.overwrites)
			await self._send(
				after.guild,
				"on_guild_channel_update",
				"log.on_guild_channel_update.permissions",
				channel=after_arg,
				updated_by=updated_by,
				diff=diff,
			)

	@commands.Cog.listener()
	async def on_guild_channel_pins_update(
		self, channel: discord.abc.GuildChannel | discord.Thread, last_pin: datetime.datetime | None
	):
		if not hasattr(channel, "guild") or not channel.guild:
			return

		last_pin_str = discord.utils.format_dt(last_pin, "R") if last_pin else "None"

		await self._send(
			channel.guild,
			"on_guild_channel_pins_update",
			"log.on_guild_channel_pins_update.pins",
			channel=convert_to_custom_channel(channel),
			last_pin=last_pin_str,
		)

	# ── role events ───────────────────────────────────────────

	@commands.Cog.listener()
	async def on_guild_role_create(self, role: discord.Role):
		entry = await _find_audit_entry(role.guild, discord.AuditLogAction.role_create, role)
		created_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			role.guild, "on_guild_role_create", "log.on_guild_role_create.create", role=role, created_by=created_by
		)

	@commands.Cog.listener()
	async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
		if before.name == after.name and before.color == after.color and before.permissions == after.permissions:
			return

		entry = await _find_audit_entry(after.guild, discord.AuditLogAction.role_update, after)
		updated_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			after.guild,
			"on_guild_role_update",
			"log.on_guild_role_update.update",
			before=before,
			after=after,
			updated_by=updated_by,
		)

	@commands.Cog.listener()
	async def on_guild_role_delete(self, role: discord.Role):
		entry = await _find_audit_entry(role.guild, discord.AuditLogAction.role_delete, role)
		deleted_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			role.guild, "on_guild_role_delete", "log.on_guild_role_delete.delete", role=role, deleted_by=deleted_by
		)

	# ── member events ─────────────────────────────────────────

	@commands.Cog.listener()
	async def on_member_join(self, member: discord.Member):
		await self._send(member.guild, "on_member_join", "log.on_member_join.join", member=member)

	@commands.Cog.listener()
	async def on_member_remove(self, member: discord.Member):
		entry = await _find_audit_entry(member.guild, discord.AuditLogAction.kick, member)
		kicked_by = _user_arg(entry.user) if entry and entry.user else None
		reason = entry.reason if entry else None

		if kicked_by:
			await self._send(
				member.guild,
				"on_member_remove",
				"log.on_member_remove.kick",
				member=member,
				kicked_by=kicked_by,
				reason=reason or "No reason provided",
			)
		else:
			await self._send(member.guild, "on_member_remove", "log.on_member_remove.leave", member=member)

	@commands.Cog.listener()
	async def on_member_update(self, before: discord.Member, after: discord.Member):
		guild = after.guild

		# role changes
		if before.roles != after.roles:
			added = set(after.roles) - set(before.roles)
			removed = set(before.roles) - set(after.roles)

			if added or removed:
				entry = await _find_audit_entry(guild, discord.AuditLogAction.member_role_update, after)
				updated_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

				added_str = ", ".join(r.mention for r in added) if added else "None"
				removed_str = ", ".join(r.mention for r in removed) if removed else "None"

				await self._send(
					guild,
					"on_member_update",
					"log.on_member_update.roles",
					member=after,
					updated_by=updated_by,
					added=added_str,
					removed=removed_str,
				)

		# nickname change
		if before.nick != after.nick:
			entry = await _find_audit_entry(guild, discord.AuditLogAction.member_update, after)
			updated_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

			await self._send(
				guild,
				"on_member_update",
				"log.on_member_update.nickname",
				member=after,
				updated_by=updated_by,
				before_nick=before.nick or "None",
				after_nick=after.nick or "None",
			)

		# timeout added or updated
		if after.timed_out_until != before.timed_out_until:
			entry = await _find_audit_entry(guild, discord.AuditLogAction.member_update, after)
			reason = entry.reason if entry else None

			if after.timed_out_until:
				timed_out_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()
				await self._send(
					guild,
					"on_member_update",
					"log.on_member_update.timeout",
					member=after,
					timed_out_by=timed_out_by,
					until=discord.utils.format_dt(after.timed_out_until, "R"),
					reason=reason or "No reason provided",
				)
			else:
				removed_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()
				await self._send(
					guild,
					"on_member_update",
					"log.on_member_update.timeout_removed",
					member=after,
					removed_by=removed_by,
				)

		# server avatar change
		if before.guild_avatar != after.guild_avatar:
			await self._send(guild, "on_member_update", "log.on_member_update.avatar", member=after)

	# ── ban / unban ───────────────────────────────────────────

	@commands.Cog.listener()
	async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
		entry = await _find_audit_entry(guild, discord.AuditLogAction.ban, user)
		banned_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()
		reason = entry.reason if entry else None

		await self._send(
			guild,
			"on_member_ban",
			"log.on_member_ban.ban",
			user=user,
			banned_by=banned_by,
			reason=reason or "No reason provided",
		)

	@commands.Cog.listener()
	async def on_member_unban(self, guild: discord.Guild, user: discord.User):
		entry = await _find_audit_entry(guild, discord.AuditLogAction.unban, user)
		unbanned_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(guild, "on_member_unban", "log.on_member_unban.unban", user=user, unbanned_by=unbanned_by)

	# ── voice state ───────────────────────────────────────────

	@commands.Cog.listener()
	async def on_voice_state_update(
		self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
	):
		guild = member.guild

		# join
		if not before.channel and after.channel:
			await self._send(
				guild,
				"on_voice_state_update",
				"log.on_voice_state_update.join",
				member=member,
				channel=convert_to_custom_channel(after.channel),
			)

		# leave
		elif before.channel and not after.channel:
			await self._send(
				guild,
				"on_voice_state_update",
				"log.on_voice_state_update.leave",
				member=member,
				channel=convert_to_custom_channel(before.channel),
			)

		# move
		elif before.channel and after.channel and before.channel != after.channel:
			await self._send(
				guild,
				"on_voice_state_update",
				"log.on_voice_state_update.move",
				member=member,
				before_channel=convert_to_custom_channel(before.channel),
				after_channel=convert_to_custom_channel(after.channel),
			)

		# server deafen / undeafen
		if before.deaf != after.deaf:
			await self._send(
				guild,
				"on_voice_state_update",
				"log.on_voice_state_update.deafen" if after.deaf else "log.on_voice_state_update.undeafen",
				member=member,
				channel=convert_to_custom_channel(after.channel or before.channel),
			)

		# server mute / unmute
		if before.mute != after.mute:
			await self._send(
				guild,
				"on_voice_state_update",
				"log.on_voice_state_update.mute" if after.mute else "log.on_voice_state_update.unmute",
				member=member,
				channel=convert_to_custom_channel(after.channel or before.channel),
			)

	# ── automod events ────────────────────────────────────────

	@commands.Cog.listener()
	async def on_automod_rule_create(self, rule: discord.AutoModRule):
		await self._send(
			rule.guild,
			"on_automod_rule_create",
			"log.on_automod_rule_create.create",
			rule=await AutoModRule.from_rule(rule),
		)

	@commands.Cog.listener()
	async def on_automod_rule_update(self, rule: discord.AutoModRule):
		await self._send(
			rule.guild,
			"on_automod_rule_update",
			"log.on_automod_rule_update.update",
			rule=await AutoModRule.from_rule(rule),
		)

	@commands.Cog.listener()
	async def on_automod_rule_delete(self, rule: discord.AutoModRule):
		await self._send(
			rule.guild,
			"on_automod_rule_delete",
			"log.on_automod_rule_delete.delete",
			rule=await AutoModRule.from_rule(rule),
		)

	@commands.Cog.listener()
	async def on_automod_action(self, execution: discord.AutoModAction):
		await self._send(
			execution.guild,
			"on_automod_action",
			"log.on_automod_action.action",
			execution=AutoModAction.from_action(execution),
		)

	# ── guild update ──────────────────────────────────────────

	@commands.Cog.listener()
	async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
		if before.name == after.name and before.icon == after.icon:
			return

		entry = await _find_audit_entry(after, discord.AuditLogAction.guild_update)
		updated_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			after, "on_guild_update", "log.on_guild_update.update", before=before, after=after, updated_by=updated_by
		)

	# ── emoji / sticker events ────────────────────────────────

	@commands.Cog.listener()
	async def on_guild_emojis_update(
		self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]
	):
		before_ids = {e.id for e in before}
		after_ids = {e.id for e in after}

		added = [e for e in after if e.id not in before_ids]
		removed = [e for e in before if e.id not in after_ids]

		if added:
			await self._send(
				guild,
				"on_guild_emojis_update",
				"log.on_guild_emojis_update.add",
				emojis=" ".join(str(e) for e in added[:20]),
			)
		if removed:
			await self._send(
				guild,
				"on_guild_emojis_update",
				"log.on_guild_emojis_update.remove",
				emojis=", ".join(f"`:{e.name}:`" for e in removed[:20]),
			)

	@commands.Cog.listener()
	async def on_guild_stickers_update(
		self, guild: discord.Guild, before: list[discord.GuildSticker], after: list[discord.GuildSticker]
	):
		before_ids = {s.id for s in before}
		after_ids = {s.id for s in after}

		added = [s for s in after if s.id not in before_ids]
		removed = [s for s in before if s.id not in after_ids]

		if added:
			await self._send(
				guild,
				"on_guild_stickers_update",
				"log.on_guild_stickers_update.add",
				stickers=", ".join(f"`{s.name}`" for s in added),
			)
		if removed:
			await self._send(
				guild,
				"on_guild_stickers_update",
				"log.on_guild_stickers_update.remove",
				stickers=", ".join(f"`{s.name}`" for s in removed),
			)

	# ── invite events ─────────────────────────────────────────

	@commands.Cog.listener()
	async def on_invite_create(self, invite: discord.Invite):
		if not invite.guild or not isinstance(invite.guild, discord.Guild):
			return

		await self._send(
			invite.guild, "on_invite_create", "log.on_invite_create.create", invite=Invite.from_invite(invite)
		)

	@commands.Cog.listener()
	async def on_invite_delete(self, invite: discord.Invite):
		if not invite.guild or not isinstance(invite.guild, discord.Guild):
			return

		await self._send(
			invite.guild, "on_invite_delete", "log.on_invite_delete.delete", invite=Invite.from_invite(invite)
		)

	# ── webhook updates ───────────────────────────────────────

	@commands.Cog.listener()
	async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
		await self._send(
			channel.guild,
			"on_webhooks_update",
			"log.on_webhooks_update.update",
			channel=convert_to_custom_channel(channel),
		)

	# ── integration events ────────────────────────────────────

	@commands.Cog.listener()
	async def on_guild_integrations_update(self, guild: discord.Guild):
		await self._send(guild, "on_guild_integrations_update", "log.on_guild_integrations_update.update")

	@commands.Cog.listener()
	async def on_raw_integration_delete(self, payload: discord.RawIntegrationDeleteEvent):
		guild = self.client.get_guild(payload.guild_id)
		if not guild:
			return
		await self._send(
			guild,
			"on_raw_integration_delete",
			"log.on_raw_integration_delete.delete",
			integration_id=payload.integration_id,
			application_id=payload.application_id,
		)

	# ── thread events ─────────────────────────────────────────

	@commands.Cog.listener()
	async def on_thread_create(self, thread: discord.Thread):
		await self._send(thread.guild, "on_thread_create", "log.on_thread_create.create", thread=thread)

	@commands.Cog.listener()
	async def on_thread_delete(self, thread: discord.Thread):
		await self._send(thread.guild, "on_thread_delete", "log.on_thread_delete.delete", thread=thread)

	@commands.Cog.listener()
	async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
		if before.name == after.name and before.archived == after.archived and before.locked == after.locked:
			return

		await self._send(after.guild, "on_thread_update", "log.on_thread_update.update", before=before, after=after)

	@commands.Cog.listener()
	async def on_thread_join(self, thread: discord.Thread):
		await self._send(thread.guild, "on_thread_join", "log.on_thread_join.join", thread=thread)

	@commands.Cog.listener()
	async def on_thread_remove(self, thread: discord.Thread):
		await self._send(thread.guild, "on_thread_remove", "log.on_thread_remove.remove", thread=thread)

	@commands.Cog.listener()
	async def on_thread_member_join(self, member: discord.ThreadMember):
		if not member.thread:
			return
		await self._send(
			member.thread.guild,
			"on_thread_member_join",
			"log.on_thread_member_join.join",
			thread=member.thread,
			user_id=member.id,
		)

	@commands.Cog.listener()
	async def on_thread_member_remove(self, member: discord.ThreadMember):
		if not member.thread:
			return
		await self._send(
			member.thread.guild,
			"on_thread_member_remove",
			"log.on_thread_member_remove.leave",
			thread=member.thread,
			user_id=member.id,
		)

	# ── scheduled event events ────────────────────────────────

	@commands.Cog.listener()
	async def on_scheduled_event_create(self, event: discord.ScheduledEvent):
		if not event.guild:
			return
		await self._send(event.guild, "on_scheduled_event_create", "log.on_scheduled_event_create.create", event=event)

	@commands.Cog.listener()
	async def on_scheduled_event_delete(self, event: discord.ScheduledEvent):
		if not event.guild:
			return
		await self._send(event.guild, "on_scheduled_event_delete", "log.on_scheduled_event_delete.delete", event=event)

	@commands.Cog.listener()
	async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent):
		if not after.guild:
			return
		if before.name == after.name and before.status == after.status:
			return

		await self._send(
			after.guild, "on_scheduled_event_update", "log.on_scheduled_event_update.update", before=before, after=after
		)

	# ── soundboard events ─────────────────────────────────────

	@commands.Cog.listener()
	async def on_soundboard_sound_create(self, sound: discord.SoundboardSound):
		if not sound.guild:
			return
		await self._send(
			sound.guild, "on_soundboard_sound_create", "log.on_soundboard_sound_create.create", sound=sound
		)

	@commands.Cog.listener()
	async def on_soundboard_sound_delete(self, sound: discord.SoundboardSound):
		if not sound.guild:
			return
		await self._send(
			sound.guild, "on_soundboard_sound_delete", "log.on_soundboard_sound_delete.delete", sound=sound
		)

	@commands.Cog.listener()
	async def on_soundboard_sound_update(self, before: discord.SoundboardSound, after: discord.SoundboardSound):
		if not after.guild:
			return
		await self._send(
			after.guild,
			"on_soundboard_sound_update",
			"log.on_soundboard_sound_update.update",
			before=before,
			after=after,
		)

	# ── stage instance events ─────────────────────────────────

	@commands.Cog.listener()
	async def on_stage_instance_create(self, stage: discord.StageInstance):
		await self._send(stage.guild, "on_stage_instance_create", "log.on_stage_instance_create.create", stage=stage)

	@commands.Cog.listener()
	async def on_stage_instance_delete(self, stage: discord.StageInstance):
		await self._send(stage.guild, "on_stage_instance_delete", "log.on_stage_instance_delete.delete", stage=stage)

	@commands.Cog.listener()
	async def on_stage_instance_update(self, before: discord.StageInstance, after: discord.StageInstance):
		if before.topic == after.topic:
			return
		await self._send(
			after.guild, "on_stage_instance_update", "log.on_stage_instance_update.update", before=before, after=after
		)

	# ── reaction events ───────────────────────────────────────

	@commands.Cog.listener()
	async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Member | discord.User):
		if not reaction.message.guild or user.bot:
			return
		await self._send(
			reaction.message.guild,
			"on_reaction_add",
			"log.on_reaction_add.add",
			user=user,
			emoji=str(reaction.emoji),
			message_url=reaction.message.jump_url,
		)

	@commands.Cog.listener()
	async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.Member | discord.User):
		if not reaction.message.guild or user.bot:
			return
		await self._send(
			reaction.message.guild,
			"on_reaction_remove",
			"log.on_reaction_remove.remove",
			user=user,
			emoji=str(reaction.emoji),
			message_url=reaction.message.jump_url,
		)

	@commands.Cog.listener()
	async def on_reaction_clear(self, message: discord.Message, reactions: list[discord.Reaction]):
		if not message.guild:
			return
		await self._send(
			message.guild,
			"on_reaction_clear",
			"log.on_reaction_clear.clear",
			message_url=message.jump_url,
			count=len(reactions),
		)

	@commands.Cog.listener()
	async def on_reaction_clear_emoji(self, reaction: discord.Reaction):
		if not reaction.message.guild:
			return
		await self._send(
			reaction.message.guild,
			"on_reaction_clear_emoji",
			"log.on_reaction_clear_emoji.clear",
			emoji=str(reaction.emoji),
			message_url=reaction.message.jump_url,
		)

	# ── poll events ───────────────────────────────────────────

	@commands.Cog.listener()
	async def on_poll_vote_add(self, payload: discord.RawPollVoteActionEvent):
		guild = self.client.get_guild(payload.guild_id) if payload.guild_id else None
		if not guild:
			return
		await self._send(
			guild,
			"on_poll_vote_add",
			"log.on_poll_vote_add.add",
			user_id=payload.user_id,
			message_id=payload.message_id,
			answer_id=payload.answer_id,
		)

	@commands.Cog.listener()
	async def on_poll_vote_remove(self, payload: discord.RawPollVoteActionEvent):
		guild = self.client.get_guild(payload.guild_id) if payload.guild_id else None
		if not guild:
			return
		await self._send(
			guild,
			"on_poll_vote_remove",
			"log.on_poll_vote_remove.remove",
			user_id=payload.user_id,
			message_id=payload.message_id,
			answer_id=payload.answer_id,
		)


async def setup(client: Bot):
	await client.add_cog(Logging(client))
