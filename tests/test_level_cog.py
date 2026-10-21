from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.level import Level
from helpers.leveling import GuildLevelConfig, LevelupMessage


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = MagicMock()
	bot.db.execute = AsyncMock()
	bot.db.fetch = AsyncMock(return_value=[])
	bot.db.fetchrow = AsyncMock(return_value=None)
	bot.custom_response = MagicMock()
	bot.custom_response.get_message = AsyncMock(
		return_value={
			"embeds": [
				discord.Embed(title="Level Leaderboard", description="Top members").add_field(
					name="#{number} {user}", value="Level: **{level}** | XP: `{xp}`"
				)
			]
		}
	)
	bot.custom_response.convert_embeds = MagicMock(side_effect=lambda x: x)
	return bot


@pytest.fixture
def level_cog(mock_bot):
	return Level(mock_bot)


@pytest.mark.asyncio
async def test_on_message_xp_ignores_bots(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = True
	await level_cog.on_message_xp(msg)
	assert not level_cog.client.db.fetchrow.called


@pytest.mark.asyncio
async def test_on_message_xp_ignores_dms(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild = None
	await level_cog.on_message_xp(msg)
	assert not level_cog.client.db.fetchrow.called


@pytest.mark.asyncio
async def test_on_message_xp_disabled_guild(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild.id = 999
	msg.author = MagicMock(spec=discord.Member)
	msg.author.roles = []

	level_cog.guild_configs[999] = GuildLevelConfig(guild_id=999, is_on=False)
	await level_cog.on_message_xp(msg)
	assert not level_cog.client.db.fetchrow.called


@pytest.mark.asyncio
async def test_on_message_xp_ignored_channel(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild.id = 999
	msg.channel.id = 444
	msg.author = MagicMock(spec=discord.Member)
	msg.author.roles = []

	level_cog.guild_configs[999] = GuildLevelConfig(guild_id=999, is_on=True)
	level_cog.channel_overrides[(999, 444)] = (1.0, True)  # Ignored

	await level_cog.on_message_xp(msg)
	assert not level_cog.client.db.fetchrow.called


@pytest.mark.asyncio
async def test_on_message_xp_ignored_role(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.author.bot = False
	msg.guild.id = 999
	msg.channel.id = 444

	role = MagicMock(spec=discord.Role)
	role.id = 777
	msg.author = MagicMock(spec=discord.Member)
	msg.author.roles = [role]

	level_cog.guild_configs[999] = GuildLevelConfig(guild_id=999, is_on=True)
	level_cog.role_overrides[(999, 777)] = (1.0, True)  # Ignored

	await level_cog.on_message_xp(msg)
	assert not level_cog.client.db.fetchrow.called


@pytest.mark.asyncio
async def test_on_message_xp_cooldown(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.guild.id = 999
	msg.channel.id = 444
	msg.author = MagicMock(spec=discord.Member)
	msg.author.bot = False
	msg.author.id = 111
	msg.author.roles = []

	level_cog.guild_configs[999] = GuildLevelConfig(guild_id=999, is_on=True, cooldown=60)
	level_cog.channel_overrides[(999, 444)] = (1.0, False)
	level_cog.role_overrides[(999, 111)] = (1.0, False)
	level_cog.client.db.fetchrow.return_value = {"xp": 20, "level": 0}

	# 1st message -> awards XP
	await level_cog.on_message_xp(msg)
	assert level_cog.client.db.fetchrow.called

	# 2nd message immediately after -> cooldown blocks it
	level_cog.client.db.fetchrow.reset_mock()
	await level_cog.on_message_xp(msg)
	assert not level_cog.client.db.fetchrow.called


@pytest.mark.asyncio
async def test_on_message_xp_levelup_and_rewards(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.guild.id = 999
	msg.channel.id = 444
	msg.author = MagicMock(spec=discord.Member)
	msg.author.bot = False
	msg.author.id = 111
	msg.author.guild = msg.guild
	msg.author.roles = []
	msg.author.mention = "<@111>"
	msg.author.name = "Tester"
	msg.author.display_name = "Tester"
	msg.channel.send = AsyncMock()

	# User gains enough XP to go from level 0 (0 XP) to level 1 (100 XP)
	level_cog.guild_configs[999] = GuildLevelConfig(
		guild_id=999,
		is_on=True,
		cooldown=0,
		min_xp=100,
		max_xp=100,
		message_mode=LevelupMessage.CURRENT,
		levelup_message="GG {user}, you reached level {level}!",
	)
	level_cog.channel_overrides[(999, 444)] = (1.0, False)

	# Mock user_levels insert returning 100 XP, old level 0
	level_cog.client.db.fetchrow.return_value = {"xp": 100, "level": 0}

	# Mock role reward at level 1
	reward_role = MagicMock(spec=discord.Role)
	reward_role.id = 888
	reward_role.name = "Novice"
	msg.guild.get_role.return_value = reward_role
	level_cog.role_rewards[999] = [(1, 888)]

	await level_cog.on_message_xp(msg)

	# Verify level was updated in DB
	level_cog.client.db.execute.assert_any_call(
		"UPDATE user_levels SET level = $1 WHERE guild_id = $2 AND user_id = $3", 1, 999, 111
	)

	# Verify role was granted
	msg.author.add_roles.assert_called_once_with(reward_role, reason="Level 1 reward")

	# Verify notification sent to current channel
	msg.channel.send.assert_called_once_with("GG <@111>, you reached level 1!")


@pytest.mark.asyncio
async def test_on_message_xp_levelup_localized_default(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.guild.id = 999
	msg.channel.id = 444
	msg.author = MagicMock(spec=discord.Member)
	msg.author.bot = False
	msg.author.id = 111
	msg.author.guild = msg.guild
	msg.author.roles = []
	msg.channel.send = AsyncMock()

	# Config with levelup_message=None
	level_cog.guild_configs[999] = GuildLevelConfig(
		guild_id=999,
		is_on=True,
		cooldown=0,
		min_xp=100,
		max_xp=100,
		message_mode=LevelupMessage.CURRENT,
		levelup_message=None,
	)
	level_cog.channel_overrides[(999, 444)] = (1.0, False)
	level_cog.client.db.fetchrow.return_value = {"xp": 100, "level": 0}
	level_cog.client.custom_response.get_message.return_value = "Localized GG!"

	await level_cog.on_message_xp(msg)

	level_cog.client.custom_response.get_message.assert_called_once()
	msg.channel.send.assert_called_once_with("Localized GG!")


@pytest.mark.asyncio
async def test_on_message_xp_levelup_dict_payload_with_reply(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.guild.id = 999
	msg.channel.id = 444
	msg.author = MagicMock(spec=discord.Member)
	msg.author.bot = False
	msg.author.id = 111
	msg.author.guild = msg.guild
	msg.author.roles = []
	msg.channel.send = AsyncMock()

	level_cog.guild_configs[999] = GuildLevelConfig(
		guild_id=999,
		is_on=True,
		cooldown=0,
		min_xp=100,
		max_xp=100,
		message_mode=LevelupMessage.CURRENT,
		levelup_message=None,
	)
	level_cog.channel_overrides[(999, 444)] = (1.0, False)
	level_cog.client.db.fetchrow.return_value = {"xp": 100, "level": 0}

	embed = MagicMock(spec=discord.Embed)
	mentions = discord.AllowedMentions(users=True)
	payload = {"content": "GG <@111>!", "embeds": [embed], "allowed_mentions": mentions, "reference": msg}
	level_cog.client.custom_response.get_message.return_value = payload

	await level_cog.on_message_xp(msg)

	msg.channel.send.assert_called_once_with(
		content="GG <@111>!", embeds=[embed], allowed_mentions=mentions, reference=msg
	)


@pytest.mark.asyncio
async def test_on_message_xp_levelup_dict_payload_separate_channel_strips_reference(level_cog):
	msg = MagicMock(spec=discord.Message)
	msg.guild.id = 999
	msg.channel.id = 444
	msg.author = MagicMock(spec=discord.Member)
	msg.author.bot = False
	msg.author.id = 111
	msg.author.guild = msg.guild
	msg.author.roles = []

	target_ch = MagicMock(spec=discord.TextChannel)
	target_ch.id = 555
	target_ch.send = AsyncMock()
	msg.guild.get_channel.return_value = target_ch

	level_cog.guild_configs[999] = GuildLevelConfig(
		guild_id=999,
		is_on=True,
		cooldown=0,
		min_xp=100,
		max_xp=100,
		message_mode=LevelupMessage.CHANNEL,
		message_channel=555,
		levelup_message=None,
	)
	level_cog.channel_overrides[(999, 444)] = (1.0, False)
	level_cog.client.db.fetchrow.return_value = {"xp": 100, "level": 0}

	embed = MagicMock(spec=discord.Embed)
	mentions = discord.AllowedMentions(users=True)
	payload = {"content": "GG <@111>!", "embeds": [embed], "allowed_mentions": mentions, "reference": msg}
	level_cog.client.custom_response.get_message.return_value = payload

	await level_cog.on_message_xp(msg)

	target_ch.send.assert_called_once_with(content="GG <@111>!", embeds=[embed], allowed_mentions=mentions)


@pytest.mark.asyncio
async def test_level_command_sends_card(level_cog):
	ctx = MagicMock()
	ctx.guild.id = 999
	ctx.guild.preferred_locale = "en"
	ctx.author = MagicMock(spec=discord.Member)
	ctx.author.id = 111
	ctx.send = AsyncMock()

	level_cog.client.db.fetchrow.side_effect = [
		{"xp": 120, "level": 1},  # user_levels row
		{"rank": 3},  # rank query
	]

	# Mock create_level_card to return a buffer
	fake_buf = io.BytesIO(b"fake_image_bytes")
	with patch("cogs.level.create_level_card", AsyncMock(return_value=fake_buf)):
		await level_cog.level_command.callback(level_cog, ctx)

	assert ctx.send.called
	call_kwargs = ctx.send.call_args[1]
	assert "file" in call_kwargs
	assert isinstance(call_kwargs["file"], discord.File)


@pytest.mark.asyncio
async def test_levels_command_leaderboard(level_cog):
	ctx = MagicMock()
	ctx.guild.id = 999
	ctx.send = AsyncMock()

	# Mock total count and rows
	level_cog.client.db.fetchrow.return_value = {"count": 2}
	level_cog.client.db.fetch.return_value = [
		{"user_id": 111, "xp": 1000, "level": 4},
		{"user_id": 222, "xp": 500, "level": 3},
	]

	u1 = MagicMock(spec=discord.User)
	u1.name = "Alice"
	u1.id = 111
	u1.bot = False
	u1.mention = "<@111>"
	u1.global_name = "Alice"
	u1.display_name = "Alice"
	u1.discriminator = "0"
	u1.created_at = discord.utils.utcnow()
	u1.accent_color = None
	u1.avatar_decoration = None
	u1.banner = None
	u1.display_avatar.url = "http://example.com/avatar.png"
	level_cog.client.get_user.side_effect = lambda uid: u1 if uid == 111 else None

	await level_cog.levels_command.callback(level_cog, ctx, page=1)

	assert ctx.send.called
	call_kwargs = ctx.send.call_args[1]
	embeds = call_kwargs.get("embeds")
	assert embeds is not None and len(embeds) == 1
	assert "Level Leaderboard" in embeds[0].title
	assert len(embeds[0].fields) == 2


@pytest.mark.asyncio
async def test_levels_command_empty_leaderboard(level_cog):
	ctx = MagicMock()
	ctx.guild.id = 999
	ctx.send = AsyncMock()

	level_cog.client.db.fetchrow.return_value = {"count": 0}
	level_cog.client.db.fetch.return_value = []

	embed = discord.Embed(title="Level Leaderboard")
	embed.add_field(name="#{number} {user}", value="Level: {level}")
	embed.add_field(name="Psst...", value="No one has earned any XP (yet).")
	level_cog.client.custom_response.get_message.return_value = {"embeds": [embed]}

	await level_cog.levels_command.callback(level_cog, ctx, page=1)

	assert ctx.send.called
	call_kwargs = ctx.send.call_args[1]
	embeds = call_kwargs.get("embeds")
	assert len(embeds[0].fields) == 1
	assert embeds[0].fields[0].name == "Psst..."
	assert "Page 1/1" in embeds[0].footer.text


@pytest.mark.asyncio
async def test_role_overrides_caching_and_invalidation(level_cog):
	guild_id = 999
	level_cog.client.db.fetch.return_value = [{"role_id": 123, "multiplier": 1.5, "is_ignored": False}]

	# First call -> fetches from DB
	res1 = await level_cog.get_role_overrides(guild_id)
	assert res1 == {123: (1.5, False)}
	assert level_cog.client.db.fetch.call_count == 1

	# Second call -> uses in-memory cache
	res2 = await level_cog.get_role_overrides(guild_id)
	assert res2 == {123: (1.5, False)}
	assert level_cog.client.db.fetch.call_count == 1

	# Invalidate cache
	level_cog.invalidate_cache(guild_id)
	res3 = await level_cog.get_role_overrides(guild_id)
	assert res3 == {123: (1.5, False)}
	assert level_cog.client.db.fetch.call_count == 2
