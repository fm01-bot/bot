from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.info import Info
from discord.ext import commands


@pytest.fixture
def cog() -> Info:
	bot = MagicMock()
	bot.db = AsyncMock()
	return Info(bot)


@pytest.fixture
def ctx() -> MagicMock:
	ctx = MagicMock()
	ctx.send = AsyncMock()
	ctx.guild = MagicMock(spec=discord.Guild)
	ctx.guild.fetch_member = AsyncMock()
	return ctx


def sent_key(ctx: MagicMock) -> str:
	return ctx.send.call_args.args[0]


async def test_user_member_shows_member_info(cog, ctx):
	member = MagicMock(spec=discord.Member)
	with patch("cogs.info.Member.from_member", return_value="m"):
		await cog.user.callback(cog, ctx, member)
	assert sent_key(ctx) == "info.user.member"


async def test_user_outside_guild_shows_user_info(cog, ctx):
	ctx.guild = None
	user = discord.User.__new__(discord.User)  # exact type check: type(user) is discord.User
	with patch("cogs.info.User.from_user", return_value="u"):
		await cog.user.callback(cog, ctx, user)
	assert sent_key(ctx) == "info.user.not_member"


async def test_user_not_in_guild_falls_back_to_user_info(cog, ctx):
	user = MagicMock(spec=discord.User)
	user.id = 5
	ctx.guild.fetch_member.side_effect = discord.NotFound(MagicMock(status=404), "unknown member")
	with patch("cogs.info.User.from_user", return_value="u"):
		await cog.user.callback(cog, ctx, user)
	assert sent_key(ctx) == "info.user.not_member"


async def test_role_defaults_to_the_authors_top_role(cog, ctx):
	ctx.author = MagicMock(spec=discord.Member)
	with patch("cogs.info.Role.from_role", return_value="r") as from_role:
		await cog.role.callback(cog, ctx, None)
	from_role.assert_called_once_with(ctx.author.top_role)
	assert sent_key(ctx) == "info.role"


async def test_role_without_a_member_author_is_a_bad_argument(cog, ctx):
	ctx.author = MagicMock(spec=discord.User)
	with pytest.raises(commands.BadArgument):
		await cog.role.callback(cog, ctx, None)


@pytest.mark.parametrize(
	("channel_type", "converter", "key"),
	[
		(discord.TextChannel, "TextChannel.from_channel", "info.channel.text"),
		(discord.VoiceChannel, "VoiceChannel.from_channel", "info.channel.voice"),
		(discord.CategoryChannel, "Category.from_category", "info.channel.category"),
		(discord.ForumChannel, "ForumChannel.from_channel", "info.channel.forum"),
		(discord.StageChannel, "StageChannel.from_channel", "info.channel.stage"),
	],
)
async def test_channel_picks_the_message_for_its_type(cog, ctx, channel_type, converter, key):
	with patch(f"cogs.info.{converter}", return_value="c"):
		await cog.channel.callback(cog, ctx, MagicMock(spec=channel_type))
	assert sent_key(ctx) == key


async def test_unicode_emoji_and_garbage(cog, ctx):
	with (
		patch("cogs.info.commands.EmojiConverter.convert", AsyncMock(side_effect=commands.BadArgument)),
		patch("cogs.info.PartialEmoji.from_emoji", return_value="e"),
	):
		await cog.emoji.callback(cog, ctx, "🍕")
		assert sent_key(ctx) == "info.emoji.unicode_emoji"

		with pytest.raises(commands.BadArgument):
			await cog.emoji.callback(cog, ctx, "notanemoji")


async def test_template_falls_back_to_a_snapshot_code(cog, ctx):
	cog.client.fetch_template = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "unknown template"))
	cog.client.db.fetchrow.return_value = {"code": "abc"}
	with patch("cogs.info.Template.from_dict", AsyncMock(return_value="t")):
		await cog.template.callback(cog, ctx, "ABCDEFG")
	cog.client.fetch_template.assert_awaited_once_with("ABCDEFG")
	cog.client.db.fetchrow.assert_awaited_once()
	assert cog.client.db.fetchrow.call_args.args[1] == "abcdefg"
	assert sent_key(ctx) == "info.template"


async def test_unknown_template_is_a_bad_argument(cog, ctx):
	cog.client.db.fetchrow.return_value = None
	with pytest.raises(commands.BadArgument):
		await cog.template.callback(cog, ctx, "!!")
	cog.client.fetch_template.assert_not_called()
