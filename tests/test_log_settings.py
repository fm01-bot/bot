"""LogSettings against real PostgreSQL, with two bot instances sharing an in-process event bus."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import asyncpg
import pytest
from cogs.log import LOG_MODULES, LogConfig, LogSettings
from core.clustering import LocalEventBus
from core.settings import EVENTS_CHANNEL, GuildSettings

GUILD = 7


def make_bot(db: asyncpg.Pool, bus: LocalEventBus) -> SimpleNamespace:
	return SimpleNamespace(settings=GuildSettings(lambda: db, bus), message_logging_guilds=set())


async def config_of(bot: SimpleNamespace) -> LogConfig:
	cfg = await LogSettings(bot).get(GUILD)
	assert cfg is not None
	return cfg


async def settle() -> None:
	for _ in range(20):
		await asyncio.sleep(0.01)


@pytest.fixture
async def bots(db: asyncpg.Pool) -> tuple[SimpleNamespace, SimpleNamespace]:
	bus = LocalEventBus()
	a, b = make_bot(db, bus), make_bot(db, bus)
	for bot in (a, b):

		async def handler(event: dict, settings: GuildSettings = bot.settings) -> None:
			await settings.handle_event(event)

		await bus.subscribe(EVENTS_CHANNEL, handler)
	return a, b


@pytest.mark.db
async def test_enable_on_a_new_guild_logs_every_module(db, bots):
	a, _ = bots

	cfg = await LogSettings(a).enable(GUILD, channel_id=123)

	assert cfg.enabled_modules == LOG_MODULES
	row = await db.fetchrow("SELECT is_on, channel, modules FROM log WHERE guild_id = $1", GUILD)
	assert (row["is_on"], int(row["channel"]), row["modules"]) == (True, 123, ["*"])
	assert GUILD in a.message_logging_guilds


@pytest.mark.db
async def test_enable_keeps_the_channel_when_none_is_given(bots):
	a, _ = bots
	logs = LogSettings(a)
	await logs.enable(GUILD, channel_id=123)
	await logs.disable(GUILD)

	cfg = await logs.enable(GUILD)

	assert (cfg.is_on, cfg.channel_id) == (True, 123)


@pytest.mark.db
async def test_disable_stops_message_buffering_on_every_instance(bots):
	a, b = bots
	await LogSettings(b).get(GUILD)  # b knows the log setting
	await LogSettings(a).enable(GUILD, channel_id=1)
	await settle()
	assert GUILD in b.message_logging_guilds  # regression: other clusters never refreshed this

	await LogSettings(a).disable(GUILD)
	await settle()

	assert GUILD not in a.message_logging_guilds
	assert GUILD not in b.message_logging_guilds


@pytest.mark.db
async def test_other_instance_sees_new_modules_without_restart(bots):
	a, b = bots
	logs_a = LogSettings(a)
	await logs_a.enable(GUILD, channel_id=1)
	await logs_a.remove_modules(GUILD, LOG_MODULES)
	await settle()
	assert not (await config_of(b)).is_enabled("on_member_join")

	await logs_a.add_modules(GUILD, ["on_member_join", "not_a_module"])
	await settle()

	cfg = await config_of(b)
	assert cfg.is_enabled("on_member_join")
	assert cfg.enabled_modules == {"on_member_join"}


@pytest.mark.db
async def test_removing_a_module_from_all_expands_the_wildcard(db, bots):
	a, _ = bots
	logs = LogSettings(a)
	await logs.enable(GUILD, channel_id=1)

	cfg = await logs.remove_modules(GUILD, ["on_message_delete"])

	assert cfg.enabled_modules == LOG_MODULES - {"on_message_delete"}
	stored = await db.fetchval("SELECT modules FROM log WHERE guild_id = $1", GUILD)
	assert "*" not in stored and "on_message_edit" in stored


@pytest.mark.db
async def test_per_event_channels_and_webhook_round_trip(bots):
	a, b = bots
	logs = LogSettings(a)
	await logs.enable(GUILD, channel_id=1)
	await logs.set_event_channel(GUILD, "on_member_join", 55)
	await logs.set_webhook(GUILD, "https://example.invalid/hook")
	await settle()

	cfg = await config_of(b)
	assert cfg.channel_for("on_member_join") == 55
	assert cfg.channel_for("on_member_remove") == 1
	assert cfg.webhook_url == "https://example.invalid/hook"


def test_wildcard_rows_from_the_old_config_fallback_log_everything():
	"""Rows written with modules = ARRAY['*'] (the column default) used to log nothing."""
	cfg = LogConfig.from_row({"guild_id": 1, "is_on": True, "channel": 2, "modules": ["*"], "channels": {}})

	assert cfg.is_enabled("on_member_join")
	assert cfg.logs_messages
