from __future__ import annotations

import asyncio
import datetime
import random
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from args import Giveaway as GiveawayArg
from cogs.giveaway import (
	UPSERT_COUNTS,
	Giveaway,
	GiveawayJoinButton,
	GiveawayLeaveButton,
	MessageCounter,
	Requirements,
	candidate_message_ids,
	draw_winners,
	parse_message_id,
)
from helpers.custom_response import CustomResponse
from helpers.scheduler import ExpiryScheduler

MESSAGE_ID = 1234567890123456789
NOW = datetime.datetime(2026, 11, 12, tzinfo=datetime.UTC)


def make_record(**overrides: Any) -> dict[str, Any]:
	record: dict[str, Any] = {
		"id": 7,
		"guild_id": 1 << 22,
		"channel_id": 555,
		"message_id": MESSAGE_ID,
		"host_id": 42,
		"prize": "Nitro",
		"winner_count": 1,
		"required_level": None,
		"required_role_id": None,
		"required_messages": None,
		"status": "active",
		"created_at": NOW,
		"ends_at": NOW + datetime.timedelta(days=1),
		"ended_at": None,
	}
	record.update(overrides)
	return record


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.wait_until_ready = AsyncMock()
	bot.shard_count = 1
	bot.shard_ids = [0]
	bot.shards = {0: MagicMock()}
	bot.debug = False
	return bot


class TestTargetParsing:
	def test_parse_bare_id(self):
		assert parse_message_id(str(MESSAGE_ID)) == MESSAGE_ID

	def test_parse_link(self):
		assert parse_message_id(f"https://discord.com/channels/1/2/{MESSAGE_ID}") == MESSAGE_ID

	@pytest.mark.parametrize("raw", [None, "", "2", "not an id"])
	def test_parse_invalid(self, raw):
		assert parse_message_id(raw) is None

	def test_candidates_prefer_reply_then_argument(self):
		assert candidate_message_ids(111111111111111111, str(MESSAGE_ID)) == [111111111111111111, MESSAGE_ID]

	def test_candidates_dedupe_and_skip_missing(self):
		assert candidate_message_ids(MESSAGE_ID, str(MESSAGE_ID)) == [MESSAGE_ID]
		assert candidate_message_ids(None, None) == []


class TestRequirements:
	def check(self, req: Requirements, **overrides: Any):
		kwargs: dict[str, Any] = {
			"role_ids": [1],
			"level": 5,
			"messages": 10,
			"level_enabled": True,
			"check_messages": True,
		}
		kwargs.update(overrides)
		return req.unmet(**kwargs)

	def test_no_requirements(self):
		assert self.check(Requirements()) is None

	def test_role(self):
		assert self.check(Requirements(role_id=2)) == "role"
		assert self.check(Requirements(role_id=1)) is None

	def test_level_ignored_when_leveling_disabled(self):
		assert self.check(Requirements(level=6)) == "level"
		assert self.check(Requirements(level=6), level_enabled=False) is None

	def test_messages_only_checked_when_asked(self):
		assert self.check(Requirements(messages=11)) == "messages"
		assert self.check(Requirements(messages=11), check_messages=False) is None

	def test_from_record(self):
		req = Requirements.from_record(make_record(required_level=3, required_role_id=99, required_messages=20))
		assert req == Requirements(level=3, role_id=99, messages=20)


class TestMessageCounter:
	def test_untracked_guild_is_ignored(self):
		counter = MessageCounter(cooldown=5)
		assert counter.record(1, 10, now=0) is False
		assert counter.drain() == []

	def test_cooldown_and_multiple_giveaways(self):
		counter = MessageCounter(cooldown=5)
		counter.track(1, 100)
		counter.track(1, 101)
		assert counter.record(1, 10, now=0) is True
		assert counter.record(1, 10, now=4.9) is False
		assert counter.record(1, 10, now=5) is True
		assert counter.get(100, 10) == 2
		assert sorted(counter.drain()) == [(100, 10, 2), (101, 10, 2)]
		assert counter.drain() == []

	def test_restore_after_failed_write(self):
		counter = MessageCounter(cooldown=0)
		counter.track(1, 100)
		counter.record(1, 10, now=0)
		items = counter.drain()
		counter.record(1, 10, now=1)
		counter.restore(items)
		assert counter.get(100, 10) == 2

	def test_untrack_keeps_buffered_counts(self):
		counter = MessageCounter(cooldown=0)
		counter.track(1, 100)
		counter.record(1, 10, now=0)
		counter.untrack(1, 100)
		assert counter.record(1, 10, now=1) is False
		assert counter.drain() == [(100, 10, 1)]
		assert counter.tracked == {}

	def test_prune(self):
		counter = MessageCounter(cooldown=5)
		counter.track(1, 100)
		counter.record(1, 10, now=0)
		counter.prune(now=10)
		assert counter._last_counted == {}


class TestDraw:
	async def test_skips_ineligible_and_caps_count(self):
		async def resolve(entrant: int) -> int | None:
			return entrant if entrant % 2 == 0 else None

		winners = await draw_winners(list(range(10)), 3, resolve, random.Random(1))
		assert len(winners) == 3
		assert all(w % 2 == 0 for w in winners)
		assert len(set(winners)) == 3

	async def test_fewer_eligible_than_winners(self):
		async def resolve(entrant: int) -> int | None:
			return entrant if entrant == 4 else None

		assert await draw_winners([1, 2, 3, 4], 3, resolve, random.Random(0)) == [4]


class RecordingScheduler(ExpiryScheduler[int]):
	def __init__(self, bot, pending=()):
		super().__init__(bot)
		self.pending = list(pending)
		self.processed: list[int] = []

	async def fetch_pending(self):
		return self.pending

	async def process_expired(self, key, guild_id):
		self.processed.append(key)


class TestExpiryScheduler:
	async def test_load_pending_processes_overdue_and_filters_shards(self, mock_bot):
		mock_bot.shard_count = 2
		mock_bot.shard_ids = [0]
		now = datetime.datetime.now(tz=datetime.UTC)
		scheduler = RecordingScheduler(
			mock_bot,
			[
				(1, 2 << 22, now - datetime.timedelta(seconds=5)),  # shard 0, overdue
				(2, 2 << 22, now + datetime.timedelta(hours=1)),  # shard 0, pending
				(3, 1 << 22, now - datetime.timedelta(seconds=5)),  # shard 1, not ours
			],
		)
		await scheduler.load_pending()
		assert scheduler.processed == [1]
		assert list(scheduler._scheduled_ids) == [2]

	async def test_reschedule_later_does_not_fire_early(self, mock_bot):
		scheduler = RecordingScheduler(mock_bot)
		now = datetime.datetime.now(tz=datetime.UTC)
		scheduler.schedule_at(1, 0, now + datetime.timedelta(milliseconds=50))
		scheduler.schedule_at(1, 0, now + datetime.timedelta(hours=1))
		scheduler.schedule_at(2, 0, now + datetime.timedelta(milliseconds=50))
		scheduler.start()
		try:
			await asyncio.sleep(0.3)
		finally:
			scheduler.stop()
		assert scheduler.processed == [2]

	async def test_cancel(self, mock_bot):
		scheduler = RecordingScheduler(mock_bot)
		scheduler.schedule_at(1, 0, datetime.datetime.now(tz=datetime.UTC))
		scheduler.cancel(1)
		scheduler.start()
		try:
			await asyncio.sleep(0.1)
		finally:
			scheduler.stop()
		assert scheduler.processed == []


def make_ctx(reference_id: int | None = None, *, interaction: bool = False):
	ctx = MagicMock()
	ctx.channel.id = 555
	ctx.interaction = MagicMock() if interaction else None
	ctx.message.reference = SimpleNamespace(message_id=reference_id) if reference_id else None
	return ctx


class TestResolveTarget:
	async def test_reply_wins(self, mock_bot):
		cog = Giveaway(mock_bot)
		record = make_record()
		mock_bot.db.fetchrow.side_effect = [record]
		assert await cog.resolve_target(make_ctx(MESSAGE_ID), None, "active") is record
		args = mock_bot.db.fetchrow.call_args.args
		assert args[1:] == (555, MESSAGE_ID, "active")

	async def test_invalid_reply_falls_back_to_argument_then_latest(self, mock_bot):
		cog = Giveaway(mock_bot)
		latest = make_record(id=9)
		mock_bot.db.fetchrow.side_effect = [None, None, latest]
		result = await cog.resolve_target(make_ctx(111111111111111111), str(MESSAGE_ID), "ended")
		assert result is latest
		calls = mock_bot.db.fetchrow.call_args_list
		assert [c.args[2] for c in calls[:2]] == [111111111111111111, MESSAGE_ID]
		assert "ORDER BY created_at DESC" in calls[2].args[0]
		assert calls[2].args[1:] == (555, "ended")

	async def test_slash_commands_ignore_reference(self, mock_bot):
		cog = Giveaway(mock_bot)
		mock_bot.db.fetchrow.side_effect = [None]
		await cog.resolve_target(make_ctx(MESSAGE_ID, interaction=True), None, "active")
		assert mock_bot.db.fetchrow.call_count == 1
		assert "ORDER BY" in mock_bot.db.fetchrow.call_args.args[0]


class TestLifecycle:
	async def test_flush_writes_one_batch(self, mock_bot):
		cog = Giveaway(mock_bot)
		cog.counter.track(1, 100)
		cog.counter.record(1, 10, now=0)
		await cog.flush_counts()
		mock_bot.db.executemany.assert_awaited_once_with(UPSERT_COUNTS, [(100, 10, 1)])

	async def test_flush_restores_on_failure(self, mock_bot):
		cog = Giveaway(mock_bot)
		mock_bot.db.executemany.side_effect = RuntimeError("db down")
		cog.counter.track(1, 100)
		cog.counter.record(1, 10, now=0)
		await cog.flush_counts()
		assert cog.counter.get(100, 10) == 1

	async def test_finish_is_noop_when_not_active(self, mock_bot):
		cog = Giveaway(mock_bot)
		mock_bot.db.fetchrow.return_value = None
		cog._draw = AsyncMock()
		assert await cog.finish(7) is None
		cog._draw.assert_not_awaited()

	async def test_finish_skips_draw_when_message_is_gone(self, mock_bot):
		cog = Giveaway(mock_bot)
		record = make_record(status="ended")
		mock_bot.db.fetchrow.return_value = record
		cog.counter.track(record["guild_id"], 7)
		cog._fetch_message = AsyncMock(return_value=None)
		cog._draw = AsyncMock()
		assert await cog.finish(7) is record
		cog._draw.assert_not_awaited()
		assert cog.counter.tracked == {}

	async def test_finish_draws_edits_and_announces(self, mock_bot):
		cog = Giveaway(mock_bot)
		record = make_record(status="ended")
		mock_bot.db.fetchrow.return_value = record
		message = MagicMock()
		winner = MagicMock()
		cog._fetch_message = AsyncMock(return_value=message)
		cog._draw = AsyncMock(return_value=[winner])
		cog._edit_layout = AsyncMock()
		cog._announce = AsyncMock()
		await cog.finish(7)
		cog._draw.assert_awaited_once()
		cog._edit_layout.assert_awaited_once_with(message, record, mock_bot.get_guild.return_value, [winner])
		cog._announce.assert_awaited_once()
		assert cog._announce.call_args.args[-1] == "end"


class TestLocalization:
	@pytest.mark.parametrize("status", ["active", "ended", "cancelled"])
	async def test_layout_button_matches_dynamic_item(self, mock_bot, status):
		cr = CustomResponse(mock_bot)
		payload = await cr.get_message(
			f"giveaway.layout.{status}",
			"en",
			giveaway=GiveawayArg.from_record(make_record(), entries=3),
			author=SimpleNamespace(mention="<@42>"),
			requirements="",
			winners="<@1>",
		)
		view = payload["view"]
		assert isinstance(view, discord.ui.LayoutView)
		buttons = [item for item in view.walk_children() if isinstance(item, discord.ui.Button)]
		assert len(buttons) == 1
		assert GiveawayJoinButton.__discord_ui_compiled_template__.fullmatch(buttons[0].custom_id or "")
		assert buttons[0].label == "🎉 3"
		assert buttons[0].disabled is (status != "active")
		assert payload["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()

	async def test_leave_prompt_button_matches_dynamic_item(self, mock_bot):
		cr = CustomResponse(mock_bot)
		payload = await cr.get_message(
			"giveaway.message.already_joined", "en", giveaway=GiveawayArg.from_record(make_record())
		)
		buttons = [item for item in payload["view"].walk_children() if isinstance(item, discord.ui.Button)]
		assert GiveawayLeaveButton.__discord_ui_compiled_template__.fullmatch(buttons[0].custom_id or "")
		assert not GiveawayJoinButton.__discord_ui_compiled_template__.fullmatch(buttons[0].custom_id or "")


class TestButtonRouting:
	async def test_join_button_reaches_cog(self, mock_bot):
		from core import Bot

		cog = Giveaway(mock_bot)
		cog.handle_join = AsyncMock()
		interaction = MagicMock()
		interaction.client = MagicMock(spec=Bot)
		interaction.client.get_cog.return_value = cog
		await GiveawayJoinButton(7).callback(interaction)
		cog.handle_join.assert_awaited_once_with(interaction, 7)

	async def test_leave_button_reaches_cog(self, mock_bot):
		from core import Bot

		cog = Giveaway(mock_bot)
		cog.handle_leave = AsyncMock()
		interaction = MagicMock()
		interaction.client = MagicMock(spec=Bot)
		interaction.client.get_cog.return_value = cog
		await GiveawayLeaveButton(7).callback(interaction)
		cog.handle_leave.assert_awaited_once_with(interaction, 7)
