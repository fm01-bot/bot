from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from discord.ext import commands, tasks
from helpers.alert_providers import get_provider

if TYPE_CHECKING:
	from args.media import Media
	from core.bot import Bot

logger = logging.getLogger(__name__)


class AlertLimitReachedError(Exception):
	"""Raised when a guild attempts to configure more than the allowed alert pairs."""


class Alerts(commands.Cog, name="Alerts"):
	"""Social media upload and live stream alert monitoring system."""

	MAX_ALERTS_PER_GUILD = 5

	def __init__(self, client: Bot) -> None:
		self.client = client
		self.session: aiohttp.ClientSession | None = None

	async def cog_load(self) -> None:
		if not self.poll_loop.is_running():
			self.poll_loop.start()

	async def cog_unload(self) -> None:
		self.poll_loop.cancel()
		if self.session and not self.session.closed:
			await self.session.close()

	async def get_session(self) -> aiohttp.ClientSession:
		if self.session is None or self.session.closed:
			self.session = aiohttp.ClientSession()
		return self.session

	@tasks.loop(minutes=2)
	async def poll_loop(self) -> None:
		"""Periodically checks tracked channels across all platforms."""
		try:
			session = await self.get_session()
			# Query distinct active accounts
			rows = await self.client.db.fetch(
				"""
				SELECT DISTINCT platform, channel_account, account_id, account_name
				FROM media_alerts
				WHERE is_enabled = true
				"""
			)
			for row in rows:
				try:
					await self.check_account(
						session=session,
						platform=row["platform"],
						channel_account=row["channel_account"],
						account_id=row["account_id"] or row["channel_account"],
						account_name=row["account_name"],
					)
				except Exception as e:  # noqa: BLE001
					logger.warning(f"Error checking {row['platform']} account {row['channel_account']}: {e}")
		except Exception as e:  # noqa: BLE001
			logger.error(f"Unhandled error in alert polling loop: {e}")

	@poll_loop.before_loop
	async def before_poll_loop(self) -> None:
		await self.client.wait_until_ready()

	async def check_account(
		self,
		session: aiohttp.ClientSession,
		platform: str,
		channel_account: str,
		account_id: str,
		account_name: str | None = None,
	) -> None:
		"""Fetches latest media for an account and dispatches alerts to subscribed guilds."""
		provider = get_provider(platform)
		if not provider:
			return

		media = await provider.fetch_latest(
			session=session,
			account_id=account_id,
			account_name=account_name,
			bot=self.client,
		)
		if not media:
			return

		# Fetch all alert subscriptions for this platform & account
		alerts = await self.client.db.fetch(
			"""
			SELECT * FROM media_alerts
			WHERE is_enabled = true
			AND platform = $1
			AND (channel_account = $2 OR account_id = $3)
			""",
			platform,
			channel_account,
			account_id,
		)

		for alert_row in alerts:
			last_id = alert_row["last_media_id"]
			if last_id == media.id:
				continue

			# If this is the initial baseline check (last_media_id is None)
			if last_id is None:
				# Initialize baseline so we don't back-notify older uploads
				await self.client.db.execute(
					"UPDATE media_alerts SET last_media_id = $1, last_media_time = $2 WHERE id = $3",
					media.id,
					datetime.datetime.now(datetime.UTC),
					alert_row["id"],
				)
				continue

			# Dispatch alert notification
			sent = await self.dispatch_alert(alert_row, media)
			if sent:
				await self.client.db.execute(
					"UPDATE media_alerts SET last_media_id = $1, last_media_time = $2 WHERE id = $3",
					media.id,
					datetime.datetime.now(datetime.UTC),
					alert_row["id"],
				)

	async def dispatch_alert(self, alert_row: dict[str, Any], media: Media) -> bool:
		"""Formats and sends the alert message using localization with dashboard override support."""
		guild_id = int(alert_row["guild_id"])
		channel_id = int(alert_row["target_channel_id"])

		guild = self.client.get_guild(guild_id)
		if not guild:
			return False

		channel = guild.get_channel(channel_id)
		if not channel or not isinstance(channel, discord.abc.Messageable):
			return False

		try:
			# Load localized message per platform (supports future dashboard overrides)
			localized_payload = await self.client.custom_response.get_message(
				f"alerts.{media.platform}",
				guild,
				media=media,
				convert_embeds=True,
				convert_components=True,
			)
			if isinstance(localized_payload, dict):
				content = localized_payload.get("content")
				embeds = localized_payload.get("embeds", [])
				view = localized_payload.get("view")
				await channel.send(content=content, embeds=embeds, view=view)
				return True
			if isinstance(localized_payload, str):
				await channel.send(content=localized_payload)
				return True
		except Exception as e:  # noqa: BLE001
			logger.debug(f"Failed to load localized alert message for {media.platform}: {e}")

		# Fallback if localization key fails
		try:
			fallback_content = f"**{media.author.name}** posted an update!\n**{media.title}**\n{media.url}"
			await channel.send(content=fallback_content)
			return True
		except (discord.Forbidden, discord.HTTPException) as e:
			logger.warning(f"Could not send alert to channel {channel_id} in guild {guild_id}: {e}")
			return False

	# Database accessors
	async def get_guild_alerts(self, guild_id: int) -> list[dict[str, Any]]:
		"""Returns all configured alerts for a guild."""
		rows = await self.client.db.fetch(
			"SELECT * FROM media_alerts WHERE guild_id = $1 ORDER BY id ASC",
			guild_id,
		)
		return [dict(row) for row in rows]

	async def get_alert(self, alert_id: int, guild_id: int | None = None) -> dict[str, Any] | None:
		"""Retrieves a specific alert by its primary key ID."""
		if guild_id is not None:
			row = await self.client.db.fetchrow(
				"SELECT * FROM media_alerts WHERE id = $1 AND guild_id = $2",
				alert_id,
				guild_id,
			)
		else:
			row = await self.client.db.fetchrow("SELECT * FROM media_alerts WHERE id = $1", alert_id)
		return dict(row) if row else None

	async def add_alert(
		self,
		guild_id: int,
		platform: str,
		channel_account: str,
		account_id: str | None,
		account_name: str | None,
		target_channel_id: int,
	) -> int:
		"""Creates a new media alert subscription enforcing the limit of 5 per server."""
		count = await self.client.db.fetchval(
			"SELECT COUNT(*) FROM media_alerts WHERE guild_id = $1",
			guild_id,
		)
		if count is not None and count >= self.MAX_ALERTS_PER_GUILD:
			raise AlertLimitReachedError(
				f"Server has reached the limit of {self.MAX_ALERTS_PER_GUILD} alert subscriptions."
			)

		row = await self.client.db.fetchrow(
			"""
			INSERT INTO media_alerts (
				guild_id, platform, channel_account, account_id,
				account_name, target_channel_id, is_enabled
			)
			VALUES ($1, $2, $3, $4, $5, $6, true)
			ON CONFLICT (guild_id, platform, channel_account, target_channel_id)
			DO UPDATE SET
				account_id = EXCLUDED.account_id,
				account_name = EXCLUDED.account_name,
				is_enabled = true
			RETURNING id
			""",
			guild_id,
			platform.lower(),
			channel_account,
			account_id,
			account_name,
			target_channel_id,
		)
		assert row is not None
		return int(row["id"])

	async def remove_alert(self, alert_id: int, guild_id: int) -> bool:
		"""Removes an alert by ID for the specified guild."""
		res = await self.client.db.execute(
			"DELETE FROM media_alerts WHERE id = $1 AND guild_id = $2",
			alert_id,
			guild_id,
		)
		return res == "DELETE 1"

	async def remove_alert_by_platform_and_account(
		self,
		guild_id: int,
		platform: str,
		channel_account: str,
	) -> int:
		"""Removes alerts matching platform and account for the specified guild."""
		res = await self.client.db.execute(
			"""
			DELETE FROM media_alerts
			WHERE guild_id = $1
			AND platform = $2
			AND (LOWER(channel_account) = LOWER($3) OR LOWER(account_id) = LOWER($3))
			""",
			guild_id,
			platform.lower(),
			channel_account,
		)
		parts = res.split()
		return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

	async def set_alert_enabled(self, alert_id: int, guild_id: int, enabled: bool) -> bool:
		"""Enables or disables an alert."""
		res = await self.client.db.execute(
			"UPDATE media_alerts SET is_enabled = $1 WHERE id = $2 AND guild_id = $3",
			enabled,
			alert_id,
			guild_id,
		)
		return res == "UPDATE 1"


async def setup(client: Bot) -> None:
	await client.add_cog(Alerts(client))
