from __future__ import annotations

import asyncio
import contextlib
import datetime
from logging import getLogger

import orjson
import redis.asyncio as aioredis

from core.clustering.interfaces import ShardCoordinator

logger = getLogger(__name__)

RELEASE_LEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

RENEW_LEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
"""


class StandaloneCoordinator(ShardCoordinator):
	"""Coordinator for BOT_MODE=standalone (relies on default discord.py sharding)."""

	async def acquire_shards(self, total_shards: int, shards_per_cluster: int) -> list[int] | None:
		return None

	async def start_heartbeat(self) -> None:
		pass

	async def release_shards(self) -> None:
		pass

	async def update_health(self, shard_id: int, latency: float, guild_count: int, status: str) -> None:
		pass

	async def close(self) -> None:
		pass


class RedisShardCoordinator(ShardCoordinator):
	"""Dynamic Redis lease-based shard coordinator for BOT_MODE=clustered."""

	def __init__(
		self,
		redis_client: aioredis.Redis,
		cluster_id: str,
		lease_ttl: int = 30,
		heartbeat_interval: int = 10,
		explicit_shard_ids: list[int] | None = None,
	) -> None:
		self.redis = redis_client
		self.cluster_id = cluster_id
		self.lease_ttl = lease_ttl
		self.heartbeat_interval = heartbeat_interval
		self.explicit_shard_ids = explicit_shard_ids
		self.claimed_shards: list[int] = []
		self._heartbeat_task: asyncio.Task | None = None
		self._running = False
		self.prefix = "fm01"

	@classmethod
	def from_url(
		cls,
		url: str,
		cluster_id: str,
		lease_ttl: int = 30,
		heartbeat_interval: int = 10,
		explicit_shard_ids: list[int] | None = None,
	) -> RedisShardCoordinator:
		client = aioredis.from_url(url, decode_responses=False)
		return cls(
			client,
			cluster_id=cluster_id,
			lease_ttl=lease_ttl,
			heartbeat_interval=heartbeat_interval,
			explicit_shard_ids=explicit_shard_ids,
		)

	async def acquire_shards(self, total_shards: int, shards_per_cluster: int) -> list[int]:
		await self.redis.set(f"{self.prefix}:shards:total", str(total_shards))

		# If explicit shard IDs are provided in environment, attempt to claim those
		target_pool = self.explicit_shard_ids if self.explicit_shard_ids is not None else list(range(total_shards))
		claimed: list[int] = []

		for shard_id in target_pool:
			if len(claimed) >= shards_per_cluster:
				break

			key = f"{self.prefix}:shard:lease:{shard_id}"
			acquired = await self.redis.set(key, self.cluster_id.encode("utf-8"), nx=True, ex=self.lease_ttl)
			if acquired:
				claimed.append(shard_id)
				logger.info(f"Cluster {self.cluster_id} acquired lease on shard {shard_id}")
			else:
				current_owner = await self.redis.get(key)
				if current_owner and current_owner.decode("utf-8") == self.cluster_id:  # type: ignore
					# We already own the lease from previous run/reboot
					await self.redis.expire(key, self.lease_ttl)
					claimed.append(shard_id)
					logger.info(f"Cluster {self.cluster_id} reclaimed existing lease on shard {shard_id}")

		if not claimed:
			raise RuntimeError(
				f"Cluster {self.cluster_id} was unable to acquire any shard leases from total {total_shards}"
			)

		self.claimed_shards = claimed
		logger.info(f"Cluster {self.cluster_id} assigned shards: {self.claimed_shards}")
		return claimed

	async def start_heartbeat(self) -> None:
		if self._running or not self.claimed_shards:
			return
		self._running = True
		self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

	async def _heartbeat_loop(self) -> None:
		logger.debug(f"Shard lease heartbeat started for {self.claimed_shards}")
		while self._running:
			try:
				await asyncio.sleep(self.heartbeat_interval)
				for shard_id in self.claimed_shards:
					key = f"{self.prefix}:shard:lease:{shard_id}"
					renewed = await self.redis.eval(
						RENEW_LEASE_LUA, 1, key, self.cluster_id.encode("utf-8"), self.lease_ttl
					)
					if not renewed:
						logger.warning(
							f"Shard {shard_id} lease lost by cluster {self.cluster_id}! Attempting re-acquisition..."
						)
						await self.redis.set(key, self.cluster_id.encode("utf-8"), ex=self.lease_ttl)
			except asyncio.CancelledError:
				break
			except Exception:
				logger.exception("Error in shard lease heartbeat loop")

	async def update_health(self, shard_id: int, latency: float, guild_count: int, status: str) -> None:
		try:
			data = {
				"cluster_id": self.cluster_id,
				"shard_id": shard_id,
				"latency_ms": round(latency * 1000, 2) if latency >= 0 else None,
				"guild_count": guild_count,
				"status": status,
				"updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
			}
			payload = orjson.dumps(data)
			await self.redis.hset(f"{self.prefix}:shards:health", str(shard_id), payload)
		except (aioredis.RedisError, OSError) as e:
			logger.debug(f"Failed to update health metrics in Redis for shard {shard_id}: {e}")

	async def release_shards(self) -> None:
		logger.info(f"Releasing shard leases for cluster {self.cluster_id}: {self.claimed_shards}")
		for shard_id in self.claimed_shards:
			key = f"{self.prefix}:shard:lease:{shard_id}"
			try:
				await self.redis.eval(RELEASE_LEASE_LUA, 1, key, self.cluster_id.encode("utf-8"))
			except (aioredis.RedisError, OSError):
				logger.exception(f"Failed to release lease on shard {shard_id}")
		self.claimed_shards.clear()

	async def close(self) -> None:
		self._running = False
		if self._heartbeat_task and not self._heartbeat_task.done():
			self._heartbeat_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await self._heartbeat_task

		with contextlib.suppress(Exception):
			await self.redis.aclose()
