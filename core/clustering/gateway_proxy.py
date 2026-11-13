from __future__ import annotations

import aiohttp
import yarl
from discord import utils
from discord.gateway import DiscordWebSocket

__all__ = ("configure_gateway_proxy", "fetch_proxy_shard_count", "shard_count_url")


def configure_gateway_proxy(gateway_url: str) -> None:
	"""Point every gateway connection discord.py opens at the gateway proxy.

	discord.py connects to ``DiscordWebSocket.DEFAULT_GATEWAY`` on startup when a shard count is set, and falls back to it
	whenever a session is invalidated, so replacing it keeps re-identifies behind the proxy as well.

	Args:
		gateway_url: The proxy's WebSocket URL, e.g. ``ws://gateway-proxy:7878``.

	Raises:
		RuntimeError: The installed discord.py negotiates a transport compression the proxy cannot produce.
	"""
	compression = getattr(utils._ActiveDecompressionContext, "COMPRESSION_TYPE", None)
	if compression != "zlib-stream":
		raise RuntimeError(
			f"discord.py uses {compression} gateway compression, but the gateway proxy only speaks zlib-stream"
		)
	DiscordWebSocket.DEFAULT_GATEWAY = yarl.URL(gateway_url)


def shard_count_url(gateway_url: str) -> str:
	"""Build the URL of the proxy's ``/shard-count`` endpoint from its WebSocket URL.

	Args:
		gateway_url: The proxy's WebSocket URL (``ws://`` or ``wss://``).

	Returns:
		str: The HTTP(S) URL that returns the proxy's shard count as plain text.
	"""
	url = yarl.URL(gateway_url)
	scheme = {"ws": "http", "wss": "https"}.get(url.scheme, url.scheme)
	return str(url.with_scheme(scheme).with_path("/shard-count").with_query(None))


async def fetch_proxy_shard_count(session: aiohttp.ClientSession, gateway_url: str) -> int:
	"""Ask the gateway proxy how many shards it runs.

	Args:
		session: The HTTP session to use.
		gateway_url: The proxy's WebSocket URL.

	Returns:
		int: The proxy's total shard count.
	"""
	async with session.get(shard_count_url(gateway_url), timeout=aiohttp.ClientTimeout(total=10)) as response:
		response.raise_for_status()
		return int(await response.text())
