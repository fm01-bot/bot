"""Locale resolution: which language a response is rendered in.

Precedence, highest first:

1. The guild's locale override (``guild_locale_overrides``, cached on ``Bot.locale_cache``).
2. The user's Discord client locale, when the source is an interaction (slash commands, components, modals).
3. The guild's preferred locale.
4. ``"en"``.

Locales are normalised to the two-letter codes the ``*.l10n.json`` files are named after (``"en-US"`` -> ``"en"``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import discord

__all__ = ("DEFAULT_LOCALE", "normalize_locale", "resolve_locale")

DEFAULT_LOCALE = "en"


def normalize_locale(locale: str | discord.Locale | None) -> str | None:
	"""Reduce a locale to its two-letter language code, or ``None`` if it is empty.

	Args:
		locale: A locale such as ``"en-US"``, ``"hu"`` or a ``discord.Locale``.

	Returns:
		str | None: The lower-case language code (``"en"``, ``"hu"``), or ``None``.
	"""
	if not locale:
		return None
	code = str(locale).strip().lower().replace("_", "-").split("-")[0]
	return code or None


def resolve_locale(source: Any, overrides: Mapping[int, str] | None = None) -> str:
	"""Decide which locale applies to a response.

	Args:
		source: What the response answers: a ``commands.Context``, ``discord.Interaction``, ``discord.Message``,
			``discord.Guild``, or an explicit locale (``str`` / ``discord.Locale``). ``None`` means the default.
		overrides: Guild ID -> locale override, normally ``Bot.locale_cache``.

	Returns:
		str: A two-letter locale code.
	"""
	if source is None:
		return DEFAULT_LOCALE
	if isinstance(source, (str, discord.Locale)):
		return normalize_locale(source) or DEFAULT_LOCALE

	guild = source if isinstance(source, discord.Guild) else getattr(source, "guild", None)
	guild_id = getattr(guild, "id", None)
	override = overrides.get(guild_id) if isinstance(overrides, Mapping) and guild_id is not None else None
	if isinstance(override, str) and (override := normalize_locale(override)):
		return override

	interaction = source if isinstance(source, discord.Interaction) else getattr(source, "interaction", None)
	if isinstance(interaction, discord.Interaction) and (user_locale := normalize_locale(interaction.locale)):
		return user_locale

	return normalize_locale(getattr(guild, "preferred_locale", None)) or DEFAULT_LOCALE
