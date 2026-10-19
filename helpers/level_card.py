from __future__ import annotations

import io
import os

import discord
from PIL import Image, ImageDraw, ImageFont

# Colors matching the design
COLOR_BG = (27, 28, 32, 255)
COLOR_TEXT_WHITE = (255, 255, 255, 255)
COLOR_TEXT_GRAY = (161, 161, 170, 255)
COLOR_TEXT_LIGHT_GRAY = (228, 228, 231, 255)
COLOR_BLUE = (100, 144, 243, 255)
COLOR_TRACK = (113, 113, 122, 255)
COLOR_AVATAR_BG = (40, 42, 48, 255)


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
	"""Load system font if available, otherwise fall back to Pillow default FreeType font."""
	candidates: list[str] = []
	if bold:
		candidates = [
			"C:/Windows/Fonts/segoeuib.ttf",
			"C:/Windows/Fonts/arialbd.ttf",
			"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
			"/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
		]
	else:
		candidates = [
			"C:/Windows/Fonts/segoeui.ttf",
			"C:/Windows/Fonts/arial.ttf",
			"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
			"/usr/share/fonts/TTF/DejaVuSans.ttf",
		]

	for path in candidates:
		if os.path.exists(path):
			try:
				return ImageFont.truetype(path, size)
			except (OSError, ValueError):
				continue

	return ImageFont.load_default(size=size)


def _truncate_text(
	text: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw
) -> str:
	"""Truncate text with ellipsis if it exceeds max_width."""
	if draw.textlength(text, font=font) <= max_width:
		return text

	ellipsis = "..."
	for i in range(len(text) - 1, 0, -1):
		candidate = text[:i] + ellipsis
		if draw.textlength(candidate, font=font) <= max_width:
			return candidate
	return text[:1] + ellipsis


async def create_level_card(
	user: discord.User | discord.Member,
	rank: int | None,
	level: int,
	current_xp: int,
	needed_xp: int,
	level_label: str = "lvl",
) -> io.BytesIO:
	"""Generate a stylized rank/level card for a user."""
	width, height = 1024, 266
	card = Image.new("RGBA", (width, height), COLOR_BG)
	draw = ImageDraw.Draw(card)

	# Fetch avatar bytes
	avatar_image: Image.Image | None = None
	try:
		avatar_bytes = await user.display_avatar.with_format("png").with_size(256).read()
		avatar_image = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
	except (discord.DiscordException, OSError, ValueError):
		avatar_image = None

	av_size = 160
	av_x, av_y = 35, 30

	if avatar_image:
		avatar_image = avatar_image.resize((av_size, av_size), Image.Resampling.LANCZOS)
	else:
		# Fallback placeholder avatar
		avatar_image = Image.new("RGBA", (av_size, av_size), COLOR_AVATAR_BG)
		av_draw = ImageDraw.Draw(avatar_image)
		initials = (user.display_name[:2] or "??").upper()
		av_draw.text(
			(av_size // 2, av_size // 2), initials, font=_get_font(48, True), fill=COLOR_TEXT_WHITE, anchor="mm"
		)

	# Apply rounded corners to avatar
	mask = Image.new("L", (av_size, av_size), 0)
	mask_draw = ImageDraw.Draw(mask)
	mask_draw.rounded_rectangle((0, 0, av_size, av_size), radius=16, fill=255)
	card.paste(avatar_image, (av_x, av_y), mask)

	# Rank text on bottom-left
	if rank is not None and rank > 0:
		rank_str = f"#{rank}"
		rank_font = _get_font(36, True)
		draw.text((av_x, 228), rank_str, font=rank_font, fill=COLOR_TEXT_WHITE, anchor="lm")

	content_x = 240
	right_margin = 989

	# Level and level label on top-right
	lvl_font = _get_font(52, True)
	lvl_label_font = _get_font(20, False)
	lvl_num_str = f"{level}."
	lbl_w = draw.textlength(level_label, font=lvl_label_font)
	lvl_w = draw.textlength(lvl_num_str, font=lvl_font)
	lbl_x = right_margin - lbl_w
	lvl_x = lbl_x - lvl_w - 6

	draw.text((lvl_x, 80), lvl_num_str, font=lvl_font, fill=COLOR_BLUE, anchor="lt")
	draw.text((lbl_x, 105), level_label, font=lvl_label_font, fill=COLOR_TEXT_GRAY, anchor="lt")

	# User display name and username tag
	name_font = _get_font(44, True)
	tag_font = _get_font(24, False)

	max_name_width = int(lvl_x - content_x - 20)
	display_name = _truncate_text(user.display_name, name_font, max_name_width, draw)
	username = f"@{user.name}"
	username_text = _truncate_text(username, tag_font, max_name_width, draw)

	draw.text((content_x, 75), display_name, font=name_font, fill=COLOR_TEXT_WHITE, anchor="ls")
	draw.text((content_x, 115), username_text, font=tag_font, fill=COLOR_TEXT_GRAY, anchor="ls")

	# XP text right above progress bar
	xp_str = f"{current_xp}/{needed_xp} xp"
	xp_font = _get_font(20, False)
	draw.text((right_margin, 185), xp_str, font=xp_font, fill=COLOR_TEXT_LIGHT_GRAY, anchor="rs")

	# Progress bar
	bar_x0 = content_x
	bar_x1 = right_margin
	bar_y0 = 205
	bar_y1 = 233
	bar_h = bar_y1 - bar_y0
	bar_r = bar_h // 2

	# Track
	draw.rounded_rectangle((bar_x0, bar_y0, bar_x1, bar_y1), radius=bar_r, fill=COLOR_TRACK)

	# Fill
	ratio = min(max(current_xp / max(needed_xp, 1), 0.0), 1.0)
	if ratio > 0:
		total_bar_w = bar_x1 - bar_x0
		fill_w = max(int(total_bar_w * ratio), bar_h)
		draw.rounded_rectangle((bar_x0, bar_y0, bar_x0 + fill_w, bar_y1), radius=bar_r, fill=COLOR_BLUE)

	buffer = io.BytesIO()
	card.save(buffer, format="PNG")
	buffer.seek(0)
	return buffer
