import json
from logging import getLogger
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import localization

__all__ = ("SlashCommandLocalizer", "command_key", "lookup", "update_slash_localizations")

logger = getLogger(__name__)

slash_command_localization: localization.Localization | None = None
"""The loaded slash localizations. Read it as ``slash_localization.slash_command_localization`` (module attribute):
it is replaced by `update_slash_localizations`, so a ``from ... import`` of it would keep the stale ``None``."""

SEPARATOR = "-"


def command_key(base: str, *parts: str) -> str:
	"""Build a slash localization key for a command, e.g. ``command_key("caserem", "args", "case_id", "name")``.

	Every name, description and parameter of a command lives under its ``l10n_key`` (its ``base``): ``<base>-name``,
	``<base>-desc``, ``<base>-usage``, ``<base>-fallback`` and ``<base>-args-<param>-name|desc``.
	"""
	return SEPARATOR.join((base, *parts))


def lookup(key: str, locale: str = "en") -> str | None:
	"""Return the string stored at ``key`` for ``locale`` (falling back to ``en``), or ``None`` if there is none."""
	if slash_command_localization is None:
		return None
	files = slash_command_localization.file
	for loc in dict.fromkeys((locale, "en")):
		value: object = files.get(loc)
		for part in key.split(SEPARATOR):
			value = value.get(part) if isinstance(value, dict) else None
		if isinstance(value, str):
			return value
	return None


def update_slash_localizations():
	slash_localizations = {}

	# load the slash localization files and combine them into one dictionary
	for file_path in Path("./slash_localization").glob("*.l10n.json"):
		lang = file_path.stem.removesuffix(".l10n")
		try:
			data = json.loads(Path(file_path).read_text(encoding="utf-8"))
			if not isinstance(data, dict):
				raise TypeError(f"Expected dict in {file_path}, got {type(data).__name__}")
			if lang not in slash_localizations:
				slash_localizations[lang] = {}
			slash_localizations[lang].update(data)
		except json.JSONDecodeError as e:
			logger.warning(f"Failed to load {file_path}: {e}")
	global slash_command_localization
	slash_command_localization = localization.Localization(
		slash_localizations, default_locale="en", separator=SEPARATOR
	)


class SlashCommandLocalizer(app_commands.Translator):
	"""Localizes slash commands and their arguments using discord-localization.

	This uses the localization set by the user, not the guild's locale.
	"""

	async def translate(
		self, string: app_commands.locale_str, locale: discord.Locale | str, context: app_commands.TranslationContext
	) -> str | None:
		if slash_command_localization:
			if str(locale).startswith("en"):
				# we hate subcultures and don't differentiate
				# between american and british english
				locale = "en"
			key = string.extras.get("key") or string.extras.get("l10n_key") or string.message
			if key == "…" or key == "...":
				return None

			return lookup(key, str(locale))
		return None
