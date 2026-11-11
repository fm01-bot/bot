from core import Bot, Context
from core.hybrid import command
from discord.ext import commands


class Setup(commands.Cog, name="Setup"):
	def __init__(self, client: Bot):
		self.client = client

	@command(user=False, permissions=["administrator"])
	async def prefix(self, ctx: Context, prefix: str, mention: bool | None = True):
		assert ctx.guild is not None
		if len(prefix) > 10:
			return await ctx.send("setup.prefix.errors.long", prefix=prefix, limit=10)
		mention_val = True if mention is None else bool(mention)
		await self.client.db.execute(
			"UPDATE guilds SET prefix = $1, mention = $2 WHERE guild_id = $3", prefix, mention_val, ctx.guild.id
		)
		self.client.prefix_cache[ctx.guild.id] = (prefix, mention_val)
		if hasattr(self.client, "event_bus"):
			await self.client.event_bus.publish("fm01:events", {"type": "INVALIDATE_PREFIX", "guild_id": ctx.guild.id})
		return await ctx.send("setup.prefix.set", prefix=prefix)


async def setup(client: Bot):
	await client.add_cog(Setup(client))
