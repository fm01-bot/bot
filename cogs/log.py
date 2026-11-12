from __future__ import annotations

import datetime
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from logging import getLogger
from typing import TYPE_CHECKING, Any, Protocol

import discord
from args import AutoModAction, AutoModRule, Invite, Member, Message, User
from args.channel import convert_to_custom_channel
from discord.ext import commands
from helpers import custom_response

if TYPE_CHECKING:
	import asyncpg
	from core import Bot
	from core.settings import GuildSetting, GuildSettings

logger = getLogger(__name__)

LOG_MODULES: frozenset[str] = frozenset(
	{
		"on_message_delete",
		"on_bulk_message_delete",
		"on_message_edit",
		"on_guild_channel_create",
		"on_guild_channel_delete",
		"on_guild_channel_update",
		"on_guild_channel_pins_update",
		"on_guild_role_create",
		"on_guild_role_update",
		"on_guild_role_delete",
		"on_member_join",
		"on_member_remove",
		"on_member_update",
		"on_member_ban",
		"on_member_unban",
		"on_voice_state_update",
		"on_automod_rule_create",
		"on_automod_rule_update",
		"on_automod_rule_delete",
		"on_automod_action",
		"on_guild_update",
		"on_guild_emojis_update",
		"on_guild_stickers_update",
		"on_invite_create",
		"on_invite_delete",
		"on_webhooks_update",
		"on_guild_integrations_update",
		"on_raw_integration_delete",
		"on_thread_create",
		"on_thread_delete",
		"on_thread_update",
		"on_thread_join",
		"on_thread_remove",
		"on_thread_member_join",
		"on_thread_member_remove",
		"on_scheduled_event_create",
		"on_scheduled_event_delete",
		"on_scheduled_event_update",
		"on_soundboard_sound_create",
		"on_soundboard_sound_delete",
		"on_soundboard_sound_update",
		"on_stage_instance_create",
		"on_stage_instance_delete",
		"on_stage_instance_update",
		"on_reaction_add",
		"on_reaction_remove",
		"on_reaction_clear",
		"on_reaction_clear_emoji",
		"on_poll_vote_add",
		"on_poll_vote_remove",
	}
)
AVAILABLE_MODULES = LOG_MODULES


ALL_MODULES = "*"
"""Stored in ``log.modules`` (it is the column default) to mean every module, including ones added later."""

MESSAGE_MODULES = frozenset({"on_message_delete", "on_message_edit"})
"""Modules that need message content, which the bot buffers for logging guilds (see ``Bot.on_message``)."""


@dataclass(frozen=True, slots=True)
class LogConfig:
	"""A guild's log configuration (one row of ``log``)."""

	guild_id: int
	is_on: bool = False
	channel_id: int | None = None
	channels: Mapping[str, int] = field(default_factory=dict)
	modules: frozenset[str] = frozenset({ALL_MODULES})
	webhook_url: str | None = None

	@classmethod
	def from_row(cls, row: Mapping[str, Any]) -> LogConfig:
		"""Build a config from a ``log`` row."""
		raw_channels = row.get("channels") or {}
		if isinstance(raw_channels, str):
			try:
				raw_channels = json.loads(raw_channels)
			except (json.JSONDecodeError, TypeError, ValueError):
				raw_channels = {}
		return cls(
			guild_id=int(row["guild_id"]),
			is_on=bool(row["is_on"]),
			channel_id=int(row["channel"]) if row.get("channel") else None,
			channels={str(k): int(v) for k, v in raw_channels.items() if v} if isinstance(raw_channels, dict) else {},
			modules=frozenset(row.get("modules") or ()),
			webhook_url=row.get("webhook"),
		)

	@property
	def enabled_modules(self) -> frozenset[str]:
		"""The modules in effect, with ``*`` expanded."""
		return LOG_MODULES if ALL_MODULES in self.modules else self.modules & LOG_MODULES

	def is_enabled(self, event: str) -> bool:
		return self.is_on and event in self.enabled_modules

	@property
	def logs_messages(self) -> bool:
		"""Whether the bot must buffer this guild's messages so deletions and edits can be logged."""
		return any(self.is_enabled(module) for module in MESSAGE_MODULES)

	def channel_for(self, event: str) -> int | None:
		"""Return the per-event channel ID override, or the default channel."""
		return self.channels.get(event) or self.channel_id

	def with_modules(self, added: Iterable[str] = (), removed: Iterable[str] = ()) -> LogConfig:
		"""Return a copy with modules enabled and disabled. Expands ``*`` when something is removed."""
		removed = frozenset(removed)
		base = self.enabled_modules if removed else self.modules
		if ALL_MODULES in base:
			return self
		return replace(self, modules=(base | frozenset(added)) - removed)


async def _load_log_config(db: asyncpg.Pool, guild_id: int) -> LogConfig | None:
	row = await db.fetchrow("SELECT * FROM log WHERE guild_id = $1", guild_id)
	return LogConfig.from_row(row) if row else None


async def _load_all_log_configs(db: asyncpg.Pool) -> dict[int, LogConfig | None]:
	return {cfg.guild_id: cfg for cfg in map(LogConfig.from_row, await db.fetch("SELECT * FROM log"))}


async def _save_log_config(db: asyncpg.Pool, guild_id: int, cfg: LogConfig | None) -> None:
	if cfg is None:
		await db.execute("DELETE FROM log WHERE guild_id = $1", guild_id)
		return
	await db.execute(
		"""
		INSERT INTO log (guild_id, is_on, channel, modules, channels, webhook)
		VALUES ($1, $2, $3, $4, $5, $6)
		ON CONFLICT (guild_id) DO UPDATE
		SET is_on = EXCLUDED.is_on, channel = EXCLUDED.channel, modules = EXCLUDED.modules,
		    channels = EXCLUDED.channels, webhook = EXCLUDED.webhook
		""",
		guild_id,
		cfg.is_on,
		cfg.channel_id,
		sorted(cfg.modules),
		dict(cfg.channels),
		cfg.webhook_url,
	)


class LogHost(Protocol):
	"""What `LogSettings` needs from the bot."""

	settings: GuildSettings
	message_logging_guilds: set[int]


class LogSettings:
	"""A guild's log configuration as a guild setting, and the changes the log commands make to it.

	Usable without the Logging cog loaded (the config commands use it directly). Keeps
	``Bot.message_logging_guilds`` in step with which guilds log message deletions or edits.
	"""

	def __init__(self, bot: LogHost) -> None:
		def track_message_logging(guild_id: int, cfg: LogConfig | None) -> None:
			if cfg is not None and cfg.logs_messages:
				bot.message_logging_guilds.add(guild_id)
			else:
				bot.message_logging_guilds.discard(guild_id)

		self.setting: GuildSetting[LogConfig | None] = bot.settings.add(
			"log",
			_load_log_config,
			_save_log_config,
			load_all=_load_all_log_configs,
			on_change=track_message_logging,
		)

	async def get(self, guild_id: int) -> LogConfig | None:
		"""The guild's configuration, or ``None`` if logging was never set up."""
		return await self.setting.get(guild_id)

	async def _update(self, guild_id: int, change: Callable[[LogConfig], LogConfig]) -> LogConfig:
		cfg = change(await self.get(guild_id) or LogConfig(guild_id))
		await self.setting.set(guild_id, cfg)
		return cfg

	async def enable(self, guild_id: int, channel_id: int | None = None) -> LogConfig:
		"""Turn logging on, optionally moving it to ``channel_id``. New guilds log every module."""
		return await self._update(
			guild_id, lambda cfg: replace(cfg, is_on=True, channel_id=channel_id or cfg.channel_id)
		)

	async def disable(self, guild_id: int) -> LogConfig:
		"""Turn logging off, keeping the rest of the configuration."""
		return await self._update(guild_id, lambda cfg: replace(cfg, is_on=False))

	async def add_modules(self, guild_id: int, modules: Iterable[str]) -> LogConfig:
		"""Enable event modules. Unknown names are ignored."""
		valid = frozenset(modules) & LOG_MODULES
		return await self._update(guild_id, lambda cfg: cfg.with_modules(added=valid))

	async def remove_modules(self, guild_id: int, modules: Iterable[str]) -> LogConfig:
		"""Disable event modules."""
		return await self._update(guild_id, lambda cfg: cfg.with_modules(removed=modules))

	async def set_event_channel(self, guild_id: int, event_name: str, channel_id: int | None) -> LogConfig:
		"""Set or clear a per-event channel override."""

		def change(cfg: LogConfig) -> LogConfig:
			channels = {k: v for k, v in cfg.channels.items() if k != event_name}
			if channel_id is not None:
				channels[event_name] = channel_id
			return replace(cfg, channels=channels)

		return await self._update(guild_id, change)

	async def set_default_channel(self, guild_id: int, channel_id: int) -> LogConfig:
		"""Set the fallback log channel."""
		return await self._update(guild_id, lambda cfg: replace(cfg, channel_id=channel_id))

	async def set_webhook(self, guild_id: int, webhook_url: str | None) -> LogConfig:
		"""Set or clear the webhook the logs are sent through."""
		return await self._update(guild_id, lambda cfg: replace(cfg, webhook_url=webhook_url))


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
	target: Any = None,
	*,
	channel: Any = None,
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
		self.config = LogSettings(client)

	async def _send(self, guild: discord.Guild, event_name: str, key: str, /, **kwargs: Any):
		"""Resolve the localized payload and send it to the configured log channel.

		Args:
			guild: The guild the event occurred in.
			event_name: The event name as stored in the ``modules`` column (e.g. ``on_message_delete``).
			key: The full localization key (e.g. ``log.on_message_delete.delete``).
			**kwargs: Formatting variables, converted to custom args where applicable.

		"""
		cfg = await self.config.get(guild.id)
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

	@commands.Cog.listener()
	async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
		if not payload.guild_id:
			return

		guild = self.client.get_guild(payload.guild_id)
		if not guild:
			return

		if payload.cached_message:
			await self.on_message_delete(payload.cached_message)
			return

		snapshot = await self.client.message_buffer.get_message(payload.channel_id, payload.message_id)
		if not snapshot:
			return

		channel = guild.get_channel_or_thread(payload.channel_id)
		author_id = snapshot.get("author_id", 0)
		author_member = guild.get_member(author_id)
		deleted_by = (
			_user_arg(author_member) if author_member else _UnknownActor(snapshot.get("author_name", "Unknown"))
		)

		entry = await _find_audit_entry(
			guild, discord.AuditLogAction.message_delete, target=author_member, channel=channel, within=4.0
		)
		if entry and entry.user:
			deleted_by = _user_arg(entry.user)

		msg_arg = Message.from_snapshot(snapshot, guild=guild, channel=channel)
		await self._send(
			guild,
			"on_message_delete",
			"log.on_message_delete.delete",
			message=msg_arg,
			deleted_by=deleted_by,
		)

	@commands.Cog.listener()
	async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
		guild_id = payload.data.get("guild_id")
		if not guild_id:
			return
		guild = self.client.get_guild(int(guild_id))
		if not guild:
			return

		if payload.cached_message:
			return

		new_content = payload.data.get("content")
		if new_content is None:
			return

		snapshot = await self.client.message_buffer.get_message(payload.channel_id, payload.message_id)
		if not snapshot:
			return

		old_content = snapshot.get("content", "")
		if old_content == new_content:
			return

		channel = guild.get_channel_or_thread(payload.channel_id)
		before_msg = Message.from_snapshot(snapshot, guild=guild, channel=channel)
		after_snapshot = dict(snapshot)
		after_snapshot["content"] = new_content
		after_msg = Message.from_snapshot(after_snapshot, guild=guild, channel=channel)

		await self._send(
			guild,
			"on_message_edit",
			"log.on_message_edit.content",
			before=before_msg,
			after=after_msg,
		)

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

	@commands.Cog.listener()
	async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
		if before.name == after.name and before.icon == after.icon:
			return

		entry = await _find_audit_entry(after, discord.AuditLogAction.guild_update)
		updated_by = _user_arg(entry.user) if entry and entry.user else _UnknownActor()

		await self._send(
			after, "on_guild_update", "log.on_guild_update.update", before=before, after=after, updated_by=updated_by
		)

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

	@commands.Cog.listener()
	async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
		await self._send(
			channel.guild,
			"on_webhooks_update",
			"log.on_webhooks_update.update",
			channel=convert_to_custom_channel(channel),
		)

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
