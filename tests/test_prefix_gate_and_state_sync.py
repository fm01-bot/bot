from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.state_sync import StateSync
from core.bot import Bot
from core.clustering import InMemoryStateStore
from core.config import Config


@pytest.fixture
def mock_bot():
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
	with patch("core.bot.update_slash_localizations"):
		bot = Bot(config=cfg)
	bot.process_commands = AsyncMock()
	bot.message_buffer = MagicMock()
	mock_user = MagicMock(spec=discord.ClientUser)
	mock_user.id = 999999
	bot._connection.user = mock_user
	return bot


@pytest.mark.asyncio
async def test_fast_path_prefix_gate_ignores_bots(mock_bot):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = True
	msg.guild = MagicMock()
	msg.content = "?!help"

	await mock_bot.on_message(msg)
	mock_bot.process_commands.assert_not_called()
	mock_bot.message_buffer.enqueue_message.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_prefix_gate_drops_normal_chat(mock_bot):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild = MagicMock()
	msg.guild.id = 123
	msg.content = "hello everyone how are you doing today"

	mock_bot.prefix_cache[123] = ("?!", True)

	await mock_bot.on_message(msg)
	mock_bot.process_commands.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_prefix_gate_processes_commands(mock_bot):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild = MagicMock()
	msg.guild.id = 123
	msg.content = "?!ping"

	mock_bot.prefix_cache[123] = ("?!", True)

	await mock_bot.on_message(msg)
	mock_bot.process_commands.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_fast_path_prefix_gate_enqueues_logging_guild(mock_bot):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild = MagicMock()
	msg.guild.id = 123
	msg.content = "chat message to be logged"

	mock_bot.prefix_cache[123] = ("?!", True)
	mock_bot.message_logging_guilds.add(123)

	await mock_bot.on_message(msg)
	mock_bot.message_buffer.enqueue_message.assert_called_once_with(msg)
	mock_bot.process_commands.assert_not_called()


@pytest.mark.asyncio
async def test_state_sync_cog_syncs_guild():
	bot = MagicMock()
	bot.state_store = InMemoryStateStore()

	cog = StateSync(bot)

	mock_guild = MagicMock(spec=discord.Guild)
	mock_guild.id = 8888
	mock_guild.name = "Sync Guild"
	mock_guild.icon = None
	mock_guild.owner_id = 1111
	mock_guild.member_count = 100
	mock_guild.shard_id = 0

	mock_channel = MagicMock(spec=discord.TextChannel)
	mock_channel.id = 777
	mock_channel.name = "general"
	mock_channel.type = discord.ChannelType.text
	mock_channel.position = 0
	mock_channel.category_id = None
	mock_channel.guild = mock_guild
	mock_guild.channels = [mock_channel]

	mock_role = MagicMock(spec=discord.Role)
	mock_role.id = 555
	mock_role.name = "Member"
	mock_role.color.value = 0x00FF00
	mock_role.position = 1
	mock_role.permissions.value = 1024
	mock_role.managed = False
	mock_role.mentionable = True
	mock_role.guild = mock_guild
	mock_guild.roles = [mock_role]

	await cog._sync_guild(mock_guild)

	guild_data = await bot.state_store.get_guild(8888)
	assert guild_data is not None
	assert guild_data["name"] == "Sync Guild"

	channels_data = await bot.state_store.get_channels(8888)
	assert channels_data is not None
	assert len(channels_data) == 1
	assert channels_data[0]["name"] == "general"

	roles_data = await bot.state_store.get_roles(8888)
	assert roles_data is not None
	assert len(roles_data) == 1
	assert roles_data[0]["name"] == "Member"

	assert await bot.state_store.is_bot_guild(8888) is True
