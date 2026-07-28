import asyncio
import random
from datetime import datetime, timedelta
from logging import getLogger
from typing import Optional

import discord
import helpers
from args import FormatDateTime
from core import Bot, Context, command
from discord import app_commands
from discord.ext import commands

logger = getLogger(__name__)


class Giveaway(commands.Cog, name="Giveaway"):
	def __init__(self, client: Bot):
		self.client = client
		self.custom_response = client.custom_response
		self.active_giveaways = {}
		self.GIVEAWAY_EMOJI = "🎉"

	async def load_active_giveaways(self):
		giveaways = await self.client.db.fetch("SELECT * FROM giveaway WHERE ended = FALSE")

		for giveaway in giveaways:
			end_time = giveaway["ends_at"]
			self.active_giveaways[giveaway["message_id"]] = {
				"end_time": end_time,
				"winners": giveaway["winners"],
				"channel_id": giveaway["channel_id"],
			}

			self.client.loop.create_task(
				self.end_giveaway(None, giveaway["message_id"], giveaway["channel_id"], datetime.now() >= end_time)
			)

	async def cog_load(self):
		await self.load_active_giveaways()

	async def end_giveaway(self, ctx: Context | None, message_id: int, channel_id: int, right_now: bool = False):
		if message_id not in self.active_giveaways:
			return

		time_until_end = (self.active_giveaways[message_id]["end_time"] - datetime.now()).total_seconds()
		if time_until_end > 0 and not right_now:
			await asyncio.sleep(time_until_end)

		channel = await self.client.fetch_channel(channel_id)
		if not channel:
			return

		try:
			message = await channel.fetch_message(message_id)  # type: ignore

			reaction: Optional[discord.Reaction] = discord.utils.get(message.reactions, emoji=self.GIVEAWAY_EMOJI)
			if not reaction:
				participants = []
			else:
				participants = [user.id async for user in reaction.users() if user.id != self.client.user.id]  # type: ignore

			winners = []
			winner_ids = []
			if participants:
				num_winners = self.active_giveaways[message_id]["winners"]
				winner_ids = random.sample(participants, min(num_winners, len(participants)))
				winners = [f"<@{winner_id}>" for winner_id in winner_ids]

			if winners:
				response = await self.custom_response(
					"giveaway.end.success", ctx or message, winners=", ".join(winners)
				)
				await message.reply(**response)  # type: ignore
			else:
				response = await self.custom_response("giveaway.end.no_winners", ctx or message)
				await message.reply(**response)  # type: ignore

			await self.client.db.execute(
				"UPDATE giveaway SET ended = TRUE, won_by = $1 WHERE message_id = $2", winner_ids, message_id
			)
			del self.active_giveaways[message_id]

			await self.client.db.execute(
				"UPDATE giveaway SET ended = TRUE, won_by = $1 WHERE message_id = $2", winner_ids, message_id
			)

		except discord.NotFound:
			await self.client.db.execute("DELETE FROM giveaway WHERE message_id = $1", message_id)
		except Exception as e:
			logger.error(f"Error ending giveaway: {e}")
			raise e

	@command(user=False)
	async def giveaway(self, ctx: Context, duration: str, winners: str | None = None, *, prize: str | None = None):
		try:
			end_time = datetime.now() + timedelta(seconds=helpers.text_to_seconds(duration))
		except (ValueError, TypeError):
			raise commands.BadArgument

		if winners is not None:
			try:
				winners_count = max(int(winners), 1)
			except ValueError:
				prize = " ".join(filter(None, [winners, prize]))
				winners_count = 1
		else:
			winners_count = 1

		if winners_count < 1 or not prize:
			raise commands.BadArgument("winners,prize")

		message = await ctx.send(
			"giveaway.start.response", prize=prize, winners=winners_count, ends=FormatDateTime(end_time, "R")
		)

		await message.add_reaction(self.GIVEAWAY_EMOJI)

		await self.client.db.execute(
			"INSERT INTO giveaway"
			" (guild_id, channel_id, message_id, author_id, prize, winners, ends_at, ended, won_by)"
			" VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, NULL)",
			ctx.guild.id,
			ctx.channel.id,
			message.id,
			ctx.author.id,
			prize,
			winners_count,
			end_time,
		)

		self.active_giveaways[message.id] = {
			"end_time": end_time,
			"winners": winners_count,
			"channel_id": ctx.channel.id,
		}

		self.client.loop.create_task(self.end_giveaway(ctx, message.id, ctx.channel.id))

	@command(user=False)
	@commands.has_permissions(manage_guild=True)
	async def endgiveaway(self, ctx, message: str):
		try:
			message_id = int(message)
		except ValueError:
			raise commands.BadArgument("message_id")

		if message_id not in self.active_giveaways:
			raise commands.BadArgument("message_id")

		await self.end_giveaway(ctx, message_id, ctx.channel.id, True)


async def setup(client: Bot):
	await client.add_cog(Giveaway(client))
