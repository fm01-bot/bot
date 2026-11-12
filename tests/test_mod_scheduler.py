from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from cogs.mod import CaseExpirationManager


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.wait_until_ready = AsyncMock()
	bot.shard_count = 10
	bot.shard_ids = [0, 1, 2, 3, 4]  # Shards 0-4
	bot.shards = {i: MagicMock() for i in range(5)}
	return bot


def test_shard_filtering(mock_bot):
	manager = CaseExpirationManager(mock_bot, MagicMock())

	# Discord snowflake formula: (guild_id >> 22) % total_shards
	assert manager.is_guild_on_shard(1 << 22) is True  # shard 1
	assert manager.is_guild_on_shard(7 << 22) is False  # shard 7

	# Standalone mode fallback (shard_ids is None)
	mock_bot.shard_ids = None
	mock_bot.shards = {7: MagicMock()}
	assert manager.is_guild_on_shard(7 << 22) is True


async def test_load_pending_expires_overdue_and_queues_future_cases(mock_bot):
	now = datetime.datetime.now(tz=datetime.UTC)
	store = MagicMock()
	store.pending = AsyncMock(
		return_value=[
			(9999, 1 << 22, now - datetime.timedelta(seconds=60)),
			(1000, 1 << 22, now + datetime.timedelta(hours=1)),
			(2000, 7 << 22, now - datetime.timedelta(seconds=60)),  # another shard's guild
		]
	)
	store.expire = AsyncMock()
	manager = CaseExpirationManager(mock_bot, store)

	await manager.load_pending()

	store.expire.assert_awaited_once_with(9999)
	assert 1000 in manager._scheduled_ids
	assert 2000 not in manager._scheduled_ids
