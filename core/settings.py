"""Guild settings: cached per-guild values that stay in step across bot instances.

Each setting is a `GuildSetting` registered on `GuildSettings` (``Bot.settings``). Callers read with `GuildSetting.get`
(or `GuildSetting.cache` for synchronous hot paths) and write with `GuildSetting.set`. Writing persists the value,
updates this instance's cache, and announces an ``INVALIDATE_SETTING`` event on the event bus; every other instance
reloads that guild's value from the database. Callers never touch caches or the event bus themselves.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import Any

import asyncpg

from core.clustering.interfaces import EventBus

__all__ = ("EVENTS_CHANNEL", "INVALIDATE_SETTING", "GuildSetting", "GuildSettings", "Prefix")

logger = logging.getLogger(__name__)

EVENTS_CHANNEL = "fm01:events"
INVALIDATE_SETTING = "INVALIDATE_SETTING"

type Loader[T] = Callable[[asyncpg.Pool, int], Awaitable[T]]
type Saver[T] = Callable[[asyncpg.Pool, int, T], Awaitable[None]]
type BulkLoader[T] = Callable[[asyncpg.Pool], Awaitable[Mapping[int, T]]]


class GuildSetting[T]:
	"""One per-guild setting with a cache. Create these through `GuildSettings.add`.

	A setting with ``load_all`` is *preloaded*: every guild's value is cached at startup, so `cache` can be read
	synchronously, and invalidations reload the value immediately. Other settings load lazily on first `get`, and
	invalidations drop the cached value.
	"""

	def __init__(
		self, registry: GuildSettings, key: str, load: Loader[T], save: Saver[T], load_all: BulkLoader[T] | None
	) -> None:
		self.key = key
		self._registry = registry
		self._load = load
		self._save = save
		self._load_all = load_all
		self._cache: dict[int, T] = {}
		self.cache: Mapping[int, T] = MappingProxyType(self._cache)
		"""Read-only live view of the cached values. Complete only for preloaded settings."""

	@property
	def preloaded(self) -> bool:
		"""Whether every guild's value is kept in `cache`."""
		return self._load_all is not None

	async def get(self, guild_id: int) -> T:
		"""Return the guild's value, loading it from the database if it isn't cached."""
		if guild_id not in self._cache:
			self._cache[guild_id] = await self._load(self._registry.db, guild_id)
		return self._cache[guild_id]

	async def set(self, guild_id: int, value: T) -> None:
		"""Persist the guild's value and tell the other instances to reload it."""
		await self._save(self._registry.db, guild_id, value)
		self._cache[guild_id] = value
		await self._registry.announce(self.key, guild_id)

	def remember(self, guild_id: int, value: T) -> None:
		"""Cache a value that is already persisted (e.g. a row just read elsewhere) without announcing it."""
		self._cache[guild_id] = value

	def forget(self, guild_id: int) -> None:
		"""Drop the guild's cached value, e.g. when the bot leaves the guild."""
		self._cache.pop(guild_id, None)

	async def refresh(self, guild_id: int) -> None:
		"""Bring the guild's cached value up to date after another instance changed it."""
		if self.preloaded:
			self._cache[guild_id] = await self._load(self._registry.db, guild_id)
		else:
			self._cache.pop(guild_id, None)

	async def preload(self) -> None:
		"""Cache every guild's value. Does nothing for lazily loaded settings."""
		if self._load_all is None:
			return
		values = await self._load_all(self._registry.db)
		self._cache.clear()
		self._cache.update(values)


class GuildSettings:
	"""Registry of `GuildSetting`s, wired to the database pool and the event bus.

	Args:
		db: Returns the database pool. A callable, because the pool is created after the bot is constructed.
		event_bus: The bus that carries ``INVALIDATE_SETTING`` events between instances.
	"""

	def __init__(self, db: Callable[[], asyncpg.Pool], event_bus: EventBus) -> None:
		self._db = db
		self._event_bus = event_bus
		self._settings: dict[str, GuildSetting[Any]] = {}
		self._origin = uuid.uuid4().hex

	@property
	def db(self) -> asyncpg.Pool:
		return self._db()

	def add[T](
		self, key: str, load: Loader[T], save: Saver[T], *, load_all: BulkLoader[T] | None = None
	) -> GuildSetting[T]:
		"""Register a setting.

		Args:
			key: Unique name, used in invalidation events.
			load: Reads one guild's value. It decides the default for guilds without a row.
			save: Writes one guild's value.
			load_all: Reads every guild's value; makes the setting preloaded.

		Returns:
			GuildSetting: The registered setting. Registering an existing key returns the existing setting.
		"""
		if key in self._settings:
			return self._settings[key]
		setting = GuildSetting(self, key, load, save, load_all)
		self._settings[key] = setting
		return setting

	def __getitem__(self, key: str) -> GuildSetting[Any]:
		return self._settings[key]

	async def preload(self) -> None:
		"""Preload every preloaded setting."""
		for setting in self._settings.values():
			try:
				await setting.preload()
			except Exception:
				logger.exception(f"Failed to preload guild setting {setting.key!r}")

	def forget_guild(self, guild_id: int) -> None:
		"""Drop every cached value for a guild."""
		for setting in self._settings.values():
			setting.forget(guild_id)

	async def announce(self, key: str, guild_id: int) -> None:
		"""Tell other instances that a guild's setting changed."""
		await self._event_bus.publish(
			EVENTS_CHANNEL, {"type": INVALIDATE_SETTING, "key": key, "guild_id": guild_id, "origin": self._origin}
		)

	async def handle_event(self, event: Mapping[str, Any]) -> bool:
		"""Apply an ``INVALIDATE_SETTING`` event from another instance.

		Returns:
			bool: Whether the event was a setting invalidation (handled or deliberately ignored).
		"""
		if event.get("type") != INVALIDATE_SETTING:
			return False
		if event.get("origin") == self._origin:
			return True
		setting = self._settings.get(str(event.get("key")))
		guild_id = event.get("guild_id")
		if setting is None or guild_id is None:
			return True
		await setting.refresh(int(guild_id))
		return True


# Settings owned by the bot core. Feature settings are registered by their cogs.

type Prefix = tuple[str, bool]
"""A guild's command prefix and whether mentioning the bot also works as a prefix."""


async def load_prefix(db: asyncpg.Pool, guild_id: int) -> Prefix:
	"""Read a guild's prefix, creating its ``guilds`` row (with the column defaults) if it has none."""
	row = await db.fetchrow(
		"INSERT INTO guilds (guild_id) VALUES ($1) "
		"ON CONFLICT (guild_id) DO UPDATE SET guild_id = EXCLUDED.guild_id RETURNING prefix, mention",
		guild_id,
	)
	assert row is not None
	return row["prefix"], row["mention"]


async def save_prefix(db: asyncpg.Pool, guild_id: int, value: Prefix) -> None:
	"""Write a guild's prefix."""
	await db.execute(
		"INSERT INTO guilds (guild_id, prefix, mention) VALUES ($1, $2, $3) "
		"ON CONFLICT (guild_id) DO UPDATE SET prefix = EXCLUDED.prefix, mention = EXCLUDED.mention",
		guild_id,
		*value,
	)


async def load_all_prefixes(db: asyncpg.Pool) -> dict[int, Prefix]:
	"""Read every guild's prefix."""
	rows = await db.fetch("SELECT guild_id, prefix, mention FROM guilds")
	return {int(row["guild_id"]): (row["prefix"], row["mention"]) for row in rows}


async def load_locale_override(db: asyncpg.Pool, guild_id: int) -> str | None:
	"""Read a guild's locale override, or ``None`` if it uses its Discord locale."""
	return await db.fetchval("SELECT locale FROM guild_locale_overrides WHERE guild_id = $1", guild_id)


async def save_locale_override(db: asyncpg.Pool, guild_id: int, value: str | None) -> None:
	"""Write a guild's locale override; ``None`` removes it."""
	if value is None:
		await db.execute("DELETE FROM guild_locale_overrides WHERE guild_id = $1", guild_id)
	else:
		await db.execute(
			"INSERT INTO guild_locale_overrides (guild_id, locale) VALUES ($1, $2) "
			"ON CONFLICT (guild_id) DO UPDATE SET locale = EXCLUDED.locale",
			guild_id,
			value,
		)


async def load_all_locale_overrides(db: asyncpg.Pool) -> dict[int, str | None]:
	"""Read every guild's locale override."""
	rows = await db.fetch("SELECT guild_id, locale FROM guild_locale_overrides")
	return {int(row["guild_id"]): row["locale"] for row in rows}
