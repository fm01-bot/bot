from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class LevelProgress(NamedTuple):
	level: int
	current_xp: int
	needed_xp: int
	remaining_xp: int


def xp_to_next_level(level: int) -> int:
	"""Calculate how much XP is needed to advance from `level` to `level + 1`.

	Formula: 5 * (level ^ 2) + (50 * level) + 100
	"""
	level = max(level, 0)
	return 5 * (level**2) + (50 * level) + 100


def total_xp_for_level(level: int) -> int:
	"""Calculate total cumulative XP required to reach `level` starting from 0.

	Sum from i=0 to level-1 of (5*i^2 + 50*i + 100)
	"""
	if level <= 0:
		return 0
	# Sum of squares formula: (L-1)*L*(2L-1)/6
	# Sum of integers formula: (L-1)*L/2
	# Sum of constants: 100 * L
	n = level
	sum_sq = (n - 1) * n * (2 * n - 1) // 6
	sum_i = (n - 1) * n // 2
	return 5 * sum_sq + 50 * sum_i + 100 * n


def level_from_total_xp(total_xp: int) -> LevelProgress:
	"""Derive the user's current level and current-level XP progress from total XP."""
	if total_xp <= 0:
		needed = xp_to_next_level(0)
		return LevelProgress(level=0, current_xp=0, needed_xp=needed, remaining_xp=needed)

	# Binary search for highest level L where total_xp_for_level(L) <= total_xp
	low = 0
	high = 1_000_000
	lvl = 0

	while low <= high:
		mid = (low + high) // 2
		if total_xp_for_level(mid) <= total_xp:
			lvl = mid
			low = mid + 1
		else:
			high = mid - 1

	base_xp = total_xp_for_level(lvl)
	current_xp = total_xp - base_xp
	needed = xp_to_next_level(lvl)
	remaining = max(0, needed - current_xp)
	return LevelProgress(level=lvl, current_xp=current_xp, needed_xp=needed, remaining_xp=remaining)


@dataclass
class GuildLevelConfig:
	guild_id: int
	is_on: bool = True
	multiplier: float = 1.0
	min_xp: int = 15
	max_xp: int = 25
	cooldown: int = 60
	message_mode: str = "current"  # "current", "channel", "disabled"
	message_channel: int | None = None
	levelup_message: str | None = None
	stack_roles: bool = True
