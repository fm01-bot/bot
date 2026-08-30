from time import perf_counter

from core import Bot, Context
from core.hybrid import command, group
from discord.ext import commands


class Basic(commands.Cog, name="Basic"):
	def __init__(self, client: Bot):
		self.client = client

	@command()
	async def ping(self, ctx: Context):
		# Database ping calculation
		database_start = perf_counter()
		await self.client.db.execute("SELECT 1")
		database = perf_counter() - database_start

		await ctx.send("ping", latency=float(self.client.latency), db=float(database))


async def setup(client: Bot):
	await client.add_cog(Basic(client))
