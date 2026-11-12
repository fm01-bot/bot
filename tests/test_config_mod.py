from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cogs.config import Config
from core.settings import INVALIDATE_SETTING, GuildSettings
from helpers.cli_parser import CLIParseError, CLIParser


@pytest.fixture
def mock_ctx():
	ctx = MagicMock()
	ctx.guild = MagicMock()
	ctx.guild.id = 12345
	ctx.bot = MagicMock()
	ctx.bot.db = AsyncMock()
	ctx.bot.event_bus = MagicMock()
	ctx.bot.event_bus.publish = AsyncMock()
	ctx.bot.settings = GuildSettings(lambda: ctx.bot.db, ctx.bot.event_bus)
	ctx.send = AsyncMock()
	return ctx


@pytest.mark.asyncio
async def test_config_mod_view_default(mock_ctx):
	config_cog = Config(mock_ctx.bot)
	mock_ctx.bot.db.fetchrow.return_value = None

	tokens = CLIParser.split_args("mod")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	mock_ctx.send.assert_called_once()
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "Moderation case retention: keep" in call_content


@pytest.mark.asyncio
async def test_config_mod_set_delete(mock_ctx):
	config_cog = Config(mock_ctx.bot)

	tokens = CLIParser.split_args("mod --retention delete")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(mock_ctx, **opts)

	# Should insert/upsert into mod_config
	execute_args = mock_ctx.bot.db.execute.call_args.args
	assert "INSERT INTO mod_config" in execute_args[0]
	assert execute_args[1] == 12345
	assert execute_args[2] == "delete"

	# Should update the cached setting and tell other instances
	assert mock_ctx.bot.settings["mod.retention"].cache[12345] == "delete"
	event = mock_ctx.bot.event_bus.publish.call_args.args[1]
	assert (event["type"], event["key"], event["guild_id"]) == (INVALIDATE_SETTING, "mod.retention", 12345)
	call_content = mock_ctx.send.call_args.kwargs.get("content", "")
	assert "Moderation case retention set to delete" in call_content


@pytest.mark.asyncio
async def test_config_mod_invalid_retention(mock_ctx):
	config_cog = Config(mock_ctx.bot)

	tokens = CLIParser.split_args("mod --retention purge")
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None

	with pytest.raises(CLIParseError, match="must be either 'keep' or 'delete'"):
		await node.callback(mock_ctx, **opts)
