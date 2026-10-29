from __future__ import annotations

import asyncio
from logging import getLogger
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

if TYPE_CHECKING:
	from core import Bot

logger = getLogger(__name__)


def format_channel(channel: discord.abc.GuildChannel) -> dict[str, Any]:
	return {
		"id": channel.id,
		"name": channel.name,
		"type": str(channel.type),
		"position": getattr(channel, "position", 0),
		"parent_id": getattr(channel, "category_id", None),
	}


def format_role(role: discord.Role) -> dict[str, Any]:
	return {
		"id": role.id,
		"name": role.name,
		"color": role.color.value,
		"position": role.position,
		"permissions": role.permissions.value,
		"managed": role.managed,
		"mentionable": role.mentionable,
	}


def format_guild(guild: discord.Guild) -> dict[str, Any]:
	return {
		"id": guild.id,
		"name": guild.name,
		"icon": guild.icon.url if guild.icon else None,
		"owner_id": guild.owner_id,
		"member_count": guild.member_count,
		"shard_id": guild.shard_id,
	}


class StateSync(commands.Cog, name="StateSync"):
	"""Synchronizes minimal guild, channel, and role state projections to the StateStore."""

	def __init__(self, client: Bot) -> None:
		self.client = client
		self._sync_lock = asyncio.Lock()

	async def _sync_guild(self, guild: discord.Guild) -> None:
		try:
			guild_data = format_guild(guild)
			channels_data = [format_channel(c) for c in guild.channels]
			roles_data = [format_role(r) for r in guild.roles]

			await self.client.state_store.set_guild(guild.id, guild_data)
			await self.client.state_store.set_channels(guild.id, channels_data)
			await self.client.state_store.set_roles(guild.id, roles_data)
			await self.client.state_store.add_bot_guild(guild.id)
		except Exception:
			logger.exception(f"Failed to sync state projection for guild {guild.id}")

	@commands.Cog.listener()
	async def on_ready(self) -> None:
		logger.info(f"Syncing state projections for {len(self.client.guilds)} guilds...")
		for guild in self.client.guilds:
			await self._sync_guild(guild)
		logger.info("State projections synchronized.")

	@commands.Cog.listener()
	async def on_guild_join(self, guild: discord.Guild) -> None:
		await self._sync_guild(guild)

	@commands.Cog.listener()
	async def on_guild_update(self, _before: discord.Guild, after: discord.Guild) -> None:
		await self._sync_guild(after)

	@commands.Cog.listener()
	async def on_guild_remove(self, guild: discord.Guild) -> None:
		try:
			await self.client.state_store.remove_guild(guild.id)
		except Exception:
			logger.exception(f"Failed to remove state projection for guild {guild.id}")

	@commands.Cog.listener()
	async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
		if channel.guild:
			channels_data = [format_channel(c) for c in channel.guild.channels]
			await self.client.state_store.set_channels(channel.guild.id, channels_data)

	@commands.Cog.listener()
	async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
		if channel.guild:
			channels_data = [format_channel(c) for c in channel.guild.channels]
			await self.client.state_store.set_channels(channel.guild.id, channels_data)

	@commands.Cog.listener()
	async def on_guild_channel_update(self, _before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
		if after.guild:
			channels_data = [format_channel(c) for c in after.guild.channels]
			await self.client.state_store.set_channels(after.guild.id, channels_data)

	@commands.Cog.listener()
	async def on_guild_role_create(self, role: discord.Role) -> None:
		if role.guild:
			roles_data = [format_role(r) for r in role.guild.roles]
			await self.client.state_store.set_roles(role.guild.id, roles_data)

	@commands.Cog.listener()
	async def on_guild_role_delete(self, role: discord.Role) -> None:
		if role.guild:
			roles_data = [format_role(r) for r in role.guild.roles]
			await self.client.state_store.set_roles(role.guild.id, roles_data)

	@commands.Cog.listener()
	async def on_guild_role_update(self, _before: discord.Role, after: discord.Role) -> None:
		if after.guild:
			roles_data = [format_role(r) for r in after.guild.roles]
			await self.client.state_store.set_roles(after.guild.id, roles_data)


async def setup(client: Bot) -> None:
	await client.add_cog(StateSync(client))
