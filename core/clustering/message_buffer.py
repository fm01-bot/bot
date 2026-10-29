from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from logging import getLogger
from typing import TYPE_CHECKING, Any

import orjson
import redis.asyncio as aioredis

from core.clustering.interfaces import MessageBuffer

if TYPE_CHECKING:
	import discord

logger = getLogger(__name__)


def serialize_message(message: discord.Message) -> dict[str, Any]:
	"""Extract minimal compact snapshot of a message (~200 bytes)."""
	attachment_urls = [a.url for a in message.attachments] if message.attachments else []
	return {
		"id": message.id,
		"channel_id": message.channel.id,
		"guild_id": message.guild.id if message.guild else 0,
		"author_id": message.author.id,
		"author_name": str(message.author),
		"author_avatar": message.author.display_avatar.url if message.author else "",
		"content": message.content or "",
		"attachment_urls": attachment_urls,
		"created_at": message.created_at.isoformat() if message.created_at else "",
	}


class InMemoryMessageBuffer(MessageBuffer):
	"""Bounded LRU message buffer for BOT_MODE=standalone."""

	def __init__(self, maxsize: int = 10_000) -> None:
		self.maxsize = maxsize
		self._cache: OrderedDict[tuple[int, int], dict[str, Any]] = OrderedDict()
		self._lock = asyncio.Lock()

	def enqueue_message(self, message: discord.Message) -> None:
		data = serialize_message(message)
		key = (data["channel_id"], data["id"])
		if len(self._cache) >= self.maxsize:
			self._cache.popitem(last=False)
		self._cache[key] = data

	async def get_message(self, channel_id: int, message_id: int) -> dict[str, Any] | None:
		async with self._lock:
			return self._cache.get((channel_id, message_id))

	async def start(self) -> None:
		pass

	async def close(self) -> None:
		async with self._lock:
			self._cache.clear()


class RedisMessageBuffer(MessageBuffer):
	"""Batched Redis pipeline message buffer with 12h TTL for BOT_MODE=clustered."""

	def __init__(
		self,
		redis_client: aioredis.Redis,
		ttl_seconds: int = 43200,
		flush_interval: float = 0.25,
		batch_size: int = 100,
	) -> None:
		self.redis = redis_client
		self.ttl = ttl_seconds
		self.flush_interval = flush_interval
		self.batch_size = batch_size
		self.prefix = "fm01:msg"
		self._queue: asyncio.Queue[tuple[int, int, bytes]] = asyncio.Queue()
		self._worker_task: asyncio.Task | None = None
		self._running = False

	@classmethod
	def from_url(cls, url: str) -> RedisMessageBuffer:
		client = aioredis.from_url(url, decode_responses=False)
		return cls(client)

	def enqueue_message(self, message: discord.Message) -> None:
		if not self._running:
			return
		try:
			data = serialize_message(message)
			payload = orjson.dumps(data)
			self._queue.put_nowait((data["channel_id"], data["id"], payload))
		except Exception:
			logger.exception("Failed to enqueue message snapshot")

	async def get_message(self, channel_id: int, message_id: int) -> dict[str, Any] | None:
		try:
			raw = await self.redis.get(f"{self.prefix}:{channel_id}:{message_id}")
			if raw:
				return orjson.loads(raw)
		except Exception:
			logger.exception(f"Failed to fetch cached message {message_id} from Redis")
		return None

	async def start(self) -> None:
		if self._running:
			return
		self._running = True
		self._worker_task = asyncio.create_task(self._flush_loop())

	async def _flush_loop(self) -> None:
		logger.debug("RedisMessageBuffer worker started")
		while self._running:
			try:
				batch: list[tuple[int, int, bytes]] = []
				# Wait for at least one item or timeout
				try:
					item = await asyncio.wait_for(self._queue.get(), timeout=self.flush_interval)
					batch.append(item)
					self._queue.task_done()
				except TimeoutError:
					continue

				# Drain up to batch_size items without blocking
				while len(batch) < self.batch_size and not self._queue.empty():
					try:
						extra = self._queue.get_nowait()
						batch.append(extra)
						self._queue.task_done()
					except asyncio.QueueEmpty:
						break

				if batch:
					await self._flush_batch(batch)
			except asyncio.CancelledError:
				break
			except Exception:
				logger.exception("Error in RedisMessageBuffer flush loop")
				await asyncio.sleep(0.5)

		# Drain remaining queue on shutdown
		remaining: list[tuple[int, int, bytes]] = []
		while not self._queue.empty():
			try:
				remaining.append(self._queue.get_nowait())
				self._queue.task_done()
			except asyncio.QueueEmpty:
				break
		if remaining:
			await self._flush_batch(remaining)
		logger.debug("RedisMessageBuffer worker stopped")

	async def _flush_batch(self, batch: list[tuple[int, int, bytes]]) -> None:
		try:
			async with self.redis.pipeline(transaction=False) as pipe:
				for channel_id, message_id, payload in batch:
					pipe.set(f"{self.prefix}:{channel_id}:{message_id}", payload, ex=self.ttl)
				await pipe.execute()
		except Exception:
			logger.exception(f"Failed to flush batch of {len(batch)} messages to Redis")

	async def close(self) -> None:
		self._running = False
		if self._worker_task and not self._worker_task.done():
			self._worker_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await self._worker_task

		with contextlib.suppress(Exception):
			await self.redis.aclose()
