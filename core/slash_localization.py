import json
from logging import getLogger
from pathlib import Path
from time import perf_counter
from typing import Optional

import discord
from discord import app_commands
from discord.ext import localization

logger = getLogger(__name__)

slash_command_localization: Optional[localization.Localization] = None


def update_slash_localizations():
	slash_localizations = {}

	# load the slash localization files and combine them into one dictionary
	for file_path in Path("./slash_localization").glob("*.l10n.json"):
		lang = file_path.stem.removesuffix(".l10n")
		try:
			data = json.loads(Path(file_path).read_text(encoding="utf-8"))
			if not isinstance(data, dict):
				raise ValueError(f"Expected dict in {file_path}, got {type(data).__name__}")
			if lang not in slash_localizations:
				slash_localizations[lang] = {}
			slash_localizations[lang].update(data)
		except Exception as e:
			logger.warning(f"Failed to load {file_path}: {e}")
	global slash_command_localization
	slash_command_localization = localization.Localization(slash_localizations, default_locale="en", separator="-")


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

			localized = slash_command_localization.translate(key, str(locale))
			if not isinstance(localized, str):
				return None

			if localized == key:
				return None

			return localized
		return None
