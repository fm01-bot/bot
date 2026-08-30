import random
from urllib.parse import quote_plus

import discord
from art import text2art
from core import Bot, Context, group
from discord import app_commands
from discord.ext import commands
from helpers import CustomResponse
from helpers.convert import text_to_emoji
from helpers.regex import DISCORD_MESSAGE_URL


class Say(commands.Cog, name="Says"):
	def __init__(self, client: Bot):
		self.client = client
		self.custom_response: CustomResponse = CustomResponse(client)

	@group()
	@commands.has_permissions(manage_messages=True)
	async def say(self, ctx: Context, *, message: commands.Range[str, 1, 2000]):
		await ctx.send("say.message", message=message)

	@say.command(permissions=["manage_messages"], l10n_key="chsay")
	async def channel_say(self, ctx: Context, channel: discord.TextChannel, *, message: commands.Range[str, 1, 2000]):
		await channel.send(message, allowed_mentions=discord.AllowedMentions.none())

	@say.command(permissions=["manage_messages"], l10n_key="editmsg")
	async def edit_message(self, ctx: Context, message_link: str, *, content: commands.Range[str, 1, 2000]):
		match = DISCORD_MESSAGE_URL.search(message_link)
		try:
			if match:
				guild_id, channel_id, message_id = match.groups()
				message = await self.client.get_channel(int(channel_id)).fetch_message(int(message_id))
			else:
				message = await ctx.channel.fetch_message(int(message_link))
		except (discord.NotFound, discord.Forbidden):
			raise commands.BadArgument("message_link")
		try:
			await message.edit(content=content, allowed_mentions=discord.AllowedMentions.none())
		except discord.Forbidden:
			raise commands.MissingPermissions(["manage_messages"])
		except discord.NotFound:
			raise commands.BadArgument("message_link")
		await ctx.send("say.edit")

	@say.command(permissions=["manage_messages"], l10n_key="asciisay")
	async def ascii_say(self, ctx: Context, *, message: commands.Range[str, 1, 20]):
		await ctx.send("say.ascii", ascii=text2art(message))

	@say.command(permissions=["manage_messages"], l10n_key="emojisay")
	async def emoji_say(self, ctx: Context, *, message: commands.Range[str, 1, 20]):
		await ctx.send("say.emoji", emoji=" ".join(text_to_emoji(message)))

	@say.command(permissions=["manage_messages"], l10n_key="mcsay")
	async def achievement_say(self, ctx: Context, *, message: commands.Range[str, 1, 50]):
		icon = random.randint(1, 29)
		localized_title = await self.custom_response("say.achievement.title", ctx)
		achievement_title = quote_plus(localized_title)
		achievement_text = quote_plus(message)
		url = f"https://skinmc.net/achievement/{icon}/{achievement_title}/{achievement_text}"
		await ctx.send("say.achievement.response", achievement=url)

	@say.command(permissions=["manage_messages"])
	async def qr_code(self, ctx: Context, *, data: commands.Range[str, 1, 500]):
		data = quote_plus(data)
		qr = f"https://api.qrserver.com/v1/create-qr-code/?data={data}&size=1000x1000&qzone=2"
		await ctx.send("say.qr", qr=qr)

	@say.command(permissions=["manage_messages"], l10n_key="reversesay")
	async def reverse_say(self, ctx: Context, *, message: commands.Range[str, 1, 2000]):
		await ctx.send("say.reverse", message=message[::-1])

	@say.command(permissions=["manage_messages"], l10n_key="clapsay")
	async def clap_say(self, ctx: Context, *, message: commands.Range[str, 1, 500]):
		await ctx.send("say.clap", message=message.replace(" ", "👏"))


async def setup(client: Bot):
	await client.add_cog(Say(client))
