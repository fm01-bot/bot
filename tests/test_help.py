from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from cogs.help import HelpCommand, HelpLayoutView, HelpSelect, clean_module_name
from discord.ext import commands
from helpers.custom_response import CustomResponse


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.debug = False
	bot.config.emojis = {"check": "✅", "x": "❌"}
	bot.can_run = AsyncMock(return_value=True)
	cr = CustomResponse(bot)
	cr.load_localizations("./localization")
	bot.custom_response = cr
	return bot


class DummyBasicCog(commands.Cog, name="Basic"):
	@commands.command(name="ping")
	async def ping(self, ctx: commands.Context) -> None:
		"""Ping command."""


class DummyModCog(commands.Cog, name="Cases"):
	@commands.command(name="ban")
	async def ban(self, ctx: commands.Context) -> None:
		"""Ban command."""


def test_clean_module_name():
	assert clean_module_name("⚙️ Basic") == "Basic"
	assert clean_module_name("<:shield:123456789> Moderation") == "Moderation"
	assert clean_module_name("<a:party:987654321> Setup") == "Setup"
	assert clean_module_name("Basic") == "Basic"
	assert clean_module_name("Információ") == "Információ"
	assert clean_module_name("Beállítás") == "Beállítás"
	assert clean_module_name("💤 AFK") == "AFK"


@pytest.mark.asyncio
async def test_resolve_cog_preferred_locale_restriction(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	basic_cog = DummyBasicCog()
	mod_cog = DummyModCog()
	mock_bot.cogs = {"Basic": basic_cog, "Cases": mod_cog}

	# English locale context
	en_ctx = MagicMock(spec=commands.Context)
	en_ctx.bot = mock_bot
	en_ctx.interaction = None
	en_guild = MagicMock()
	en_guild.preferred_locale = discord.Locale.american_english
	en_ctx.guild = en_guild

	help_cmd.context = en_ctx

	# English locale should NOT be able to resolve Hungarian 'alap'
	assert help_cmd.resolve_cog("alap") is None

	# English locale should be able to resolve 'basic' and 'Basic'
	assert help_cmd.resolve_cog("basic") is basic_cog
	assert help_cmd.resolve_cog("Basic") is basic_cog

	# Hungarian locale context
	hu_ctx = MagicMock(spec=commands.Context)
	hu_ctx.bot = mock_bot
	hu_ctx.interaction = None
	hu_guild = MagicMock()
	hu_guild.preferred_locale = discord.Locale.hungarian
	hu_ctx.guild = hu_guild

	help_cmd.context = hu_ctx

	# Hungarian locale CAN resolve 'alap' to Basic cog
	assert help_cmd.resolve_cog("alap") is basic_cog
	# Hungarian locale CAN also resolve 'basic'
	assert help_cmd.resolve_cog("basic") is basic_cog


@pytest.mark.asyncio
async def test_resolve_cog_excluding_emojis(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	basic_cog = DummyBasicCog()
	mock_bot.cogs = {"Basic": basic_cog}

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.interaction = None
	ctx.guild.preferred_locale = "en"
	help_cmd.context = ctx

	# Module is named '⚙️ Basic' in en.l10n.json
	# User searches without emoji:
	assert help_cmd.resolve_cog("basic") is basic_cog
	assert help_cmd.resolve_cog("Basic") is basic_cog

	# User searches with emoji:
	assert help_cmd.resolve_cog("⚙️ basic") is basic_cog
	assert help_cmd.resolve_cog("⚙️ Basic") is basic_cog


@pytest.mark.asyncio
async def test_build_bot_help_components_v2(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	basic_cog = DummyBasicCog()
	mock_bot.cogs = {"Basic": basic_cog}

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.command = None
	ctx.clean_prefix = "?!"
	ctx.interaction = None
	ctx.guild.preferred_locale = "en"
	ctx.author.id = 12345
	help_cmd.context = ctx

	payload = await help_cmd.build_bot_help_payload()
	assert "view" in payload
	view = payload["view"]
	assert isinstance(view, HelpLayoutView)
	assert view.has_components_v2() is True

	# Verify select menu is present
	selects = [item for item in view.walk_children() if isinstance(item, HelpSelect)]
	assert len(selects) == 1
	select = selects[0]
	assert select.options[0].value == "overview"
	assert select.options[0].default is True
	# Cog option
	cog_opts = [opt for opt in select.options if opt.value == "Basic"]
	assert len(cog_opts) == 1
	assert cog_opts[0].label == "Basic"
	assert cog_opts[0].emoji is not None
	assert cog_opts[0].description == "1 commands"

	# Verify module list is removed from overview container
	text_items = [
		c
		for container in view.children
		if isinstance(container, discord.ui.Container)
		for c in container.children
		if isinstance(c, discord.ui.TextDisplay)
	]
	all_text = " ".join(t.content for t in text_items)
	assert "{modules}" not in all_text


@pytest.mark.asyncio
async def test_build_cog_help_components_v2(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	basic_cog = DummyBasicCog()
	mock_bot.cogs = {"Basic": basic_cog}

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.command = None
	ctx.clean_prefix = "?!"
	ctx.interaction = None
	ctx.guild.preferred_locale = "en"
	ctx.author.id = 12345
	help_cmd.context = ctx

	payload = await help_cmd.build_cog_help_payload(basic_cog)
	assert "view" in payload
	view = payload["view"]
	assert isinstance(view, HelpLayoutView)
	assert view.has_components_v2() is True

	selects = [item for item in view.walk_children() if isinstance(item, HelpSelect)]
	assert len(selects) == 1
	select = selects[0]
	cog_opts = [opt for opt in select.options if opt.value == "Basic"]
	assert len(cog_opts) == 1
	assert cog_opts[0].default is True


@pytest.mark.asyncio
async def test_help_select_callback_author_and_non_author(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	basic_cog = DummyBasicCog()
	mock_bot.cogs = {"Basic": basic_cog}

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.command = None
	ctx.clean_prefix = "?!"
	ctx.interaction = None
	ctx.guild.preferred_locale = "en"
	ctx.author.id = 12345
	help_cmd.context = ctx

	payload = await help_cmd.build_bot_help_payload()
	view: HelpLayoutView = payload["view"]
	select: HelpSelect = next(item for item in view.walk_children() if isinstance(item, HelpSelect))

	# Non-author interaction
	non_author_interaction = MagicMock(spec=discord.Interaction)
	non_author_interaction.user.id = 99999
	non_author_interaction.guild.preferred_locale = "en"
	non_author_interaction.response.send_message = AsyncMock()

	select._values = ["Basic"]
	await select.callback(non_author_interaction)
	non_author_interaction.response.send_message.assert_awaited_once()
	assert non_author_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

	# Author interaction
	author_interaction = MagicMock(spec=discord.Interaction)
	author_interaction.user.id = 12345
	author_interaction.guild.preferred_locale = "en"
	author_interaction.response.edit_message = AsyncMock()

	select._values = ["Basic"]
	await select.callback(author_interaction)
	author_interaction.response.edit_message.assert_awaited_once()
	edit_kwargs = author_interaction.response.edit_message.call_args.kwargs
	assert "view" in edit_kwargs
	assert isinstance(edit_kwargs["view"], HelpLayoutView)


class DummyCasesCog(commands.Cog, name="Cases"):
	@commands.group(name="case", invoke_without_command=True)
	async def case(self, ctx: commands.Context) -> None:
		"""Case root command."""

	@case.command(name="delete")
	async def case_delete(self, ctx: commands.Context) -> None:
		"""Delete a case."""

	@case.command(name="edit")
	async def case_edit(self, ctx: commands.Context) -> None:
		"""Edit a case."""


class DummyCustomNamedCog(commands.Cog):
	name = "CustomModule"

	@commands.command(name="custom")
	async def custom(self, ctx: commands.Context) -> None:
		"""Custom command."""


@pytest.mark.asyncio
async def test_get_localized_cog_name_fallback_to_cog_name(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.guild.preferred_locale = "en"
	help_cmd.context = ctx

	# Cog with localization key: Basic -> '⚙️ Basic'
	basic_cog = DummyBasicCog()
	assert await help_cmd.get_localized_cog_name(basic_cog) == "⚙️ Basic"

	# Cog without localization key: Cases -> 'Cases'
	cases_cog = DummyCasesCog()
	assert await help_cmd.get_localized_cog_name(cases_cog) == "Cases"

	# Cog with explicit name attribute: CustomModule -> 'CustomModule'
	custom_cog = DummyCustomNamedCog()
	assert await help_cmd.get_localized_cog_name(custom_cog) == "CustomModule"


@pytest.mark.asyncio
async def test_cog_single_command_group_help(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	cases_cog = DummyCasesCog()
	mock_bot.cogs = {"Cases": cases_cog}

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.command = None
	ctx.clean_prefix = "?!"
	ctx.interaction = None
	ctx.guild.preferred_locale = "en"
	ctx.author.id = 12345
	help_cmd.context = ctx

	# build_cog_help_payload should route to group help when single command is a Group
	payload = await help_cmd.build_cog_help_payload(cases_cog)
	assert "view" in payload
	view = payload["view"]
	assert isinstance(view, HelpLayoutView)

	# Verify subcommands are included in the view text
	text_items = [
		c
		for container in view.children
		if isinstance(container, discord.ui.Container)
		for c in container.children
		if isinstance(c, discord.ui.TextDisplay)
	]
	all_text = " ".join(t.content for t in text_items)
	assert "case" in all_text
	assert "case delete" in all_text
	assert "case edit" in all_text

	# Verify dropdown select has Cases active
	select = next(item for item in view.walk_children() if isinstance(item, HelpSelect))
	cases_opt = next(opt for opt in select.options if opt.value == "Cases")
	assert cases_opt.default is True

	# send_cog_help should route to send_group_help
	send_mock = AsyncMock()
	help_cmd.get_destination = MagicMock(return_value=MagicMock(send=send_mock))
	await help_cmd.send_cog_help(cases_cog)
	send_mock.assert_awaited_once()
	sent_kwargs = send_mock.call_args.kwargs
	assert "view" in sent_kwargs


@pytest.mark.asyncio
async def test_help_select_dropdown_single_command_group_cog(mock_bot):
	help_cmd = HelpCommand()
	help_cmd.custom_response = mock_bot.custom_response

	cases_cog = DummyCasesCog()
	basic_cog = DummyBasicCog()
	mock_bot.cogs = {"Basic": basic_cog, "Cases": cases_cog}

	ctx = MagicMock(spec=commands.Context)
	ctx.bot = mock_bot
	ctx.command = None
	ctx.clean_prefix = "?!"
	ctx.interaction = None
	ctx.guild.preferred_locale = "en"
	ctx.author.id = 12345
	help_cmd.context = ctx

	# Start on overview
	payload = await help_cmd.build_bot_help_payload()
	view: HelpLayoutView = payload["view"]
	select: HelpSelect = next(item for item in view.walk_children() if isinstance(item, HelpSelect))

	# User selects Cases from the dropdown
	author_interaction = MagicMock(spec=discord.Interaction)
	author_interaction.user.id = 12345
	author_interaction.guild.preferred_locale = "en"
	author_interaction.response.edit_message = AsyncMock()

	select._values = ["Cases"]
	await select.callback(author_interaction)

	author_interaction.response.edit_message.assert_awaited_once()
	edit_kwargs = author_interaction.response.edit_message.call_args.kwargs
	assert "view" in edit_kwargs
	new_view: HelpLayoutView = edit_kwargs["view"]

	# Verify the message contains group subcommands
	text_items = [
		c
		for container in new_view.children
		if isinstance(container, discord.ui.Container)
		for c in container.children
		if isinstance(c, discord.ui.TextDisplay)
	]
	all_text = " ".join(t.content for t in text_items)
	assert "case delete" in all_text
	assert "case edit" in all_text
