"""Setup and Admin commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cogs.admin import Admin
from cogs.setup import Setup
from discord.ext import commands


@pytest.fixture
def ctx() -> MagicMock:
	ctx = MagicMock()
	ctx.send = AsyncMock()
	ctx.reply = AsyncMock()
	ctx.guild.id = 9
	return ctx


async def test_setup_prefix_saves_prefix_and_mention(ctx):
	bot = MagicMock()
	bot.prefix.set = AsyncMock()
	cog = Setup(bot)

	await cog.prefix.callback(cog, ctx, "!", None)

	bot.prefix.set.assert_awaited_once_with(9, ("!", True))
	ctx.send.assert_awaited_once_with("setup.prefix.set", prefix="!")


async def test_setup_prefix_rejects_long_prefixes(ctx):
	bot = MagicMock()
	bot.prefix.set = AsyncMock()
	cog = Setup(bot)

	await cog.prefix.callback(cog, ctx, "x" * 11, False)

	bot.prefix.set.assert_not_awaited()
	ctx.send.assert_awaited_once_with("setup.prefix.errors.long", prefix="x" * 11, limit=10)


@pytest.mark.parametrize("command", ["reload", "load", "unload"])
async def test_admin_extension_commands_report_success_and_failure(ctx, command):
	bot = MagicMock()
	method = AsyncMock()
	setattr(bot, f"{command}_extension", method)
	cog = Admin(bot)
	callback = getattr(cog, command).callback

	await callback(cog, ctx, "basic")
	method.assert_awaited_once_with("cogs.basic")
	assert "`basic`" in ctx.reply.call_args.kwargs["content"]

	method.side_effect = commands.ExtensionNotFound("cogs.nope")
	await callback(cog, ctx, "nope")
	assert ctx.reply.call_args.kwargs["content"].startswith("Failed")


async def test_l10n_reload_refuses_paths_outside_the_localization_folders(ctx):
	cog = Admin(MagicMock())

	await cog.l10nreload.callback(cog, ctx, "./core")

	ctx.bot.custom_response.load_localizations.assert_not_called()
	assert "Access denied" in ctx.reply.call_args.kwargs["content"]


async def test_l10n_reload_loads_the_localization_folder(ctx):
	cog = Admin(MagicMock())

	await cog.l10nreload.callback(cog, ctx, "./localization")

	ctx.bot.custom_response.load_localizations.assert_called_once()
