from typing import Optional

from core import Bot, Context
from core.hybrid import command
from discord.ext import commands


class Setup(commands.Cog, name="Setup"):
	def __init__(self, client: Bot):
		self.client = client

	@command(user=False, permissions=["administrator"])
	async def prefix(self, ctx: Context, prefix: str, mention: Optional[bool] = True):
		if len(prefix) > 10:
			return await ctx.send("setup.prefix.errors.long", prefix=prefix, limit=10)
		await self.client.db.execute(
			"UPDATE guilds SET prefix = $1, mention = $2 WHERE guild_id = $3", prefix, mention, ctx.guild.id
		)
		self.client.prefix_cache[ctx.guild.id] = (prefix, mention or True)
		return await ctx.send("setup.prefix.set", prefix=prefix)


async def setup(client: Bot):
	await client.add_cog(Setup(client))
