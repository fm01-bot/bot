import logging
import random

import discord
from core import Bot
from discord.ext import commands, tasks


class Status(commands.Cog, command_attrs=dict(hidden=True)):
	def __init__(self, client: Bot):
		self.client = client

	@tasks.loop(minutes=1)
	async def update_status(self):
		await self.statusupdate()

	@update_status.before_loop
	async def before_update_status(self):
		await self.client.wait_until_ready()

	async def statusupdate(self) -> None:
		prefix = "?!"
		try:
			random_command = prefix + random.choice(
				[command.qualified_name for command in self.client.commands if not command.hidden]
			)
		except IndexError:
			random_command = prefix + "help"

		await self.client.change_presence(
			activity=discord.CustomActivity(name=f"{len(self.client.guilds)} servers | {random_command}"),
			status=discord.Status.online,
		)

	async def cog_unload(self) -> None:
		self.update_status.cancel()
		logging.info("Status unloaded!")

	async def cog_load(self) -> None:
		if not self.update_status.is_running():
			self.update_status.start()
			logging.info("Status loaded!")


async def setup(client: Bot):
	await client.add_cog(Status(client))
