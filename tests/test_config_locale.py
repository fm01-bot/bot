from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from cogs.config import Config
from helpers.cli_parser import CLIParseError, CLIParser
from helpers.custom_response import CustomResponse


@pytest.fixture
def mock_ctx():
	ctx = MagicMock()
	ctx.guild = MagicMock()
	ctx.guild.id = 12345
	ctx.guild.preferred_locale = discord.Locale.american_english
	ctx.bot = MagicMock()
	ctx.bot.db = AsyncMock()
	ctx.bot.event_bus = MagicMock()
	ctx.bot.event_bus.publish = AsyncMock()
	ctx.bot.locale_cache = {}
	ctx.send = AsyncMock()
	return ctx


@pytest.mark.asyncio
async def test_config_locale_view_default_no_override(mock_ctx):
	config_cog = Config(mock_ctx.bot)
	mock_ctx.bot.db.fetchrow.return_value = None

	tokens = CLIParser.split_args("locale")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	mock_ctx.send.assert_called_once()
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "Locale: en-US" in call_content


@pytest.mark.asyncio
async def test_config_locale_view_with_cached_override(mock_ctx):
	config_cog = Config(mock_ctx.bot)
	mock_ctx.bot.locale_cache[12345] = "hu"

	tokens = CLIParser.split_args("locale")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	mock_ctx.send.assert_called_once()
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "Locale: hu (override)" in call_content
	assert "Server: en-US" in call_content


@pytest.mark.asyncio
async def test_config_locale_view_fallback_to_db(mock_ctx):
	config_cog = Config(mock_ctx.bot)
	mock_ctx.bot.locale_cache = {}
	mock_ctx.bot.db.fetchrow.return_value = {"locale": "hu"}

	tokens = CLIParser.split_args("locale")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	assert mock_ctx.bot.locale_cache.get(12345) == "hu"
	mock_ctx.send.assert_called_once()
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "Locale: hu (override)" in call_content


@pytest.mark.asyncio
async def test_config_locale_set_option(mock_ctx):
	config_cog = Config(mock_ctx.bot)

	tokens = CLIParser.split_args("locale --locale hu")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	# Verify DB execute called with upsert
	mock_ctx.bot.db.execute.assert_called_once()
	sql_args = mock_ctx.bot.db.execute.call_args.args
	assert "INSERT INTO guild_locale_overrides" in sql_args[0]
	assert sql_args[1] == 12345
	assert sql_args[2] == "hu"

	# Verify cache updated
	assert mock_ctx.bot.locale_cache[12345] == "hu"

	# Verify event published
	mock_ctx.bot.event_bus.publish.assert_called_once_with(
		"fm01:events", {"type": "INVALIDATE_LOCALE", "guild_id": 12345, "locale": "hu"}
	)

	# Verify response message
	mock_ctx.send.assert_called_once()
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "[+] Locale set to hu" in call_content


@pytest.mark.asyncio
async def test_config_locale_set_positional(mock_ctx):
	config_cog = Config(mock_ctx.bot)

	tokens = CLIParser.split_args("locale hu")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	assert mock_ctx.bot.locale_cache[12345] == "hu"
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "[+] Locale set to hu" in call_content


@pytest.mark.asyncio
async def test_config_locale_clear_default(mock_ctx):
	config_cog = Config(mock_ctx.bot)
	mock_ctx.bot.locale_cache[12345] = "hu"

	tokens = CLIParser.split_args("locale --default")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	# Verify DB delete
	mock_ctx.bot.db.execute.assert_called_once()
	sql_args = mock_ctx.bot.db.execute.call_args.args
	assert "DELETE FROM guild_locale_overrides WHERE guild_id = $1" in sql_args[0]
	assert sql_args[1] == 12345

	# Verify cache removed
	assert 12345 not in mock_ctx.bot.locale_cache

	# Verify event published
	mock_ctx.bot.event_bus.publish.assert_called_once_with(
		"fm01:events", {"type": "INVALIDATE_LOCALE", "guild_id": 12345, "locale": None}
	)

	# Verify response message
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "[+] Locale override cleared. Using server locale (en-US)" in call_content


@pytest.mark.asyncio
async def test_config_locale_invalid_code(mock_ctx):
	config_cog = Config(mock_ctx.bot)

	tokens = CLIParser.split_args("locale --locale en-US")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None

	with pytest.raises(CLIParseError, match="Locales use two letter country codes"):
		await node.callback(mock_ctx, **opts)


@pytest.mark.asyncio
async def test_config_locale_dm_error(mock_ctx):
	mock_ctx.guild = None
	config_cog = Config(mock_ctx.bot)

	tokens = CLIParser.split_args("locale")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None

	with pytest.raises(CLIParseError, match="This command can only be used in a server"):
		await node.callback(mock_ctx, **opts)


@pytest.mark.asyncio
async def test_custom_response_respects_locale_cache():
	bot = MagicMock()
	bot.debug = False
	bot.config.emojis = {"check": "✅", "x": "❌"}
	bot.locale_cache = {12345: "hu"}

	cr = CustomResponse(bot)
	cr.update_localizations(
		{
			"en": {"test": {"greeting": "Hello"}},
			"hu": {"test": {"greeting": "Szia"}},
		}
	)

	guild = MagicMock(spec=discord.Guild)
	guild.id = 12345
	guild.preferred_locale = "en"

	ctx = MagicMock()
	ctx.guild = guild
	ctx.author = MagicMock(spec=discord.Member)
	ctx.author.guild = guild
	ctx.author.id = 1
	ctx.author.name = "testuser"
	ctx.author.roles = []
	ctx.author.display_avatar.url = ""

	res = await cr.get_message("test.greeting", ctx)
	assert str(res) == "Szia"


@pytest.mark.asyncio
async def test_bot_cluster_event_invalidate_locale():
	from core.bot import Bot
	from core.config import Config

	cfg = Config(
		debug=False,
		owner_ids=[123],
		modules=["*"],
		emojis={},
		log_channel_id=999,
		allowed_contexts={"guild": True, "dm_channel": True, "private_channel": True},
		allowed_installs={"guild": True, "user": True},
		allowed_mentions={"everyone": False, "roles": False, "users": False},
	)
	bot = Bot(config=cfg)
	bot.locale_cache[12345] = "en"

	# Receive event to update locale
	await bot._on_cluster_event({"type": "INVALIDATE_LOCALE", "guild_id": 12345, "locale": "hu"})
	assert bot.locale_cache[12345] == "hu"

	# Receive event to clear locale (None)
	await bot._on_cluster_event({"type": "INVALIDATE_LOCALE", "guild_id": 12345, "locale": None})
	assert 12345 not in bot.locale_cache


@pytest.mark.asyncio
async def test_bot_cache_locales():
	from core.bot import Bot
	from core.config import Config

	cfg = Config(
		debug=False,
		owner_ids=[123],
		modules=["*"],
		emojis={},
		log_channel_id=999,
		allowed_contexts={"guild": True, "dm_channel": True, "private_channel": True},
		allowed_installs={"guild": True, "user": True},
		allowed_mentions={"everyone": False, "roles": False, "users": False},
	)
	bot = Bot(config=cfg)
	bot.db = AsyncMock()
	bot.db.fetch.return_value = [
		{"guild_id": 12345, "locale": "hu"},
		{"guild_id": 67890, "locale": "en"},
	]

	await bot.cache_locales()
	assert bot.locale_cache[12345] == "hu"
	assert bot.locale_cache[67890] == "en"
