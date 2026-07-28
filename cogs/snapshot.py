import asyncio
import datetime
import json
import uuid
from typing import Optional, Union
from uuid import UUID

import asyncpg
import discord
from core import Bot, Context, group
from discord import app_commands
from discord.ext import commands


class Snapshot(commands.Cog, name="Snapshots"):
	def __init__(self, client: Bot):
		self.client = client
		self.connection: asyncpg.Pool = client.db
		self.custom_response = client.custom_response

	@staticmethod
	async def save(ctx: Context) -> dict:
		"""
		Creates a snapshot of the server.

		Parameters
		----------
		ctx: `Context`
		        The context to get the guild data from.

		Returns
		-------
		`dict`
		        The payload of the snapshot.
		"""
		payload = {"roles": {}, "channels": {}}

		for x in ctx.guild.roles:
			payload["roles"][x.id] = {
				"perms": x.permissions.value,
				"color": x.color.value,
				"hoist": x.hoist,
				"managable": x.managed,
				"position": x.position,
				"name": x.name,
				"display_icon": (await x.display_icon.read()).decode("latin1")
				if x.display_icon and x.display_icon is discord.Asset
				else x.display_icon
				if x.display_icon
				else None,
			}

		for x in ctx.guild.channels:
			payload["channels"][x.id] = {
				"position": x.position,
				"type": str(x.type),
				"category": x.category.name if x.category else None,
				"name": x.name,
				"bitrate": x.bitrate if x.type == [discord.ChannelType.voice] else None,
				"slowmode": x.slowmode_delay
				if x.type
				not in [discord.ChannelType.voice, discord.ChannelType.category, discord.ChannelType.stage_voice]
				else None,
				"nsfw": x.is_nsfw()
				if x.type
				not in [discord.ChannelType.voice, discord.ChannelType.category, discord.ChannelType.stage_voice]
				else None,
				"user_limit": x.user_limit if x.type in [discord.ChannelType.voice] else None,
				"topic": x.topic if x.type not in [discord.ChannelType.voice, discord.ChannelType.category] else None,
				"permission_sync": x.permissions_synced if x.type not in [discord.ChannelType.category] else None,
				"default_auto_archive_duration": x.default_auto_archive_duration
				if x.type in [discord.ChannelType.text, discord.ChannelType.forum]
				else 0,
				"rtc_region": x.rtc_region if x.type in [discord.ChannelType.voice] else None,
			}
			payload["channels"][x.id]["overwrites"] = {}
			for y in x.overwrites:
				payload["channels"][x.id]["overwrites"][y.id] = {
					"allow": x.overwrites[y].pair()[0].value,
					"deny": x.overwrites[y].pair()[1].value,
					"role": y.name,
				}

		return payload

	async def create_snapshot(self, ctx: Context) -> Optional[UUID]:
		"""
		Creates a snapshot and inserts it into the database.

		Parameters
		----------
		ctx: `Context`
		        The context to get the guild data from.

		Returns
		-------
		`UUID`
		        Code (`UUID`) if the snapshot was successful.
		"""
		payload = await self.save(ctx)

		code = uuid.uuid4()
		row = await self.connection.fetchrow("SELECT * FROM snapshots WHERE code = $1", str(code))
		while row:  # if the code already exists
			code = uuid.uuid4()
			row = await self.connection.fetchrow("SELECT * FROM snapshots WHERE code = $1", str(code))

		await self.connection.execute(
			"INSERT INTO snapshots(guild_id, name, payload, author_id, date, code) VALUES($1, $2, $3, $4, $5, $6)",
			ctx.guild.id,
			await self.custom_response("snapshot.strings.server_snapshot", ctx),
			json.dumps(payload),
			ctx.author.id,
			datetime.datetime.now(),
			str(code),
		)

		return code

	async def get_snapshot(self, code: Union[str, UUID]) -> Optional[dict]:
		"""
		Gets a snapshot from the database.

		Parameters
		----------
		code: Union[`str`, `UUID`]
		        The code of the snapshot.

		Returns
		-------
		`dict`
		        The snapshot's payload.
		"""
		payload = await self.connection.fetchval("SELECT payload FROM snapshots WHERE code = $1", code)
		if payload:
			return json.loads(payload)
		else:
			return None

	async def delete_all_channels(self, ctx: Context):
		"""
		Deletes all channels in the server.

		Parameters
		----------
		ctx: `Context`
		        The context to get the guild data from.
		"""
		for x in ctx.guild.channels:
			try:
				await x.delete(reason=await self.custom_response("snapshot.strings.save_load_reason", ctx))
			except (discord.Forbidden, discord.NotFound, discord.HTTPException):
				continue
			await asyncio.sleep(0.5)

	async def delete_all_roles(self, ctx: Context):
		"""
		Deletes all roles in the server.

		Parameters
		----------
		ctx: `Context`
		        The context to get the guild data from.
		"""
		for x in ctx.guild.roles:
			try:
				await x.delete(reason=await self.custom_response("snapshot.strings.save_load_reason", ctx))
			except (discord.Forbidden, discord.NotFound, discord.HTTPException):
				continue
			await asyncio.sleep(0.5)

	async def load_snapshot(self, ctx: Context, payload: dict):
		for x in sorted(payload["roles"], key=lambda r: payload["roles"][r]["position"], reverse=True):
			perms = discord.Permissions(permissions=int(payload["roles"][x]["perms"]))
			if payload["roles"][x]["color"]:
				color = discord.Colour(int(payload["roles"][x]["color"]))
			else:
				color = None
			if not payload["roles"][x]["name"] == "@everyone":
				try:
					dicon = (
						payload["roles"][x]["display_icon"].encode("latin1")
						if payload["roles"][x]["display_icon"]
						else None
					)
				except (AttributeError, TypeError):
					dicon = payload["roles"][x]["display_icon"] if payload["roles"][x]["display_icon"] else None
				role = await ctx.guild.create_role(
					name=payload["roles"][x]["name"],
					permissions=perms,
					colour=color,
					hoist=bool(payload["roles"][x]["hoist"]),
					reason=await self.custom_response("snapshot.strings.save_load_reason", ctx),
					display_icon=dicon if "ROLE_ICONS" in ctx.guild.features else None,
				)
				await asyncio.sleep(0.5)
		for y in sorted(payload["channels"], key=lambda x: payload["channels"][x]["type"]):
			x = payload["channels"][y]
			if x["type"] == "text" or x["type"] == "news":
				try:
					cat = discord.utils.get(ctx.guild.categories, name=x["category"])
					overwrites = {}
					for z in x["overwrites"]:
						role = discord.utils.get(ctx.guild.roles, name=x["overwrites"][z]["role"])
						if role:
							overwrites[role] = discord.PermissionOverwrite.from_pair(
								discord.Permissions(x["overwrites"][z]["allow"]),
								discord.Permissions(x["overwrites"][z]["deny"]),
							)
					await ctx.guild.create_text_channel(
						name=x["name"],
						category=cat if cat else None,
						position=int(x["position"]),
						reason=await self.custom_response("snapshot.strings.save_load_reason", ctx),
						slowmode_delay=int(x["slowmode"]) if x["slowmode"] else None,
						topic=x["topic"] if x["topic"] else None,
						nsfw=bool(x["nsfw"]),
						overwrites=overwrites,
						news=x["type"] == "news",
						default_auto_archive_duration=x["default_auto_archive_duration"],
					)
					await asyncio.sleep(0.5)
				except (discord.Forbidden, discord.HTTPException):
					continue
			elif x["type"] == "voice":
				try:
					cat = discord.utils.get(ctx.guild.categories, name=x["category"])
					overwrites = {}
					for z in x["overwrites"]:
						role = discord.utils.get(ctx.guild.roles, name=x["overwrites"][z]["role"])
						if role:
							overwrites[role] = discord.PermissionOverwrite.from_pair(
								discord.Permissions(x["overwrites"][z]["allow"]),
								discord.Permissions(x["overwrites"][z]["deny"]),
							)
					await ctx.guild.create_voice_channel(
						name=x["name"],
						category=cat if cat else None,
						position=int(x["position"]),
						reason=await self.custom_response("snapshot.strings.save_load_reason", ctx),
						bitrate=int(x["bitrate"]) if x["bitrate"] else None,
						user_limit=int(x["user_limit"]) if x["user_limit"] else None,
						overwrites=overwrites,
						rtc_region=x["rtc_region"],
					)
					await asyncio.sleep(0.5)
				except (discord.Forbidden, discord.HTTPException):
					continue
			elif x["type"] == "stage_voice":
				try:
					cat = discord.utils.get(ctx.guild.categories, name=x["category"])
					overwrites = {}
					for z in x["overwrites"]:
						role = discord.utils.get(ctx.guild.roles, name=x["overwrites"][z]["role"])
						if role:
							overwrites[role] = discord.PermissionOverwrite.from_pair(
								discord.Permissions(x["overwrites"][z]["allow"]),
								discord.Permissions(x["overwrites"][z]["deny"]),
							)
					await ctx.guild.create_stage_channel(
						name=x["name"],
						category=cat if cat else None,
						position=int(x["position"]),
						reason=await self.custom_response("snapshot.strings.save_load_reason", ctx),
						overwrites=overwrites,
					)
					await asyncio.sleep(0.5)
				except (discord.Forbidden, discord.HTTPException):
					continue
			elif x["type"] == "category":
				try:
					overwrites = {}
					for z in x["overwrites"]:
						role = discord.utils.get(ctx.guild.roles, name=x["overwrites"][z]["role"])
						if role:
							overwrites[role] = discord.PermissionOverwrite.from_pair(
								discord.Permissions(x["overwrites"][z]["allow"]),
								discord.Permissions(x["overwrites"][z]["deny"]),
							)
					await ctx.guild.create_category(
						name=x["name"],
						position=int(x["position"]),
						reason=await self.custom_response("snapshot.strings.save_load_reason", ctx),
						overwrites=overwrites,
					)
					await asyncio.sleep(0.5)
				except (discord.Forbidden, discord.HTTPException):
					continue
			elif x["type"] == "forum":
				try:
					overwrites = {}
					for z in x["overwrites"]:
						role = discord.utils.get(ctx.guild.roles, name=x["overwrites"][z]["role"])
						if role:
							overwrites[role] = discord.PermissionOverwrite.from_pair(
								discord.Permissions(x["overwrites"][z]["allow"]),
								discord.Permissions(x["overwrites"][z]["deny"]),
							)
					cat = discord.utils.get(ctx.guild.categories, name=x["category"])
					await ctx.guild.create_forum(
						name=x["name"],
						category=cat if cat else None,
						position=int(x["position"]),
						reason=await self.custom_response("snapshot.strings.save_load_reason", ctx),
						nsfw=bool(x["nsfw"]),
						topic=x["topic"] if x["topic"] else None,
						default_thread_slowmode_delay=int(x["slowmode"]) if x["slowmode"] else None,
						overwrites=overwrites,
						default_auto_archive_duration=x["default_auto_archive_duration"],
					)
					await asyncio.sleep(0.5)
				except (discord.Forbidden, discord.HTTPException):
					continue

	@group(permissions=["administrator"])
	async def snapshot(self, ctx: Context):
		code = await self.create_snapshot(ctx)

		await ctx.send("snapshot.create", code=code)

	@snapshot.command(l10n_key="ss_load", permissions=["administrator"])
	async def load(self, ctx: Context, code: str):
		payload = await self.get_snapshot(code)
		if not payload:
			await ctx.send("snapshot.not_found")
			return

		old = await self.create_snapshot(ctx)

		await self.delete_all_channels(ctx)
		await self.delete_all_roles(ctx)
		await self.load_snapshot(ctx, payload)

		if not ctx.guild.owner_id == ctx.author.id:  # prevent griefs by sending the code to the owner
			alert = await self.custom_response("snapshot.owner_alert", ctx, code=old)
			alert.pop("reply", None)  # type: ignore
			alert.pop("ephemeral", None)  # type: ignore
			alert.pop("delete_after", None)  # type: ignore
			await ctx.guild.owner.send(**alert)  # type: ignore

		await ctx.send("snapshot.load")


async def setup(client: Bot):
	await client.add_cog(Snapshot(client))
