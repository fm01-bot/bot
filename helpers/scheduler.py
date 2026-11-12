"""Shard-aware, event-driven expiry scheduler shared by cogs that act on timestamps."""

from __future__ import annotations

import asyncio
import datetime
import heapq
import logging
from abc import ABC, abstractmethod
from collections.abc import Hashable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from core.bot import Bot

__all__ = ("ExpiryScheduler", "is_guild_on_shard")

logger = logging.getLogger(__name__)


def is_guild_on_shard(bot: Bot, guild_id: int) -> bool:
	"""Check whether a guild belongs to a shard handled by this bot instance.

	Args:
		bot: The bot instance.
		guild_id: The guild's ID.

	Returns:
		bool: ``True`` if this process owns the guild's shard (always ``True`` without sharding info).
	"""
	total_shards = bot.shard_count or len(bot.shards) or 1
	shard_ids = bot.shard_ids if bot.shard_ids is not None else list(bot.shards.keys())
	if not shard_ids:
		return True
	return (guild_id >> 22) % total_shards in shard_ids


class ExpiryScheduler[K: Hashable](ABC):
	"""Priority-queue scheduler that sleeps until the next item expires and then processes it.

	Subclasses provide the pending items on startup (`fetch_pending`) and the work to do once an item
	expires (`process_expired`). Only items belonging to guilds on this process's shards are scheduled.
	Items that expired while the bot was offline are processed as soon as the bot is ready.
	"""

	def __init__(self, bot: Bot) -> None:
		self.bot = bot
		self._queue: list[tuple[float, K, int]] = []
		self._scheduled_ids: dict[K, float] = {}
		self._wake_event = asyncio.Event()
		self._task: asyncio.Task[None] | None = None
		self._running = False

	@abstractmethod
	async def fetch_pending(self) -> Iterable[tuple[K, int, datetime.datetime]]:
		"""Return every pending item as ``(key, guild_id, expires_at)``."""

	@abstractmethod
	async def process_expired(self, key: K, guild_id: int) -> None:
		"""Handle an item whose expiry time has been reached."""

	def is_guild_on_shard(self, guild_id: int) -> bool:
		"""Check if the guild belongs to a shard handled by this bot instance."""
		return is_guild_on_shard(self.bot, guild_id)

	def schedule_at(self, key: K, guild_id: int, expires: datetime.datetime) -> None:
		"""Schedule (or reschedule) ``key`` to expire at ``expires``.

		Args:
			key: Unique identifier of the item.
			guild_id: The guild the item belongs to.
			expires: When the item expires.
		"""
		if not self.is_guild_on_shard(guild_id):
			return
		expires_ts = expires.timestamp()
		heapq.heappush(self._queue, (expires_ts, key, guild_id))
		self._scheduled_ids[key] = expires_ts
		self._wake_event.set()

	def cancel(self, key: K) -> None:
		"""Cancel a pending item. Its stale queue entry is discarded lazily."""
		self._scheduled_ids.pop(key, None)
		self._wake_event.set()

	def _is_stale(self, entry: tuple[float, K, int]) -> bool:
		return self._scheduled_ids.get(entry[1]) != entry[0]

	async def _safe_process(self, key: K, guild_id: int) -> None:
		try:
			await self.process_expired(key, guild_id)
		except Exception:
			logger.exception(f"Failed to process expired item {key!r} in {type(self).__name__}")

	async def load_pending(self) -> None:
		"""Process overdue items and queue the remaining ones for guilds on this bot's shards."""
		await self.bot.wait_until_ready()
		now = datetime.datetime.now(tz=datetime.UTC)

		for key, guild_id, expires in await self.fetch_pending():
			if not self.is_guild_on_shard(guild_id):
				continue
			if expires.tzinfo is None:
				expires = expires.replace(tzinfo=datetime.UTC)

			if expires <= now:
				await self._safe_process(key, guild_id)
			else:
				heapq.heappush(self._queue, (expires.timestamp(), key, guild_id))
				self._scheduled_ids[key] = expires.timestamp()

		self._wake_event.set()

	async def _runner(self) -> None:
		await self.load_pending()

		while self._running:
			try:
				while self._queue and self._is_stale(self._queue[0]):
					heapq.heappop(self._queue)

				if not self._queue:
					self._wake_event.clear()
					await self._wake_event.wait()
					continue

				earliest_ts, key, guild_id = self._queue[0]
				delay = earliest_ts - datetime.datetime.now(tz=datetime.UTC).timestamp()

				if delay <= 0:
					heapq.heappop(self._queue)
					self._scheduled_ids.pop(key, None)
					await self._safe_process(key, guild_id)
					continue

				self._wake_event.clear()
				try:
					await asyncio.wait_for(self._wake_event.wait(), timeout=delay)
				except TimeoutError:
					pass
			except asyncio.CancelledError:
				break
			except Exception:
				logger.exception(f"Error in {type(self).__name__} runner loop")
				await asyncio.sleep(1)

	def start(self) -> None:
		"""Start the background runner."""
		if not self._running:
			self._running = True
			self._task = asyncio.create_task(self._runner())

	def stop(self) -> None:
		"""Stop the background runner."""
		self._running = False
		if self._task and not self._task.done():
			self._task.cancel()
