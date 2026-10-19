from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from helpers.level_card import create_level_card
from helpers.leveling import GuildLevelConfig, level_from_total_xp, total_xp_for_level, xp_to_next_level
from PIL import Image


def test_xp_to_next_level_formula():
	"""Verify xp_to_next_level matches 5 * (lvl^2) + 50 * lvl + 100."""
	assert xp_to_next_level(0) == 100
	assert xp_to_next_level(1) == 155
	assert xp_to_next_level(2) == 220
	assert xp_to_next_level(3) == 295
	assert xp_to_next_level(24) == 4180

	# Test that all XP requirements end in 0 or 5 (round-ish numbers)
	for lvl in range(100):
		req = xp_to_next_level(lvl)
		assert req % 5 == 0


def test_total_xp_for_level_consistency():
	"""Verify cumulative total_xp matches the iterative summation."""
	assert total_xp_for_level(0) == 0
	assert total_xp_for_level(1) == 100
	assert total_xp_for_level(2) == 255
	assert total_xp_for_level(3) == 475

	running_sum = 0
	for lvl in range(50):
		assert total_xp_for_level(lvl) == running_sum
		assert total_xp_for_level(lvl) % 5 == 0
		running_sum += xp_to_next_level(lvl)


def test_level_from_total_xp():
	"""Verify level derivation and current-level progress calculations."""
	# Level 0
	p0 = level_from_total_xp(0)
	assert p0.level == 0
	assert p0.current_xp == 0
	assert p0.needed_xp == 100
	assert p0.remaining_xp == 100

	# Level 0 partial
	p_partial = level_from_total_xp(45)
	assert p_partial.level == 0
	assert p_partial.current_xp == 45
	assert p_partial.needed_xp == 100
	assert p_partial.remaining_xp == 55

	# Exactly Level 1 (100 total XP)
	p1 = level_from_total_xp(100)
	assert p1.level == 1
	assert p1.current_xp == 0
	assert p1.needed_xp == 155
	assert p1.remaining_xp == 155

	# Level 1 partial (120 total XP -> 20 XP into level 1)
	p1_mid = level_from_total_xp(120)
	assert p1_mid.level == 1
	assert p1_mid.current_xp == 20
	assert p1_mid.needed_xp == 155
	# User formula check: 5 * (1^2) + 50*1 + 100 - 20 = 135
	assert p1_mid.remaining_xp == 135

	# Just before Level 2 (254 total XP)
	p1_end = level_from_total_xp(254)
	assert p1_end.level == 1
	assert p1_end.current_xp == 154
	assert p1_end.needed_xp == 155
	assert p1_end.remaining_xp == 1

	# Exactly Level 2 (255 total XP)
	p2 = level_from_total_xp(255)
	assert p2.level == 2
	assert p2.current_xp == 0
	assert p2.needed_xp == 220
	assert p2.remaining_xp == 220


def test_guild_level_config_defaults():
	cfg = GuildLevelConfig(guild_id=123)
	assert cfg.guild_id == 123
	assert cfg.is_on is True
	assert cfg.multiplier == 1.0
	assert cfg.min_xp == 15
	assert cfg.max_xp == 25
	assert cfg.cooldown == 60
	assert cfg.message_mode == "current"
	assert cfg.levelup_message is None
	assert cfg.stack_roles is True


@pytest.mark.asyncio
async def test_create_level_card_generates_valid_image():
	"""Verify create_level_card produces a valid 1024x266 PNG image."""
	mock_user = MagicMock(spec=discord.Member)
	mock_user.name = "pearoo"
	mock_user.display_name = "rnxm"
	mock_user.id = 123456789

	# Mock avatar read to return a small 1x1 png or fallback
	mock_avatar = MagicMock()
	mock_avatar.with_format.return_value = mock_avatar
	mock_avatar.with_size.return_value = mock_avatar

	# Generate 1x1 PNG bytes
	img_bytes_io = io.BytesIO()
	Image.new("RGBA", (100, 100), (50, 50, 50, 255)).save(img_bytes_io, format="PNG")
	mock_avatar.read = AsyncMock(return_value=img_bytes_io.getvalue())
	mock_user.display_avatar = mock_avatar

	buffer = await create_level_card(
		user=mock_user, rank=2, level=24, current_xp=1500, needed_xp=4180, level_label="szint"
	)

	assert isinstance(buffer, io.BytesIO)
	card_img = Image.open(buffer)
	assert card_img.size == (1024, 266)
	assert card_img.format == "PNG"


@pytest.mark.asyncio
async def test_create_level_card_with_avatar_fallback():
	"""Verify card generation succeeds when avatar fetching raises an error."""
	mock_user = MagicMock(spec=discord.User)
	mock_user.name = "fallback_user"
	mock_user.display_name = "Fallback"
	mock_user.id = 987654321

	mock_avatar = MagicMock()
	mock_avatar.with_format.return_value = mock_avatar
	mock_avatar.with_size.return_value = mock_avatar
	mock_avatar.read = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "Failed"))
	mock_user.display_avatar = mock_avatar

	buffer = await create_level_card(user=mock_user, rank=None, level=0, current_xp=0, needed_xp=100, level_label="lvl")

	card_img = Image.open(buffer)
	assert card_img.size == (1024, 266)
