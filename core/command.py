import logging
from dataclasses import dataclass
from typing import Any

from discord.ext import commands

from core import slash_localization

logger = logging.getLogger(__name__)

__all__ = ("Command",)


def _has_l10n_key(l10n: Any, key: str, locale: str) -> bool:
	if not l10n or not getattr(l10n, "file", None):
		return False
	loc_dict = l10n.file.get(locale) or l10n.file.get(getattr(l10n, "default_locale", "en"))
	if not isinstance(loc_dict, dict):
		return False
	separator = getattr(l10n, "separator", "-")
	parts = key.split(separator)
	curr = loc_dict
	for part in parts:
		if not isinstance(curr, dict) or part not in curr:
			return False
		curr = curr[part]
	return True


@dataclass
class Command:
	name: str
	description: str
	usage: str
	prefix: str
	aliases: str | None

	@classmethod
	def from_ctx(cls, ctx: commands.Context):
		l10n = slash_localization.slash_command_localization
		if ctx.command and l10n:
			has_params = bool(ctx.command.clean_params)
			usage_attr = getattr(ctx.command, "usage", None) if has_params else None
			desc_attr = getattr(ctx.command, "description", None)
			target_locale = str(ctx.guild.preferred_locale) if ctx.guild else "en"
			if ctx.guild and hasattr(ctx.bot, "locale_cache") and ctx.guild.id in ctx.bot.locale_cache:
				target_locale = ctx.bot.locale_cache[ctx.guild.id]
			usage = None
			if usage_attr and _has_l10n_key(l10n, usage_attr, target_locale):
				usage = l10n(usage_attr, target_locale) if ctx.guild else l10n(usage_attr, "en")
			description = (l10n(desc_attr, target_locale) if ctx.guild else l10n(desc_attr, "en")) if desc_attr else None
			usage_text = f"{ctx.clean_prefix}{usage}" if usage else f"{ctx.clean_prefix}{ctx.command.qualified_name}"
			return cls(
				name=ctx.command.qualified_name,
				description=description if isinstance(description, str) and description else "-",
				usage=usage_text,
				prefix=ctx.clean_prefix,
				aliases=", ".join(ctx.command.aliases) if len(ctx.command.aliases) > 0 else None,
			)
		return None

	@classmethod
	def from_command(cls, command: commands.Command, ctx: commands.Context):
		l10n = slash_localization.slash_command_localization
		if l10n:
			has_params = bool(command.clean_params)
			usage_attr = getattr(command, "usage", None) if has_params else None
			desc_attr = getattr(command, "description", None)
			target_locale = str(ctx.guild.preferred_locale) if ctx.guild else "en"
			if ctx.guild and hasattr(ctx.bot, "locale_cache") and ctx.guild.id in ctx.bot.locale_cache:
				target_locale = ctx.bot.locale_cache[ctx.guild.id]
			usage = None
			if usage_attr and _has_l10n_key(l10n, usage_attr, target_locale):
				usage = l10n(usage_attr, target_locale) if ctx.guild else l10n(usage_attr, "en")
			description = (l10n(desc_attr, target_locale) if ctx.guild else l10n(desc_attr, "en")) if desc_attr else None
			usage_text = (
				f"{ctx.clean_prefix}{usage}"
				if usage and usage != usage_attr
				else f"{ctx.clean_prefix}{command.qualified_name}"
			)
			return cls(
				name=command.qualified_name,
				description=description if isinstance(description, str) and description else "-",
				usage=usage_text,
				prefix=ctx.clean_prefix,
				aliases=", ".join(command.aliases) if len(command.aliases) > 0 else None,
			)
		return None
