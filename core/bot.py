from core.config import Config
import asyncio
import datetime
import json
import os
import socket
import traceback
from io import StringIO
from logging import getLogger
from pathlib import Path
from time import perf_counter
from typing import Any, Optional, Union, cast

import aiohttp
import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, localization
from helpers import custom_response, seconds_to_text
from helpers.emojis import LOADING

from core import Command, Context, SlashCommandLocalizer, slash_command_localization, update_slash_localizations


class Bot(commands.AutoShardedBot):
	def __init__(self, config: Config):
		self.config = config
		update_slash_localizations()
		self.debug: bool = self.config.get("debug")
		self.logger = getLogger(__name__)
		self.uptime: Optional[datetime.datetime] = None
		self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
		intents: discord.Intents = discord.Intents.all()
		self.db: asyncpg.Pool = None
		self.session: aiohttp.ClientSession | None = None
		self.owner_ids: set[int] = set(self.config.get("owner_ids"))
		super().__init__(
			command_prefix=Bot.fetch_prefix,
			heartbeat_timeout=150.0,
			intents=intents,
			case_insensitive=False,
			activity=discord.CustomActivity(name="Bot starting...", emoji="🟡"),
			status=discord.Status.idle,
			chunk_guilds_at_startup=False,
			member_cache_flags=discord.MemberCacheFlags.from_intents(intents),
			max_messages=20000,
			allowed_contexts=app_commands.AppCommandContext(**self.config.get("allowed_contexts")),
			allowed_installs=app_commands.AppInstallationType(**self.config.get("allowed_installs")),
			allowed_mentions=discord.AllowedMentions(**self.config.get("allowed_mentions")),
		)
		self.prefix_cache: dict[int, tuple[str | list[str], bool]] = {}
		self.custom_response = custom_response.CustomResponse(self)

	async def fetch_prefix(self, message: discord.Message) -> str | list[str]:
		if self.debug:
			return "?"
		if not message.guild:
			return "?!"
		if message.guild.id in self.prefix_cache:
			prefix, mention = self.prefix_cache[message.guild.id]
		else:
			row = await self.db.fetchrow("SELECT prefix, mention FROM guilds WHERE guild_id = $1", message.guild.id)
			if row:
				prefix, mention = row.get("prefix", "?!"), row.get("mention", True)
			else:
				prefix, mention = "?!", True
			self.prefix_cache[message.guild.id] = (prefix, mention)
		if mention:
			if isinstance(prefix, str):
				return commands.when_mentioned_or(prefix)(self, message)
			else:
				return commands.when_mentioned_or(*prefix)(self, message)
		else:
			return prefix

	async def request(self, url: str) -> dict:
		if self.session:
			async with self.session.get(url) as response:
				return await response.json()
		else:
			return {"error": 400}

	async def on_guild_join(self, guild: discord.Guild):
		row = await self.db.fetchrow("SELECT * FROM guilds WHERE guild_id = $1", guild.id)
		if not row:
			await self.db.execute("INSERT INTO guilds (guild_id) VALUES ($1)", guild.id)
			self.prefix_cache[guild.id] = ("?!", True)
		else:
			self.prefix_cache[guild.id] = (row.get("prefix", "?!"), row.get("mention", True))

	async def on_guild_remove(self, guild: discord.Guild):
		if guild.id in self.prefix_cache:
			del self.prefix_cache[guild.id]

	async def get_context(self, origin: Union[discord.Message, discord.Interaction], /, *, cls=None) -> Any:
		return await super().get_context(origin, cls=Context)

	async def setup_hook(self):
		self.logger.info("Running initial setup hook...")
		benchmark = perf_counter()

		try:
			await self.database_initialization()
		except asyncpg.InvalidAuthorizationSpecificationError:
			self.logger.error("Failed to connect to database", exc_info=True)
			exit(-1)
		await self.load_cogs()
		await self.cache_prefixes()
		await self.tree.set_translator(SlashCommandLocalizer())
		self.session = aiohttp.ClientSession(
			connector=aiohttp.TCPConnector(resolver=aiohttp.AsyncResolver(), family=socket.AF_INET)
		)
		end = perf_counter() - benchmark
		self.logger.debug(f"Initial setup hook complete in {end:.2f}s")

	async def close(self) -> None:
		self.logger.debug("Running bot shutdown hook...")
		if self.session and not self.session.closed:
			self.logger.debug("Closing aiohttp session...")
			await self.session.close()
		if self.db:
			self.logger.debug("Closing database connection...")
			await self.db.close()
		self.logger.debug("Closing bot superclass...")
		await super().close()
		self.logger.info("Bot closed.")

	@staticmethod
	async def db_connection_init(connection: asyncpg.connection.Connection):
		await connection.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
		await connection.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

	async def database_initialization(self):
		self.logger.info("Connecting to database...")
		benchmark = perf_counter()
		# Connects to database
		self.db = await asyncpg.create_pool(
			host=os.getenv("DB_HOST"),
			database="lumin_beta",
			# ! Replace with default database name when ran for the first time
			# ! Any subsequent executions of this code must use `database="lumin"`
			user="lumin",
			password=os.getenv("DB_PASSWORD"),
			port=os.getenv("DB_PORT"),
			timeout=None,
			init=self.db_connection_init,
			max_inactive_connection_lifetime=120,  # timeout is 2 mins
		)
		end = perf_counter() - benchmark
		self.logger.debug(f"Connected to database in {end:.2f}s")

	async def load_cogs(self):
		self.logger.info("Loading cogs...")
		benchmark = perf_counter()

		allowed: list[str] = self.config.get("modules")
		self.logger.debug(f"Allowed cogs: {', '.join(allowed)}")

		cogs = Path("cogs").glob("*.py")
		for cog in cogs:
			if cog.stem in allowed or "*" in allowed:  # if you're having issues with cogs not loading, check this list
				await self.load_extension(f"cogs.{cog.stem}")
				self.logger.debug(f"Loaded extension {cog.name}")
		end = perf_counter() - benchmark
		self.logger.debug(f"Loaded cogs in {end:.2f}s")

	async def cache_prefixes(self):
		self.logger.info("Caching prefixes...")
		result = await self.db.fetch("SELECT guild_id, prefix, mention FROM guilds")
		for row in result:
			self.prefix_cache[row["guild_id"]] = (row["prefix"], row["mention"])

	async def on_ready(self):
		if not hasattr(self, "uptime"):
			self.uptime = discord.utils.utcnow()
		self.logger.info("Bot is ready!")
		self.logger.info(f"Servers: {len(self.guilds)}, Commands: {len(self.commands)}, Shards: {self.shard_count}")
		self.logger.info(f"Loaded cogs: {', '.join([cog for cog in self.cogs])}")
		self.logger.debug(f"discord-localization v{localization.__version__}")

	async def handle_error(self, ctx: Context, error: Union[commands.CommandError, app_commands.AppCommandError]):
		command = None
		if isinstance(ctx, (Context, commands.Context)):
			command = Command.from_ctx(ctx)
		elif hasattr(ctx, "command") and ctx.command:
			command = Command.from_ctx(ctx)

		if isinstance(error, commands.HybridCommandError):
			error = error.original

		match error:
			case commands.MissingRequiredArgument():
				if slash_command_localization:
					name = slash_command_localization(error.param.name, ctx)
				else:
					name = "-"
				parameter = f"[{name if error.param.required else f'({name})'}]"

				await ctx.send("errors.missing_required_argument", command=command, parameter=parameter)
			case commands.BotMissingPermissions() | app_commands.BotMissingPermissions():
				permissions: list[str] = [
					(await self.custom_response(f"permissions.{permission}", ctx))
					for permission in error.missing_permissions
				]  # type: ignore

				await ctx.send("errors.bot_missing_permissions", command=command, permissions=", ".join(permissions))
			case commands.MissingPermissions() | app_commands.MissingPermissions():
				permissions: list[str] = [
					(await self.custom_response(f"permissions.{permission}", ctx))
					for permission in error.missing_permissions
				]  # type: ignore

				await ctx.send("errors.missing_permissions", command=command, permissions=", ".join(permissions))
			case commands.CommandOnCooldown():
				retry_after = seconds_to_text(int(error.retry_after))
				await ctx.send("errors.command_on_cooldown", command=command, retry_after=retry_after)
			case commands.ChannelNotFound():
				await ctx.send("errors.channel_not_found", command=command)
			case commands.EmojiNotFound():
				await ctx.send("errors.emoji_not_found", command=command)
			case commands.MemberNotFound():
				await ctx.send("errors.member_not_found", command=command)
			case commands.UserNotFound():
				await ctx.send("errors.user_not_found", command=command)
			case commands.RoleNotFound():
				await ctx.send("errors.role_not_found", command=command)
			case commands.BadArgument() | commands.BadUnionArgument():
				await ctx.send("errors.bad_argument", command=command)
				raise error
			case discord.Forbidden():
				await ctx.send("errors.forbidden", command=command)
			case commands.NotOwner():
				await ctx.send("errors.not_owner", command=command)
			case (
				commands.CommandNotFound()
				| app_commands.CommandNotFound()
				| commands.PrivateMessageOnly()
				| commands.NoPrivateMessage()
			):
				return
			case app_commands.CommandSignatureMismatch():
				await ctx.send(
					content=f"The signature for {error.command.qualified_name} is mismatched.\n```{error.command}```"
				)
			case _:
				self.logger.error("An unknown error has occured", exc_info=error)

				# if the error is unknown, log it
				channel = (
					ctx.channel
					if self.debug and ctx and ctx.channel
					else await self.fetch_channel(self.config.get("log_channel_id"))
				)

				if channel and isinstance(channel, discord.TextChannel):
					# show original error for chained exceptions
					root_exc = None
					if getattr(error, "__cause__"):
						root_exc = error.__cause__
					elif getattr(error, "__context__") and not getattr(error, "__suppress_context__"):
						root_exc = error.__context__
					if root_exc:
						stack = "".join(traceback.format_exception(type(root_exc), root_exc, root_exc.__traceback__))
					else:
						stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))

					# if stack is more than 1700 characters, make it a file
					too_long = len(stack) > 1700
					file: discord.File | None = None
					if too_long:
						s = StringIO()
						s.write(stack)
						s.seek(0)
						file = discord.File(s, filename="error.txt")  # type: ignore # stringIO is supported
						stack = "The stack trace was too long to send in a message, so it was saved as a file."

					webhook = None
					if self.user:
						webhook = discord.utils.get(await channel.webhooks(), name=f"{self.user.display_name} Errors")
						if not webhook:
							webhook = await channel.create_webhook(
								name=f"{self.user.display_name} Errors", avatar=await ctx.me.avatar.read()
							)
					if webhook:
						await webhook.send(
							content=f"**ID:** {ctx.message.id}\n"
							f"**Guild:** {ctx.guild.name if ctx.guild else 'DMs'} / {ctx.guild.id if ctx.guild else 0}\n"
							f"**User:** {ctx.author} / {ctx.author.id}\n"
							f"**Command:** {ctx.command}\n"
							f"```{stack}```",
							file=file if too_long and file else discord.abc.MISSING,
						)
					await ctx.reply(
						content=f"An error has occured and has been reported to the developers. Report ID: `{ctx.message.id}`",
						mention_author=False,
					)

	async def on_command_error(self, ctx: Context, error: commands.CommandError):
		await self.handle_error(ctx, error)

	async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
		await self.handle_error(await Context.from_interaction(interaction), error)

	async def before_invoke(self, ctx: Context):  # type: ignore
		if ctx.guild:
			is_set_up: bool = await self.db.fetchrow("SELECT * FROM guilds WHERE guild_id = $1", ctx.guild.id)
			if not is_set_up:
				await self.db.execute("INSERT INTO guilds (guild_id) VALUES ($1)", ctx.guild.id)
		try:
			# Signals that the bot is still thinking / performing a task
			if ctx.interaction and ctx.interaction.type == discord.InteractionType.application_command:
				await ctx.interaction.response.defer(thinking=True)
			else:
				await ctx.message.add_reaction(LOADING)
		except discord.HTTPException:
			pass

	async def after_invoke(self, ctx: Context):  # type: ignore
		if ctx.interaction:
			return
		try:
			await ctx.message.remove_reaction(LOADING, ctx.me)
		except discord.HTTPException:
			pass
