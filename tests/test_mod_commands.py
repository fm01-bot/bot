from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from cogs.mod import Case, Cases, Moderation, Warn
from discord.ext import commands


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.wait_until_ready = AsyncMock()
	bot.shard_count = 1
	bot.shard_ids = [0]
	bot.shards = {0: MagicMock()}

	custom_resp = MagicMock()
	custom_resp.get_message = AsyncMock()
	bot.custom_response = custom_resp

	return bot


@pytest.fixture
def mock_ctx(mock_bot):
	ctx = MagicMock()
	ctx.guild = MagicMock()
	ctx.guild.id = 12345
	ctx.guild.members = []
	ctx.author = MagicMock(spec=discord.Member)
	ctx.author.id = 999
	ctx.author.guild_permissions.moderate_members = True
	ctx.send = AsyncMock()
	ctx.bot = mock_bot
	return ctx


@pytest.mark.asyncio
async def test_case_delete(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)
	mod_cog = Moderation(mock_bot)
	mock_bot.get_cog.return_value = mod_cog

	# Mock Case.from_id
	fake_case = Warn(
		_id=123,
		bot=mock_bot,
		guild=mock_ctx.guild,
		user=mock_ctx.author,
		moderator=mock_ctx.author,
		reason="Rule violation",
	)
	fake_case.delete = AsyncMock()

	with (
		patch.object(Case, "from_id", AsyncMock(return_value=fake_case)),
		patch.object(Warn, "from_id", AsyncMock(return_value=fake_case)),
	):
		await cases_cog.delete.callback(cases_cog, mock_ctx, "123")

	fake_case.delete.assert_called_once_with(mock_bot.db)
	mock_ctx.send.assert_called_once_with("mod.delete.response", case=fake_case)


@pytest.mark.asyncio
async def test_case_remove_keep_retention(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)
	mod_cog = Moderation(mock_bot)
	mod_cog.manager.get_guild_retention = AsyncMock(return_value="keep")
	mock_bot.get_cog.return_value = mod_cog

	fake_case = Warn(
		_id=123,
		bot=mock_bot,
		guild=mock_ctx.guild,
		user=mock_ctx.author,
		moderator=mock_ctx.author,
		reason="Rule violation",
	)
	fake_case.deactivate = AsyncMock()
	fake_case.delete = AsyncMock()

	with (
		patch.object(Case, "from_id", AsyncMock(return_value=fake_case)),
		patch.object(Warn, "from_id", AsyncMock(return_value=fake_case)),
	):
		await cases_cog.remove.callback(cases_cog, mock_ctx, "123")

	fake_case.deactivate.assert_called_once_with(mock_bot.db)
	fake_case.delete.assert_not_called()
	mock_ctx.send.assert_called_once_with("mod.remove.response", case=fake_case)


@pytest.mark.asyncio
async def test_case_remove_delete_retention(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)
	mod_cog = Moderation(mock_bot)
	mod_cog.manager.get_guild_retention = AsyncMock(return_value="delete")
	mock_bot.get_cog.return_value = mod_cog

	fake_case = Warn(
		_id=123,
		bot=mock_bot,
		guild=mock_ctx.guild,
		user=mock_ctx.author,
		moderator=mock_ctx.author,
		reason="Rule violation",
	)
	fake_case.deactivate = AsyncMock()
	fake_case.delete = AsyncMock()

	with (
		patch.object(Case, "from_id", AsyncMock(return_value=fake_case)),
		patch.object(Warn, "from_id", AsyncMock(return_value=fake_case)),
	):
		await cases_cog.remove.callback(cases_cog, mock_ctx, "123")

	fake_case.delete.assert_called_once_with(mock_bot.db)
	fake_case.deactivate.assert_not_called()
	mock_ctx.send.assert_called_once_with("mod.delete.response", case=fake_case)


@pytest.mark.asyncio
async def test_case_edit_expires(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)
	mod_cog = Moderation(mock_bot)
	mod_cog.manager.reschedule = MagicMock()
	mock_bot.get_cog.return_value = mod_cog

	fake_case = Warn(
		_id=123,
		bot=mock_bot,
		guild=mock_ctx.guild,
		user=mock_ctx.author,
		moderator=mock_ctx.author,
		reason="Initial",
	)
	fake_case.edit = AsyncMock()

	with patch.object(Case, "from_id", AsyncMock(return_value=fake_case)):
		await cases_cog.edit.callback(cases_cog, mock_ctx, "123", "expires", new_value="1h")

	fake_case.edit.assert_called_once()
	mock_ctx.send.assert_called_once_with("mod.edit.response", case=fake_case)


@pytest.mark.asyncio
async def test_case_list_permissions(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)

	# User viewing someone else without moderate_members permission
	mock_ctx.author.id = 111
	mock_ctx.author.guild_permissions.moderate_members = False
	target_user = MagicMock(spec=discord.Member)
	target_user.id = 222

	with pytest.raises(commands.MissingPermissions):
		await cases_cog.list.callback(cases_cog, mock_ctx, user=target_user)


@pytest.mark.asyncio
async def test_case_list_default_filter(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)
	mock_response = {
		"embeds": [
			discord.Embed.from_dict(
				{
					"title": "Case list",
					"color": 6656243,
					"fields": [
						{"name": "{case.id}", "value": "{case.reason}"},
						{"name": "No cases", "value": "No cases found."},
					],
				}
			)
		]
	}
	cases_cog.custom_response.get_message = AsyncMock(return_value=mock_response)

	# 1. Moderator viewing self -> defaults to 'all'
	mock_ctx.author.id = 123
	mock_ctx.author.guild_permissions.moderate_members = True
	with patch.object(Case, "from_user", AsyncMock(return_value=[])) as mock_from_user:
		await cases_cog.list.callback(cases_cog, mock_ctx)
		mock_from_user.assert_called_once_with(
			mock_bot.db, mock_ctx.author, mock_bot, mock_ctx.guild, get_type=True, status_filter="all"
		)

	# 2. Regular user viewing self -> defaults to 'active'
	mock_ctx.author.guild_permissions.moderate_members = False
	with patch.object(Case, "from_user", AsyncMock(return_value=[])) as mock_from_user:
		await cases_cog.list.callback(cases_cog, mock_ctx)
		mock_from_user.assert_called_once_with(
			mock_bot.db, mock_ctx.author, mock_bot, mock_ctx.guild, get_type=True, status_filter="active"
		)


@pytest.mark.asyncio
async def test_case_list_pagination_components_v2(mock_bot, mock_ctx):
	cases_cog = Cases(mock_bot)
	mock_response = {
		"embeds": [
			discord.Embed.from_dict(
				{
					"title": "Case list",
					"color": 6656243,
					"fields": [
						{"name": "{case.id}", "value": "{case.reason}"},
					],
				}
			)
		]
	}
	cases_cog.custom_response.get_message = AsyncMock(return_value=mock_response)

	# 7 cases -> should create 2 pages (5 on page 1, 2 on page 2)
	fake_cases = [
		Warn(
			_id=i,
			bot=mock_bot,
			guild=mock_ctx.guild,
			user=mock_ctx.author,
			moderator=mock_ctx.author,
			reason=f"Reason {i}",
		)
		for i in range(1, 8)
	]

	with patch.object(Case, "from_user", AsyncMock(return_value=fake_cases)):
		await cases_cog.list.callback(cases_cog, mock_ctx)

	# Should send with PaginationView
	send_kwargs = mock_ctx.send.call_args.kwargs
	assert "view" in send_kwargs
	assert len(send_kwargs["view"].pages) == 2
