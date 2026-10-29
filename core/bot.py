import asyncio
import contextlib
import datetime
import json
import os
import socket
import sys
import traceback
from io import StringIO
from logging import getLogger
from pathlib import Path
from time import perf_counter
from typing import Any

import aiohttp
import asyncpg
import discord
import discord.http
import wavelink
import yarl
from discord import app_commands
from discord.ext import commands, localization
from discord.gateway import DiscordWebSocket
from discord.shard import Shard
from discord.utils import MISSING
from helpers import custom_response, seconds_to_text

from core import Command, Context, SlashCommandLocalizer, slash_command_localization, update_slash_localizations
from core.clustering import (
	ClusterConfig,
	EventBus,
	InMemoryMessageBuffer,
	InMemoryStateStore,
	LocalEventBus,
	MessageBuffer,
	NullSessionPersister,
	RedisMessageBuffer,
	RedisPubSubBus,
	RedisSessionPersister,
	RedisShardCoordinator,
	RedisStateStore,
	SessionPersister,
	ShardCoordinator,
	StandaloneCoordinator,
	StateStore,
)
from core.config import Config

__all__ = ("Bot",)


class Bot(commands.AutoShardedBot):
	def __init__(self, config: Config):
		self.config = config
		self.cluster_config = ClusterConfig.from_env()

		if self.cluster_config.discord_proxy_url:
			proxy_url = self.cluster_config.discord_proxy_url.rstrip("/")
			discord.http.Route.BASE = proxy_url

		update_slash_localizations()
		self._sentry_enabled = False
		self.debug: bool = config.debug
		self.logger = getLogger(__name__)
		self.uptime: datetime.datetime | MISSING = None
		self.lavalink: dict[str, wavelink.Node] | MISSING = None
		intents: discord.Intents = discord.Intents.all()
		self.db: asyncpg.Pool | MISSING = None
		self.session: aiohttp.ClientSession | None = None
		self.owner_ids: set[int] = set(config.owner_ids)

		shard_count = self.cluster_config.shard_count if self.cluster_config.is_clustered else None

		super().__init__(
			command_prefix=Bot.fetch_prefix,
			heartbeat_timeout=150.0,
			intents=intents,
			case_insensitive=False,
			activity=discord.CustomActivity(name="Bot starting...", emoji="🟡"),
			status=discord.Status.idle,
			chunk_guilds_at_startup=False,
			member_cache_flags=discord.MemberCacheFlags.from_intents(intents),
			max_messages=None,
			shard_count=shard_count,
			allowed_contexts=app_commands.AppCommandContext(**config.allowed_contexts),
			allowed_installs=app_commands.AppInstallationType(**config.allowed_installs),
			allowed_mentions=discord.AllowedMentions(**config.allowed_mentions),
		)

		if self.cluster_config.is_clustered:
			self.state_store: StateStore = RedisStateStore.from_url(self.cluster_config.redis_url)
			self.event_bus: EventBus = RedisPubSubBus.from_url(self.cluster_config.redis_url)
			self.message_buffer: MessageBuffer = RedisMessageBuffer.from_url(self.cluster_config.redis_msg_url)
			self.coordinator: ShardCoordinator = RedisShardCoordinator.from_url(
				self.cluster_config.redis_url,
				cluster_id=self.cluster_config.cluster_id,
				lease_ttl=self.cluster_config.lease_ttl,
				heartbeat_interval=self.cluster_config.heartbeat_interval,
				explicit_shard_ids=self.cluster_config.shard_ids,
			)
			self.session_persister: SessionPersister = RedisSessionPersister.from_url(
				self.cluster_config.redis_url, session_ttl=self.cluster_config.lease_ttl * 3
			)
		else:
			self.state_store = InMemoryStateStore()
			self.event_bus = LocalEventBus()
			self.message_buffer = InMemoryMessageBuffer()
			self.coordinator = StandaloneCoordinator()
			self.session_persister = NullSessionPersister()

		self.message_logging_guilds: set[int] = set()
		self._health_task: asyncio.Task | None = None
		self.prefix_cache: dict[int, tuple[str | list[str], bool]] = {}
		self.custom_response = custom_response.CustomResponse(self)
		self._error_webhook: discord.Webhook | None = None

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

	async def get_context(self, origin: discord.Message | discord.Interaction, /, *, cls=None) -> Any:
		return await super().get_context(origin, cls=Context)

	async def setup_hook(self):
		self.logger.info("Running initial setup hook...")
		benchmark = perf_counter()

		try:
			await self.database_initialization()
		except asyncpg.InvalidAuthorizationSpecificationError:
			self.logger.exception("Failed to connect to database")
			sys.exit()

		await self.message_buffer.start()
		await self.event_bus.start()
		await self.event_bus.subscribe("fm01:events", self._on_cluster_event)

		if self.cluster_config.is_clustered:
			claimed_shards = await self.coordinator.acquire_shards(
				self.cluster_config.shard_count, self.cluster_config.shards_per_cluster
			)
			self.shard_ids = claimed_shards
			self.shard_count = self.cluster_config.shard_count
			self._connection.shard_count = self.shard_count
			self._connection.shard_ids: list[int] = self.shard_ids  # type: ignore
			await self.coordinator.start_heartbeat()

		await self.load_cogs()
		await self.cache_prefixes()
		await self.refresh_logging_guilds()
		await self.tree.set_translator(SlashCommandLocalizer())
		self.session = aiohttp.ClientSession(
			connector=aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver(), family=socket.AF_INET)
		)
		end = perf_counter() - benchmark
		self.logger.debug(f"Initial setup hook complete in {end:.2f}s")

	async def refresh_logging_guilds(self) -> None:
		try:
			rows = await self.db.fetch(
				"SELECT guild_id FROM log WHERE is_on = true AND ('on_message_delete' = ANY(modules) OR 'on_message_edit' = ANY(modules))"
			)
			self.message_logging_guilds = {int(r["guild_id"]) for r in rows}
			self.logger.debug(f"Cached {len(self.message_logging_guilds)} active message logging guilds")
		except Exception:
			self.logger.exception("Failed to load message logging guilds")

	async def _on_cluster_event(self, event: dict[str, Any]) -> None:
		event_type = event.get("type")
		guild_id = event.get("guild_id")
		if event_type == "INVALIDATE_PREFIX" and guild_id:
			self.prefix_cache.pop(int(guild_id), None)
		elif event_type == "INVALIDATE_LOG_CONFIG" and guild_id:
			await self.refresh_logging_guilds()

	async def on_message(self, message: discord.Message) -> None:
		if message.author.bot:
			return

		if message.guild and message.guild.id in self.message_logging_guilds:
			self.message_buffer.enqueue_message(message)

		prefix_entry = self.prefix_cache.get(message.guild.id)
		if prefix_entry:
			prefix, mention = prefix_entry
			prefixes: list[str] = [prefix] if isinstance(prefix, str) else list(prefix)
		else:
			prefixes = ["?!", "?"]
			mention = True

		content = message.content
		is_command = False
		for p in prefixes:
			if content.startswith(p):
				is_command = True
				break

		if (
			not is_command
			and mention
			and self.user
			and content.startswith((f"<@{self.user.id}>", f"<@!{self.user.id}>"))
		):
			is_command = True

		if not is_command:
			return

		await self.process_commands(message)

	async def launch_shard(self, gateway: yarl.URL, shard_id: int, *, initial: bool = False) -> None:
		session = await self.session_persister.get_session(shard_id)
		if session and session.get("session_id") and session.get("sequence") is not None:
			resume_gateway = yarl.URL(session["gateway"]) if session.get("gateway") else gateway
			try:
				coro = DiscordWebSocket.from_client(
					self,
					initial=False,
					gateway=resume_gateway,
					shard_id=shard_id,
					session=session["session_id"],
					sequence=session["sequence"],
					resume=True,
				)
				ws = await asyncio.wait_for(coro, timeout=self.shard_connect_timeout)
				self._AutoShardedClient__shards[shard_id] = ret = Shard(  # type: ignore
					ws,
					self,
					self._AutoShardedClient__queue.put_nowait,  # type: ignore
				)
				ret.launch()
				self.logger.info(f"Shard {shard_id} successfully RESUMED gateway session {session.get('session_id')}")
				return
			except (discord.DiscordException, aiohttp.ClientError, TimeoutError, OSError) as e:
				self.logger.warning(
					f"Failed to resume session for shard {shard_id}: {e}. Falling back to cold identify..."
				)
				await self.session_persister.clear_session(shard_id)

		await super().launch_shard(gateway, shard_id, initial=initial)

	async def before_identify_hook(self, shard_id: int | None, *, initial: bool = False) -> None:
		if shard_id is not None and self.cluster_config.is_clustered:
			await self.session_persister.acquire_identify_lock(shard_id, self.cluster_config.max_concurrency)
		await super().before_identify_hook(shard_id, initial=initial)

	async def _health_reporting_loop(self) -> None:
		while not self.is_closed():
			try:
				await asyncio.sleep(10)
				for shard_id, shard in self.shards.items():
					ws = getattr(shard, "ws", None)
					latency = getattr(ws, "latency", -1.0) if ws else -1.0
					guild_count = sum(1 for g in self.guilds if g.shard_id == shard_id)
					status = "ready" if self.is_ready() else "connecting"
					await self.coordinator.update_health(shard_id, latency, guild_count, status)
			except asyncio.CancelledError:
				break
			except (discord.DiscordException, OSError) as e:
				self.logger.debug(f"Error in shard health reporting loop: {e}")

	async def close(self) -> None:
		self.logger.debug("Running bot shutdown hook...")
		if self._health_task and not self._health_task.done():
			self._health_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await self._health_task

		if self.cluster_config.is_clustered:
			sessions: dict[int, dict[str, Any]] = {}
			for shard_id, shard in self.shards.items():
				ws = getattr(shard, "ws", None)
				if ws and getattr(ws, "session_id", None) and getattr(ws, "sequence", None) is not None:
					sessions[shard_id] = {
						"session_id": ws.session_id,
						"sequence": ws.sequence,
						"gateway": str(getattr(ws, "gateway", "")),
					}
			if sessions:
				await self.session_persister.save_sessions(sessions)

			for shard in self.shards.values():
				ws = getattr(shard, "ws", None)
				if ws and hasattr(ws, "socket") and ws.socket and not ws.socket.closed:
					with contextlib.suppress(Exception):
						await ws.socket.close(code=4000)

		await self.coordinator.release_shards()
		await self.coordinator.close()
		await self.message_buffer.close()
		await self.event_bus.close()
		await self.state_store.close()
		await self.session_persister.close()

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
		self.db = await asyncpg.create_pool(
			host=os.getenv("DB_HOST"),
			database=os.getenv("DB_NAME"),
			user=os.getenv("DB_USER"),
			password=os.getenv("DB_PASSWORD"),
			port=os.getenv("DB_PORT"),
			timeout=None,
			init=self.db_connection_init,
			max_inactive_connection_lifetime=120,  # timeout is 2 mins
			max_size=50,
		)
		end = perf_counter() - benchmark
		self.logger.debug(f"Connected to database in {end:.2f}s")

	async def load_cogs(self):
		self.logger.info("Loading cogs...")
		benchmark = perf_counter()

		allowed: list[str] = self.config.modules
		self.logger.debug(f"Allowed cogs: {', '.join(allowed)}")

		cogs = Path("cogs").glob("*.py")
		for cog in cogs:
			if cog.stem in allowed or "*" in allowed:  # if you're having issues with cogs not loading, check this list
				await self.load_extension(f"cogs.{cog.stem}")
				self.logger.debug(f"Loaded extension {cog.name}")
		for module in allowed:
			if module != "*" and not (Path("cogs") / f"{module}.py").exists():
				await self.load_extension(module)
				self.logger.debug(f"Loaded external extension {module}")
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
		if self.cluster_config.is_clustered and (self._health_task is None or self._health_task.done()):
			self._health_task = asyncio.create_task(self._health_reporting_loop())

	async def handle_error(self, ctx: Context, error: commands.CommandError | app_commands.AppCommandError):
		command = None
		if isinstance(ctx, (Context, commands.Context)) or hasattr(ctx, "command") and ctx.command:
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
				]

				await ctx.send("errors.bot_missing_permissions", command=command, permissions=", ".join(permissions))
			case commands.MissingPermissions() | app_commands.MissingPermissions():
				permissions: list[str] = [
					(await self.custom_response(f"permissions.{permission}", ctx))
					for permission in error.missing_permissions
				]

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

				# show original error for chained exceptions
				root_exc = getattr(error, "original", None) or error.__cause__
				if not root_exc and error.__context__ and not error.__suppress_context__:
					root_exc = error.__context__
				target_exc = root_exc or error

				stack = "".join(traceback.format_exception(type(target_exc), target_exc, target_exc.__traceback__))

				# if stack is more than 1700 characters, make it a file
				too_long = len(stack) > 1700
				file: discord.File | None = None
				if too_long:
					s = StringIO()
					s.write(stack)
					s.seek(0)
					file = discord.File(s, filename="error.txt")  # type: ignore # stringIO is supported
					message_stack = "The stack trace was too long to send in a message, so it was saved as a file."
				else:
					message_stack = stack

				# if debug is on, bypass Sentry entirely and send the error directly to the current channel
				if self.debug:
					await ctx.reply(
						content=f"```{message_stack}```",
						file=file if too_long and file else discord.abc.MISSING,
						mention_author=False,
					)
					return

				# if sentry is enabled, capture error with rich context and return Sentry event ID
				if self._sentry_enabled:
					import sentry_sdk

					with sentry_sdk.new_scope() as scope:
						if ctx.author:
							scope.set_user({"id": str(ctx.author.id), "username": str(ctx.author)})
						if ctx.command:
							scope.set_tag("command", ctx.command.qualified_name)
						if ctx.guild:
							scope.set_tag("guild_id", str(ctx.guild.id))
							scope.set_extra("guild_name", ctx.guild.name)
						else:
							scope.set_tag("guild_id", "DM")
						if ctx.channel:
							scope.set_tag("channel_id", str(ctx.channel.id))
							scope.set_extra("channel_name", getattr(ctx.channel, "name", str(ctx.channel)))
						if ctx.message:
							scope.set_extra("message_id", ctx.message.id)
						elif ctx.interaction:
							scope.set_extra("interaction_id", ctx.interaction.id)

						report_id = sentry_sdk.capture_exception(target_exc, scope=scope)

					if not report_id:
						report_id = ctx.message.id if ctx.message else (ctx.interaction.id if ctx.interaction else 0)

					await ctx.reply(
						content=f"An error has occured and has been reported to the developers. Report ID: `{report_id}`",
						mention_author=False,
					)
					return

				# old fashioned way: log via webhook if available
				channel = await self.fetch_channel(self.config.log_channel_id)
				if channel and isinstance(channel, discord.TextChannel):
					webhook = self._error_webhook
					if not webhook and self.user:
						try:
							webhooks = await channel.webhooks()
							webhook = discord.utils.get(webhooks, name=f"{self.user.display_name} Errors")
							if not webhook:
								avatar = await ctx.me.avatar.read() if ctx.me.avatar else None
								webhook = await channel.create_webhook(
									name=f"{self.user.display_name} Errors", avatar=avatar
								)
							self._error_webhook = webhook
						except discord.HTTPException as e:
							self.logger.warning(f"Failed to fetch or create error webhook: {e}")
							webhook = None
					if webhook:
						try:
							await webhook.send(
								content=f"**ID:** {ctx.message.id if ctx.message else 0}\n"
								f"**Guild:** {ctx.guild.name if ctx.guild else 'DMs'} / {ctx.guild.id if ctx.guild else 0}\n"
								f"**User:** {ctx.author} / {ctx.author.id if ctx.author else 0}\n"
								f"**Command:** {ctx.command}\n"
								f"```{message_stack}```",
								file=file if too_long and file else discord.abc.MISSING,
							)
						except discord.HTTPException as e:
							self.logger.warning(f"Failed to send error to webhook: {e}")
				await ctx.reply(
					content=f"An error has occured and has been reported to the developers. Report ID: `{ctx.message.id if ctx.message else 0}`",
					mention_author=False,
				)

	async def on_command_error(self, ctx: Context, error: commands.CommandError):  # type: ignore
		await self.handle_error(ctx, error)

	async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
		await self.handle_error(await Context.from_interaction(interaction), error)

	async def before_invoke(self, ctx: Context):  # type: ignore
		if ctx.guild and ctx.guild.id not in self.prefix_cache:
			is_set_up: bool = await self.db.fetchrow("SELECT * FROM guilds WHERE guild_id = $1", ctx.guild.id)
			if not is_set_up:
				await self.db.execute("INSERT INTO guilds (guild_id) VALUES ($1)", ctx.guild.id)
				self.prefix_cache[ctx.guild.id] = ("?!", True)
		try:
			# Signals that the bot is still thinking / performing a task
			if ctx.interaction and ctx.interaction.type == discord.InteractionType.application_command:
				await ctx.interaction.response.defer(thinking=True)
			else:
				await ctx.message.add_reaction(self.config.emojis.get("loading", ""))
		except discord.HTTPException:
			pass

	async def after_invoke(self, ctx: Context):  # type: ignore
		if ctx.interaction:
			return
		try:
			await ctx.message.remove_reaction(self.config.emojis.get("loading", ""), ctx.me)
		except discord.HTTPException:
			pass
