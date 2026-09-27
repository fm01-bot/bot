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
		self.afk_cache: dict[tuple[int, int], dict[str, str]] = {}

	async def cog_load(self):
		await self.client.wait_until_ready()
		rows = await self.client.db.fetch(
			"SELECT guild_id, user_id, message, previous_nick FROM afk WHERE state = TRUE"
		)
		for r in rows:
			self.afk_cache[(int(r["guild_id"]), int(r["user_id"]))] = {
				"message": r["message"],
				"previous_nick": r["previous_nick"],
			}

	@commands.Cog.listener("on_message")
	async def check_afk(self, message: discord.Message) -> None:
		"""Listens to messages sent. If the author of the message is AFK, turn AFK off."""
		if not message.guild:
			return
		key = (message.guild.id, message.author.id)
		if key not in self.afk_cache:
			return

		ctx = await self.client.get_context(message)
		if ctx.command and ctx.command.name == "afk":
			return

		data = self.afk_cache.pop(key, None)
		await self.client.db.execute(
			"UPDATE afk SET state = $1 WHERE user_id = $2 AND guild_id = $3", False, ctx.author.id, ctx.guild.id
		)
		if data and data.get("previous_nick"):
			try:
				await ctx.author.edit(nick=data["previous_nick"])
			except (discord.Forbidden, discord.HTTPException):
				pass
		await ctx.reply("afk.off")

	@commands.Cog.listener("on_message")
	async def answer_afk_reason(self, message: discord.Message) -> None:
		"""Listens to messages. Replies with the AFK reason(s) if mentioned users are AFK."""
		if message.author.bot or not message.guild or not message.mentions:
			return

		afk_mentions = [
			u for u in message.mentions if (message.guild.id, u.id) in self.afk_cache and u.id != message.author.id
		]
		if not afk_mentions:
			return

		ctx = await self.client.get_context(message)
		afk_lines = []
		for user in afk_mentions:
			cached = self.afk_cache.get((message.guild.id, user.id))
			if not cached:
				continue
			text = await self.custom_response(
				"afk.reason",
				ctx,
				user=User.from_user(user) if isinstance(user, discord.User) else Member.from_member(user),
				reason=cached["message"],
			)
			if isinstance(text, dict) and "content" in text:
				afk_lines.append(text["content"])

		if afk_lines:
			await ctx.reply("\n".join(afk_lines))

	@command(user=False)
	async def afk(self, ctx: Context, reason: str | None = None):
		reason_text = reason
		if not reason:
			reason_text = await self.custom_response("afk.dnd", ctx)

		if isinstance(reason_text, str) and regex.DISCORD_INVITE.search(reason_text):
			return await ctx.send("afk.link")

		key = (ctx.guild.id, ctx.author.id)
		row = await self.client.db.fetchrow(
			"SELECT * FROM afk WHERE user_id = $1 AND guild_id = $2", ctx.author.id, ctx.guild.id
		)
		if not row:
			await self.client.db.execute(
				"INSERT INTO afk (user_id, guild_id, message, state, previous_nick) VALUES($1, $2, $3, $4, $5)",
				ctx.author.id,
				ctx.guild.id,
				reason_text,
				True,
				ctx.author.display_name,
			)
			self.afk_cache[key] = {"message": str(reason_text), "previous_nick": ctx.author.display_name}
			try:
				nick = await self.custom_response("afk.name", ctx, nickname=ctx.author.display_name)
				if isinstance(nick, str):
					nick = nick[:32]
				await ctx.author.edit(nick=nick)
			except (discord.Forbidden, discord.HTTPException):
				pass
			return await ctx.send("afk.on")

		if row["state"]:
			# Turn off AFK
			self.afk_cache.pop(key, None)
			await self.client.db.execute(
				"UPDATE afk SET state = $1 WHERE user_id = $2 AND guild_id = $3", False, ctx.author.id, ctx.guild.id
			)
			try:
				await ctx.author.edit(nick=row["previous_nick"])
			except (discord.Forbidden, discord.HTTPException):
				pass
			return await ctx.send("afk.off")
		else:
			# Turn on AFK
			self.afk_cache[key] = {"message": str(reason_text), "previous_nick": ctx.author.display_name}
			await self.client.db.execute(
				"UPDATE afk SET state = $1, message = $2, previous_nick = $3 WHERE user_id = $4 AND guild_id = $5",
				True,
				reason_text,
				ctx.author.display_name,
				ctx.author.id,
				ctx.guild.id,
			)
			try:
				nick = await self.custom_response("afk.name", ctx, nickname=ctx.author.display_name)
				if isinstance(nick, str):
					nick = nick[:32]
				await ctx.author.edit(nick=nick)
			except (discord.Forbidden, discord.HTTPException):
				pass
			return await ctx.send("afk.on")


async def setup(client: Bot):
	await client.add_cog(AFK(client))
