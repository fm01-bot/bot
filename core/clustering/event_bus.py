from __future__ import annotations

import asyncio
import contextlib
from logging import getLogger
from typing import Any

import orjson
import redis.asyncio as aioredis

from core.clustering.interfaces import EventBus, EventHandler

logger = getLogger(__name__)


class LocalEventBus(EventBus):
	"""In-process asyncio EventBus for BOT_MODE=standalone."""

	def __init__(self) -> None:
		self._handlers: dict[str, list[EventHandler]] = {}
		self._lock = asyncio.Lock()

	async def publish(self, channel: str, message: dict[str, Any]) -> None:
		handlers: list[EventHandler] = []
		async with self._lock:
			handlers = list(self._handlers.get(channel, []))

		for handler in handlers:
			asyncio.create_task(self._safe_dispatch(handler, message))

	async def subscribe(self, channel: str, handler: EventHandler) -> None:
		async with self._lock:
			self._handlers.setdefault(channel, []).append(handler)

	async def _safe_dispatch(self, handler: EventHandler, message: dict[str, Any]) -> None:
		try:
			await handler(message)
		except Exception:
			logger.exception("Error dispatching local event")

	async def start(self) -> None:
		pass

	async def close(self) -> None:
		async with self._lock:
			self._handlers.clear()


class RedisPubSubBus(EventBus):
	"""Distributed Redis Pub/Sub EventBus for BOT_MODE=clustered."""

	def __init__(self, redis_client: aioredis.Redis) -> None:
		self.redis = redis_client
		self.pubsub = self.redis.pubsub()
		self._handlers: dict[str, list[EventHandler]] = {}
		self._task: asyncio.Task | None = None
		self._lock = asyncio.Lock()
		self._running = False

	@classmethod
	def from_url(cls, url: str) -> RedisPubSubBus:
		client = aioredis.from_url(url, decode_responses=False)
		return cls(client)

	async def publish(self, channel: str, message: dict[str, Any]) -> None:
		try:
			payload = orjson.dumps(message)
			await self.redis.publish(channel, payload)
		except Exception:
			logger.exception(f"Failed to publish to Redis channel {channel}")

	async def subscribe(self, channel: str, handler: EventHandler) -> None:
		async with self._lock:
			is_new_channel = channel not in self._handlers or not self._handlers[channel]
			self._handlers.setdefault(channel, []).append(handler)
			if is_new_channel and self._running:
				await self.pubsub.subscribe(channel)

	async def start(self) -> None:
		if self._running:
			return
		self._running = True

		async with self._lock:
			channels = list(self._handlers.keys())
			if channels:
				await self.pubsub.subscribe(*channels)

		self._task = asyncio.create_task(self._listen_loop())

	async def _listen_loop(self) -> None:
		logger.debug("Redis PubSub listener started")
		try:
			async for msg in self.pubsub.listen():
				if not self._running:
					break
				if msg.get("type") != "message":
					continue

				raw_channel = msg.get("channel")
				channel_name = raw_channel.decode("utf-8") if isinstance(raw_channel, bytes) else str(raw_channel)
				raw_data = msg.get("data")

				try:
					data = orjson.loads(raw_data) if isinstance(raw_data, (bytes, bytearray, memoryview)) else {}
				except (orjson.JSONDecodeError, ValueError) as e:
					logger.warning(f"Invalid JSON payload on PubSub channel {channel_name}: {e}")
					continue

				async with self._lock:
					handlers = list(self._handlers.get(channel_name, []))

				for handler in handlers:
					asyncio.create_task(self._safe_dispatch(handler, data))
		except asyncio.CancelledError:
			pass
		except (aioredis.RedisError, OSError):
			logger.exception("Error in Redis PubSub listen loop")
		finally:
			logger.debug("Redis PubSub listener terminated")

	async def _safe_dispatch(self, handler: EventHandler, message: dict[str, Any]) -> None:
		try:
			await handler(message)
		except Exception:
			logger.exception("Error executing PubSub event handler")

	async def close(self) -> None:
		self._running = False
		if self._task and not self._task.done():
			self._task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await self._task

		with contextlib.suppress(Exception):
			await self.pubsub.unsubscribe()
			await self.pubsub.aclose()
			await self.redis.aclose()

		async with self._lock:
			self._handlers.clear()
