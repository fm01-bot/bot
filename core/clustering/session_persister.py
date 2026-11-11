from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from logging import getLogger
from typing import Any

import orjson
import redis.asyncio as aioredis

from core.clustering.interfaces import SessionPersister

logger = getLogger(__name__)

RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class NullSessionPersister(SessionPersister):
	"""No-op SessionPersister for BOT_MODE=standalone."""

	async def save_sessions(self, sessions: dict[int, dict[str, Any]]) -> None:
		pass

	async def get_session(self, shard_id: int) -> dict[str, Any] | None:
		return None

	async def clear_session(self, shard_id: int) -> None:
		pass

	async def acquire_identify_lock(self, shard_id: int, max_concurrency: int = 1) -> bool:
		return True

	async def release_identify_lock(self, shard_id: int, max_concurrency: int = 1) -> None:
		pass

	async def close(self) -> None:
		pass


class RedisSessionPersister(SessionPersister):
	"""Persists shard session IDs and gateway URLs to Redis for zero-blackout rolling restarts."""

	def __init__(self, redis_client: aioredis.Redis, session_ttl: int = 90) -> None:
		self.redis = redis_client
		self.session_ttl = session_ttl
		self.worker_id = uuid.uuid4().hex
		self.prefix = "fm01"

	@classmethod
	def from_url(cls, url: str, session_ttl: int = 90) -> RedisSessionPersister:
		client = aioredis.from_url(url, decode_responses=False)
		return cls(client, session_ttl=session_ttl)

	async def save_sessions(self, sessions: dict[int, dict[str, Any]]) -> None:
		if not sessions:
			return
		logger.info(f"Persisting {len(sessions)} shard session(s) to Redis with TTL {self.session_ttl}s...")
		try:
			async with self.redis.pipeline(transaction=True) as pipe:
				for shard_id, data in sessions.items():
					payload = orjson.dumps(data)
					pipe.set(f"{self.prefix}:shard:session:{shard_id}", payload, ex=self.session_ttl)
				await pipe.execute()
			logger.info("Successfully persisted shard sessions for zero-blackout resumption.")
		except Exception:
			logger.exception("Failed to persist shard sessions to Redis")

	async def get_session(self, shard_id: int) -> dict[str, Any] | None:
		try:
			raw = await self.redis.get(f"{self.prefix}:shard:session:{shard_id}")
			if raw:
				data = orjson.loads(raw)
				logger.info(f"Loaded saved gateway session for shard {shard_id}: session_id={data.get('session_id')}")
				return data
		except Exception:
			logger.exception(f"Failed to fetch saved session from Redis for shard {shard_id}")
		return None

	async def clear_session(self, shard_id: int) -> None:
		with contextlib.suppress(Exception):
			await self.redis.delete(f"{self.prefix}:shard:session:{shard_id}")

	async def acquire_identify_lock(self, shard_id: int, max_concurrency: int = 1, timeout: float = 30.0) -> bool:
		"""Acquire distributed IDENTIFY lock to avoid colliding with other containers on cold IDENTIFY."""
		bucket = shard_id % max_concurrency
		lock_key = f"{self.prefix}:identify_lock:{bucket}"
		start_time = time.monotonic()

		while time.monotonic() - start_time < timeout:
			acquired = await self.redis.set(lock_key, self.worker_id.encode("utf-8"), nx=True, ex=6)
			if acquired:
				logger.debug(f"Acquired IDENTIFY lock on bucket {bucket} for shard {shard_id}")
				return True
			await asyncio.sleep(0.5)

		logger.warning(f"Timed out waiting for IDENTIFY lock on bucket {bucket} for shard {shard_id}")
		return False

	async def release_identify_lock(self, shard_id: int, max_concurrency: int = 1) -> None:
		bucket = shard_id % max_concurrency
		lock_key = f"{self.prefix}:identify_lock:{bucket}"
		with contextlib.suppress(Exception):
			await self.redis.eval(RELEASE_LOCK_LUA, 1, lock_key, self.worker_id.encode("utf-8"))

	async def close(self) -> None:
		with contextlib.suppress(Exception):
			await self.redis.aclose()
