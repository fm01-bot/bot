from typing import Optional

import discord
from args import Member, User
from core import Bot, Context, command
from discord import app_commands
from discord.ext import commands
from helpers import regex


@app_commands.guild_only()
@commands.guild_only()
class AFK(commands.Cog):
	def __init__(self, client: Bot):
		self.client = client
		self.custom_response = client.custom_response

	@commands.Cog.listener("on_message")
	async def check_afk(self, message: discord.Message) -> None:
		"""Listens to messages sent. If the author of the message is AFK, turn AFK off."""
		if not message.guild:
			return
		row = await self.client.db.fetchrow(
			"SELECT * FROM afk WHERE guild_id = $1 AND user_id = $2 AND state = TRUE",
			message.guild.id,
			message.author.id,
		)
		if not row:
			return

		# Turn off AFK
		ctx = await self.client.get_context(message)

		if ctx.command and ctx.command.name == "afk":
			return

		await self.client.db.execute(
			"UPDATE afk SET state = $1 WHERE user_id = $2 AND guild_id = $3", False, ctx.author.id, ctx.guild.id
		)
		try:
			await ctx.author.edit(nick=row["previous_nick"])
		except discord.Forbidden:
			pass
		await ctx.reply("afk.off")

	@commands.Cog.listener("on_message")
	async def answer_afk_reason(self, message: discord.Message) -> None:
		"""Listens to messages. Replies with the AFK reason(s) if mentioned users are AFK."""
		if message.author.bot or not message.guild or not message.mentions:
			return

		ctx = await self.client.get_context(message)

		afk_lines = []

		for user in message.mentions:
			row = await self.client.db.fetchrow(
				"SELECT * FROM afk WHERE guild_id = $1 AND user_id = $2 AND state = TRUE", message.guild.id, user.id
			)

			if row and row["user_id"] != message.author.id:
				# Use localization for each AFK user
				text = await self.custom_response(
					"afk.reason",
					ctx,
					user=User.from_user(user) if isinstance(user, discord.User) else Member.from_member(user),
					reason=row["message"],
				)
				if isinstance(text, dict):
					afk_lines.append(text["content"])
		if not afk_lines:
			return

		final_message = "\n".join(afk_lines)
		await ctx.reply(final_message)

	@command(user=False)
	async def afk(self, ctx: Context, reason: Optional[str] = None):
		reason_text = reason
		if not reason:
			reason_text = await self.custom_response("afk.dnd", ctx)

		if isinstance(reason_text, str) and regex.DISCORD_INVITE.search(reason_text):
			return await ctx.send("afk.link")

		row = await self.client.db.fetchrow(
			"SELECT * FROM afk WHERE user_id = $1 AND guild_id = $2", ctx.author.id, ctx.guild.id
		)
		if not row:
			await self.client.db.execute(
				"INSERT INTO afk (user_id, guild_id, message, state, previous_nick) VALUES($1, $2, $3, $4, $5)",
				ctx.author.id,
				ctx.guild.id,
				reason,
				True,
				ctx.author.display_name,
			)
			try:
				await ctx.author.edit(
					nick=(await self.custom_response("afk.name", ctx, nickname=ctx.author.display_name))
				)
			except discord.errors.Forbidden:
				pass
			return await ctx.send("afk.on")

		if row["state"]:
			# Turn off AFK
			await self.client.db.execute(
				"UPDATE afk SET state = $1 WHERE user_id = $2 AND guild_id = $3", False, ctx.author.id, ctx.guild.id
			)
			try:
				await ctx.author.edit(nick=row["previous_nick"])
			except discord.Forbidden:
				pass
			return await ctx.send("afk.off")
		else:
			# Turn on AFK
			await self.client.db.execute(
				"UPDATE afk SET state = $1, message = $2, previous_nick = $3 WHERE user_id = $4 AND guild_id = $5",
				True,
				reason,
				ctx.author.display_name,
				ctx.author.id,
				ctx.guild.id,
			)
			try:
				await ctx.author.edit(
					nick=(await self.custom_response("afk.name", ctx, nickname=ctx.author.display_name))
				)
			except discord.Forbidden:
				pass
			return await ctx.send("afk.on")


async def setup(client: Bot):
	await client.add_cog(AFK(client))
