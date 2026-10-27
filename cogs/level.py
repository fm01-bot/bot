"""Leveling system cog for XP tracking, rank cards, leaderboards, and rewards."""

from __future__ import annotations

import logging
import random
import time

import discord
from args import User
from core import Bot, Context, command
from discord import app_commands
from discord.ext import commands
from discord.ext.localization import Localization
from helpers.level_card import create_level_card
from helpers.leveling import GuildLevelConfig, LevelupMessage, level_from_total_xp

logger = logging.getLogger(__name__)


@app_commands.guild_only()
@commands.guild_only()
class Level(commands.Cog, name="Level"):
	"""Cog handling user XP gain, rank card rendering, leaderboards, and automated role rewards."""

	def __init__(self, client: Bot):
		"""Initialize the Level cog.

		Args:
			client: The main bot instance.
		"""
		self.client = client
		self.guild_configs: dict[int, GuildLevelConfig] = {}
		self.role_rewards: dict[int, list[tuple[int, int]]] = {}
		self.channel_overrides: dict[tuple[int, int], tuple[float, bool]] = {}
		self.guild_role_overrides: dict[int, dict[int, tuple[float, bool]]] = {}
		self.role_overrides: dict[tuple[int, int], tuple[float, bool]] = {}
		self.cooldowns: dict[tuple[int, int], float] = {}

	def invalidate_cache(self, guild_id: int) -> None:
		"""Invalidate cached leveling configuration and overrides for a guild.

		Args:
			guild_id: Discord guild ID.
		"""
		self.guild_configs.pop(guild_id, None)
		self.role_rewards.pop(guild_id, None)
		self.guild_role_overrides.pop(guild_id, None)
		keys_to_remove = [k for k in self.channel_overrides if k[0] == guild_id]
		for k in keys_to_remove:
			self.channel_overrides.pop(k, None)
		keys_to_remove = [k for k in self.role_overrides if k[0] == guild_id]
		for k in keys_to_remove:
			self.role_overrides.pop(k, None)

	async def get_guild_config(self, guild_id: int) -> GuildLevelConfig:
		"""Retrieve or load cached leveling configuration for a guild.

		Args:
			guild_id: Discord guild ID.

		Returns:
			GuildLevelConfig: Configuration dataclass for the guild.
		"""
		if guild_id in self.guild_configs:
			return self.guild_configs[guild_id]

		row = await self.client.db.fetchrow("SELECT * FROM level_config WHERE guild_id = $1", guild_id)
		if row:
			raw_mode = row["message_mode"]
			mode = LevelupMessage(raw_mode) if raw_mode in LevelupMessage._value2member_map_ else LevelupMessage.CURRENT
			config = GuildLevelConfig(
				guild_id=guild_id,
				is_on=bool(row["is_on"]),
				multiplier=float(row["multiplier"]),
				min_xp=int(row["min_xp"]),
				max_xp=int(row["max_xp"]),
				cooldown=int(row["cooldown"]),
				message_mode=mode,
				message_channel=int(row["message_channel"]) if row["message_channel"] else None,
				levelup_message=str(row["levelup_message"]) if row["levelup_message"] else None,
				stack_roles=bool(row["stack_roles"]),
			)
		else:
			config = GuildLevelConfig(guild_id=guild_id)

		self.guild_configs[guild_id] = config
		return config

	async def get_role_rewards(self, guild_id: int) -> list[tuple[int, int]]:
		"""Retrieve role rewards ordered by level ascending.

		Args:
			guild_id: Discord guild ID.

		Returns:
			list[tuple[int, int]]: List of (level, role_id) reward pairs.
		"""
		if guild_id in self.role_rewards:
			return self.role_rewards[guild_id]

		rows = await self.client.db.fetch(
			"SELECT level, role_id FROM level_roles WHERE guild_id = $1 ORDER BY level ASC", guild_id
		)
		rewards = [(int(r["level"]), int(r["role_id"])) for r in rows]
		self.role_rewards[guild_id] = rewards
		return rewards

	async def get_channel_override(self, guild_id: int, channel_id: int) -> tuple[float, bool] | None:
		"""Retrieve (multiplier, is_ignored) override for a channel.

		Args:
			guild_id: Discord guild ID.
			channel_id: Discord channel ID.

		Returns:
			tuple[float, bool] | None: Tuple of multiplier and is_ignored flag, or None if no override.
		"""
		key = (guild_id, channel_id)
		if key in self.channel_overrides:
			return self.channel_overrides[key]

		row = await self.client.db.fetchrow(
			"SELECT multiplier, is_ignored FROM level_channel_overrides WHERE guild_id = $1 AND channel_id = $2",
			guild_id,
			channel_id,
		)
		if row:
			res = (float(row["multiplier"]), bool(row["is_ignored"]))
			self.channel_overrides[key] = res
			return res
		return None

	async def get_role_overrides(self, guild_id: int) -> dict[int, tuple[float, bool]]:
		"""Retrieve mapping of role_id -> (multiplier, is_ignored) for a guild.

		Args:
			guild_id: Discord guild ID.

		Returns:
			dict[int, tuple[float, bool]]: Mapping of role ID to multiplier and is_ignored flag.
		"""
		if guild_id in self.guild_role_overrides:
			return self.guild_role_overrides[guild_id]

		rows = await self.client.db.fetch(
			"SELECT role_id, multiplier, is_ignored FROM level_role_overrides WHERE guild_id = $1", guild_id
		)
		res: dict[int, tuple[float, bool]] = {}
		for r in rows:
			rid = int(r["role_id"])
			val = (float(r["multiplier"]), bool(r["is_ignored"]))
			res[rid] = val
			self.role_overrides[(guild_id, rid)] = val
		self.guild_role_overrides[guild_id] = res
		return res

	async def enable_leveling(self, guild_id: int) -> None:
		"""Enable leveling in the given guild.

		Args:
			guild_id: Discord guild ID.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_config (guild_id, is_on)
			VALUES ($1, true)
			ON CONFLICT (guild_id) DO UPDATE SET is_on = true
			""",
			guild_id,
		)
		cfg = await self.get_guild_config(guild_id)
		cfg.is_on = True

	async def disable_leveling(self, guild_id: int) -> None:
		"""Disable leveling in the given guild.

		Args:
			guild_id: Discord guild ID.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_config (guild_id, is_on)
			VALUES ($1, false)
			ON CONFLICT (guild_id) DO UPDATE SET is_on = false
			""",
			guild_id,
		)
		cfg = await self.get_guild_config(guild_id)
		cfg.is_on = False

	async def update_xp_config(
		self,
		guild_id: int,
		*,
		min_xp: int | None = None,
		max_xp: int | None = None,
		multiplier: float | None = None,
		cooldown: int | None = None,
	) -> None:
		"""Update XP generation rates and cooldown settings for a guild.

		Args:
			guild_id: Discord guild ID.
			min_xp: Minimum base XP awarded per message.
			max_xp: Maximum base XP awarded per message.
			multiplier: Global XP multiplier.
			cooldown: Cooldown in seconds between XP gains per member.
		"""
		cfg = await self.get_guild_config(guild_id)
		new_min = min_xp if min_xp is not None else cfg.min_xp
		new_max = max_xp if max_xp is not None else cfg.max_xp
		new_mult = multiplier if multiplier is not None else cfg.multiplier
		new_cd = cooldown if cooldown is not None else cfg.cooldown

		await self.client.db.execute(
			"""
			INSERT INTO level_config (guild_id, min_xp, max_xp, multiplier, cooldown)
			VALUES ($1, $2, $3, $4, $5)
			ON CONFLICT (guild_id) DO UPDATE SET
				min_xp = $2,
				max_xp = $3,
				multiplier = $4,
				cooldown = $5
			""",
			guild_id,
			new_min,
			new_max,
			new_mult,
			new_cd,
		)
		cfg.min_xp = new_min
		cfg.max_xp = new_max
		cfg.multiplier = new_mult
		cfg.cooldown = new_cd

	async def update_message_config(
		self, guild_id: int, *, mode: str | None = None, channel_id: int | None = None, template: str | None = None
	) -> None:
		"""Update level-up announcement delivery mode, channel, and message template.

		Args:
			guild_id: Discord guild ID.
			mode: Delivery mode ('current', 'channel', or 'disabled').
			channel_id: Target channel ID when mode is 'channel'.
			template: Custom announcement message template.
		"""
		cfg = await self.get_guild_config(guild_id)
		new_mode = mode if mode is not None else cfg.message_mode.value
		new_ch = channel_id if channel_id is not None else cfg.message_channel
		new_tmpl = template if template is not None else cfg.levelup_message

		await self.client.db.execute(
			"""
			INSERT INTO level_config (guild_id, message_mode, message_channel, levelup_message)
			VALUES ($1, $2, $3, $4)
			ON CONFLICT (guild_id) DO UPDATE SET
				message_mode = $2,
				message_channel = $3,
				levelup_message = $4
			""",
			guild_id,
			new_mode,
			new_ch,
			new_tmpl,
		)
		cfg.message_mode = (
			LevelupMessage(new_mode) if new_mode in LevelupMessage._value2member_map_ else LevelupMessage.CURRENT
		)
		cfg.message_channel = new_ch
		cfg.levelup_message = new_tmpl

	async def add_role_reward(self, guild_id: int, level: int, role_id: int) -> None:
		"""Add a role reward unlocked upon reaching a level.

		Args:
			guild_id: Discord guild ID.
			level: Level milestone.
			role_id: Discord role ID to award.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_roles (guild_id, level, role_id)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id, level, role_id) DO NOTHING
			""",
			guild_id,
			level,
			role_id,
		)
		self.role_rewards.pop(guild_id, None)

	async def remove_role_reward(self, guild_id: int, level: int, role_id: int | None = None) -> None:
		"""Remove role reward(s) associated with a level.

		Args:
			guild_id: Discord guild ID.
			level: Level milestone.
			role_id: Optional specific role ID to remove. If None, removes all roles for that level.
		"""
		if role_id is not None:
			await self.client.db.execute(
				"DELETE FROM level_roles WHERE guild_id = $1 AND level = $2 AND role_id = $3", guild_id, level, role_id
			)
		else:
			await self.client.db.execute("DELETE FROM level_roles WHERE guild_id = $1 AND level = $2", guild_id, level)
		self.role_rewards.pop(guild_id, None)

	async def set_stack_roles(self, guild_id: int, stack: bool) -> None:
		"""Configure whether role rewards stack or replace previous tiers.

		Args:
			guild_id: Discord guild ID.
			stack: True to keep all previous role rewards, False to retain only highest unlocked.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_config (guild_id, stack_roles)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE SET stack_roles = $2
			""",
			guild_id,
			stack,
		)
		cfg = await self.get_guild_config(guild_id)
		cfg.stack_roles = stack

	async def set_channel_ignored(self, guild_id: int, channel_id: int, is_ignored: bool) -> None:
		"""Set whether a channel is excluded from XP gain.

		Args:
			guild_id: Discord guild ID.
			channel_id: Discord channel ID.
			is_ignored: True to ignore channel, False to allow XP.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_channel_overrides (guild_id, channel_id, is_ignored)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id, channel_id) DO UPDATE SET is_ignored = $3
			""",
			guild_id,
			channel_id,
			is_ignored,
		)
		mult = self.channel_overrides.get((guild_id, channel_id), (1.0, False))[0]
		self.channel_overrides[(guild_id, channel_id)] = (mult, is_ignored)

	async def set_channel_multiplier(self, guild_id: int, channel_id: int, multiplier: float) -> None:
		"""Set custom XP multiplier for a channel.

		Args:
			guild_id: Discord guild ID.
			channel_id: Discord channel ID.
			multiplier: XP multiplier factor.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_channel_overrides (guild_id, channel_id, multiplier)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id, channel_id) DO UPDATE SET multiplier = $3
			""",
			guild_id,
			channel_id,
			multiplier,
		)
		ignored = self.channel_overrides.get((guild_id, channel_id), (1.0, False))[1]
		self.channel_overrides[(guild_id, channel_id)] = (multiplier, ignored)

	async def set_role_ignored(self, guild_id: int, role_id: int, is_ignored: bool) -> None:
		"""Set whether members with a role are excluded from XP gain.

		Args:
			guild_id: Discord guild ID.
			role_id: Discord role ID.
			is_ignored: True to ignore role, False to allow XP.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_role_overrides (guild_id, role_id, is_ignored)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id, role_id) DO UPDATE SET is_ignored = $3
			""",
			guild_id,
			role_id,
			is_ignored,
		)
		mult = self.role_overrides.get((guild_id, role_id), (1.0, False))[0]
		self.role_overrides[(guild_id, role_id)] = (mult, is_ignored)
		self.guild_role_overrides.pop(guild_id, None)

	async def set_role_multiplier(self, guild_id: int, role_id: int, multiplier: float) -> None:
		"""Set custom XP multiplier for a role.

		Args:
			guild_id: Discord guild ID.
			role_id: Discord role ID.
			multiplier: XP multiplier factor.
		"""
		await self.client.db.execute(
			"""
			INSERT INTO level_role_overrides (guild_id, role_id, multiplier)
			VALUES ($1, $2, $3)
			ON CONFLICT (guild_id, role_id) DO UPDATE SET multiplier = $3
			""",
			guild_id,
			role_id,
			multiplier,
		)
		ignored = self.role_overrides.get((guild_id, role_id), (1.0, False))[1]
		self.role_overrides[(guild_id, role_id)] = (multiplier, ignored)
		self.guild_role_overrides.pop(guild_id, None)

	@command(name="level", aliases=["rank"], user=False)
	async def level_command(self, ctx: Context, member: discord.Member | None = None) -> None:
		if not ctx.guild:
			return

		target = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
		if not target:
			return

		row = await self.client.db.fetchrow(
			"SELECT xp, level FROM user_levels WHERE guild_id = $1 AND user_id = $2", ctx.guild.id, target.id
		)
		total_xp = int(row["xp"]) if row else 0
		progress = level_from_total_xp(total_xp)

		rank: int | None = None
		if total_xp > 0:
			rank_row = await self.client.db.fetchrow(
				"SELECT COUNT(*) + 1 as rank FROM user_levels WHERE guild_id = $1 AND xp > $2", ctx.guild.id, total_xp
			)
			rank = int(rank_row["rank"]) if rank_row else 1
		else:
			rank = None

		localized_label = await self.client.custom_response.get_message("level_card.label", ctx)
		if isinstance(localized_label, str) and localized_label != "level_card.label":
			level_label = localized_label
		else:
			locale = ctx.guild.preferred_locale if ctx.guild else "en"
			level_label = "szint" if str(locale).startswith("hu") else "lvl"

		card_buffer = await create_level_card(
			user=target,
			rank=rank,
			level=progress.level,
			current_xp=progress.current_xp,
			needed_xp=progress.needed_xp,
			level_label=level_label,
		)
		file = discord.File(card_buffer, filename=f"level_{target.id}.png")
		await ctx.send(file=file)

	@command(name="levels", aliases=["top"], user=False)
	async def levels_command(self, ctx: Context, page: int = 1) -> None:
		if not ctx.guild:
			return

		page = max(page, 1)

		per_page = 10
		offset = (page - 1) * per_page

		total_count_row = await self.client.db.fetchrow(
			"SELECT COUNT(*) as count FROM user_levels WHERE guild_id = $1", ctx.guild.id
		)
		total_count = int(total_count_row["count"]) if total_count_row else 0
		total_pages = max(1, (total_count + per_page - 1) // per_page)

		if page > total_pages:
			page = total_pages
			offset = (page - 1) * per_page

		rows = await self.client.db.fetch(
			"SELECT user_id, xp, level FROM user_levels WHERE guild_id = $1 ORDER BY xp DESC LIMIT $2 OFFSET $3",
			ctx.guild.id,
			per_page,
			offset,
		)

		message = await self.client.custom_response.get_message("levels_leaderboard", ctx)
		if not isinstance(message, dict):
			raise TypeError("levels_leaderboard response is not a dict")

		embeds: list[discord.Embed] = message.get("embeds", [])
		if not rows:
			if embeds and len(embeds[0].fields) > 1:
				embeds[0].remove_field(0)
				embeds[0].set_footer(text=f"Page {page}/{total_pages}")
			await ctx.send(**message)
			return

		if embeds:
			template = embeds[0].to_dict().get("fields", [None])[0]
			if template:
				embeds[0].clear_fields()
				for idx, row in enumerate(rows):
					rank_num = offset + idx + 1
					user_id = int(row["user_id"])
					cached_user = self.client.get_user(user_id)
					user_arg = User.from_user(cached_user) if cached_user else None
					user_name_str = f"@{cached_user.name}" if cached_user else f"User {user_id}"
					formatted = Localization.format_strings(
						template,
						number=rank_num,
						user=user_arg or user_name_str,
						level=row["level"],
						xp=f"{int(row['xp']):,}",
					)
					embeds[0].add_field(**formatted)
				embeds[0].set_footer(text=f"Page {page}/{total_pages}")
				message["embeds"] = self.client.custom_response.convert_embeds(embeds)

		await ctx.send(**message)

	async def handle_role_rewards(
		self, member: discord.Member, old_level: int, new_level: int, stack_roles: bool
	) -> None:
		"""Assign role rewards based on levels earned.

		Args:
			member: The member who leveled up.
			old_level: Member's level prior to the XP update.
			new_level: Member's newly reached level.
			stack_roles: Whether all unlocked roles are kept or only highest tier.
		"""
		rewards = await self.get_role_rewards(member.guild.id)
		if not rewards:
			return

		if stack_roles:
			for lvl, r_id in rewards:
				if old_level < lvl <= new_level:
					role = member.guild.get_role(r_id)
					if role and role not in member.roles:
						try:
							await member.add_roles(role, reason=f"Level {lvl} reward")
						except (discord.Forbidden, discord.HTTPException):
							logger.warning(f"Failed to add role {role.name} to {member.name} in {member.guild.name}")
		else:
			unlocked = [r for r in rewards if r[0] <= new_level]
			if unlocked:
				highest_lvl, highest_r_id = unlocked[-1]
				highest_role = member.guild.get_role(highest_r_id)

				roles_to_remove = [
					r_obj
					for _lvl, rid in unlocked[:-1]
					if rid != highest_r_id
					and (r_obj := member.guild.get_role(rid)) is not None
					and r_obj in member.roles
				]
				if roles_to_remove:
					try:
						await member.remove_roles(*roles_to_remove, reason="Replacing lower level role reward")
					except (discord.Forbidden, discord.HTTPException):
						pass

				if highest_role and highest_role not in member.roles:
					try:
						await member.add_roles(highest_role, reason=f"Level {highest_lvl} reward")
					except (discord.Forbidden, discord.HTTPException):
						logger.warning(
							f"Failed to add highest role {highest_role.name} to {member.name} in {member.guild.name}"
						)

	async def send_levelup_notification(
		self, message: discord.Message, config: GuildLevelConfig, new_level: int, total_xp: int
	) -> None:
		"""Send custom level up announcement if configured.

		Args:
			message: The original trigger message sent by member.
			config: Guild leveling configuration.
			new_level: Newly reached level.
			total_xp: Total cumulative XP for the member.
		"""
		if config.message_mode == LevelupMessage.DISABLED:
			return

		target_channel: discord.abc.Messageable | None = None
		if config.message_mode == LevelupMessage.CHANNEL and config.message_channel and message.guild:
			ch = message.guild.get_channel(config.message_channel)
			if isinstance(ch, discord.abc.Messageable):
				target_channel = ch

		if not target_channel:
			target_channel = message.channel

		if config.levelup_message:
			text = (
				config.levelup_message.replace("{user.mention}", message.author.mention)
				.replace("{user}", message.author.mention)
				.replace("{username}", message.author.name)
				.replace("{display_name}", message.author.display_name)
				.replace("{level}", str(new_level))
				.replace("{xp}", f"{total_xp:,}")
			)
			try:
				await target_channel.send(text)
			except (discord.Forbidden, discord.HTTPException):
				guild_id = message.guild.id if message.guild else 0
				logger.warning(f"Failed to send level-up message in guild {guild_id}")
			return

		payload = await self.client.custom_response.get_message(
			"levelup_message", message, user=message.author, level=new_level, xp=f"{total_xp:,}"
		)
		if isinstance(payload, dict):
			send_kwargs = dict(payload)
			if getattr(target_channel, "id", None) != getattr(message.channel, "id", None):
				send_kwargs.pop("reference", None)
			try:
				await target_channel.send(**send_kwargs)
			except (discord.Forbidden, discord.HTTPException):
				guild_id = message.guild.id if message.guild else 0
				logger.warning(f"Failed to send level-up message in guild {guild_id}")
		else:
			try:
				await target_channel.send(str(payload))
			except (discord.Forbidden, discord.HTTPException):
				guild_id = message.guild.id if message.guild else 0
				logger.warning(f"Failed to send level-up message in guild {guild_id}")

	@commands.Cog.listener("on_message")
	async def on_message_xp(self, message: discord.Message) -> None:
		"""Award XP to members on message send with cooldowns and multipliers.

		Args:
			message: Discord message event.
		"""
		if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
			return

		guild_id = message.guild.id
		config = await self.get_guild_config(guild_id)
		if not config.is_on:
			return

		ch_override = await self.get_channel_override(guild_id, message.channel.id)
		if ch_override and ch_override[1]:
			return

		role_overrides = await self.get_role_overrides(guild_id)
		member_role_ids = {r.id for r in message.author.roles}
		for r_id in member_role_ids:
			if r_id in role_overrides and role_overrides[r_id][1]:
				return

		now = time.time()
		cd_key = (guild_id, message.author.id)
		last_xp_time = self.cooldowns.get(cd_key, 0.0)
		if now - last_xp_time < config.cooldown:
			return

		self.cooldowns[cd_key] = now

		effective_mult = config.multiplier
		if ch_override and ch_override[0] > 0:
			effective_mult *= ch_override[0]

		role_mults = [
			role_overrides[r_id][0]
			for r_id in member_role_ids
			if r_id in role_overrides and role_overrides[r_id][0] > 0
		]
		if role_mults:
			effective_mult *= max(role_mults)

		raw_xp = random.randint(config.min_xp, config.max_xp)
		xp_to_add = round(raw_xp * effective_mult)
		if xp_to_add <= 0:
			return

		row = await self.client.db.fetchrow(
			"""
			INSERT INTO user_levels (guild_id, user_id, xp, level, last_message_at)
			VALUES ($1, $2, $3, 0, now())
			ON CONFLICT (guild_id, user_id) DO UPDATE SET
				xp = user_levels.xp + $3,
				last_message_at = now()
			RETURNING xp, level
			""",
			guild_id,
			message.author.id,
			xp_to_add,
		)
		if not row:
			return

		new_total_xp = int(row["xp"])
		old_level = int(row["level"])
		new_progress = level_from_total_xp(new_total_xp)

		if new_progress.level > old_level:
			await self.client.db.execute(
				"UPDATE user_levels SET level = $1 WHERE guild_id = $2 AND user_id = $3",
				new_progress.level,
				guild_id,
				message.author.id,
			)

			await self.handle_role_rewards(message.author, old_level, new_progress.level, config.stack_roles)
			await self.send_levelup_notification(message, config, new_progress.level, new_total_xp)


async def setup(client: Bot):
	"""Load Level cog extension into the bot.

	Args:
		client: The main bot instance.
	"""
	await client.add_cog(Level(client))
