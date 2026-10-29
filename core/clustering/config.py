from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field


@dataclass
class ClusterConfig:
	"""Configuration for bot runtime clustering."""

	mode: str = "standalone"
	shard_count: int = 64
	shards_per_cluster: int = 16
	cluster_id: str = field(default_factory=lambda: f"cluster-{uuid.uuid4().hex[:8]}")
	shard_ids: list[int] | None = None
	redis_url: str = "redis://localhost:6379/0"
	redis_msg_url: str = "redis://localhost:6379/1"
	discord_proxy_url: str | None = None
	lease_ttl: int = 30
	heartbeat_interval: int = 10
	max_concurrency: int = 1

	@property
	def is_clustered(self) -> bool:
		return self.mode.lower() == "clustered"

	@classmethod
	def from_env(cls) -> ClusterConfig:
		mode = os.getenv("BOT_MODE", "standalone").strip().lower()
		shard_count = int(os.getenv("SHARD_COUNT", "64"))
		shards_per_cluster = int(os.getenv("SHARDS_PER_CLUSTER", "16"))
		raw_cluster_id = (os.getenv("CLUSTER_ID") or "").strip()
		if raw_cluster_id:
			cluster_id = raw_cluster_id
		else:
			hostname = (os.getenv("HOSTNAME") or "").strip()
			cluster_id = f"cluster-{hostname}" if hostname else f"cluster-{uuid.uuid4().hex[:8]}"

		shard_ids_raw = os.getenv("SHARD_IDS")
		shard_ids: list[int] | None = None
		if shard_ids_raw:
			try:
				shard_ids = [int(s.strip()) for s in shard_ids_raw.split(",") if s.strip()]
			except ValueError:
				shard_ids = None

		redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
		redis_msg_url = os.getenv("REDIS_MSG_URL", "redis://localhost:6379/1")
		discord_proxy_url = os.getenv("DISCORD_PROXY_URL") or os.getenv("DISCORD_API_PROXY_URL")

		lease_ttl = int(os.getenv("LEASE_TTL", "30"))
		heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "10"))
		max_concurrency = int(os.getenv("MAX_CONCURRENCY", "1"))

		return cls(
			mode=mode,
			shard_count=shard_count,
			shards_per_cluster=shards_per_cluster,
			cluster_id=cluster_id,
			shard_ids=shard_ids,
			redis_url=redis_url,
			redis_msg_url=redis_msg_url,
			discord_proxy_url=discord_proxy_url,
			lease_ttl=lease_ttl,
			heartbeat_interval=heartbeat_interval,
			max_concurrency=max_concurrency,
		)
