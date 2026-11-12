"""GuildSettings: caching and cross-instance invalidation, with real PostgreSQL and a shared in-process event bus."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest
from cogs.mod.cases import retention_setting
from core.clustering import LocalEventBus
from core.settings import (
	EVENTS_CHANNEL,
	GuildSetting,
	GuildSettings,
	Prefix,
	load_all_locale_overrides,
	load_all_prefixes,
	load_locale_override,
	load_prefix,
	save_locale_override,
	save_prefix,
)

pytestmark = pytest.mark.db

GUILD = 42


class Instance:
	"""One bot process: its own caches, sharing the database and event bus with the others."""

	def __init__(self, db: asyncpg.Pool, bus: LocalEventBus) -> None:
		self.settings = GuildSettings(lambda: db, bus)
		self.prefix: GuildSetting[Prefix] = self.settings.add(
			"prefix", load_prefix, save_prefix, load_all=load_all_prefixes
		)
		self.locale: GuildSetting[str | None] = self.settings.add(
			"locale", load_locale_override, save_locale_override, load_all=load_all_locale_overrides
		)
		self.retention = retention_setting(self.settings)


async def settle() -> None:
	"""Let LocalEventBus deliver (it dispatches in tasks) and the handlers finish their queries."""
	for _ in range(20):
		await asyncio.sleep(0.01)


@pytest.fixture
async def instances(db: asyncpg.Pool) -> tuple[Instance, Instance]:
	bus = LocalEventBus()
	a, b = Instance(db, bus), Instance(db, bus)
	for instance in (a, b):

		async def handler(event: dict, settings: GuildSettings = instance.settings) -> None:
			await settings.handle_event(event)

		await bus.subscribe(EVENTS_CHANNEL, handler)
	return a, b


async def test_loading_a_new_guild_creates_its_row_with_database_defaults(db, instances):
	a, _ = instances

	assert await a.prefix.get(GUILD) == ("?!", True)
	assert await a.retention.get(GUILD) == "keep"
	assert await db.fetchval("SELECT count(*) FROM guilds WHERE guild_id = $1", GUILD) == 1
	assert await db.fetchval("SELECT count(*) FROM mod_config WHERE guild_id = $1", GUILD) == 1


async def test_set_persists_and_updates_the_writer_immediately(db, instances):
	a, _ = instances

	await a.prefix.set(GUILD, ("!", False))

	assert a.prefix.cache[GUILD] == ("!", False)
	row = await db.fetchrow("SELECT prefix, mention FROM guilds WHERE guild_id = $1", GUILD)
	assert (row["prefix"], row["mention"]) == ("!", False)


async def test_preloaded_setting_is_reloaded_on_other_instances(instances):
	a, b = instances
	await a.settings.preload()
	await b.settings.preload()
	assert GUILD not in b.locale.cache

	await a.locale.set(GUILD, "hu")
	await settle()
	assert b.locale.cache[GUILD] == "hu"  # synchronous readers see it without a get()

	await a.locale.set(GUILD, None)
	await settle()
	assert b.locale.cache[GUILD] is None


async def test_lazy_setting_is_dropped_on_other_instances_and_reloaded_on_next_get(instances):
	a, b = instances
	assert await b.retention.get(GUILD) == "keep"

	await a.retention.set(GUILD, "delete")
	await settle()

	assert GUILD not in b.retention.cache
	assert await b.retention.get(GUILD) == "delete"


async def test_writer_ignores_its_own_invalidation(db, instances):
	a, _ = instances
	await a.retention.set(GUILD, "delete")
	await db.execute("UPDATE mod_config SET case_retention = 'keep' WHERE guild_id = $1", GUILD)
	await settle()

	# Had the writer handled its own event, it would have dropped the value and re-read "keep".
	assert a.retention.cache[GUILD] == "delete"


async def test_preload_reads_every_guild(db, instances):
	a, _ = instances
	await db.execute("INSERT INTO guilds (guild_id, prefix, mention) VALUES (1, '!', true), (2, '$', false)")

	await a.settings.preload()

	assert a.prefix.cache == {1: ("!", True), 2: ("$", False)}


async def test_forget_guild_drops_every_setting(instances):
	a, _ = instances
	await a.prefix.get(GUILD)
	await a.retention.get(GUILD)

	a.settings.forget_guild(GUILD)

	assert GUILD not in a.prefix.cache
	assert GUILD not in a.retention.cache


async def test_registering_a_key_twice_returns_the_same_setting(instances):
	a, _ = instances
	assert retention_setting(a.settings) is a.retention


async def test_targeted_write_reported_with_changed_reaches_other_instances(db, instances):
	a, b = instances

	async def load(pool: asyncpg.Pool, guild_id: int) -> bool:
		return bool(await pool.fetchval("SELECT stack_roles FROM level_config WHERE guild_id = $1", guild_id))

	stack_a = a.settings.add("test.stack", load)
	stack_b = b.settings.add("test.stack", load)
	assert await stack_b.get(GUILD) is False

	await db.execute("INSERT INTO level_config (guild_id, stack_roles) VALUES ($1, true)", GUILD)
	await stack_a.changed(GUILD)
	await settle()

	assert await stack_a.get(GUILD) is True
	assert await stack_b.get(GUILD) is True
	with pytest.raises(TypeError):
		await stack_a.set(GUILD, False)
