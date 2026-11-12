from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, ClassVar, Literal, Self, TypeVar

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import MISSING

from core import slash_localization
from core.slash_localization import command_key

__all__ = ("HybridCommand", "HybridGroup", "command", "group")

T = TypeVar("T")
CogT = TypeVar("CogT")

CommandCallback = Callable[..., Any]

type Permission = Literal[
	"add_reactions",
	"administrator",
	"attach_files",
	"ban_members",
	"change_nickname",
	"connect",
	"create_events",
	"create_expressions",
	"create_instant_invite",
	"create_polls",
	"create_private_threads",
	"create_public_threads",
	"deafen_members",
	"embed_links",
	"external_emojis",
	"external_stickers",
	"kick_members",
	"manage_channels",
	"manage_emojis",
	"manage_emojis_and_stickers",
	"manage_events",
	"manage_expressions",
	"manage_guild",
	"manage_messages",
	"manage_nicknames",
	"manage_permissions",
	"manage_roles",
	"manage_threads",
	"manage_webhooks",
	"mention_everyone",
	"moderate_members",
	"move_members",
	"mute_members",
	"priority_speaker",
	"read_message_history",
	"read_messages",
	"request_to_speak",
	"send_messages",
	"send_messages_in_threads",
	"send_polls",
	"send_tts_messages",
	"send_voice_messages",
	"speak",
	"stream",
	"use_application_commands",
	"use_embedded_activities",
	"use_external_apps",
	"use_external_emojis",
	"use_external_sounds",
	"use_external_stickers",
	"use_soundboard",
	"use_voice_activation",
	"value",
	"view_audit_log",
	"view_channel",
	"view_creator_monetization_analytics",
	"view_guild_insights",
]

__all__ = ("command", "group")


def _normalize_l10n_message(message: str | app_commands.locale_str | None, fallback: str) -> str:
	if isinstance(message, app_commands.locale_str):
		return message.message
	if message:
		return message
	return fallback


def _l10n_str(message: str | app_commands.locale_str, key: str) -> app_commands.locale_str:
	return app_commands.locale_str(_normalize_l10n_message(message, ""), key=key)


def _l10n_desc(message: str | app_commands.locale_str | None, key: str) -> app_commands.locale_str:
	return app_commands.locale_str(_normalize_l10n_message(message, "..."), key=key)


def _localize_params(command: app_commands.Command | commands.hybrid.HybridAppCommand, base: str) -> None:
	for param in command._params.values():
		param._rename = _l10n_str(param.name, command_key(base, "args", param.name, "name"))
		param.description = _l10n_desc(param.description, command_key(base, "args", param.name, "desc"))


def _localize_app_command_attributes(
	command_or_group: None | app_commands.Command | app_commands.Group | commands.hybrid.HybridAppCommand, base: str
) -> None | app_commands.Command | app_commands.Group | commands.hybrid.HybridAppCommand:
	"""Point a command's (or group's) name, description and parameters at its keys under ``base``."""
	if not command_or_group:
		return None
	command_or_group._locale_name = _l10n_str(command_or_group.name, command_key(base, "name"))
	command_or_group._locale_description = _l10n_desc(command_or_group.description, command_key(base, "desc"))
	if not isinstance(command_or_group, app_commands.Group):
		_localize_params(command_or_group, base)
	return command_or_group


class HybridAppCommand(commands.hybrid.HybridAppCommand):
	__commands_is_hybrid_app_command__: ClassVar[bool] = True

	@property
	def usage(self) -> str | None:
		return getattr(self.wrapped, "usage", None)

	def __init__(self, wrapped: HybridCommand | HybridGroup, name: str | app_commands.locale_str | None = None) -> None:
		super().__init__(wrapped, name)

		base = getattr(wrapped, "l10n_key", None)
		if base:
			if isinstance(wrapped, HybridGroup):
				# The group's own callback, exposed as its fallback subcommand.
				self._locale_name = _l10n_str(self.name, command_key(base, "fallback"))
				self._locale_description = _l10n_desc(self.description, command_key(base, "desc"))
				_localize_params(self, base)
			else:
				_localize_app_command_attributes(self, base)

	async def _transform_arguments(
		self, interaction: discord.Interaction, namespace: app_commands.Namespace
	) -> dict[str, Any]:
		# Ensure all param.display_name keys exist in namespace if keyed by param.name
		for param in self._params.values():
			if param.display_name not in namespace.__dict__ and param.name in namespace.__dict__:
				namespace.__dict__[param.display_name] = namespace.__dict__[param.name]
		return await super()._transform_arguments(interaction, namespace)


class _CommandOptions:
	"""Options shared by `HybridCommand` and `HybridGroup`: permissions, where it runs, and its localization key."""

	permissions: list[Permission] | None
	l10n_key: str | None
	user: bool
	guild: bool
	usage: str | None
	checks: list[Any]
	clean_params: dict[str, Any]
	__original_kwargs__: dict[str, Any]

	def _apply_options(
		self, base: str | None, permissions: list[Permission] | None, l10n_key: str | None, user: bool, guild: bool
	) -> None:
		self.permissions = permissions
		self.l10n_key = l10n_key
		self.user = user
		self.guild = guild

		if self.usage is None and self.clean_params and base:
			self.usage = command_key(base, "usage")
			self.__original_kwargs__["usage"] = self.usage

		if permissions:
			self.checks.append(commands.has_permissions(**dict.fromkeys(permissions, True)).predicate)
		if not user:
			self.checks.append(commands.guild_only().predicate)
		if not guild:
			self.checks.append(commands.dm_only().predicate)

	def _apply_installs(self, app_command: Any) -> None:
		app_command.allowed_installs = app_commands.AppInstallationType(guild=self.guild, user=self.user)
		app_command.allowed_contexts = app_commands.AppCommandContext(
			guild=self.guild, dm_channel=self.user, private_channel=self.user
		)

	def _copy_options(self, other: Any) -> Any:
		other.permissions = self.permissions
		other.l10n_key = self.l10n_key
		other.user = self.user
		other.guild = self.guild
		other.usage = self.usage
		return other


class HybridCommand(_CommandOptions, commands.HybridCommand):
	callback: Any

	def __init__(
		self,
		func: CommandCallback | Callable[..., Coroutine[Any, Any, Any]],
		/,
		name: Any,
		description: Any,
		permissions: list[Permission] | None = None,
		l10n_key: str | None = None,
		user: bool = True,
		guild: bool = True,
		usage: str | None = None,
		**kwargs: Any,
	):
		base = l10n_key or name or getattr(func, "__name__", None)
		super().__init__(func, name=name, description=description, usage=usage, **kwargs)
		self._apply_options(base, permissions, l10n_key, user, guild)

		if self.with_app_command:
			self.app_command = HybridAppCommand(self)
			self._apply_installs(self.app_command)

	def _ensure_assignment_on_copy(self, other: Self) -> Self:
		return self._copy_options(super()._ensure_assignment_on_copy(other))


class HybridGroup(_CommandOptions, commands.HybridGroup):
	callback: Any

	def __init__(
		self,
		func: CommandCallback | Callable[..., Any],
		/,
		name: str | app_commands.locale_str = MISSING,
		description: str | app_commands.locale_str = MISSING,
		permissions: list[Permission] | None = None,
		fallback: bool | str | None = True,
		l10n_key: str | None = None,
		user: bool = True,
		guild: bool = True,
		usage: str | None = None,
		**kwargs: Any,
	):
		base = _normalize_l10n_message(l10n_key or name or None, getattr(func, "__name__", ""))
		if isinstance(fallback, str):
			resolved_fallback = fallback
		elif fallback:
			resolved_fallback = slash_localization.lookup(command_key(base, "fallback"))
		else:
			resolved_fallback = None

		super().__init__(func, name=name, description=description, fallback=resolved_fallback, usage=usage, **kwargs)
		self._apply_options(base, permissions, l10n_key, user, guild)

		if self.app_command:
			# Here rather than in group(): copies made by CogMeta re-run __init__ with a fresh app_commands.Group.
			_localize_app_command_attributes(self.app_command, base)
			self._apply_installs(self.app_command)

		if self.fallback:
			self.app_command.remove_command(self.fallback)
			fallback_command = HybridAppCommand(self, name=getattr(self, "fallback_locale", None) or self.fallback)
			self.app_command.add_command(fallback_command)

	def _ensure_assignment_on_copy(self, other: Self) -> Self:
		return self._copy_options(super()._ensure_assignment_on_copy(other))

	def command(  # type: ignore[override]
		self,
		name: str | app_commands.locale_str | None = None,
		*args: Any,
		l10n_key: str | None = None,
		with_app_command: bool = True,
		user: bool = True,
		guild: bool = True,
		**kwargs: Any,
	) -> Callable[[CommandCallback], Any]:
		def decorator(func: CommandCallback):
			kwargs.setdefault("parent", self)
			result = command(
				name=name.message
				if isinstance(name, app_commands.locale_str)
				else name or getattr(func, "__name__", None),  # ugly but it works
				l10n_key=l10n_key,
				user=user,
				guild=guild,
				with_app_command=with_app_command,
				**kwargs,
			)(func)
			self.add_command(result)
			return result

		return decorator


def command(
	name: str | None = None,
	description: str | None = None,
	with_app_command: bool = True,
	permissions: list[Permission] | None = None,
	nsfw: bool = False,
	guild_only: bool = False,
	hidden: bool = False,
	l10n_key: str | None = None,
	parent: HybridGroup | HybridCommand | None = None,
	user: bool = True,
	guild: bool = True,
	aliases: list[str] | None = None,
	usage: str | None = None,
	**kwargs: Any,
) -> Callable[[CommandCallback], HybridCommand]:
	def decorator(func: CommandCallback) -> HybridCommand:
		if isinstance(func, commands.Command):
			raise TypeError("Callback is already a command")

		base = l10n_key or name or func.__name__  # type: ignore

		text_description = description or command_key(base, "desc")

		cmd = HybridCommand(
			func,
			name=name or base,
			description=text_description,
			usage=usage,
			with_app_command=with_app_command,
			permissions=permissions or [],
			nsfw=nsfw,
			guild_only=guild_only,
			hidden=hidden,
			parent=parent,
			l10n_key=base,
			user=user,
			guild=guild,
			aliases=aliases or [],
			**kwargs,
		)

		return cmd

	return decorator


def group(
	name: str | None = None,
	description: str | None = None,
	with_app_command: bool = True,
	permissions: list[Permission] | None = None,
	nsfw: bool = False,
	guild_only: bool = False,
	hidden: bool = False,
	fallback: bool | str | None = True,
	l10n_key: str | None = None,
	user: bool = True,
	guild: bool = True,
	usage: str | None = None,
	**kwargs: Any,
) -> Callable[[Callable[..., Any]], HybridGroup]:
	def decorator(func: Callable[..., Any]) -> HybridGroup:
		if isinstance(func, commands.Command):
			raise TypeError("Callback is already a command")

		base = l10n_key or name or func.__name__  # type: ignore

		text_description = description or command_key(base, "desc")

		result = HybridGroup(
			func,
			name=name or base,
			description=text_description,
			with_app_command=with_app_command,
			permissions=permissions or [],
			nsfw=nsfw,
			guild_only=guild_only,
			hidden=hidden,
			fallback=fallback,
			l10n_key=base,
			user=user,
			guild=guild,
			usage=usage,
			**kwargs,
		)

		return result

	return decorator
