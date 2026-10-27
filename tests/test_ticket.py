from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.config import Config
from cogs.ticket import (
	ActiveTicketControlsView,
	ArchivedTicketControlsView,
	Ticket,
)
from helpers.cli_parser import CLIParseError, CLIParser


def test_config_ticket_enable_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket enable")
	node, _opts = config_cog.parser.parse(tokens)
	assert node.name == "enable"


def test_config_ticket_disable_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket disable")
	node, _opts = config_cog.parser.parse(tokens)
	assert node.name == "disable"


def test_config_ticket_panel_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args('ticket panel --channel #tickets --title "Support" --button "Open"')
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "panel"
	assert opts["channel"] == "#tickets"
	assert opts["title"] == "Support"
	assert opts["button"] == "Open"


def test_config_ticket_category_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args('ticket category --category "Support Tickets"')
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "category"
	assert opts["category"] == "Support Tickets"


def test_config_ticket_category_clear_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket category --clear")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "category"
	assert opts["clear"] is True


def test_config_ticket_log_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket log --channel #ticket-log")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "log"
	assert opts["channel"] == "#ticket-log"


def test_config_ticket_log_disable_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket log --disable")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "log"
	assert opts["disable"] is True


def test_config_ticket_role_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket role --role @Support")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "role"
	assert opts["role"] == "@Support"


def test_config_ticket_limit_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket limit 2")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "limit"
	assert opts["max_pos"] == "2"


def test_config_ticket_dm_parse():
	config_cog = Config(MagicMock())
	tokens = CLIParser.split_args("ticket dm --enable")
	node, opts = config_cog.parser.parse(tokens)
	assert node.name == "dm"
	assert opts["enable"] is True


@pytest.mark.asyncio
async def test_config_ticket_execution_flow():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.get_cog.return_value = None

	guild = MagicMock()
	guild.id = 12345
	guild.name = "Test Guild"
	text_ch = MagicMock(spec=discord.TextChannel)
	text_ch.name = "tickets"
	text_ch.id = 999
	text_ch.permissions_for.return_value.send_messages = True
	text_ch.permissions_for.return_value.embed_links = True
	guild.channels = [text_ch]
	guild.threads = []
	guild.get_channel_or_thread.return_value = text_ch

	cat = MagicMock(spec=discord.CategoryChannel)
	cat.name = "Support"
	cat.id = 777
	guild.categories = [cat]
	guild.me = MagicMock()

	guild.get_channel = MagicMock(side_effect=lambda cid: cat if cid == 777 else (text_ch if cid == 999 else None))

	role = MagicMock(spec=discord.Role)
	role.name = "Support"
	role.id = 555
	guild.roles = [role]
	guild.get_role.return_value = role

	ctx = MagicMock()
	ctx.guild = guild
	ctx.channel = text_ch
	ctx.bot = bot
	ctx.send = AsyncMock()

	config_cog = Config(bot)

	# Execute enable
	await config_cog.parser.execute("ticket enable", ctx=ctx)
	bot.db.execute.assert_called()
	assert "[+] Ticket system enabled" in ctx.send.call_args[1]["content"]

	# Execute category
	await config_cog.parser.execute('ticket category --category "Support"', ctx=ctx)
	assert "[+] Ticket category set to 'Support'" in ctx.send.call_args[1]["content"]

	# Execute log
	await config_cog.parser.execute("ticket log --channel #tickets", ctx=ctx)
	assert "[+] Ticket log channel set to #tickets" in ctx.send.call_args[1]["content"]

	# Execute role
	await config_cog.parser.execute("ticket role --role @Support", ctx=ctx)
	assert "[+] Support role set to @Support" in ctx.send.call_args[1]["content"]

	# Execute limit
	await config_cog.parser.execute("ticket limit 3", ctx=ctx)
	assert "[+] Max concurrent tickets set to: 3 ticket(s) per user" in ctx.send.call_args[1]["content"]

	# Execute dm
	await config_cog.parser.execute("ticket dm --disable", ctx=ctx)
	assert "[+] DM transcripts disabled" in ctx.send.call_args[1]["content"]

	# Execute panel
	await config_cog.parser.execute('ticket panel --channel #tickets --title "Help Desk"', ctx=ctx)
	assert "[+] Ticket panel deployed in #tickets" in ctx.send.call_args[1]["content"]
	text_ch.send.assert_called_once()

	# Execute status
	bot.db.fetchrow.return_value = {
		"is_on": True,
		"category_id": 777,
		"log_channel_id": 999,
		"support_role_id": 555,
		"max_tickets": 3,
		"dm_transcript": False,
	}
	await config_cog.parser.execute("ticket status", ctx=ctx)
	status_out = ctx.send.call_args[1]["content"]
	assert "Status:        Enabled" in status_out
	assert "Category:      Support" in status_out
	assert "Log Channel:   #tickets" in status_out
	assert "Support Role:  @Support" in status_out
	assert "Max Tickets:   3 per user" in status_out


@pytest.mark.asyncio
async def test_config_ticket_limit_invalid():
	bot = MagicMock()
	bot.db = AsyncMock()
	ctx = MagicMock()
	ctx.guild = MagicMock()
	config_cog = Config(bot)

	with pytest.raises(CLIParseError):
		await config_cog.parser.execute("ticket limit -5", ctx=ctx)

	with pytest.raises(CLIParseError):
		await config_cog.parser.execute("ticket limit abc", ctx=ctx)


@pytest.mark.asyncio
async def test_ticket_permissions():
	bot = MagicMock()
	bot.db = AsyncMock()
	cog = Ticket(bot)

	guild = MagicMock()
	guild.id = 12345

	member = MagicMock(spec=discord.Member)
	member.id = 100
	member.guild_permissions.administrator = False
	member.guild_permissions.manage_channels = False
	member.roles = []

	interaction = MagicMock()
	interaction.guild = guild
	interaction.user = member

	ticket_row = {
		"id": 1,
		"user_id": 100,
	}

	# Opener should be allowed
	assert await cog.can_manage_ticket(interaction, ticket_row) is True

	# Different member should be denied
	member.id = 200
	bot.db.fetchrow.return_value = None
	assert await cog.can_manage_ticket(interaction, ticket_row) is False

	# Administrator should be allowed
	member.guild_permissions.administrator = True
	assert await cog.can_manage_ticket(interaction, ticket_row) is True
	member.guild_permissions.administrator = False

	# Support role member should be allowed
	support_role = MagicMock(spec=discord.Role)
	support_role.id = 300
	member.roles = [support_role]
	bot.db.fetchrow.return_value = {"support_role_id": 300}
	assert await cog.can_manage_ticket(interaction, ticket_row) is True


@pytest.mark.asyncio
async def test_ticket_create_flow():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.custom_response.get_message = AsyncMock(return_value="Your ticket has been created: #ticket-alice")
	cog = Ticket(bot)

	guild = MagicMock()
	guild.id = 12345
	guild.default_role = MagicMock()
	guild.me = MagicMock()

	cat = MagicMock(spec=discord.CategoryChannel)
	cat.name = "Tickets"
	guild.categories = [cat]
	guild.create_category = AsyncMock(return_value=cat)

	created_ch = MagicMock(spec=discord.TextChannel)
	created_ch.id = 888
	created_ch.name = "ticket-alice"
	created_ch.mention = "<#888>"
	guild.create_text_channel = AsyncMock(return_value=created_ch)

	member = MagicMock(spec=discord.Member)
	member.id = 100
	member.name = "Alice"
	member.display_name = "Alice"
	member.display_avatar.url = "https://example.com/avatar.png"
	member.mention = "<@100>"

	interaction = MagicMock()
	interaction.guild = guild
	interaction.user = member
	interaction.response = MagicMock()
	interaction.response.defer = AsyncMock()
	interaction.followup = MagicMock()
	interaction.followup.send = AsyncMock()

	# Config: enabled, limit 1, no open tickets
	bot.db.fetchrow.return_value = {"is_on": True, "max_tickets": 1, "category_id": None, "log_channel_id": None}
	bot.db.fetchval = AsyncMock(side_effect=[0, 42])  # count=0, returning ticket_id=42

	await cog.handle_ticket_create(interaction, topic="Billing issue", description="I need help with my payment")

	guild.create_text_channel.assert_called_once()
	created_ch.send.assert_called_once()
	interaction.followup.send.assert_called_once()
	assert "ticket-alice" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_ticket_create_limit_exceeded():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.custom_response.get_message = AsyncMock(
		return_value="You already have 1 open ticket(s). The maximum allowed is 1."
	)
	cog = Ticket(bot)

	guild = MagicMock()
	guild.id = 12345
	member = MagicMock(spec=discord.Member)
	member.id = 100
	member.name = "Bob"

	interaction = MagicMock()
	interaction.guild = guild
	interaction.user = member
	interaction.response.defer = AsyncMock()
	interaction.followup.send = AsyncMock()

	bot.db.fetchrow.return_value = {"is_on": True, "max_tickets": 1}
	bot.db.fetchval.return_value = 1  # already has 1 ticket open

	await cog.handle_ticket_create(interaction, topic="Issue", description="Description")

	guild.create_text_channel.assert_not_called()
	interaction.followup.send.assert_called_once()
	assert "already have" in interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_ticket_archive_and_reopen():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.custom_response.get_message = AsyncMock(side_effect=lambda key, *args, **kwargs: key)
	cog = Ticket(bot)

	guild = MagicMock()
	guild.id = 12345
	member = MagicMock(spec=discord.Member)
	member.id = 100
	guild.get_member.return_value = member

	channel = MagicMock(spec=discord.TextChannel)
	channel.id = 777
	channel.name = "ticket-test"
	channel.set_permissions = AsyncMock()
	channel.send = AsyncMock()

	interaction = MagicMock()
	interaction.guild = guild
	interaction.user = member
	interaction.channel = channel
	interaction.response.defer = AsyncMock()

	bot.db.fetchrow.side_effect = [
		{"id": 10, "user_id": 100, "channel_id": 777},  # get_ticket
		{"is_on": True, "log_channel_id": None},  # get_ticket_config
	]

	# Test archive
	await cog.handle_archive_action(interaction)
	channel.set_permissions.assert_called_with(
		member, send_messages=False, view_channel=True, read_message_history=True
	)
	channel.send.assert_called_once()
	view = channel.send.call_args[1]["view"]
	assert isinstance(view, ArchivedTicketControlsView)

	# Test reopen
	channel.set_permissions.reset_mock()
	channel.send.reset_mock()
	bot.db.fetchrow.side_effect = [
		{"id": 10, "user_id": 100, "channel_id": 777},  # get_ticket
		{"is_on": True, "log_channel_id": None},  # get_ticket_config
	]
	await cog.handle_reopen_action(interaction)
	channel.set_permissions.assert_called_with(member, send_messages=True, view_channel=True, read_message_history=True)
	channel.send.assert_called_once()
	view = channel.send.call_args[1]["view"]
	assert isinstance(view, ActiveTicketControlsView)


@pytest.mark.asyncio
async def test_ticket_save_and_close():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.custom_response.get_message = AsyncMock(return_value="Success")
	cog = Ticket(bot)

	guild = MagicMock()
	guild.id = 12345
	member = MagicMock(spec=discord.Member)
	member.id = 100
	guild.get_member.return_value = member

	log_channel = MagicMock(spec=discord.TextChannel)
	log_channel.id = 999
	log_channel.send = AsyncMock()
	guild.get_channel.return_value = log_channel

	channel = MagicMock(spec=discord.TextChannel)
	channel.id = 777
	channel.name = "ticket-test"
	channel.delete = AsyncMock()

	interaction = MagicMock()
	interaction.guild = guild
	interaction.user = member
	interaction.channel = channel
	interaction.message = MagicMock()
	interaction.message.edit = AsyncMock()
	interaction.response.defer = AsyncMock()
	interaction.followup.send = AsyncMock()

	bot.db.fetchrow.side_effect = [
		{"id": 10, "user_id": 100, "channel_id": 777, "title": "Help"},  # get_ticket
		{"is_on": True, "log_channel_id": 999, "dm_transcript": True},  # get_ticket_config
	]

	# Mock chat_exporter
	with patch("chat_exporter.export", AsyncMock(return_value="<html>transcript</html>")):
		await cog.handle_close_action(interaction)

	log_channel.send.assert_called_once()
	# Transcripts attached as file
	assert "file" in log_channel.send.call_args[1]
	member.send.assert_called_once()
	channel.delete.assert_called_once()


@pytest.mark.asyncio
async def test_on_guild_channel_delete():
	bot = MagicMock()
	bot.db = AsyncMock()
	cog = Ticket(bot)

	ch = MagicMock(spec=discord.TextChannel)
	ch.id = 12345
	await cog.on_guild_channel_delete(ch)
	bot.db.execute.assert_called_once()
	assert "UPDATE tickets" in bot.db.execute.call_args[0][0]
	assert bot.db.execute.call_args[0][1] == 12345
