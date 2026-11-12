"""Shared fixtures: a throwaway PostgreSQL 16 database for tests marked ``db``."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
	"""Start a PostgreSQL 16 container, migrate it to head, and yield its DSN.

	Skips when Docker is unavailable, unless ``REQUIRE_DB_TESTS`` is set (as in CI), in which case it fails.
	"""
	try:
		from testcontainers.community.postgres import PostgresContainer

		container = PostgresContainer("postgres:16-alpine", driver=None)
		container.start()
	except Exception as exc:
		if os.getenv("REQUIRE_DB_TESTS"):
			raise
		pytest.skip(f"Docker unavailable for database tests: {exc}")

	try:
		dsn = container.get_connection_url()
		subprocess.run(
			[sys.executable, "-m", "alembic", "-x", f"url={dsn.replace('postgresql://', 'postgresql+asyncpg://', 1)}"]
			+ ["upgrade", "head"],
			cwd=ROOT,
			check=True,
			capture_output=True,
		)
		yield dsn
	finally:
		container.stop()


@pytest.fixture
async def db(postgres_dsn: str) -> AsyncIterator[asyncpg.Pool]:
	"""Yield a connection pool to an empty, fully migrated database."""
	pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=4)
	assert pool is not None
	tables = await pool.fetch(
		"SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
	)
	if tables:
		names = ", ".join(f'"{row["tablename"]}"' for row in tables)
		await pool.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
	try:
		yield pool
	finally:
		await pool.close()
