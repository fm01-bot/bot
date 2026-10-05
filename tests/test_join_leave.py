from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from cogs.join_leave import JoinLeave


def create_mock_member(
	guild_id: int = 12345,
	guild_name: str = "Test Server",
	member_count: int = 42,
	member_id: int = 99999,
	name: str = "alice",
	discriminator: str = "0",
	display_name: str = "Alice In Wonderland",
	mention: str = "<@99999>",
) -> MagicMock:
	guild = MagicMock(spec=discord.Guild)
	guild.id = guild_id
	guild.name = guild_name
	guild.member_count = member_count
	guild.icon = None
	guild.banner = None
	guild.splash = None
	guild.discovery_splash = None
	guild.description = "Test Description"
	guild.owner = None
	guild.premium_subscription_count = 3
	guild.created_at = None
	guild.verification_level = discord.VerificationLevel.none
	guild.default_notifications = discord.NotificationLevel.all_messages
	guild.explicit_content_filter = discord.ContentFilter.disabled
	guild.mfa_level = discord.MFALevel.disabled
	guild.system_channel = None
	guild.rules_channel = None
	guild.public_updates_channel = None
	guild.preferred_locale = discord.Locale.american_english
	guild.afk_channel = None
	guild.afk_timeout = 300
	guild.vanity_url = None
	guild.premium_tier = 1
	guild.premium_subscribers = []
	guild.premium_subscriber_role = None
	guild.nsfw_level = discord.NSFWLevel.default
	guild.channels = []
	guild.voice_channels = []
	guild.stage_channels = []
	guild.text_channels = []
	guild.categories = []
	guild.forums = []
	guild.threads = []
	guild.roles = []
	guild.emojis = ()
	guild.emoji_limit = 50
	guild.stickers = ()
	guild.sticker_limit = 15
	guild.bitrate_limit = 96000.0
	guild.filesize_limit = 8388608
	guild.scheduled_events = []
	guild.shard_id = 0

	member = MagicMock(spec=discord.Member)
	member.guild = guild
	member.id = member_id
	member.name = name
	member.discriminator = discriminator
	member.global_name = name
	member.display_name = display_name
	member.nick = None
	member.bot = False
	member.color = discord.Color.default()
	member.accent_color = None
	member.display_avatar.url = "https://cdn.discordapp.com/avatars/99999/avatar.png"
	member.avatar_decoration = None
	member.banner = None
	member.created_at = None
	member.joined_at = None
	member.roles = []
	member.mention = mention
	return member


def test_format_message_with_args_attributes():
	cog = JoinLeave(MagicMock())
	member = create_mock_member()

	# Template using args/ dataclass fields
	template = "Welcome {user.name} ({user.mention}) to {guild.name}! Member #{guild.members}"
	result = cog.format_message(template, member)
	assert result == "Welcome alice (<@99999>) to Test Server! Member #42"


def test_format_message_with_member_and_user_objects():
	cog = JoinLeave(MagicMock())
	member = create_mock_member()

	# {user} or {member} string representation
	template = "Hello {user}! You joined {guild}."
	result = cog.format_message(template, member)
	assert "Hello Alice In Wonderland! You joined Test Server." in result


def test_format_message_legacy_placeholders():
	cog = JoinLeave(MagicMock())
	member = create_mock_member()

	template = "Goodbye {username}, server now has {member_count} members."
	result = cog.format_message(template, member)
	assert result == "Goodbye alice, server now has 42 members."


def test_format_message_malformed_template_fallback():
	cog = JoinLeave(MagicMock())
	member = create_mock_member()

	# Unclosed brace should gracefully return the template without raising an unhandled exception
	template = "Welcome {user.name to the server!"
	result = cog.format_message(template, member)
	assert result == template


def test_format_message_with_channel_and_server_and_extra_kwargs():
	cog = JoinLeave(MagicMock())
	member = create_mock_member()

	channel = MagicMock(spec=discord.TextChannel)
	channel.name = "general"
	channel.mention = "<#112233>"
	channel.guild = member.guild
	channel.id = 112233
	channel.topic = "General Chat"
	channel.position = 0
	channel.slowmode_delay = 0
	channel.nsfw = False
	channel.default_auto_archive_duration = 60
	channel.default_thread_slowmode_delay = 0
	channel.members = [member]
	channel.threads = []
	channel.is_news.return_value = False
	channel.category = None
	channel.created_at = None
	channel.jump_url = "https://discord.com/channels/12345/112233"
	channel.overwrites = {}

	template = "Welcome {user} to {server.name} in {channel.name} ({channel.mention})!"
	result = cog.format_message(template, member, channel=channel)
	assert result == "Welcome Alice In Wonderland to Test Server in general (<#112233>)!"


@pytest.mark.asyncio
async def test_on_member_join_listener():
	bot = MagicMock()
	bot.db = AsyncMock()
	cog = JoinLeave(bot)

	member = create_mock_member()
	channel = MagicMock(spec=discord.TextChannel)
	channel.send = AsyncMock()
	member.guild.get_channel.return_value = channel

	bot.db.fetchrow.return_value = {
		"guild_id": member.guild.id,
		"is_on": True,
		"channel": 123456,
		"message": "Welcome {user.mention} to {guild.name}!",
	}

	await cog.on_member_join(member)
	channel.send.assert_called_once_with("Welcome <@99999> to Test Server!")


@pytest.mark.asyncio
async def test_on_member_join_disabled_or_no_message():
	bot = MagicMock()
	bot.db = AsyncMock()
	cog = JoinLeave(bot)

	member = create_mock_member()
	channel = MagicMock(spec=discord.TextChannel)
	channel.send = AsyncMock()
	member.guild.get_channel.return_value = channel

	# is_on is False
	bot.db.fetchrow.return_value = {
		"guild_id": member.guild.id,
		"is_on": False,
		"channel": 123456,
		"message": "Welcome {user.mention}!",
	}

	await cog.on_member_join(member)
	channel.send.assert_not_called()

	# bot user ignored
	member.bot = True
	bot.db.fetchrow.return_value = {
		"guild_id": member.guild.id,
		"is_on": True,
		"channel": 123456,
		"message": "Welcome {user.mention}!",
	}
	await cog.on_member_join(member)
	channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_member_remove_listener():
	bot = MagicMock()
	bot.db = AsyncMock()
	cog = JoinLeave(bot)

	member = create_mock_member()
	channel = MagicMock(spec=discord.TextChannel)
	channel.send = AsyncMock()
	member.guild.get_channel.return_value = channel

	bot.db.fetchrow.return_value = {
		"guild_id": member.guild.id,
		"is_on": True,
		"channel": 654321,
		"message": "Goodbye {user.name} from {guild.name}!",
	}

	await cog.on_member_remove(member)
	channel.send.assert_called_once_with("Goodbye alice from Test Server!")
