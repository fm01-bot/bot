from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.automod import AutoMod, AutoModConfig
from cogs.config import Config
from helpers.cli_parser import CLIParser


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.custom_response = MagicMock()
	bot.custom_response.get_message = AsyncMock(return_value={"content": "Violation notice"})
	return bot


@pytest.fixture
def automod_cog(mock_bot):
	cog = AutoMod(mock_bot)
	return cog


@pytest.fixture
def mock_guild():
	guild = MagicMock(spec=discord.Guild)
	guild.id = 111222333
	guild.name = "Test Guild"
	guild.owner_id = 999999999
	guild.vanity_url_code = "myguild"
	guild.channels = []
	guild.categories = []
	guild.roles = []
	guild.members = []
	guild.me = MagicMock(spec=discord.Member)
	guild.me.id = 555555555
	return guild


@pytest.fixture
def mock_channel(mock_guild):
	channel = MagicMock(spec=discord.TextChannel)
	channel.id = 1000001
	channel.name = "general"
	channel.category_id = 2000001
	channel.guild = mock_guild
	channel.send = AsyncMock()
	return channel


@pytest.fixture
def mock_member(mock_guild):
	member = MagicMock(spec=discord.Member)
	member.id = 3000001
	member.name = "alice"
	member.guild = mock_guild
	member.bot = False
	member.guild_permissions = discord.Permissions.none()
	role = MagicMock(spec=discord.Role)
	role.id = 4000001
	role.name = "MemberRole"
	member.roles = [role]
	return member


def test_automod_config_defaults():
	cfg = AutoModConfig(guild_id=123)
	assert cfg.guild_id == 123
	assert cfg.is_on is True
	assert cfg.is_feature_enabled("phrase") is False
	assert cfg.is_feature_enabled("link") is False
	assert cfg.is_feature_enabled("spam") is False

	action = cfg.get_action("phrase")
	assert action["delete"] is True
	assert action["notify"] is True
	assert action["notify_duration"] == 5
	assert action["case"] is None


def test_automod_config_from_row():
	row = {"guild_id": 456, "is_on": True, "settings": '{"rules": {"phrase": {"enabled": true, "phrases": ["bad"]}}}'}
	cfg = AutoModConfig.from_row(row, 456)
	assert cfg.guild_id == 456
	assert cfg.is_on is True
	assert cfg.is_feature_enabled("phrase") is True
	assert cfg.settings["rules"]["phrase"]["phrases"] == ["bad"]


def test_check_phrases(automod_cog):
	phrases = ["badword", "free nitro"]

	# Positive matches
	assert automod_cog.check_phrases("You are a badword!", phrases) is True
	assert automod_cog.check_phrases("Claim your FREE NITRO now", phrases) is True
	assert automod_cog.check_phrases("badword", phrases) is True

	# Word boundary test: "badwords" vs "badword"
	# Single word "badword" does not match "mybadwordisgood"
	assert automod_cog.check_phrases("mybadwordisgood", phrases) is False

	# Multi-word matches substring
	assert automod_cog.check_phrases("get some free nitro today", phrases) is True

	# Negative matches
	assert automod_cog.check_phrases("This is a clean message.", phrases) is False
	assert automod_cog.check_phrases("", phrases) is False
	assert automod_cog.check_phrases("clean", []) is False


def test_check_links(automod_cog):
	allowlist = ["youtube.com", "tenor.com"]

	# Unallowed links
	assert automod_cog.check_links("Check out https://evil-site.com/hack", allowlist) is True
	assert automod_cog.check_links("Visit www.phishing.org/login", allowlist) is True
	assert automod_cog.check_links("Go to random-domain.xyz", allowlist) is True

	# Allowed links
	assert automod_cog.check_links("Watch https://www.youtube.com/watch?v=123", allowlist) is False
	assert automod_cog.check_links("Look at this gif https://media.tenor.com/view/123", allowlist) is False
	assert automod_cog.check_links("Clean text with no urls", allowlist) is False


def test_check_invites(automod_cog, mock_guild):
	allowlist = ["partnercode"]

	# Unallowed invite
	assert automod_cog.check_invites("Join discord.gg/unknown123", allowlist, mock_guild) is True
	assert automod_cog.check_invites("Join https://discord.com/invite/badcode", allowlist, mock_guild) is True

	# Allowed invite via allowlist
	assert automod_cog.check_invites("Join discord.gg/partnercode", allowlist, mock_guild) is False

	# Allowed invite via guild vanity
	assert automod_cog.check_invites("Join discord.gg/myguild", allowlist, mock_guild) is False

	# Non-invite message
	assert automod_cog.check_invites("Hello world", allowlist, mock_guild) is False


def test_check_spam(automod_cog):
	guild_id = 111
	user_id = 222
	max_msgs = 5
	window = 6.0

	# Send 5 messages: all allowed
	for _ in range(5):
		assert automod_cog.check_spam(guild_id, user_id, max_msgs, window) is False

	# 6th message in same window: flagged as spam
	assert automod_cog.check_spam(guild_id, user_id, max_msgs, window) is True


def test_check_mentions(automod_cog):
	msg = MagicMock(spec=discord.Message)
	msg.mentions = [MagicMock(), MagicMock(), MagicMock()]
	msg.role_mentions = [MagicMock()]
	msg.mention_everyone = True
	# Total mentions: 3 + 1 + 1 = 5

	assert automod_cog.check_mentions(msg, limit=4) is True
	assert automod_cog.check_mentions(msg, limit=5) is False
	assert automod_cog.check_mentions(msg, limit=10) is False


def test_check_lines(automod_cog):
	text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
	assert automod_cog.check_lines(text, limit=4) is True
	assert automod_cog.check_lines(text, limit=5) is False
	assert automod_cog.check_lines(text, limit=10) is False


def test_is_bypassed(automod_cog, mock_guild, mock_channel, mock_member):
	cfg = AutoModConfig(mock_guild.id)

	# Regular member is not bypassed
	assert automod_cog.is_bypassed(mock_member, mock_channel, "link", cfg) is False

	# Guild owner is always bypassed
	owner_member = MagicMock(spec=discord.Member)
	owner_member.id = mock_guild.owner_id
	owner_member.guild = mock_guild
	assert automod_cog.is_bypassed(owner_member, mock_channel, "link", cfg) is True

	# Administrator is always bypassed
	admin_member = MagicMock(spec=discord.Member)
	admin_member.id = 8888888
	admin_member.guild = mock_guild
	admin_member.guild_permissions = discord.Permissions(administrator=True)
	assert automod_cog.is_bypassed(admin_member, mock_channel, "link", cfg) is True

	# Global user bypass
	cfg.settings["bypasses"]["global"]["users"].append(mock_member.id)
	assert automod_cog.is_bypassed(mock_member, mock_channel, "link", cfg) is True
	cfg.settings["bypasses"]["global"]["users"].clear()

	# Global channel bypass
	cfg.settings["bypasses"]["global"]["channels"].append(mock_channel.id)
	assert automod_cog.is_bypassed(mock_member, mock_channel, "link", cfg) is True
	cfg.settings["bypasses"]["global"]["channels"].clear()

	# Global category bypass
	cfg.settings["bypasses"]["global"]["categories"].append(mock_channel.category_id)
	assert automod_cog.is_bypassed(mock_member, mock_channel, "link", cfg) is True
	cfg.settings["bypasses"]["global"]["categories"].clear()

	# Global role bypass
	cfg.settings["bypasses"]["global"]["roles"].append(mock_member.roles[0].id)
	assert automod_cog.is_bypassed(mock_member, mock_channel, "link", cfg) is True
	cfg.settings["bypasses"]["global"]["roles"].clear()

	# Feature-specific bypass
	cfg.settings["bypasses"]["features"]["link"]["channels"].append(mock_channel.id)
	assert automod_cog.is_bypassed(mock_member, mock_channel, "link", cfg) is True
	# Should NOT bypass other features like invite
	assert automod_cog.is_bypassed(mock_member, mock_channel, "invite", cfg) is False


@pytest.mark.asyncio
async def test_handle_violation_actions(automod_cog, mock_guild, mock_channel, mock_member):
	cfg = AutoModConfig(mock_guild.id)
	cfg.settings["actions"]["default"] = {
		"delete": True,
		"notify": True,
		"notify_duration": 5,
		"case": "warn",
	}

	msg = MagicMock(spec=discord.Message)
	msg.id = 77777777
	msg.guild = mock_guild
	msg.channel = mock_channel
	msg.author = mock_member
	msg.content = "bad link http://scam.org"
	msg.delete = AsyncMock()

	with patch("cogs.mod.Warn.create", AsyncMock()) as mock_warn_create:
		await automod_cog.handle_violation(msg, "link", cfg)

		# Check deletion
		msg.delete.assert_called_once()

		# Check case creation
		mock_warn_create.assert_called_once()

		# Check temporary notification sent
		mock_channel.send.assert_called_once_with(content="Violation notice", delete_after=5)


async def run_cli(config_cog: Config, ctx: Any, cmdline: str) -> None:
	tokens = CLIParser.split_args(cmdline)
	node, opts = config_cog.parser.parse(tokens)
	assert node.callback is not None
	await node.callback(ctx, **opts)


@pytest.mark.asyncio
async def test_cli_automod_status(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	tokens = CLIParser.split_args("automod status")
	node, _opts = config_cog.parser.parse(tokens)
	assert node.name == "status"

	await run_cli(config_cog, ctx, "automod status")
	ctx.send.assert_called_once()
	sent_content = ctx.send.call_args[1]["content"]
	assert "Auto Moderation Configuration" in sent_content
	assert "Master Status:" in sent_content


@pytest.mark.asyncio
async def test_cli_automod_enable_disable(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	# Master disable
	await run_cli(config_cog, ctx, "automod disable")
	assert "master system disabled" in ctx.send.call_args[1]["content"]

	# Feature enable
	await run_cli(config_cog, ctx, "automod enable link")
	assert "rule `link` enabled" in ctx.send.call_args[1]["content"]


@pytest.mark.asyncio
async def test_cli_phrase_subcommands(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	# Add phrase
	await run_cli(config_cog, ctx, 'automod phrase add "free nitro" scammer')
	assert "Added 2 phrase(s)" in ctx.send.call_args[1]["content"]

	# List phrases
	await run_cli(config_cog, ctx, "automod phrase list")
	assert "free nitro" in ctx.send.call_args[1]["content"]

	# Remove phrase
	await run_cli(config_cog, ctx, "automod phrase remove scammer")
	assert "Removed 1 phrase(s)" in ctx.send.call_args[1]["content"]


@pytest.mark.asyncio
async def test_cli_link_subcommands(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	# Allow domain
	await run_cli(config_cog, ctx, "automod link allow youtube.com tenor.com")
	assert "Added to link allowlist" in ctx.send.call_args[1]["content"]

	# List allowed domains
	await run_cli(config_cog, ctx, "automod link list")
	assert "youtube.com" in ctx.send.call_args[1]["content"]


@pytest.mark.asyncio
async def test_cli_invite_subcommands(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	# Allow invite
	await run_cli(config_cog, ctx, "automod invite allow partnercode")
	assert "Added to invite allowlist" in ctx.send.call_args[1]["content"]


@pytest.mark.asyncio
async def test_cli_spam_and_limits(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	# Spam limit
	await run_cli(config_cog, ctx, "automod spam limit 7")
	assert "limit set to 7 messages" in ctx.send.call_args[1]["content"]

	# Spam window
	await run_cli(config_cog, ctx, "automod spam window 8.5")
	assert "window duration set to 8.5s" in ctx.send.call_args[1]["content"]

	# Mention limit
	await run_cli(config_cog, ctx, "automod mention limit 3")
	assert "threshold set to 3" in ctx.send.call_args[1]["content"]

	# Lines limit
	await run_cli(config_cog, ctx, "automod lines limit 20")
	assert "threshold set to 20" in ctx.send.call_args[1]["content"]


@pytest.mark.asyncio
async def test_cli_bypass_subcommands(automod_cog, mock_guild, mock_channel):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	mock_guild.channels = [mock_channel]
	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	# Add global channel bypass
	await run_cli(config_cog, ctx, "automod bypass add --channel #general")
	assert "Added bypass for global: Channel #general" in ctx.send.call_args[1]["content"]

	# Add feature role bypass
	mock_role = MagicMock(spec=discord.Role)
	mock_role.id = 998877
	mock_role.name = "VIP"
	mock_guild.roles = [mock_role]

	await run_cli(config_cog, ctx, "automod bypass add --feature link --role VIP")
	assert "Added bypass for feature `link`: Role @VIP" in ctx.send.call_args[1]["content"]

	# List bypasses
	await run_cli(config_cog, ctx, "automod bypass list")
	assert "Global Bypasses" in ctx.send.call_args[1]["content"]


@pytest.mark.asyncio
async def test_cli_action_subcommand(automod_cog, mock_guild):
	config_cog = Config(automod_cog.client)
	automod_cog.client.get_cog = MagicMock(return_value=automod_cog)
	automod_cog.client.db.fetchrow = AsyncMock(return_value=None)
	automod_cog.save_config = AsyncMock()

	ctx = MagicMock()
	ctx.bot = automod_cog.client
	ctx.guild = mock_guild
	ctx.send = AsyncMock()

	await run_cli(config_cog, ctx, "automod action --delete on --notify on --notify-duration 10 --case warn")
	sent = ctx.send.call_args[1]["content"]
	assert "delete=yes" in sent
	assert "notify=yes" in sent
	assert "notify_duration=10s" in sent
	assert "case=warn" in sent
