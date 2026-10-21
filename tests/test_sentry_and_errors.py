from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from core.bot import Bot
from core.config import Config
from core.context import Context
from discord.ext import commands


@pytest.fixture
def mock_config():
	return Config(
		debug=False,
		owner_ids=[123456],
		modules=["admin"],
		log_channel_id=987654321,
		allowed_contexts={"guild": True, "dm_channel": True, "private_channel": True},
		allowed_installs={"guild": True, "user": True},
		allowed_mentions={"everyone": False, "roles": False, "users": False},
		emojis={"check": "✅", "x": "❌", "loading": "⏳"},
	)


def test_context_repr_and_str():
	ctx = MagicMock(spec=Context)
	ctx.author = MagicMock()
	ctx.author.__str__.return_value = "TestUser#0001"
	ctx.author.id = 111
	ctx.guild = MagicMock()
	ctx.guild.__str__.return_value = "TestGuild"
	ctx.guild.id = 222
	ctx.channel = MagicMock()
	ctx.channel.__str__.return_value = "TestChannel"
	ctx.channel.id = 333
	ctx.command = MagicMock()
	ctx.command.qualified_name = "test_command"

	# Test Context.__repr__ directly
	repr_str = Context.__repr__(ctx)
	assert "TestUser#0001" in repr_str
	assert "111" in repr_str
	assert "TestGuild" in repr_str
	assert "222" in repr_str
	assert "TestChannel" in repr_str
	assert "333" in repr_str
	assert "test_command" in repr_str

	# Test DM context (guild is None)
	ctx.guild = None
	repr_dm = Context.__repr__(ctx)
	assert "guild=None" in repr_dm


@pytest.mark.asyncio
async def test_handle_error_debug_mode(mock_config):
	mock_config.debug = True
	bot = Bot(config=mock_config)
	bot.debug = True
	bot._sentry_enabled = False

	ctx = MagicMock(spec=Context)
	ctx.command = None
	ctx.reply = AsyncMock()
	ctx.channel = MagicMock(spec=discord.TextChannel)

	raw_error = RuntimeError("Debug error occurred")
	test_error = commands.CommandInvokeError(raw_error)

	with patch(
		"core.bot.traceback.format_exception", return_value=["Traceback line 1\n", "RuntimeError: Debug error\n"]
	):
		await bot.handle_error(ctx, test_error)

	# Verify reply sent directly to channel with traceback and mention_author=False
	ctx.reply.assert_called_once()
	call_kwargs = ctx.reply.call_args.kwargs
	assert "```Traceback line 1\nRuntimeError: Debug error\n```" == ctx.reply.call_args.kwargs["content"]
	assert call_kwargs["mention_author"] is False


@pytest.mark.asyncio
async def test_handle_error_sentry_enabled(mock_config):
	mock_config.debug = False
	bot = Bot(config=mock_config)
	bot.debug = False
	bot._sentry_enabled = True

	ctx = MagicMock(spec=Context)
	ctx.reply = AsyncMock()
	ctx.author = MagicMock()
	ctx.author.id = 12345
	ctx.author.__str__.return_value = "AuthorUser"
	ctx.command = MagicMock()
	ctx.command.qualified_name = "reload"
	ctx.guild = MagicMock()
	ctx.guild.id = 67890
	ctx.guild.name = "My Guild"
	ctx.channel = MagicMock()
	ctx.channel.id = 54321
	ctx.channel.name = "general"
	ctx.message = MagicMock()
	ctx.message.id = 999999
	ctx.interaction = None

	raw_error = ZeroDivisionError("division by zero")
	test_error = commands.CommandInvokeError(raw_error)

	fake_scope = MagicMock()
	mock_new_scope = MagicMock()
	mock_new_scope.return_value.__enter__.return_value = fake_scope
	mock_new_scope.return_value.__exit__.return_value = None

	with (
		patch("sentry_sdk.new_scope", mock_new_scope),
		patch("sentry_sdk.capture_exception", return_value="fake_sentry_event_id_123") as mock_capture,
		patch.object(bot, "fetch_channel", AsyncMock()) as mock_fetch_channel,
	):
		await bot.handle_error(ctx, test_error)

		# Sentry capture_exception should be called with root_exc (raw_error)
		mock_capture.assert_called_once_with(raw_error, scope=fake_scope)

		# Scope tags and context should be set without message content (GDPR compliant)
		fake_scope.set_user.assert_called_once_with({"id": "12345", "username": "AuthorUser"})
		fake_scope.set_tag.assert_any_call("command", "reload")
		fake_scope.set_tag.assert_any_call("guild_id", "67890")
		fake_scope.set_tag.assert_any_call("channel_id", "54321")
		fake_scope.set_extra.assert_any_call("guild_name", "My Guild")
		fake_scope.set_extra.assert_any_call("channel_name", "general")
		fake_scope.set_extra.assert_any_call("message_id", 999999)

		# Webhook channel should NOT be fetched
		mock_fetch_channel.assert_not_called()

		# User should receive reply with Sentry event ID
		ctx.reply.assert_called_once_with(
			content="An error has occured and has been reported to the developers. Report ID: `fake_sentry_event_id_123`",
			mention_author=False,
		)


@pytest.mark.asyncio
async def test_handle_error_sentry_disabled_webhook_fallback(mock_config):
	mock_config.debug = False
	bot = Bot(config=mock_config)
	bot.debug = False
	bot._sentry_enabled = False

	ctx = MagicMock(spec=Context)
	ctx.reply = AsyncMock()
	ctx.author = MagicMock()
	ctx.author.id = 12345
	ctx.author.__str__.return_value = "AuthorUser"
	ctx.command = MagicMock()
	ctx.command.__str__.return_value = "reload"
	ctx.guild = MagicMock()
	ctx.guild.id = 67890
	ctx.guild.name = "My Guild"
	ctx.channel = MagicMock()
	ctx.message = MagicMock()
	ctx.message.id = 888888
	ctx.interaction = None

	log_channel = MagicMock(spec=discord.TextChannel)
	webhook = MagicMock()
	webhook.send = AsyncMock()
	bot._error_webhook = webhook

	raw_error = ValueError("Something went wrong")
	test_error = commands.CommandInvokeError(raw_error)

	with patch.object(bot, "fetch_channel", AsyncMock(return_value=log_channel)):
		await bot.handle_error(ctx, test_error)

	# Webhook send should be called with message ID
	webhook.send.assert_called_once()
	assert "**ID:** 888888" in webhook.send.call_args.kwargs["content"]

	# Reply to user should use message ID
	ctx.reply.assert_called_once_with(
		content="An error has occured and has been reported to the developers. Report ID: `888888`",
		mention_author=False,
	)


@pytest.mark.asyncio
async def test_handle_error_debug_mode_long_stack(mock_config):
	bot = Bot(config=mock_config)
	bot.debug = True

	ctx = MagicMock(spec=Context)
	ctx.command = None
	ctx.reply = AsyncMock()

	# Create long stack trace > 1700 chars
	long_error_text = "E" * 2000
	test_error = commands.CommandInvokeError(RuntimeError("Long error"))
	with patch("core.bot.traceback.format_exception", return_value=[long_error_text]):
		await bot.handle_error(ctx, test_error)

	ctx.reply.assert_called_once()
	assert "saved as a file" in ctx.reply.call_args.kwargs["content"]
	assert isinstance(ctx.reply.call_args.kwargs["file"], discord.File)


@pytest.mark.asyncio
async def test_handle_error_sentry_dm_interaction_fallback(mock_config):
	bot = Bot(config=mock_config)
	bot.debug = False
	bot._sentry_enabled = True

	ctx = MagicMock(spec=Context)
	ctx.command = None
	ctx.author = None
	ctx.guild = None
	ctx.channel = None
	ctx.message = None
	ctx.interaction = MagicMock(id=55555)
	ctx.reply = AsyncMock()

	fake_scope = MagicMock()
	mock_new_scope = MagicMock()
	mock_new_scope.return_value.__enter__.return_value = fake_scope

	test_error = commands.CommandInvokeError(RuntimeError("DM Interaction error"))
	with (
		patch("sentry_sdk.new_scope", mock_new_scope),
		patch("sentry_sdk.capture_exception", return_value=None),  # Sentry returns None
	):
		await bot.handle_error(ctx, test_error)

		fake_scope.set_tag.assert_any_call("guild_id", "DM")
		fake_scope.set_extra.assert_any_call("interaction_id", 55555)
		# Fallback should use interaction.id
		ctx.reply.assert_called_once_with(
			content="An error has occured and has been reported to the developers. Report ID: `55555`",
			mention_author=False,
		)
