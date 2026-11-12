"""Moderation and Cases commands, with the Case module replaced by a double (it has its own database tests)."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from cogs.mod import Cases, CaseStore, CaseType, Moderation, Mute, Warn
from discord.ext import commands


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = AsyncMock()
	return bot


@pytest.fixture
def store():
	return MagicMock(spec=CaseStore)


@pytest.fixture
def mod_cog(mock_bot, store):
	return Moderation(mock_bot, store)


@pytest.fixture
def cases_cog(mock_bot, store):
	return Cases(mock_bot, store)


@pytest.fixture
def mock_ctx(mock_bot):
	ctx = MagicMock()
	ctx.guild = MagicMock()
	ctx.guild.id = 12345
	ctx.guild.unban = AsyncMock()
	ctx.author = MagicMock(spec=discord.Member)
	ctx.author.id = 999
	ctx.author.guild_permissions.moderate_members = True
	ctx.send = AsyncMock()
	ctx.bot = mock_bot
	return ctx


def make_warn(mock_bot, mock_ctx, case_id: int = 123, **kwargs) -> Warn:
	return Warn(case_id, mock_bot, mock_ctx.guild, mock_ctx.author, mock_ctx.author, **kwargs)


def make_member(timed_out: bool) -> MagicMock:
	member = MagicMock(spec=discord.Member)
	member.id = 42
	member.edit = AsyncMock()
	member.timed_out_until = datetime.datetime.now(tz=datetime.UTC) if timed_out else None
	return member


async def test_case_delete(cases_cog, store, mock_bot, mock_ctx):
	case = make_warn(mock_bot, mock_ctx)
	store.get.return_value = case

	await cases_cog.delete.callback(cases_cog, mock_ctx, "123")

	store.delete.assert_awaited_once_with(case)
	mock_ctx.send.assert_awaited_once_with("mod.delete.response", case=case)


@pytest.mark.parametrize(
	("outcome", "key"), [("deactivated", "mod.remove.response"), ("deleted", "mod.delete.response")]
)
async def test_case_remove_reports_the_retention_outcome(cases_cog, store, mock_bot, mock_ctx, outcome, key):
	case = make_warn(mock_bot, mock_ctx)
	store.get.return_value = case
	store.close.return_value = outcome

	await cases_cog.remove.callback(cases_cog, mock_ctx, "123")

	store.close.assert_awaited_once_with(case)
	mock_ctx.send.assert_awaited_once_with(key, case=case)


async def test_case_remove_unknown_case(cases_cog, store, mock_ctx):
	store.get.return_value = None

	await cases_cog.remove.callback(cases_cog, mock_ctx, "123")

	store.close.assert_not_awaited()
	mock_ctx.send.assert_awaited_once_with("mod.remove.errors.not_found", case_id=123)


async def test_case_edit_expires(cases_cog, store, mock_bot, mock_ctx):
	case = make_warn(mock_bot, mock_ctx, reason="Initial")
	store.get.return_value = case

	await cases_cog.edit.callback(cases_cog, mock_ctx, "123", "expires", new_value="1h")

	(edited,), kwargs = store.edit.await_args
	assert edited is case
	assert set(kwargs) == {"expires"}
	assert kwargs["expires"] > datetime.datetime.now(tz=datetime.UTC)
	mock_ctx.send.assert_awaited_once_with("mod.edit.response", case=case)


async def test_case_edit_rejects_invalid_time(cases_cog, store, mock_bot, mock_ctx):
	store.get.return_value = make_warn(mock_bot, mock_ctx)

	await cases_cog.edit.callback(cases_cog, mock_ctx, "123", "expires", new_value="soon")

	store.edit.assert_not_awaited()
	mock_ctx.send.assert_awaited_once_with("mod.edit.errors.invalid_time", case_id=123)


async def test_case_list_permissions(cases_cog, mock_ctx):
	mock_ctx.author.id = 111
	mock_ctx.author.guild_permissions.moderate_members = False
	target_user = MagicMock(spec=discord.Member)
	target_user.id = 222

	with pytest.raises(commands.MissingPermissions):
		await cases_cog.list.callback(cases_cog, mock_ctx, user=target_user)


@pytest.mark.parametrize(("is_moderator", "status"), [(True, "all"), (False, "active")])
async def test_case_list_default_filter(cases_cog, store, mock_ctx, is_moderator, status):
	cases_cog.custom_response.get_message = AsyncMock(
		return_value={"embeds": [discord.Embed.from_dict({"fields": [{"name": "{case.id}", "value": "x"}]})]}
	)
	store.for_user.return_value = []
	mock_ctx.author.guild_permissions.moderate_members = is_moderator

	await cases_cog.list.callback(cases_cog, mock_ctx)

	store.for_user.assert_awaited_once_with(mock_ctx.guild, mock_ctx.author, status)


async def test_case_list_paginates(cases_cog, store, mock_bot, mock_ctx):
	cases_cog.custom_response.get_message = AsyncMock(
		return_value={
			"embeds": [discord.Embed.from_dict({"fields": [{"name": "{case.id}", "value": "{case.reason}"}]})]
		}
	)
	store.for_user.return_value = [make_warn(mock_bot, mock_ctx, i, reason=f"Reason {i}") for i in range(1, 8)]

	await cases_cog.list.callback(cases_cog, mock_ctx)

	send_kwargs = mock_ctx.send.call_args.kwargs
	assert len(send_kwargs["view"].pages) == 2


async def test_unban_closes_active_bans(mod_cog, store, mock_bot, mock_ctx):
	user = MagicMock(spec=discord.User)
	ban_case = MagicMock()
	store.active.return_value = [ban_case]

	await mod_cog.unban.callback(mod_cog, mock_ctx, user)

	store.active.assert_awaited_once_with(mock_ctx.guild, user, CaseType.BAN)
	store.close.assert_awaited_once_with(ban_case)
	mock_ctx.guild.unban.assert_not_awaited()
	mock_ctx.send.assert_awaited_once_with("mod.unban.response", user=user)


async def test_unban_without_case_unbans_directly(mod_cog, store, mock_ctx):
	user = MagicMock(spec=discord.User)
	store.active.return_value = []

	await mod_cog.unban.callback(mod_cog, mock_ctx, user)

	mock_ctx.guild.unban.assert_awaited_once()


@pytest.mark.parametrize(
	("has_case", "timed_out", "key"),
	[
		(True, True, "mod.unmute.response"),
		(True, False, "mod.unmute.timeout_already_removed"),
		(False, True, "mod.unmute.no_case"),
		(False, False, "mod.unmute.errors.not_muted"),
	],
)
async def test_unmute(mod_cog, store, mock_ctx, has_case, timed_out, key):
	member = make_member(timed_out)
	mute_case = MagicMock(spec=Mute)
	store.active.return_value = [mute_case] if has_case else []

	await mod_cog.unmute.callback(mod_cog, mock_ctx, member)

	store.active.assert_awaited_once_with(mock_ctx.guild, member, CaseType.MUTE)
	if has_case:
		store.close.assert_awaited_once_with(mute_case)
	# Without a case the command lifts the timeout itself; with one, Mute.before_deletion does it.
	assert member.edit.await_count == (1 if timed_out and not has_case else 0)
	mock_ctx.send.assert_awaited_once_with(key, member=member, user=member)
