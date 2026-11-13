from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import yarl
from aiohttp import web
from aiohttp.test_utils import TestServer
from core.bot import Bot
from core.clustering import ClusterConfig, configure_gateway_proxy, fetch_proxy_shard_count
from core.clustering.gateway_proxy import shard_count_url
from core.config import Config
from discord.gateway import DiscordWebSocket

PROXY_URL = "ws://gateway-proxy:7878"


@pytest.fixture(autouse=True)
def restore_default_gateway(monkeypatch):
	monkeypatch.setattr(DiscordWebSocket, "DEFAULT_GATEWAY", DiscordWebSocket.DEFAULT_GATEWAY)


@pytest.fixture
def config() -> Config:
	return Config(
		debug=False,
		owner_ids=[123],
		modules=["*"],
		emojis={},
		log_channel_id=999,
		allowed_contexts={"guild": True, "dm_channel": True, "private_channel": True},
		allowed_installs={"guild": True, "user": True},
		allowed_mentions={"everyone": False, "roles": False, "users": False},
	)


def make_bot(config: Config) -> Bot:
	with patch("core.bot.update_slash_localizations"):
		return Bot(config=config)


@pytest.mark.parametrize(
	("gateway_url", "expected"),
	[
		("ws://gateway-proxy:7878", "http://gateway-proxy:7878/shard-count"),
		("wss://proxy.example.com/", "https://proxy.example.com/shard-count"),
		("ws://localhost:7878/?v=10&encoding=json", "http://localhost:7878/shard-count"),
	],
)
def test_shard_count_url(gateway_url, expected):
	assert shard_count_url(gateway_url) == expected


def test_configure_gateway_proxy_replaces_default_gateway():
	configure_gateway_proxy(PROXY_URL)
	assert DiscordWebSocket.DEFAULT_GATEWAY == yarl.URL(PROXY_URL)


def test_cluster_config_reads_gateway_url(monkeypatch):
	monkeypatch.setenv("DISCORD_GATEWAY_URL", PROXY_URL)
	monkeypatch.setenv("SHARD_COUNT", "32")
	cfg = ClusterConfig.from_env()
	assert cfg.uses_gateway_proxy is True
	assert cfg.gateway_url == PROXY_URL
	assert cfg.shard_count == 32


def test_cluster_config_without_gateway_url(monkeypatch):
	monkeypatch.setenv("DISCORD_GATEWAY_URL", "")
	monkeypatch.delenv("SHARD_COUNT", raising=False)
	cfg = ClusterConfig.from_env()
	assert cfg.uses_gateway_proxy is False
	assert cfg.shard_count == 64


def test_bot_connects_directly_without_proxy(monkeypatch, config):
	monkeypatch.delenv("DISCORD_GATEWAY_URL", raising=False)
	monkeypatch.setenv("BOT_MODE", "standalone")
	original = DiscordWebSocket.DEFAULT_GATEWAY
	bot = make_bot(config)
	assert bot.shard_count is None
	assert DiscordWebSocket.DEFAULT_GATEWAY == original


@pytest.mark.asyncio
async def test_bot_behind_proxy_skips_identify_spacing(monkeypatch, config):
	monkeypatch.setenv("DISCORD_GATEWAY_URL", PROXY_URL)
	monkeypatch.setenv("SHARD_COUNT", "32")
	monkeypatch.setenv("BOT_MODE", "standalone")
	bot = make_bot(config)
	assert bot.shard_count == 32
	assert DiscordWebSocket.DEFAULT_GATEWAY == yarl.URL(PROXY_URL)

	with patch("discord.client.asyncio.sleep", new=AsyncMock()) as sleep:
		await bot.before_identify_hook(5, initial=False)
	sleep.assert_not_called()


@pytest.mark.asyncio
async def test_bot_without_proxy_keeps_identify_spacing(monkeypatch, config):
	monkeypatch.delenv("DISCORD_GATEWAY_URL", raising=False)
	bot = make_bot(config)
	with patch("discord.client.asyncio.sleep", new=AsyncMock()) as sleep:
		await bot.before_identify_hook(5, initial=False)
	sleep.assert_awaited_once_with(5.0)


@pytest.mark.asyncio
async def test_verify_shard_count_rejects_mismatch(monkeypatch, config):
	monkeypatch.setenv("DISCORD_GATEWAY_URL", PROXY_URL)
	monkeypatch.setenv("SHARD_COUNT", "32")
	bot = make_bot(config)
	with (
		patch("core.bot.fetch_proxy_shard_count", new=AsyncMock(return_value=31)),
		pytest.raises(RuntimeError, match="SHARD_COUNT=31"),
	):
		await bot.verify_gateway_proxy_shard_count(PROXY_URL)


@pytest.mark.asyncio
async def test_verify_shard_count_accepts_match(monkeypatch, config):
	monkeypatch.setenv("DISCORD_GATEWAY_URL", PROXY_URL)
	monkeypatch.setenv("SHARD_COUNT", "32")
	bot = make_bot(config)
	with patch("core.bot.fetch_proxy_shard_count", new=AsyncMock(return_value=32)):
		await bot.verify_gateway_proxy_shard_count(PROXY_URL)


@pytest.mark.asyncio
async def test_fetch_proxy_shard_count():
	async def shard_count(_request: web.Request) -> web.Response:
		return web.Response(text="32")

	app = web.Application()
	app.router.add_get("/shard-count", shard_count)
	async with TestServer(app) as server, aiohttp.ClientSession() as session:
		gateway_url = f"ws://{server.host}:{server.port}"
		assert await fetch_proxy_shard_count(session, gateway_url) == 32
