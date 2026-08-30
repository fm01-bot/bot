from __future__ import annotations

import inspect
from typing import (
	TYPE_CHECKING,
	Any,
	Callable,
	ClassVar,
	Coroutine,
	Dict,
	Literal,
	Optional,
	Self,
	Tuple,
	Type,
	TypeVar,
	Union,
	Unpack,
)

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Cog, FlagConverter
from discord.ext.commands.hybrid import _CallableDefault, maybe_coroutine, replace_parameters
from discord.utils import MISSING

if TYPE_CHECKING:
	from discord.ext.commands.hybrid import _HybridCommandDecoratorKwargs, _HybridGroupDecoratorKwargs

import core.slash_localization as slash_localization

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


def _localize_app_command_attributes(
	command_or_group: None | app_commands.Command | app_commands.Group | commands.hybrid.HybridAppCommand, base: str
) -> None | app_commands.Command | app_commands.Group | commands.hybrid.HybridAppCommand:
	if not command_or_group:
		return None

	name_key = f"{base}-name"
	if isinstance(command_or_group, commands.hybrid.HybridAppCommand):
		if getattr(command_or_group.wrapped, "parent", None) is not None:
			name_key = command_or_group.name

	command_or_group._locale_name = _l10n_str(command_or_group.name, name_key)
	command_or_group._locale_description = _l10n_desc(command_or_group.description, f"{base}-desc")

	if not isinstance(command_or_group, app_commands.Group):
		for param in command_or_group._params.values():
			param_name = param.name
			param._rename = _l10n_str(param.name, f"{base}-args-{param_name}-name")
			param.description = _l10n_desc(param.description, f"{base}-args-{param_name}-desc")

	return command_or_group


def _resolve_fallback_name(base: str) -> str | None:
	if not slash_localization.slash_command_localization:
		return None

	localizations = slash_localization.slash_command_localization.file
	default_locale = slash_localization.slash_command_localization.default_locale or "en"
	locale_data = localizations.get(default_locale)
	if not isinstance(locale_data, dict):
		return None

	value: object = locale_data
	for key in f"{base}-fallback".split("-"):
		if not isinstance(value, dict):
			return None
		value = value.get(key)
		if value is None:
			return None

	return value


class HybridAppCommand(commands.hybrid.HybridAppCommand):
	__commands_is_hybrid_app_command__: ClassVar[bool] = True

	@property
	def usage(self) -> Optional[str]:
		return getattr(self.wrapped, "usage", None)

	def __init__(
		self, wrapped: Union[HybridCommand, HybridGroup], name: Optional[Union[str, app_commands.locale_str]] = None
	) -> None:
		super().__init__(wrapped, name)

		base = getattr(wrapped, "l10n_key", None)
		if base:
			if isinstance(wrapped, HybridGroup):
				self._locale_name = _l10n_str(self.name, f"{base}-fallback")
				self._locale_description = _l10n_desc(self.description, f"{base}-desc")

				for param in self._params.values():
					param_name = param.name
					param._rename = _l10n_str(param.name, f"{base}-args-{param_name}-name")
					param.description = _l10n_desc(param.description, f"{base}-args-{param_name}-desc")
			else:
				_localize_app_command_attributes(self, base)

	async def _transform_arguments(
		self, interaction: discord.Interaction, namespace: app_commands.Namespace
	) -> Dict[str, Any]:
		values = namespace.__dict__
		transformed_values = {}

		for param in self._params.values():
			try:
				# Use param.name instead of param.display_name because
				# Namespace uses internal names, but we might have renamed
				# the parameter for localization via _rename.
				value = values[param.name]
			except KeyError:
				if param.display_name in values:
					transformed_values[param.name] = await param.transform(interaction, values[param.display_name])
				elif not param.required:
					if isinstance(param.default, _CallableDefault):
						transformed_values[param.name] = await maybe_coroutine(param.default.func, interaction._baton)
					else:
						transformed_values[param.name] = param.default
				else:
					raise app_commands.CommandSignatureMismatch(self) from None
			else:
				transformed_values[param.name] = await param.transform(interaction, value)

		if self.flag_converter is not None:
			param_name, flag_cls = self.flag_converter
			flag = flag_cls.__new__(flag_cls)
			for f in flag_cls.__commands_flags__.values():
				try:
					value = transformed_values.pop(f.attribute)
				except KeyError:
					raise app_commands.CommandSignatureMismatch(self) from None
				else:
					setattr(flag, f.attribute, value)

			transformed_values[param_name] = flag

		return transformed_values


class HybridCommand(commands.HybridCommand):
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
		**kwargs: Any,
	):
		super().__init__(func, name=name, description=description, **kwargs)
		self.permissions = permissions
		self.l10n_key = l10n_key
		self.user = user
		self.guild = guild

		if permissions:
			perms_dict = {perm: True for perm in permissions}
			self.checks.append(commands.has_permissions(**perms_dict).predicate)

		if not user:
			self.checks.append(commands.guild_only().predicate)
		if not guild:
			self.checks.append(commands.dm_only().predicate)

		if self.with_app_command:
			self.app_command = HybridAppCommand(self)
			self.app_command.allowed_installs = app_commands.AppInstallationType(guild=guild, user=user)
			self.app_command.allowed_contexts = app_commands.AppCommandContext(
				guild=guild, dm_channel=user, private_channel=user
			)


class HybridGroup(commands.HybridGroup):
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
		**kwargs: Any,
	):
		base = l10n_key or name or func.__name__  # type: ignore
		if isinstance(fallback, str):
			resolved_fallback = fallback
		elif fallback:
			resolved_fallback = _resolve_fallback_name(base)  # type: ignore
		else:
			resolved_fallback = None

		super().__init__(func, name=name, description=description, fallback=resolved_fallback, **kwargs)
		self.permissions = permissions
		self.l10n_key = l10n_key
		self.user = user
		self.guild = guild

		if permissions:
			perms_dict = {perm: True for perm in permissions}
			self.checks.append(commands.has_permissions(**perms_dict).predicate)

		if not user:
			self.checks.append(commands.guild_only().predicate)
		if not guild:
			self.checks.append(commands.dm_only().predicate)

		if self.app_command:
			self.app_command.allowed_installs = app_commands.AppInstallationType(guild=guild, user=user)
			self.app_command.allowed_contexts = app_commands.AppCommandContext(
				guild=guild, dm_channel=user, private_channel=user
			)

		if self.fallback:
			self.app_command.remove_command(self.fallback)
			fallback_command = HybridAppCommand(self, name=getattr(self, "fallback_locale", None) or self.fallback)
			self.app_command.add_command(fallback_command)

	def add_command(self, command: HybridGroup[CogT, ..., Any] | HybridCommand[CogT, ..., Any], /) -> None:
		super().add_command(command)
		if isinstance(command, commands.hybrid.HybridCommand) and command.app_command:
			command.app_command._locale_name = _l10n_str(command.name, command.name)

	def command(
		self,
		name: str | app_commands.locale_str | None = None,
		*args: Any,
		l10n_key: str | None = None,
		with_app_command: bool = True,
		user: bool = True,
		guild: bool = True,
		**kwargs: Unpack[_HybridCommandDecoratorKwargs],
	) -> Callable[[CommandCallback], HybridCommand]:
		def decorator(func: CommandCallback):
			kwargs.setdefault("parent", self)
			result = command(
				name=name.message
				if isinstance(name, app_commands.locale_str)
				else name or getattr(func, "__name__", None),  # ugly but it works
				l10n_key=l10n_key,
				user=user,
				guild=guild,
				**kwargs,
				with_app_command=with_app_command,
			)(func)
			self.add_command(result)
			return result

		return decorator

	# def group(
	# 	self,
	# 	name: str | app_commands.locale_str = MISSING,
	# 	*args: Any,
	# 	with_app_command: bool = True,
	# 	user: bool = True,
	# 	guild: bool = True,
	# 	**kwargs: Unpack[_HybridGroupDecoratorKwargs],
	# ) -> Callable[[CommandCallback], HybridGroup]:
	# 	def decorator(func: CommandCallback):
	# 		kwargs.setdefault("parent", self)
	# 		result = group(
	# 			name=(
	# 				name.message
	# 				if isinstance(name, app_commands.locale_str)
	# 				else name or getattr(func, "__name__", None)
	# 			),
	# 			*args,
	# 			user=user,
	# 			guild=guild,
	# 			**kwargs,
	# 			with_app_command=with_app_command,
	# 		)(func)
	# 		self.add_command(result)
	# 		return result

	# 	return decorator


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
) -> Callable[[CommandCallback], HybridCommand]:
	def decorator(func: CommandCallback) -> HybridCommand:
		if isinstance(func, commands.Command):
			raise TypeError("Callback is already a command")

		base = l10n_key or name or func.__name__  # type: ignore

		text_description = description or f"{base}-desc"

		usage = f"{base}-usage"

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
) -> Callable[[Callable[..., Any]], HybridGroup]:
	def decorator(func: Callable[..., Any]) -> HybridGroup:
		if isinstance(func, commands.Command):
			raise TypeError("Callback is already a command")

		base = l10n_key or name or func.__name__  # type: ignore

		text_description = description or f"{base}-desc"

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
		)

		result.app_command = _localize_app_command_attributes(result.app_command, base)  # type: ignore

		return result

	return decorator
