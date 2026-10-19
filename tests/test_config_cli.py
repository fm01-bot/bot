from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from cogs.config import Config
from helpers.cli_parser import CLIParseError, CLIParser, HelpRequested


def test_split_args():
	cmd = 'config join enable --channel #join --message "Welcome {user} to the server!"'
	tokens = CLIParser.split_args(cmd)
	assert tokens == ["config", "join", "enable", "--channel", "#join", "--message", "Welcome {user} to the server!"]


def test_short_flags_and_clustering():
	parser = CLIParser("app")
	cmd = parser.root.add_subcommand("ls")
	cmd.add_option("all", "a", is_flag=True)
	cmd.add_option("long", "l", is_flag=True)

	_node, opts = parser.parse(["ls", "-al"])
	assert opts["all"] is True
	assert opts["long"] is True

	# Separate flags
	_node, opts = parser.parse(["ls", "-a", "-l"])
	assert opts["all"] is True
	assert opts["long"] is True


def test_short_flag_with_value():
	parser = CLIParser("app")
	cmd = parser.root.add_subcommand("zip")
	cmd.add_option("exclude", "x")

	# zip -x "*node_modules*"
	_node, opts = parser.parse(["zip", "-x", "*node_modules*"])
	assert opts["exclude"] == "*node_modules*"

	# zip -x="*node_modules*"
	_node, opts = parser.parse(["zip", "-x=*node_modules*"])
	assert opts["exclude"] == "*node_modules*"


def test_docker_compose_up_d():
	parser = CLIParser("docker")
	compose = parser.root.add_subcommand("compose")
	up = compose.add_subcommand("up")
	up.add_option("detach", "d", is_flag=True)

	node, opts = parser.parse(["compose", "up", "-d"])
	assert node.name == "up"
	assert opts["detach"] is True


def test_config_log_enable_flag():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("log enable --channel #log")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "enable"
	assert opts["channel"] == "#log"


def test_config_log_enable_positional():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("log enable #log")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "enable"
	assert opts["channel_pos"] == "#log"


def test_config_log_modules_enable():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("log modules enable on_message_delete on_message_edit")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "enable"
	assert opts["modules"] == ["on_message_delete", "on_message_edit"]


def test_config_log_modules_disable():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("log modules disable on_message_delete")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "disable"
	assert opts["modules"] == ["on_message_delete"]


def test_config_join_enable():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args('join enable --channel #join --message "Welcome {user} to the server!"')
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "enable"
	assert opts["channel"] == "#join"
	assert opts["message"] == "Welcome {user} to the server!"


def test_help_requested():
	config_cog = Config(MagicMock())
	with pytest.raises(HelpRequested) as exc_info:
		config_cog.parser.parse(["log", "--help"])
	assert "config log" in exc_info.value.help_text.lower()


def test_unknown_subcommand_error():
	config_cog = Config(MagicMock())
	with pytest.raises(CLIParseError) as exc_info:
		config_cog.parser.parse(["nonexistent"])
	assert "unknown subcommand" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_full_execution_flow():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.get_cog.return_value = None

	guild = MagicMock()
	guild.id = 12345
	guild.name = "Test Guild"
	text_ch = MagicMock(spec=discord.TextChannel)
	text_ch.name = "log"
	text_ch.id = 999
	guild.channels = [text_ch]
	guild.threads = []
	guild.get_channel_or_thread.return_value = text_ch

	join_ch = MagicMock(spec=discord.TextChannel)
	join_ch.name = "join"
	join_ch.id = 888
	guild.channels.append(join_ch)

	ctx = MagicMock()
	ctx.guild = guild
	ctx.channel = text_ch
	ctx.bot = bot
	ctx.send = AsyncMock()

	config_cog = Config(bot)

	def check_code_block_response(mock_send):
		kwargs = mock_send.call_args[1]
		assert "embed" not in kwargs or kwargs["embed"] is None
		assert "embeds" not in kwargs or kwargs["embeds"] is None
		content = kwargs.get("content", "")
		assert content.startswith("```") and content.endswith("```")

	# 1. Execute: log enable --channel #log
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="log enable --channel #log")
	assert ctx.send.called
	assert bot.db.execute.called
	check_code_block_response(ctx.send)

	# 2. Execute: log enable #log (positional)
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="log enable #log")
	assert ctx.send.called
	assert bot.db.execute.called
	check_code_block_response(ctx.send)

	# 3. Execute: log modules enable on_message_delete on_message_edit
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(
		config_cog, ctx, flags_and_args="log modules enable on_message_delete on_message_edit"
	)
	assert ctx.send.called
	assert bot.db.execute.call_count >= 2
	check_code_block_response(ctx.send)

	# 4. Execute: log modules disable on_message_delete
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="log modules disable on_message_delete")
	assert ctx.send.called
	assert bot.db.execute.called
	check_code_block_response(ctx.send)

	# 5. Execute: join enable --channel #join --message "Welcome {user} to the server!"
	guild.get_channel_or_thread.return_value = join_ch
	bot.db.fetchrow.return_value = {"message": "Welcome {user} to the server!"}
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(
		config_cog, ctx, flags_and_args='join enable --channel #join --message "Welcome {user} to the server!"'
	)
	assert ctx.send.called
	assert bot.db.execute.called
	check_code_block_response(ctx.send)

	# 6. Execute: config (empty -> shows help)
	ctx.send.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="")
	assert ctx.send.called
	check_code_block_response(ctx.send)
	call_content = ctx.send.call_args[1].get("content") or ctx.send.call_args[0][0]
	assert "Config CLI Help" in call_content

	# 7. Execute: log status
	ctx.send.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="log status")
	assert ctx.send.called
	check_code_block_response(ctx.send)

	# 8. Execute: join status
	ctx.send.reset_mock()
	bot.db.fetchrow.return_value = {"guild_id": 12345, "is_on": True, "channel": 888, "message": "Hello {user}!"}
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="join status")
	assert ctx.send.called
	check_code_block_response(ctx.send)
	status_content = ctx.send.call_args[1].get("content")
	assert "Hello {user}!" in status_content  # Template is not replaced in preview


@pytest.mark.asyncio
async def test_config_level_execution():
	bot = MagicMock()
	bot.db = MagicMock()
	bot.db.execute = AsyncMock()
	bot.db.fetch = AsyncMock(return_value=[])
	bot.db.fetchrow = AsyncMock(return_value=None)
	bot.get_cog.return_value = None

	ctx = MagicMock()
	ctx.bot = bot
	ctx.send = AsyncMock()

	guild = MagicMock()
	guild.id = 12345
	guild.name = "Test Guild"

	test_channel = MagicMock(spec=discord.TextChannel)
	test_channel.id = 555
	test_channel.name = "general"
	guild.channels = [test_channel]
	guild.threads = []
	guild.get_channel_or_thread.return_value = test_channel
	guild.get_channel.return_value = test_channel

	test_role = MagicMock(spec=discord.Role)
	test_role.id = 777
	test_role.name = "VIP"
	guild.roles = [test_role]
	guild.get_role.return_value = test_role

	ctx.guild = guild
	ctx.channel = test_channel

	config_cog = Config(bot)

	# 1. config level enable
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level enable")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "[+] Leveling system enabled" in ctx.send.call_args[1]["content"]

	# 2. config level disable
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level disable")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "[-] Leveling system disabled" in ctx.send.call_args[1]["content"]

	# 3. config level xp
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(
		config_cog, ctx, flags_and_args="level xp --min 20 --max 30 --multiplier 1.5 --cooldown 45"
	)
	assert ctx.send.called
	assert bot.db.execute.called
	content = ctx.send.call_args[1]["content"]
	assert "Minimum XP: 20" in content
	assert "Maximum XP: 30" in content
	assert "Multiplier: 1.5x" in content
	assert "Cooldown: 45s" in content

	# 4. config level message
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(
		config_cog, ctx, flags_and_args='level message --mode channel --channel #general --template "Congrats {user}!"'
	)
	assert ctx.send.called
	assert bot.db.execute.called
	content = ctx.send.call_args[1]["content"]
	assert "Mode: channel" in content
	assert "Channel: #general" in content

	# 5. config level rewards add
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level rewards add 5 @VIP")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "[+] Added reward: @VIP at Level 5" in ctx.send.call_args[1]["content"]

	# 6. config level rewards remove
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level rewards remove 5")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "[-] Removed role reward(s) for Level 5" in ctx.send.call_args[1]["content"]

	# 7. config level rewards stack
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level rewards stack false")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "Replace previous" in ctx.send.call_args[1]["content"]

	# 8. config level channel ignore
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level channel ignore #general")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "Ignored channel #general" in ctx.send.call_args[1]["content"]

	# 9. config level channel unignore
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level channel unignore #general")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "Unignored channel #general" in ctx.send.call_args[1]["content"]

	# 10. config level channel multiplier
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level channel multiplier #general 2.0")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "set to 2.0x" in ctx.send.call_args[1]["content"]

	# 11. config level role ignore
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level role ignore @VIP")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "Ignored role @VIP" in ctx.send.call_args[1]["content"]

	# 12. config level role unignore
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level role unignore @VIP")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "Unignored role @VIP" in ctx.send.call_args[1]["content"]

	# 13. config level role multiplier
	ctx.send.reset_mock()
	bot.db.execute.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level role multiplier @VIP 1.5")
	assert ctx.send.called
	assert bot.db.execute.called
	assert "set to 1.5x" in ctx.send.call_args[1]["content"]

	# 14. config level show
	ctx.send.reset_mock()
	await config_cog.config_command.callback(config_cog, ctx, flags_and_args="level show")
	assert ctx.send.called
	assert "Leveling System Configuration" in ctx.send.call_args[1]["content"]
