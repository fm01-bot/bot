from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from helpers.alert_providers import SUPPORTED_PLATFORMS, get_provider
from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_channel

if TYPE_CHECKING:
	from core import Context


def setup_alert_subcommands(parent_node: CLINode) -> CLINode:
	"""Registers alert configuration subcommands under the ?!config tree."""
	alert_node = parent_node.create_subcommand(
		"alert",
		description="Configure YouTube, Twitch, TikTok, and Instagram upload and stream alerts.",
	)

	# 1. alert add
	add_node = alert_node.create_subcommand("add", description="Add an upload or stream alert.")
	add_node.add_argument("platform", help="Platform name: youtube, twitch, tiktok, or instagram")
	add_node.add_argument("account", help="Channel account name, handle, URL, or ID")
	add_node.add_argument("channel_pos", required=False, help="Target Discord channel mention or name")
	add_node.add_option("channel", "c", help="Target Discord channel")

	async def alert_add(
		ctx: Context,
		platform: str,
		account: str,
		channel: str | None = None,
		channel_pos: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		plat = platform.lower().strip()
		if plat not in SUPPORTED_PLATFORMS:
			supported_str = ", ".join(SUPPORTED_PLATFORMS)
			raise CLIParseError(
				f"Unsupported platform `{platform}`. Supported platforms are: {supported_str}.",
				add_node,
			)

		provider = get_provider(plat)
		if not provider:
			raise CLIParseError(f"Provider for platform `{platform}` is not available.", add_node)

		# Check 5-alert total limit per server
		count = await ctx.bot.db.fetchval(
			"SELECT COUNT(*) FROM media_alerts WHERE guild_id = $1",
			ctx.guild.id,
		)
		if count is not None and count >= 5:
			raise CLIParseError(
				"This server has reached the maximum limit of 5 alert subscriptions. "
				"Remove an existing alert using `?!config alert remove` before adding a new one.",
				add_node,
			)

		# Resolve target Discord channel
		ch_raw = channel or channel_pos
		target_channel: discord.abc.GuildChannel | discord.Thread | None = None
		if ch_raw:
			target_channel = resolve_channel(ctx.guild, ch_raw)
			if not target_channel or not isinstance(target_channel, discord.abc.Messageable):
				raise CLIParseError(
					f"Channel `{ch_raw}` was not found or is not a valid text channel.",
					add_node,
				)
		elif isinstance(ctx.channel, (discord.abc.GuildChannel, discord.Thread)):
			target_channel = ctx.channel
		else:
			raise CLIParseError("Please specify a target Discord channel for alerts.", add_node)

		# Resolve account handle/ID via provider
		alerts_cog: Any = ctx.bot.get_cog("Alerts")
		session: aiohttp.ClientSession
		if alerts_cog and hasattr(alerts_cog, "get_session"):
			session = await alerts_cog.get_session()
		else:
			session = aiohttp.ClientSession()

		try:
			account_id, account_name = await provider.resolve_channel(session, account, bot=ctx.bot)
		finally:
			if not alerts_cog or not hasattr(alerts_cog, "get_session"):
				await session.close()

		# Add alert to database
		if alerts_cog and hasattr(alerts_cog, "add_alert"):
			alert_id = await alerts_cog.add_alert(
				guild_id=ctx.guild.id,
				platform=plat,
				channel_account=account,
				account_id=account_id,
				account_name=account_name,
				target_channel_id=target_channel.id,
			)
		else:
			row = await ctx.bot.db.fetchrow(
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
				ctx.guild.id,
				plat,
				account,
				account_id,
				account_name,
				target_channel.id,
			)
			alert_id = int(row["id"]) if row else 0

		lines = [
			f"[+] Alert #{alert_id} successfully added ({plat})",
			f"Creator: {account_name} ({account_id})",
			f"Target: #{target_channel.name}",
		]
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	add_node.callback = alert_add

	# 2. alert remove
	remove_node = alert_node.create_subcommand("remove", description="Remove an alert subscription.")
	remove_node.add_argument("target", help="Numeric alert ID from list, or platform name (youtube, twitch, etc.)")
	remove_node.add_argument("account", required=False, help="Channel account name if platform was given")

	async def alert_remove(ctx: Context, target: str, account: str | None = None, **kwargs: Any):
		assert ctx.guild is not None
		target_clean = target.strip()
		alerts_cog: Any = ctx.bot.get_cog("Alerts")

		# If target is numeric alert ID
		if target_clean.isdigit():
			alert_id = int(target_clean)
			removed = False
			if alerts_cog and hasattr(alerts_cog, "remove_alert"):
				removed = await alerts_cog.remove_alert(alert_id, ctx.guild.id)
			else:
				res = await ctx.bot.db.execute(
					"DELETE FROM media_alerts WHERE id = $1 AND guild_id = $2",
					alert_id,
					ctx.guild.id,
				)
				removed = res == "DELETE 1"

			if not removed:
				raise CLIParseError(f"Alert #{alert_id} was not found in this server.", remove_node)
			return await ctx.send(content=f"```ansi\n[-] Alert #{alert_id} removed\n```")

		# If target is platform
		plat = target_clean.lower()
		if plat in SUPPORTED_PLATFORMS:
			if not account:
				raise CLIParseError(
					f"Please provide the account name to remove: `?!config alert remove {plat} <account>`",
					remove_node,
				)
			del_count = 0
			if alerts_cog and hasattr(alerts_cog, "remove_alert_by_platform_and_account"):
				del_count = await alerts_cog.remove_alert_by_platform_and_account(ctx.guild.id, plat, account.strip())
			else:
				res = await ctx.bot.db.execute(
					"""
					DELETE FROM media_alerts
					WHERE guild_id = $1
					AND platform = $2
					AND (LOWER(channel_account) = LOWER($3) OR LOWER(account_id) = LOWER($3))
					""",
					ctx.guild.id,
					plat,
					account.strip(),
				)
				parts = res.split()
				del_count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

			if del_count == 0:
				raise CLIParseError(
					f"No alerts found for {plat} account `{account}` in this server.",
					remove_node,
				)
			return await ctx.send(
				content=f"```ansi\n[-] Removed {del_count} alert(s) for {plat} account {account}\n```"
			)

		raise CLIParseError(
			f"Invalid target `{target}`. Provide an alert ID (e.g. `1`) or platform name (e.g. `youtube <account>`).",
			remove_node,
		)

	remove_node.callback = alert_remove

	# 3. alert list
	list_node = alert_node.create_subcommand("list", description="List all configured alerts in this server.")

	async def alert_list(ctx: Context, **kwargs: Any):
		assert ctx.guild is not None
		rows = await ctx.bot.db.fetch(
			"SELECT * FROM media_alerts WHERE guild_id = $1 ORDER BY id ASC",
			ctx.guild.id,
		)
		if not rows:
			return await ctx.send(
				content="```ansi\n[-] No media alerts configured for this server (Limit: 5).\nUse `?!config alert add <platform> <channel>` to add one.\n```"
			)

		lines = [f"[Configured Social Media Alerts ({len(rows)}/5)]"]
		for row in rows:
			status = "Active" if row["is_enabled"] else "Disabled"
			target_ch = ctx.guild.get_channel(int(row["target_channel_id"]))
			ch_name = f"#{target_ch.name}" if target_ch else str(row["target_channel_id"])
			creator = row["account_name"] or row["channel_account"]
			lines.append(f"#{row['id']} [{row['platform'].upper()}] {creator} -> {ch_name} [{status}]")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	list_node.callback = alert_list

	# 4. alert enable
	enable_node = alert_node.create_subcommand("enable", description="Enable a media alert.")
	enable_node.add_argument("target", help="Numeric alert ID")

	async def alert_enable(ctx: Context, target: str, **kwargs: Any):
		assert ctx.guild is not None
		if not target.strip().isdigit():
			raise CLIParseError("Target must be a numeric alert ID.", enable_node)
		alert_id = int(target.strip())
		res = await ctx.bot.db.execute(
			"UPDATE media_alerts SET is_enabled = true WHERE id = $1 AND guild_id = $2",
			alert_id,
			ctx.guild.id,
		)
		if res != "UPDATE 1":
			raise CLIParseError(f"Alert #{alert_id} was not found in this server.", enable_node)
		return await ctx.send(content=f"```ansi\n[+] Alert #{alert_id} enabled\n```")

	enable_node.callback = alert_enable

	# 5. alert disable
	disable_node = alert_node.create_subcommand("disable", description="Disable a media alert.")
	disable_node.add_argument("target", help="Numeric alert ID")

	async def alert_disable(ctx: Context, target: str, **kwargs: Any):
		assert ctx.guild is not None
		if not target.strip().isdigit():
			raise CLIParseError("Target must be a numeric alert ID.", disable_node)
		alert_id = int(target.strip())
		res = await ctx.bot.db.execute(
			"UPDATE media_alerts SET is_enabled = false WHERE id = $1 AND guild_id = $2",
			alert_id,
			ctx.guild.id,
		)
		if res != "UPDATE 1":
			raise CLIParseError(f"Alert #{alert_id} was not found in this server.", disable_node)
		return await ctx.send(content=f"```ansi\n[-] Alert #{alert_id} disabled\n```")

	disable_node.callback = alert_disable

	return alert_node
