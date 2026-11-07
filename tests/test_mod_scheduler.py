from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from cogs.mod import CaseExpirationManager, CaseType, Warn


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.db = AsyncMock()
	bot.wait_until_ready = AsyncMock()
	bot.shard_count = 10
	bot.shard_ids = [0, 1, 2, 3, 4]  # Shards 0-4
	bot.shards = {i: MagicMock() for i in range(5)}
	bot.get_cog = MagicMock(return_value=None)
	return bot


def test_shard_filtering(mock_bot):
	manager = CaseExpirationManager(mock_bot)

	# Discord snowflake formula: (guild_id >> 22) % total_shards
	# If shard_count = 10:
	# Guild 1: (1 << 22) has shard_id = 1 % 10 = 1 (on shards 0-4 -> True)
	guild_id_1 = 1 << 22
	assert manager.is_guild_on_shard(guild_id_1) is True

	# Guild 2: (7 << 22) has shard_id = 7 % 10 = 7 (on shards 5-9 -> False)
	guild_id_2 = 7 << 22
	assert manager.is_guild_on_shard(guild_id_2) is False

	# Standalone mode fallback (shard_ids is None)
	mock_bot.shard_ids = None
	mock_bot.shards = {7: MagicMock()}
	assert manager.is_guild_on_shard(guild_id_2) is True


def test_schedule_and_reschedule(mock_bot):
	manager = CaseExpirationManager(mock_bot)

	# Create a case for shard 1
	guild = MagicMock()
	guild.id = 1 << 22
	user = MagicMock()
	user.id = 123
	mod = MagicMock()
	mod.id = 456

	future_exp = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=60)
	case = Warn(
		_id=1001,
		bot=mock_bot,
		guild=guild,
		user=user,
		moderator=mod,
		expires=future_exp,
	)

	manager.schedule(case)
	assert len(manager._queue) == 1
	assert 1001 in manager._scheduled_ids
	assert manager._wake_event.is_set()

	# Reschedule case
	manager._wake_event.clear()
	new_exp = future_exp + datetime.timedelta(seconds=120)
	manager.reschedule(1001, guild.id, new_exp)
	assert 1001 in manager._scheduled_ids
	assert manager._wake_event.is_set()

	# Cancel case
	manager.cancel(1001)
	assert 1001 not in manager._scheduled_ids


@pytest.mark.asyncio
async def test_load_pending_processes_overdue(mock_bot):
	manager = CaseExpirationManager(mock_bot)
	past_time = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(seconds=60)

	overdue_guild_id = 1 << 22
	# Row representing an overdue case
	mock_bot.db.fetch.return_value = [
		{
			"id": 1,
			"type": CaseType.WARN.value,
			"guild_id": overdue_guild_id,
			"case_id": 9999,
			"user_id": 123,
			"moderator_id": 456,
			"reason": "Test",
			"expires": past_time,
			"message": None,
			"active": True,
		}
	]

	# Mock fetchrow for processing
	mock_guild = MagicMock()
	mock_guild.id = overdue_guild_id
	mock_bot.get_guild.return_value = mock_guild

	manager._process_expiration = AsyncMock()
	await manager.load_pending()

	# Overdue case should be processed immediately
	manager._process_expiration.assert_called_once_with(9999, overdue_guild_id)


@pytest.mark.asyncio
async def test_process_expiration_retention_modes(mock_bot):
	manager = CaseExpirationManager(mock_bot)
	guild_id = 1 << 22
	case_id = 5555

	mock_guild = MagicMock()
	mock_guild.id = guild_id
	mock_member = MagicMock()
	mock_member.timed_out_until = datetime.datetime.now(tz=datetime.UTC)
	mock_member.edit = AsyncMock()
	mock_guild.get_member.return_value = mock_member
	mock_bot.get_guild.return_value = mock_guild
	mock_user = MagicMock()
	mock_user.id = 123
	mock_user.send = AsyncMock()
	mock_bot.get_user.return_value = mock_user

	# Mock CustomResponse to avoid KeyError or real network calls
	mock_cr = MagicMock()
	mock_cr.get_message = AsyncMock(return_value="Unmuted")
	mock_bot.custom_response = mock_cr

	row_data = {
		"id": 1,
		"type": CaseType.MUTE.value,
		"guild_id": guild_id,
		"case_id": case_id,
		"user_id": 123,
		"moderator_id": 456,
		"reason": "Muted",
		"expires": datetime.datetime.now(tz=datetime.UTC),
		"message": None,
		"active": True,
	}
	mock_bot.db.fetchrow.return_value = row_data

	# 1. Test "keep" retention mode (default)
	manager.set_guild_retention(guild_id, "keep")
	await manager._process_expiration(case_id, guild_id)

	# Must call UPDATE cases SET active = false
	execute_calls = [call.args[0] for call in mock_bot.db.execute.call_args_list]
	assert any("UPDATE cases SET active = false" in q for q in execute_calls)

	# 2. Test "delete" retention mode
	mock_bot.db.execute.reset_mock()
	manager.set_guild_retention(guild_id, "delete")
	await manager._process_expiration(case_id, guild_id)

	delete_calls = [call.args[0] for call in mock_bot.db.execute.call_args_list]
	assert any("DELETE FROM cases WHERE case_id = $1" in q for q in delete_calls)
