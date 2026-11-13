from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest
from core.locale import normalize_locale, resolve_locale

GUILD_ID = 1


def guild(preferred: str | None = "en-US") -> MagicMock:
	g = MagicMock(spec=discord.Guild)
	g.id = GUILD_ID
	g.preferred_locale = discord.Locale(preferred) if preferred else None
	return g


def interaction(user_locale: str, g: MagicMock | None) -> MagicMock:
	i = MagicMock(spec=discord.Interaction)
	i.locale = discord.Locale(user_locale)
	i.guild = g
	return i


def ctx(g: MagicMock | None, inter: MagicMock | None = None) -> MagicMock:
	c = MagicMock()
	c.guild = g
	c.interaction = inter
	return c


@pytest.mark.parametrize(
	("raw", "expected"),
	[
		("en-US", "en"),
		("en_GB", "en"),
		("HU", "hu"),
		(discord.Locale.brazil_portuguese, "pt"),
		("", None),
		(None, None),
	],
)
def test_normalize_locale(raw, expected):
	assert normalize_locale(raw) == expected


@pytest.mark.parametrize(
	("source", "overrides", "expected"),
	[
		# 1. Guild override beats everything.
		(ctx(guild("en-US"), interaction("en-US", guild())), {GUILD_ID: "hu"}, "hu"),
		(guild("en-US"), {GUILD_ID: "hu"}, "hu"),
		# 2. The user's client locale applies to interactions (slash commands, components) only.
		(ctx(guild("en-US"), interaction("hu", guild())), {}, "hu"),
		(interaction("hu", guild("en-US")), {}, "hu"),
		(ctx(guild("en-US")), {}, "en"),
		# 3. Then the guild's preferred locale.
		(ctx(guild("hu")), {}, "hu"),
		(guild("hu"), None, "hu"),
		# 4. Then English.
		(ctx(None), {}, "en"),
		(None, {GUILD_ID: "hu"}, "en"),
		# Explicit locales are normalised and used as-is.
		("hu-HU", {GUILD_ID: "en"}, "hu"),
		(discord.Locale.american_english, None, "en"),
	],
)
def test_resolve_locale_precedence(source, overrides, expected):
	assert resolve_locale(source, overrides) == expected


def test_override_for_another_guild_is_ignored():
	assert resolve_locale(ctx(guild("hu")), {GUILD_ID + 1: "en"}) == "hu"
