from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core import command
from discord.ext import commands
from helpers.cli_parser import CLIParseError, CLIParser, HelpRequested

from .config_subcommands import register_all_subcommands

if TYPE_CHECKING:
	from core import Bot, Context

logger = logging.getLogger(__name__)


class Config(commands.Cog, name="Config"):
	def __init__(self, client: Bot):
		self.client = client
		self.parser = CLIParser("config", description="Configure bot features with bash-style flags and subcommands.")
		register_all_subcommands(self.parser.root)

	@command(name="config", permissions=["administrator"], user=False)
	async def config_command(self, ctx: Context, *, flags_and_args: str = ""):
		trimmed = flags_and_args.strip()

		if not trimmed:
			help_text = self.parser.root.format_help()
			return await ctx.send(content=f"```ansi\nConfig CLI Help\n\n{help_text}\n```")

		try:
			await self.parser.execute(trimmed, ctx=ctx)
		except HelpRequested as e:
			return await ctx.send(content=f"```ansi\nHelp\n\n{e.help_text}\n```")
		except CLIParseError as e:
			err_msg = f"```ansi\nError: {e.message}\n"
			if e.node:
				err_msg += f"\n{e.node.format_help()}\n"
			err_msg += "```"
			return await ctx.send(content=err_msg)
		except Exception as e:
			logger.exception(f"Unexpected error executing config command with args `{trimmed}`")
			return await ctx.send(content=f"```ansi\nError: {e}\n```")


async def setup(client: Bot):
	await client.add_cog(Config(client))
