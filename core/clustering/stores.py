from __future__ import annotations

import asyncio
import contextlib
from logging import getLogger
from typing import Any

import orjson
import redis.asyncio as aioredis

from core.clustering.interfaces import StateStore

logger = getLogger(__name__)


class InMemoryStateStore(StateStore):
	"""In-memory StateStore implementation for BOT_MODE=standalone."""

	def __init__(self) -> None:
		self._guilds: dict[int, dict[str, Any]] = {}
		self._channels: dict[int, list[dict[str, Any]]] = {}
		self._roles: dict[int, list[dict[str, Any]]] = {}
		self._bot_guilds: set[int] = set()
		self._lock = asyncio.Lock()

	async def set_guild(self, guild_id: int, data: dict[str, Any]) -> None:
		async with self._lock:
			self._guilds[guild_id] = data
			self._bot_guilds.add(guild_id)

	async def get_guild(self, guild_id: int) -> dict[str, Any] | None:
		async with self._lock:
			return self._guilds.get(guild_id)

	async def remove_guild(self, guild_id: int) -> None:
		async with self._lock:
			self._guilds.pop(guild_id, None)
			self._channels.pop(guild_id, None)
			self._roles.pop(guild_id, None)
			self._bot_guilds.discard(guild_id)

	async def set_channels(self, guild_id: int, channels: list[dict[str, Any]]) -> None:
		async with self._lock:
			self._channels[guild_id] = channels

	async def get_channels(self, guild_id: int) -> list[dict[str, Any]] | None:
		async with self._lock:
			return self._channels.get(guild_id)

	async def set_roles(self, guild_id: int, roles: list[dict[str, Any]]) -> None:
		async with self._lock:
			self._roles[guild_id] = roles

	async def get_roles(self, guild_id: int) -> list[dict[str, Any]] | None:
		async with self._lock:
			return self._roles.get(guild_id)

	async def add_bot_guild(self, guild_id: int) -> None:
		async with self._lock:
			self._bot_guilds.add(guild_id)

	async def remove_bot_guild(self, guild_id: int) -> None:
		async with self._lock:
			self._bot_guilds.discard(guild_id)

	async def is_bot_guild(self, guild_id: int) -> bool:
		async with self._lock:
			return guild_id in self._bot_guilds

	async def close(self) -> None:
		async with self._lock:
			self._guilds.clear()
			self._channels.clear()
			self._roles.clear()
			self._bot_guilds.clear()


class RedisStateStore(StateStore):
	"""Redis-backed write-through StateStore implementation for BOT_MODE=clustered."""

	def __init__(self, redis_client: aioredis.Redis) -> None:
		self.redis = redis_client
		self.prefix = "fm01"

	@classmethod
	def from_url(cls, url: str) -> RedisStateStore:
		client = aioredis.from_url(url, decode_responses=False)
		return cls(client)

	async def set_guild(self, guild_id: int, data: dict[str, Any]) -> None:
		try:
			payload = orjson.dumps(data)
			async with self.redis.pipeline(transaction=True) as pipe:
				pipe.set(f"{self.prefix}:guild:{guild_id}", payload)
				pipe.sadd(f"{self.prefix}:bot:guilds", str(guild_id))
				await pipe.execute()
		except Exception:
			logger.exception(f"Failed to set guild state in Redis for {guild_id}")

	async def get_guild(self, guild_id: int) -> dict[str, Any] | None:
		try:
			raw = await self.redis.get(f"{self.prefix}:guild:{guild_id}")
			if raw:
				return orjson.loads(raw)
		except Exception:
			logger.exception(f"Failed to get guild state from Redis for {guild_id}")
		return None

	async def remove_guild(self, guild_id: int) -> None:
		try:
			async with self.redis.pipeline(transaction=True) as pipe:
				pipe.delete(f"{self.prefix}:guild:{guild_id}")
				pipe.delete(f"{self.prefix}:guild:{guild_id}:channels")
				pipe.delete(f"{self.prefix}:guild:{guild_id}:roles")
				pipe.srem(f"{self.prefix}:bot:guilds", str(guild_id))
				await pipe.execute()
		except Exception:
			logger.exception(f"Failed to remove guild state from Redis for {guild_id}")

	async def set_channels(self, guild_id: int, channels: list[dict[str, Any]]) -> None:
		try:
			payload = orjson.dumps(channels)
			await self.redis.set(f"{self.prefix}:guild:{guild_id}:channels", payload)
		except Exception:
			logger.exception(f"Failed to set guild channels in Redis for {guild_id}")

	async def get_channels(self, guild_id: int) -> list[dict[str, Any]] | None:
		try:
			raw = await self.redis.get(f"{self.prefix}:guild:{guild_id}:channels")
			if raw:
				return orjson.loads(raw)
		except Exception:
			logger.exception(f"Failed to get guild channels from Redis for {guild_id}")
		return None

	async def set_roles(self, guild_id: int, roles: list[dict[str, Any]]) -> None:
		try:
			payload = orjson.dumps(roles)
			await self.redis.set(f"{self.prefix}:guild:{guild_id}:roles", payload)
		except Exception:
			logger.exception(f"Failed to set guild roles in Redis for {guild_id}")

	async def get_roles(self, guild_id: int) -> list[dict[str, Any]] | None:
		try:
			raw = await self.redis.get(f"{self.prefix}:guild:{guild_id}:roles")
			if raw:
				return orjson.loads(raw)
		except Exception:
			logger.exception(f"Failed to get guild roles from Redis for {guild_id}")
		return None

	async def add_bot_guild(self, guild_id: int) -> None:
		try:
			await self.redis.sadd(f"{self.prefix}:bot:guilds", str(guild_id))
		except Exception:
			logger.exception(f"Failed to add bot guild in Redis for {guild_id}")

	async def remove_bot_guild(self, guild_id: int) -> None:
		try:
			await self.redis.srem(f"{self.prefix}:bot:guilds", str(guild_id))
		except Exception:
			logger.exception(f"Failed to remove bot guild in Redis for {guild_id}")

	async def is_bot_guild(self, guild_id: int) -> bool:
		try:
			return bool(await self.redis.sismember(f"{self.prefix}:bot:guilds", str(guild_id)))
		except Exception:
			logger.exception(f"Failed to check bot guild in Redis for {guild_id}")
			return False

	async def close(self) -> None:
		with contextlib.suppress(Exception):
			await self.redis.aclose()
