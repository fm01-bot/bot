from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.afk import AFK
from cogs.basic import Basic
from cogs.config_subcommands.leave import setup_leave_subcommands
from cogs.status import Status
from helpers.cli_parser import CLINode, CLIParseError


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.latency = 0.042
	bot.commands = []
	bot.guilds = [MagicMock(), MagicMock()]
	bot.custom_response = AsyncMock()
	bot.change_presence = AsyncMock()
	bot.get_cog = MagicMock(return_value=None)
	bot.get_context = AsyncMock()
	return bot


class TestBasicCommands:
	@pytest.mark.asyncio
	async def test_ping_command(self, mock_bot):
		cog = Basic(mock_bot)
		ctx = MagicMock()
		ctx.send = AsyncMock()

		# Run the ping command callback
		await cog.ping.callback(cog, ctx)

		mock_bot.db.execute.assert_called_once_with("SELECT 1")
		ctx.send.assert_called_once()
		args, kwargs = ctx.send.call_args
		assert args[0] == "ping"
		assert kwargs["latency"] == pytest.approx(0.042)
		assert "db" in kwargs
		assert isinstance(kwargs["db"], float)


class TestStatusCog:
	@pytest.mark.asyncio
	async def test_statusupdate(self, mock_bot):
		cog = Status(mock_bot)

		cmd1 = MagicMock()
		cmd1.qualified_name = "ping"
		cmd1.hidden = False
		mock_bot.commands = [cmd1]

		await cog.statusupdate()

		mock_bot.change_presence.assert_called_once()
		presence_kwargs = mock_bot.change_presence.call_args[1]
		assert presence_kwargs["status"] == discord.Status.online
		activity = presence_kwargs["activity"]
		assert isinstance(activity, discord.CustomActivity)
		assert "2 servers | ?!ping" in activity.name

	@pytest.mark.asyncio
	async def test_statusupdate_empty_commands(self, mock_bot):
		cog = Status(mock_bot)
		mock_bot.commands = []

		await cog.statusupdate()

		mock_bot.change_presence.assert_called_once()
		activity = mock_bot.change_presence.call_args[1]["activity"]
		assert "2 servers | ?!help" in activity.name

	@pytest.mark.asyncio
	async def test_cog_load_and_unload(self, mock_bot):
		cog = Status(mock_bot)
		with (
			patch.object(cog.update_status, "start") as mock_start,
			patch.object(cog.update_status, "is_running", return_value=False),
		):
			await cog.cog_load()
			mock_start.assert_called_once()

		with patch.object(cog.update_status, "cancel") as mock_cancel:
			await cog.cog_unload()
			mock_cancel.assert_called_once()


class TestAFKCog:
	@pytest.mark.asyncio
	async def test_afk_command_with_reason(self, mock_bot):
		cog = AFK(mock_bot)
		ctx = MagicMock()
		ctx.guild.id = 123
		ctx.author.id = 456
		ctx.author.display_name = "Alice"
		ctx.author.edit = AsyncMock()
		ctx.send = AsyncMock()

		mock_bot.db.fetchrow.return_value = None

		await cog.afk.callback(cog, ctx, reason="Studying for exams")

		mock_bot.db.execute.assert_called()
		ctx.send.assert_called_once_with("afk.on")
		assert (123, 456) in cog.afk_cache
		assert cog.afk_cache[(123, 456)]["message"] == "Studying for exams"

	@pytest.mark.asyncio
	async def test_afk_command_rejects_discord_invite(self, mock_bot):
		cog = AFK(mock_bot)
		ctx = MagicMock()
		ctx.guild.id = 123
		ctx.author.id = 456
		ctx.send = AsyncMock()

		await cog.afk.callback(cog, ctx, reason="Join my server discord.gg/malicious")

		ctx.send.assert_called_once_with("afk.link")
		mock_bot.db.execute.assert_not_called()
		assert (123, 456) not in cog.afk_cache

	@pytest.mark.asyncio
	async def test_check_afk_listener_turns_afk_off(self, mock_bot):
		cog = AFK(mock_bot)
		cog.afk_cache[(123, 456)] = {"message": "AFK", "previous_nick": "OldNick"}

		message = MagicMock(spec=discord.Message)
		message.guild.id = 123
		message.author.id = 456
		message.author.edit = AsyncMock()

		ctx = MagicMock()
		ctx.guild.id = 123
		ctx.author = message.author
		ctx.command = None
		ctx.reply = AsyncMock()
		mock_bot.get_context.return_value = ctx

		await cog.check_afk(message)

		assert (123, 456) not in cog.afk_cache
		mock_bot.db.execute.assert_called_once()
		message.author.edit.assert_called_once_with(nick="OldNick")
		ctx.reply.assert_called_once_with("afk.off")

	@pytest.mark.asyncio
	async def test_answer_afk_reason_listener(self, mock_bot):
		cog = AFK(mock_bot)
		cog.afk_cache[(123, 789)] = {"message": "Sleeping", "previous_nick": "None"}

		afk_user = MagicMock(spec=discord.Member)
		afk_user.id = 789
		afk_user.name = "Sleeper"

		message = MagicMock(spec=discord.Message)
		message.author.bot = False
		message.author.id = 456
		message.guild.id = 123
		message.mentions = [afk_user]

		ctx = MagicMock()
		ctx.reply = AsyncMock()
		mock_bot.get_context.return_value = ctx
		mock_bot.custom_response.return_value = {"content": "Sleeper is AFK: Sleeping"}

		await cog.answer_afk_reason(message)

		ctx.reply.assert_called_once_with("Sleeper is AFK: Sleeping")


class TestLeaveConfigCommands:
	@pytest.mark.asyncio
	async def test_leave_enable_and_disable(self, mock_bot):
		root = CLINode(prog="config")
		setup_leave_subcommands(root)

		ctx = MagicMock()
		ctx.guild.id = 123
		ctx.guild.name = "Test Guild"
		channel = MagicMock(spec=discord.TextChannel)
		channel.name = "goodbye"
		channel.id = 999
		ctx.guild.channels = [channel]
		ctx.guild.get_channel.return_value = channel
		ctx.channel = channel
		ctx.send = AsyncMock()
		ctx.bot = mock_bot

		# Execute enable
		parser_action = root._subparsers_action.choices["leave"]  # type: ignore
		enable_action = parser_action._subparsers_action.choices["enable"]
		await enable_action.callback(ctx, channel="#goodbye", message="{user} has left!")

		mock_bot.db.execute.assert_called_once()
		assert "Leave messages enabled in #goodbye" in ctx.send.call_args[1]["content"]

		# Execute disable
		ctx.send.reset_mock()
		mock_bot.db.execute.reset_mock()
		disable_action = parser_action._subparsers_action.choices["disable"]
		await disable_action.callback(ctx)

		mock_bot.db.execute.assert_called_once()
		assert "Leave messages disabled" in ctx.send.call_args[1]["content"]

	@pytest.mark.asyncio
	async def test_leave_message_and_status(self, mock_bot):
		root = CLINode(prog="config")
		setup_leave_subcommands(root)

		ctx = MagicMock()
		ctx.guild.id = 123
		ctx.guild.name = "Test Guild"
		ctx.channel.id = 888
		ctx.channel.name = "bye-channel"
		ctx.guild.get_channel.return_value = ctx.channel
		ctx.send = AsyncMock()
		ctx.bot = mock_bot

		parser_action = root._subparsers_action.choices["leave"]  # type: ignore
		msg_action = parser_action._subparsers_action.choices["message"]

		# Test message without template raises
		with pytest.raises(CLIParseError):
			await msg_action.callback(ctx, message=None, message_pos=None)

		# Test setting message
		await msg_action.callback(ctx, message="Bye bye {user}!")
		mock_bot.db.execute.assert_called_once()
		assert "Leave message template updated" in ctx.send.call_args[1]["content"]

		# Test status
		ctx.send.reset_mock()
		mock_bot.db.fetchrow.return_value = {
			"guild_id": 123,
			"is_on": True,
			"channel": 888,
			"message": "Bye bye {user}!",
		}
		status_action = parser_action._subparsers_action.choices["status"]
		await status_action.callback(ctx)

		ctx.send.assert_called_once()
		status_output = ctx.send.call_args[1]["content"]
		assert "Leave Configuration (Test Guild)" in status_output
		assert "Status:   Enabled" in status_output
		assert "Channel:  #bye-channel" in status_output


class TestSayCog:
	@pytest.mark.asyncio
	async def test_say_command(self, mock_bot):
		from cogs.say import Say

		cog = Say(mock_bot)
		ctx = MagicMock()
		ctx.send = AsyncMock()

		await cog.say.callback(cog, ctx, message="Hello Discord!")
		ctx.send.assert_called_once()
		args, kwargs = ctx.send.call_args
		assert args[0] == "say.message"
		assert kwargs["message"] == "Hello Discord!"
		assert isinstance(kwargs["allowed_mentions"], discord.AllowedMentions)
		assert kwargs["allowed_mentions"].everyone is False

	@pytest.mark.asyncio
	async def test_channel_say_command(self, mock_bot):
		from cogs.say import Say

		cog = Say(mock_bot)
		ctx = MagicMock()
		channel = MagicMock(spec=discord.TextChannel)
		channel.send = AsyncMock()

		await cog.channel_say.callback(cog, ctx, channel=channel, message="Channel message")
		channel.send.assert_called_once()
		args, kwargs = channel.send.call_args
		assert args[0] == "Channel message"
		assert isinstance(kwargs["allowed_mentions"], discord.AllowedMentions)
		assert kwargs["allowed_mentions"].everyone is False

	@pytest.mark.asyncio
	async def test_reverse_say_command(self, mock_bot):
		from cogs.say import Say

		cog = Say(mock_bot)
		ctx = MagicMock()
		ctx.send = AsyncMock()

		await cog.reverse_say.callback(cog, ctx, message="abcdef")
		ctx.send.assert_called_once_with("say.reverse", message="fedcba")

	@pytest.mark.asyncio
	async def test_clap_say_command(self, mock_bot):
		from cogs.say import Say

		cog = Say(mock_bot)
		ctx = MagicMock()
		ctx.send = AsyncMock()

		await cog.clap_say.callback(cog, ctx, message="great job everyone")
		ctx.send.assert_called_once_with("say.clap", message="great👏job👏everyone")

	@pytest.mark.asyncio
	async def test_qr_code_command(self, mock_bot):
		from cogs.say import Say

		cog = Say(mock_bot)
		ctx = MagicMock()
		ctx.send = AsyncMock()

		await cog.qr_code.callback(cog, ctx, data="https://example.com/test?a=1&b=2")
		ctx.send.assert_called_once()
		qr_url = ctx.send.call_args[1]["qr"]
		assert "https://api.qrserver.com/v1/create-qr-code/?data=" in qr_url
		assert "https%3A%2F%2Fexample.com%2Ftest%3Fa%3D1%26b%3D2" in qr_url
