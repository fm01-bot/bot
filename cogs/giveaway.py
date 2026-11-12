"""Persistent giveaways with entry requirements, rerolls and restart recovery."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import random
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import discord
from args import Giveaway as GiveawayArg
from core import Bot, Context, group
from core.context import VALID_SEND_KWARGS
from discord.ext import commands, tasks
from helpers import text_to_seconds
from helpers.leveling import level_from_total_xp
from helpers.regex import SNOWFLAKE
from helpers.scheduler import ExpiryScheduler, is_guild_on_shard

logger = logging.getLogger(__name__)

MIN_DURATION = 10
MAX_DURATION = 60 * 86400
MAX_ACTIVE_PER_GUILD = 25
FLUSH_INTERVAL = 5.0
MESSAGE_COOLDOWN = 5.0
RETENTION_DAYS = 30

type GiveawayStatus = Literal["active", "ended", "cancelled"]
type Requirement = Literal["level", "role", "messages"]
type GiveawayChannel = discord.TextChannel | discord.Thread | discord.VoiceChannel | discord.StageChannel

UPSERT_COUNTS = """
	INSERT INTO giveaway_message_counts (giveaway_id, user_id, count)
	VALUES ($1, $2, $3)
	ON CONFLICT (giveaway_id, user_id) DO UPDATE SET count = giveaway_message_counts.count + EXCLUDED.count
"""


def parse_message_id(raw: str | None) -> int | None:
	"""Extract a message ID from a bare snowflake or a message link.

	Args:
		raw: User input.

	Returns:
		int | None: The message ID, or ``None`` if the input contains none.
	"""
	if not raw:
		return None
	match = SNOWFLAKE.search(raw.strip())
	return int(match.group(1)) if match else None


def candidate_message_ids(reference_id: int | None, raw: str | None) -> list[int]:
	"""Return the message IDs to try, in priority order: the replied-to message, then the given ID or link.

	Args:
		reference_id: ID of the message the command replied to, if any.
		raw: The ``message`` argument, if any.

	Returns:
		list[int]: Candidate IDs.
	"""
	candidates: list[int] = []
	for message_id in (reference_id, parse_message_id(raw)):
		if message_id is not None and message_id not in candidates:
			candidates.append(message_id)
	return candidates


@dataclass(slots=True, frozen=True)
class Requirements:
	"""Entry requirements of a giveaway."""

	level: int | None = None
	role_id: int | None = None
	messages: int | None = None

	@classmethod
	def from_record(cls, record: Mapping[str, Any]) -> Requirements:
		"""Read requirements from a ``giveaways`` row."""
		role_id = record["required_role_id"]
		return cls(
			level=record["required_level"],
			role_id=int(role_id) if role_id is not None else None,
			messages=record["required_messages"],
		)

	def unmet(
		self,
		*,
		role_ids: Iterable[int],
		level: int,
		messages: int,
		level_enabled: bool,
		check_messages: bool,
	) -> Requirement | None:
		"""Return the first requirement the member doesn't meet, or ``None`` if they meet all of them.

		Args:
			role_ids: The member's role IDs.
			level: The member's current level.
			messages: Messages the member sent since the giveaway started.
			level_enabled: Whether leveling is enabled; the level requirement is ignored otherwise.
			check_messages: Whether to check the message requirement (it can't be met when joining).
		"""
		if self.role_id is not None and self.role_id not in set(role_ids):
			return "role"
		if self.level is not None and level_enabled and level < self.level:
			return "level"
		if check_messages and self.messages is not None and messages < self.messages:
			return "messages"
		return None


class MessageCounter:
	"""Process-local buffer of message counts for giveaways with a message requirement.

	Counts live here until they are drained and written to the database in one batch. A message only counts
	if the author's previous counted message in the guild was at least ``cooldown`` seconds earlier.
	"""

	def __init__(self, cooldown: float = MESSAGE_COOLDOWN) -> None:
		self.cooldown = cooldown
		self.tracked: dict[int, set[int]] = {}
		self.pending: Counter[tuple[int, int]] = Counter()
		self._last_counted: dict[tuple[int, int], float] = {}

	def track(self, guild_id: int, giveaway_id: int) -> None:
		"""Start counting messages in ``guild_id`` for ``giveaway_id``."""
		self.tracked.setdefault(guild_id, set()).add(giveaway_id)

	def untrack(self, guild_id: int, giveaway_id: int) -> None:
		"""Stop counting new messages for ``giveaway_id``. Already buffered counts are kept until drained."""
		ids = self.tracked.get(guild_id)
		if ids is None:
			return
		ids.discard(giveaway_id)
		if not ids:
			del self.tracked[guild_id]

	def record(self, guild_id: int, user_id: int, now: float) -> bool:
		"""Count a message for every tracked giveaway in the guild.

		Returns:
			bool: Whether the message was counted.
		"""
		ids = self.tracked.get(guild_id)
		if not ids:
			return False
		key = (guild_id, user_id)
		if now - self._last_counted.get(key, float("-inf")) < self.cooldown:
			return False
		self._last_counted[key] = now
		for giveaway_id in ids:
			self.pending[(giveaway_id, user_id)] += 1
		return True

	def get(self, giveaway_id: int, user_id: int) -> int:
		"""Return the not yet written count of a user for a giveaway."""
		return self.pending.get((giveaway_id, user_id), 0)

	def drain(self) -> list[tuple[int, int, int]]:
		"""Take every buffered count as ``(giveaway_id, user_id, count)`` and clear the buffer."""
		items = [(giveaway_id, user_id, count) for (giveaway_id, user_id), count in self.pending.items()]
		self.pending.clear()
		return items

	def restore(self, items: Iterable[tuple[int, int, int]]) -> None:
		"""Put drained counts back, e.g. after a failed write."""
		for giveaway_id, user_id, count in items:
			self.pending[(giveaway_id, user_id)] += count

	def prune(self, now: float) -> None:
		"""Forget cooldowns that already ran out."""
		self._last_counted = {k: v for k, v in self._last_counted.items() if now - v < self.cooldown}


async def draw_winners[T, M](
	pool: Sequence[T],
	count: int,
	resolve: Callable[[T], Awaitable[M | None]],
	rng: random.Random,
) -> list[M]:
	"""Draw up to ``count`` winners from ``pool`` in random order, skipping entrants ``resolve`` rejects.

	Args:
		pool: The entrants.
		count: Maximum number of winners.
		resolve: Returns the winner object for an eligible entrant, or ``None`` if they're ineligible.
		rng: Random number generator.

	Returns:
		list[M]: The winners, fewer than ``count`` if not enough entrants are eligible.
	"""
	order = list(pool)
	rng.shuffle(order)
	winners: list[M] = []
	for entrant in order:
		if len(winners) >= count:
			break
		if (winner := await resolve(entrant)) is not None:
			winners.append(winner)
	return winners


class GiveawayScheduler(ExpiryScheduler[int]):
	"""Ends giveaways when they expire, including ones that expired while the bot was offline."""

	def __init__(self, bot: Bot, cog: Giveaway) -> None:
		super().__init__(bot)
		self.cog = cog

	async def fetch_pending(self) -> list[tuple[int, int, datetime.datetime]]:
		"""Return every active giveaway."""
		rows = await self.bot.db.fetch("SELECT id, guild_id, ends_at FROM giveaways WHERE status = 'active'")
		return [(int(row["id"]), int(row["guild_id"]), row["ends_at"]) for row in rows]

	async def process_expired(self, key: int, guild_id: int) -> None:
		"""End the expired giveaway."""
		await self.cog.finish(key)


def _cog(interaction: discord.Interaction) -> commands.Cog | None:
	client = interaction.client
	return client.get_cog("Giveaway") if isinstance(client, Bot) else None


class GiveawayJoinButton(discord.ui.DynamicItem[discord.ui.Button], template=r"giveaway:(?P<id>\d+)"):
	def __init__(self, giveaway_id: int) -> None:
		super().__init__(discord.ui.Button(custom_id=f"giveaway:{giveaway_id}"))
		self.giveaway_id = giveaway_id

	@classmethod
	async def from_custom_id(
		cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str], /
	) -> GiveawayJoinButton:
		return cls(int(match["id"]))

	async def callback(self, interaction: discord.Interaction) -> None:
		if isinstance(cog := _cog(interaction), Giveaway):
			await cog.handle_join(interaction, self.giveaway_id)


class GiveawayLeaveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"giveaway-leave:(?P<id>\d+)"):
	def __init__(self, giveaway_id: int) -> None:
		super().__init__(discord.ui.Button(custom_id=f"giveaway-leave:{giveaway_id}"))
		self.giveaway_id = giveaway_id

	@classmethod
	async def from_custom_id(
		cls, interaction: discord.Interaction, item: discord.ui.Item[Any], match: re.Match[str], /
	) -> GiveawayLeaveButton:
		return cls(int(match["id"]))

	async def callback(self, interaction: discord.Interaction) -> None:
		if isinstance(cog := _cog(interaction), Giveaway):
			await cog.handle_leave(interaction, self.giveaway_id)


def _send_kwargs(payload: Any) -> dict[str, Any]:
	if isinstance(payload, dict):
		return {k: v for k, v in payload.items() if k in VALID_SEND_KWARGS}
	return {"content": str(payload)}


def _stop_view(kwargs: Mapping[str, Any]) -> None:
	# Localized layouts are sent as persistent views; the dynamic items handle their buttons, so the stored
	# view would only leak memory.
	view = kwargs.get("view")
	if isinstance(view, (discord.ui.View, discord.ui.LayoutView)):
		view.stop()


class Giveaway(commands.Cog, name="Giveaway"):
	def __init__(self, bot: Bot) -> None:
		self.bot = bot
		self.scheduler = GiveawayScheduler(bot, self)
		self.counter = MessageCounter()
		self.rng = random.SystemRandom()
		self._flush_lock = asyncio.Lock()
		self._dirty: set[int] = set()
		self._background: set[asyncio.Task[None]] = set()

	async def cog_load(self) -> None:
		self.bot.add_dynamic_items(GiveawayJoinButton, GiveawayLeaveButton)
		self._spawn(self._load_tracked())
		self.scheduler.start()
		self.tick.start()
		self.purge.start()

	async def cog_unload(self) -> None:
		self.tick.cancel()
		self.purge.cancel()
		self.scheduler.stop()
		self.bot.remove_dynamic_items(GiveawayJoinButton, GiveawayLeaveButton)
		await self.flush_counts()

	def _spawn(self, coro: Awaitable[None]) -> None:
		async def runner() -> None:
			try:
				await coro
			except Exception:
				logger.exception("Giveaway background task failed")

		task = asyncio.create_task(runner())
		self._background.add(task)
		task.add_done_callback(self._background.discard)

	async def _load_tracked(self) -> None:
		await self.bot.wait_until_ready()
		rows = await self.bot.db.fetch(
			"SELECT id, guild_id FROM giveaways WHERE status = 'active' AND required_messages IS NOT NULL"
		)
		for row in rows:
			guild_id = int(row["guild_id"])
			if is_guild_on_shard(self.bot, guild_id):
				self.counter.track(guild_id, int(row["id"]))

	@tasks.loop(seconds=FLUSH_INTERVAL)
	async def tick(self) -> None:
		"""Write buffered message counts and refresh entry counts of changed giveaways."""
		try:
			await self.flush_counts()
			await self._refresh_dirty()
			self.counter.prune(time.monotonic())
		except Exception:
			logger.exception("Giveaway tick failed")

	@tasks.loop(hours=6)
	async def purge(self) -> None:
		"""Delete entries and message counts of giveaways that finished more than 30 days ago."""
		for table in ("giveaway_entries", "giveaway_message_counts"):
			await self.bot.db.execute(
				f"""
				DELETE FROM {table} t USING giveaways g
				WHERE t.giveaway_id = g.id AND g.status <> 'active'
				AND g.ended_at < now() - make_interval(days => $1)
				""",
				RETENTION_DAYS,
			)

	async def flush_counts(self) -> None:
		"""Write every buffered message count to the database in one batch."""
		async with self._flush_lock:
			items = self.counter.drain()
			if not items:
				return
			try:
				await self.bot.db.executemany(UPSERT_COUNTS, items)
			except Exception:
				self.counter.restore(items)
				logger.exception("Failed to flush giveaway message counts")

	async def _refresh_dirty(self) -> None:
		ids, self._dirty = self._dirty, set()
		for giveaway_id in ids:
			record = await self._fetch(giveaway_id)
			if record is None or record["status"] != "active":
				continue
			guild = self.bot.get_guild(int(record["guild_id"]))
			channel = self._channel(guild, record)
			if guild is None or channel is None or record["message_id"] is None:
				continue
			try:
				await self._edit_layout(channel.get_partial_message(int(record["message_id"])), record, guild)
			except discord.HTTPException:
				logger.debug(f"Couldn't refresh giveaway {giveaway_id}", exc_info=True)

	@commands.Cog.listener("on_message")
	async def count_message(self, message: discord.Message) -> None:
		if message.guild is None or message.author.bot:
			return
		self.counter.record(message.guild.id, message.author.id, time.monotonic())

	async def _fetch(self, giveaway_id: int) -> Mapping[str, Any] | None:
		return await self.bot.db.fetchrow("SELECT * FROM giveaways WHERE id = $1", giveaway_id)

	async def _entry_count(self, giveaway_id: int) -> int:
		return int(
			await self.bot.db.fetchval("SELECT count(*) FROM giveaway_entries WHERE giveaway_id = $1", giveaway_id)
		)

	async def _level_enabled(self, guild_id: int) -> bool:
		is_on = await self.bot.db.fetchval("SELECT is_on FROM level_config WHERE guild_id = $1", guild_id)
		return True if is_on is None else bool(is_on)

	async def _levels(self, guild_id: int, user_ids: Sequence[int]) -> dict[int, int]:
		rows = await self.bot.db.fetch(
			"SELECT user_id, xp FROM user_levels WHERE guild_id = $1 AND user_id = ANY($2::numeric[])",
			guild_id,
			list(user_ids),
		)
		return {int(row["user_id"]): level_from_total_xp(int(row["xp"])).level for row in rows}

	async def _message_counts(self, giveaway_id: int) -> dict[int, int]:
		rows = await self.bot.db.fetch(
			"SELECT user_id, count FROM giveaway_message_counts WHERE giveaway_id = $1", giveaway_id
		)
		return {int(row["user_id"]): int(row["count"]) for row in rows}

	async def resolve_target(self, ctx: Context, raw: str | None, status: GiveawayStatus) -> Mapping[str, Any] | None:
		"""Find the giveaway a command targets: the replied-to message, the given ID or link, else the latest one.

		Only giveaways in the current channel with the given status are considered.
		"""
		reference = ctx.message.reference if ctx.interaction is None else None
		reference_id = reference.message_id if reference else None
		for message_id in candidate_message_ids(reference_id, raw):
			record = await self.bot.db.fetchrow(
				"SELECT * FROM giveaways WHERE channel_id = $1 AND message_id = $2 AND status = $3",
				ctx.channel.id,
				message_id,
				status,
			)
			if record is not None:
				return record
		return await self.bot.db.fetchrow(
			"""
			SELECT * FROM giveaways WHERE channel_id = $1 AND status = $2
			ORDER BY created_at DESC, id DESC LIMIT 1
			""",
			ctx.channel.id,
			status,
		)

	@staticmethod
	def _channel(guild: discord.Guild | None, record: Mapping[str, Any]) -> GiveawayChannel | None:
		if guild is None:
			return None
		channel = guild.get_channel_or_thread(int(record["channel_id"]))
		if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
			return channel
		return None

	async def _user(self, guild: discord.Guild, user_id: int) -> discord.Member | discord.User | None:
		if user := guild.get_member(user_id) or self.bot.get_user(user_id):
			return user
		try:
			return await self.bot.fetch_user(user_id)
		except discord.HTTPException:
			return None

	async def _member(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
		if member := guild.get_member(user_id):
			return member
		try:
			return await guild.fetch_member(user_id)
		except discord.HTTPException:
			return None

	@staticmethod
	def _requirements(record: Mapping[str, Any], guild: discord.Guild) -> Requirements:
		# A deleted role can't be met by anyone, so it stops being a requirement.
		req = Requirements.from_record(record)
		if req.role_id is not None and guild.get_role(req.role_id) is None:
			return dataclasses.replace(req, role_id=None)
		return req

	async def _requirements_text(self, record: Mapping[str, Any], guild: discord.Guild) -> str:
		get = self.bot.custom_response.get_message
		req = self._requirements(record, guild)
		lines: list[str] = []
		if req.level is not None:
			lines.append(str(await get("giveaway.requirements.level", guild, level=req.level)))
		if req.role_id is not None and (role := guild.get_role(req.role_id)):
			lines.append(str(await get("giveaway.requirements.role", guild, role=role)))
		if req.messages is not None:
			lines.append(str(await get("giveaway.requirements.messages", guild, messages=req.messages)))
		if not lines:
			return ""
		return "\n".join([str(await get("giveaway.requirements.header", guild)), *lines])

	async def _layout(
		self,
		record: Mapping[str, Any],
		guild: discord.Guild,
		winners: Sequence[discord.Member] | None = None,
	) -> dict[str, Any]:
		status: GiveawayStatus = record["status"]
		host = await self._user(guild, int(record["host_id"]))
		winners_text = ""
		if status == "ended":
			winners_text = (
				", ".join(w.mention for w in winners)
				if winners
				else str(await self.bot.custom_response.get_message("giveaway.layout.no_winners", guild))
			)
		payload = await self.bot.custom_response.get_message(
			f"giveaway.layout.{status}",
			guild,
			giveaway=GiveawayArg.from_record(record, await self._entry_count(int(record["id"]))),
			author=host or guild.me,
			requirements=await self._requirements_text(record, guild),
			winners=winners_text,
		)
		return _send_kwargs(payload)

	async def _edit_layout(
		self,
		message: discord.Message | discord.PartialMessage,
		record: Mapping[str, Any],
		guild: discord.Guild,
		winners: Sequence[discord.Member] | None = None,
	) -> None:
		kwargs = await self._layout(record, guild, winners)
		try:
			await message.edit(view=kwargs.get("view"), allowed_mentions=kwargs.get("allowed_mentions"))
		finally:
			_stop_view(kwargs)

	async def _respond(self, interaction: discord.Interaction, key: str, **kwargs: Any) -> None:
		send = _send_kwargs(await self.bot.custom_response.get_message(key, interaction, **kwargs))
		send.setdefault("ephemeral", True)
		try:
			await interaction.response.send_message(**send)
		finally:
			_stop_view(send)

	async def _draw(self, record: Mapping[str, Any], guild: discord.Guild, count: int) -> list[discord.Member]:
		giveaway_id = int(record["id"])
		await self.flush_counts()
		rows = await self.bot.db.fetch(
			"SELECT user_id FROM giveaway_entries WHERE giveaway_id = $1 AND NOT has_won", giveaway_id
		)
		entrants = [int(row["user_id"]) for row in rows]
		if not entrants:
			return []

		req = self._requirements(record, guild)
		level_enabled = req.level is not None and await self._level_enabled(guild.id)
		levels = await self._levels(guild.id, entrants) if level_enabled else {}
		counts = await self._message_counts(giveaway_id) if req.messages is not None else {}

		async def resolve(user_id: int) -> discord.Member | None:
			member = await self._member(guild, user_id)
			if member is None:
				return None
			unmet = req.unmet(
				role_ids=(r.id for r in member.roles),
				level=levels.get(user_id, 0),
				messages=counts.get(user_id, 0),
				level_enabled=level_enabled,
				check_messages=True,
			)
			return member if unmet is None else None

		winners = await draw_winners(entrants, count, resolve, self.rng)
		if winners:
			await self.bot.db.execute(
				"UPDATE giveaway_entries SET has_won = true WHERE giveaway_id = $1 AND user_id = ANY($2::numeric[])",
				giveaway_id,
				[w.id for w in winners],
			)
		return winners

	async def _announce(
		self,
		message: discord.Message,
		record: Mapping[str, Any],
		guild: discord.Guild,
		winners: Sequence[discord.Member],
		action: Literal["end", "reroll"],
	) -> None:
		key = f"giveaway.{action}.success" if winners else f"giveaway.{action}.no_winners"
		giveaway = GiveawayArg.from_record(record, await self._entry_count(int(record["id"])))
		payload = await self.bot.custom_response.get_message(
			key, guild, giveaway=giveaway, winners=", ".join(w.mention for w in winners)
		)
		kwargs = _send_kwargs(payload)
		kwargs.pop("ephemeral", None)
		kwargs["allowed_mentions"] = discord.AllowedMentions(
			users=[discord.Object(w.id) for w in winners], roles=False, everyone=False
		)
		try:
			await message.reply(**kwargs, mention_author=False)
		finally:
			_stop_view(kwargs)

		if winners:
			self._spawn(self._dm_winners(giveaway, guild, winners))

	async def _dm_winners(self, giveaway: GiveawayArg, guild: discord.Guild, winners: Sequence[discord.Member]) -> None:
		for winner in winners:
			kwargs = _send_kwargs(
				await self.bot.custom_response.get_message("giveaway.dm.won", guild, giveaway=giveaway)
			)
			kwargs.pop("ephemeral", None)
			try:
				await winner.send(**kwargs)
			except discord.HTTPException:
				pass
			finally:
				_stop_view(kwargs)

	async def _fetch_message(self, guild: discord.Guild, record: Mapping[str, Any]) -> discord.Message | None:
		channel = self._channel(guild, record)
		if channel is None or record["message_id"] is None:
			return None
		try:
			return await channel.fetch_message(int(record["message_id"]))
		except discord.HTTPException:
			return None

	async def finish(self, giveaway_id: int) -> Mapping[str, Any] | None:
		"""End an active giveaway: draw winners, update its message, announce and DM the winners.

		If the giveaway's message or channel no longer exists, the giveaway is marked as ended without a draw.

		Returns:
			The ended giveaway's row, or ``None`` if it wasn't active.
		"""
		record = await self.bot.db.fetchrow(
			"UPDATE giveaways SET status = 'ended', ended_at = now() WHERE id = $1 AND status = 'active' RETURNING *",
			giveaway_id,
		)
		if record is None:
			return None
		guild_id = int(record["guild_id"])
		self.scheduler.cancel(giveaway_id)
		self.counter.untrack(guild_id, giveaway_id)
		self._dirty.discard(giveaway_id)

		guild = self.bot.get_guild(guild_id)
		if guild is None or (message := await self._fetch_message(guild, record)) is None:
			return record

		winners = await self._draw(record, guild, int(record["winner_count"]))
		try:
			await self._edit_layout(message, record, guild, winners)
		except discord.HTTPException:
			logger.warning(f"Couldn't edit ended giveaway {giveaway_id}", exc_info=True)
		await self._announce(message, record, guild, winners, "end")
		return record

	async def handle_join(self, interaction: discord.Interaction, giveaway_id: int) -> None:
		"""Enter a member into a giveaway, or offer to leave it if they've already entered."""
		member = interaction.user
		if interaction.guild is None or not isinstance(member, discord.Member):
			return
		record = await self._fetch(giveaway_id)
		if record is None or record["status"] != "active":
			await self._respond(interaction, "giveaway.message.ended")
			return
		giveaway = GiveawayArg.from_record(record)

		entered = await self.bot.db.fetchval(
			"SELECT 1 FROM giveaway_entries WHERE giveaway_id = $1 AND user_id = $2", giveaway_id, member.id
		)
		if entered:
			await self._respond(interaction, "giveaway.message.already_joined", giveaway=giveaway)
			return

		req = self._requirements(record, interaction.guild)
		level_enabled = req.level is not None and await self._level_enabled(interaction.guild.id)
		level = (await self._levels(interaction.guild.id, [member.id])).get(member.id, 0) if level_enabled else 0
		unmet = req.unmet(
			role_ids=(r.id for r in member.roles),
			level=level,
			messages=0,
			level_enabled=level_enabled,
			check_messages=False,
		)
		if unmet == "role":
			role = interaction.guild.get_role(req.role_id or 0)
			await self._respond(interaction, "giveaway.message.requirements.role", role=role)
			return
		if unmet == "level":
			await self._respond(interaction, "giveaway.message.requirements.level", level=req.level, current=level)
			return

		await self.bot.db.execute(
			"INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
			giveaway_id,
			member.id,
		)
		self._dirty.add(giveaway_id)

		if req.messages is None:
			await self._respond(interaction, "giveaway.message.joined", giveaway=giveaway)
			return
		stored = await self.bot.db.fetchval(
			"SELECT count FROM giveaway_message_counts WHERE giveaway_id = $1 AND user_id = $2",
			giveaway_id,
			member.id,
		)
		count = int(stored or 0) + self.counter.get(giveaway_id, member.id)
		await self._respond(
			interaction, "giveaway.message.joined_progress", giveaway=giveaway, count=count, required=req.messages
		)

	async def handle_leave(self, interaction: discord.Interaction, giveaway_id: int) -> None:
		"""Remove a member's entry from an active giveaway."""
		record = await self._fetch(giveaway_id)
		if record is None or record["status"] != "active":
			await self._respond(interaction, "giveaway.message.ended")
			return
		removed = await self.bot.db.fetchval(
			"DELETE FROM giveaway_entries WHERE giveaway_id = $1 AND user_id = $2 RETURNING 1",
			giveaway_id,
			interaction.user.id,
		)
		if not removed:
			await self._respond(interaction, "giveaway.message.not_joined")
			return
		self._dirty.add(giveaway_id)
		await self._respond(interaction, "giveaway.message.left", giveaway=GiveawayArg.from_record(record))

	@group(user=False, fallback=None, permissions=["manage_messages"], invoke_without_command=True)
	async def giveaway(self, ctx: Context) -> None:
		await ctx.send_help(ctx.command)

	@giveaway.command(l10n_key="giveawaystart", user=False, permissions=["manage_messages"])
	async def start(
		self,
		ctx: Context,
		duration: str,
		winners: commands.Range[int, 1, 50],
		prize: commands.Range[str, 1, 256],
		level: commands.Range[int, 1, 10000] | None = None,
		role: discord.Role | None = None,
		messages: commands.Range[int, 1, 100000] | None = None,
	) -> None:
		assert ctx.guild is not None
		try:
			seconds = text_to_seconds(duration)
		except ValueError:
			await ctx.send("giveaway.start.errors.duration")
			return
		if not MIN_DURATION <= seconds <= MAX_DURATION:
			await ctx.send("giveaway.start.errors.duration_range")
			return
		channel = ctx.channel
		if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
			await ctx.send("giveaway.start.errors.send_failed")
			return

		active = await self.bot.db.fetchval(
			"SELECT count(*) FROM giveaways WHERE guild_id = $1 AND status = 'active'", ctx.guild.id
		)
		if int(active) >= MAX_ACTIVE_PER_GUILD:
			await ctx.send("giveaway.start.errors.limit", limit=MAX_ACTIVE_PER_GUILD)
			return
		if level is not None and not await self._level_enabled(ctx.guild.id):
			await ctx.send("giveaway.start.errors.level_disabled")
			return

		await ctx.defer(ephemeral=True)
		ends_at = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(seconds=seconds)
		record = await self.bot.db.fetchrow(
			"""
			INSERT INTO giveaways (guild_id, channel_id, host_id, prize, winner_count, required_level,
				required_role_id, required_messages, ends_at)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
			RETURNING *
			""",
			ctx.guild.id,
			channel.id,
			ctx.author.id,
			prize,
			winners,
			level,
			role.id if role else None,
			messages,
			ends_at,
		)
		assert record is not None
		giveaway_id = int(record["id"])

		kwargs = await self._layout(record, ctx.guild)
		try:
			message = await channel.send(**kwargs)
		except discord.HTTPException:
			await self.bot.db.execute("DELETE FROM giveaways WHERE id = $1", giveaway_id)
			await ctx.send("giveaway.start.errors.send_failed")
			return
		finally:
			_stop_view(kwargs)

		record = await self.bot.db.fetchrow(
			"UPDATE giveaways SET message_id = $2 WHERE id = $1 RETURNING *", giveaway_id, message.id
		)
		assert record is not None
		self.scheduler.schedule_at(giveaway_id, ctx.guild.id, ends_at)
		if messages is not None:
			self.counter.track(ctx.guild.id, giveaway_id)
		await ctx.send("giveaway.start.success", giveaway=GiveawayArg.from_record(record))

	@giveaway.command(l10n_key="giveawayend", user=False, permissions=["manage_messages"])
	async def end(self, ctx: Context, message: str | None = None) -> None:
		target = await self.resolve_target(ctx, message, "active")
		if target is None:
			await ctx.send("giveaway.not_found.active")
			return
		await ctx.defer(ephemeral=True)
		record = await self.finish(int(target["id"]))
		if record is None:
			await ctx.send("giveaway.not_found.active")
			return
		await ctx.send("giveaway.end.done", giveaway=GiveawayArg.from_record(record))

	@giveaway.command(l10n_key="giveawayreroll", user=False, permissions=["manage_messages"])
	async def reroll(
		self, ctx: Context, message: str | None = None, count: commands.Range[int, 1, 50] | None = None
	) -> None:
		assert ctx.guild is not None
		# `?!giveaway reroll 2` means "redraw two winners", not "the giveaway with message ID 2".
		if count is None and message and message.isdigit() and parse_message_id(message) is None:
			message, count = None, int(message)

		record = await self.resolve_target(ctx, message, "ended")
		if record is None:
			await ctx.send("giveaway.not_found.ended")
			return
		giveaway_message = await self._fetch_message(ctx.guild, record)
		if giveaway_message is None:
			await ctx.send("giveaway.not_found.ended")
			return

		await ctx.defer(ephemeral=True)
		winners = await self._draw(record, ctx.guild, count or int(record["winner_count"]))
		await self._announce(giveaway_message, record, ctx.guild, winners, "reroll")
		await ctx.send("giveaway.reroll.done", giveaway=GiveawayArg.from_record(record))

	@giveaway.command(l10n_key="giveawaycancel", user=False, permissions=["manage_messages"])
	async def cancel(self, ctx: Context, message: str | None = None) -> None:
		assert ctx.guild is not None
		target = await self.resolve_target(ctx, message, "active")
		if target is None:
			await ctx.send("giveaway.not_found.active")
			return
		record = await self.bot.db.fetchrow(
			"""
			UPDATE giveaways SET status = 'cancelled', ended_at = now()
			WHERE id = $1 AND status = 'active' RETURNING *
			""",
			int(target["id"]),
		)
		if record is None:
			await ctx.send("giveaway.not_found.active")
			return
		giveaway_id = int(record["id"])
		self.scheduler.cancel(giveaway_id)
		self.counter.untrack(ctx.guild.id, giveaway_id)
		self._dirty.discard(giveaway_id)

		if (giveaway_message := await self._fetch_message(ctx.guild, record)) is not None:
			try:
				await self._edit_layout(giveaway_message, record, ctx.guild)
			except discord.HTTPException:
				logger.debug(f"Couldn't edit cancelled giveaway {giveaway_id}", exc_info=True)
		await ctx.send("giveaway.cancel.success", giveaway=GiveawayArg.from_record(record))


async def setup(bot: Bot) -> None:
	await bot.add_cog(Giveaway(bot))
