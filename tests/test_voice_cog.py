from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import wavelink
from cogs.voice import Voice, format_ms, make_progress_bar


@pytest.mark.parametrize(("ms", "text"), [(0, "00:00"), (-5, "00:00"), (61_000, "01:01"), (3_661_000, "01:01:01")])
def test_format_ms(ms, text):
	assert format_ms(ms) == text


def test_progress_bar_marks_the_position_and_handles_streams():
	assert make_progress_bar(5_000, 0) == "🔴 `Live`"
	bar = make_progress_bar(30_000, 60_000, length=10)
	assert bar.startswith("`00:30` ") and bar.endswith(" `01:00`")
	assert bar.index("🔘") == len("`00:30` ") + 5
	assert make_progress_bar(90_000, 60_000, length=4).count("▬") == 4  # clamped past the end


def player(**attrs) -> MagicMock:
	p = MagicMock()
	p.queue = MagicMock()
	p.queue.mode = wavelink.QueueMode.normal
	p.set_volume = AsyncMock()
	p.seek = AsyncMock()
	for key, value in attrs.items():
		setattr(p, key, value)
	return p


@pytest.fixture
def cog() -> Voice:
	return Voice(MagicMock())


@pytest.fixture
def ctx() -> MagicMock:
	ctx = MagicMock()
	ctx.send = AsyncMock()
	return ctx


@pytest.mark.parametrize(
	("mode", "expected"),
	[("track", wavelink.QueueMode.loop), ("queue", wavelink.QueueMode.loop_all), ("off", wavelink.QueueMode.normal)],
)
async def test_loop_sets_the_requested_mode(cog, ctx, mode, expected):
	p = player()
	cog._get_player = AsyncMock(return_value=p)
	await cog.loop.callback(cog, ctx, mode)
	assert p.queue.mode == expected


async def test_loop_without_a_mode_cycles(cog, ctx):
	p = player()
	cog._get_player = AsyncMock(return_value=p)
	seen = []
	for _ in range(3):
		await cog.loop.callback(cog, ctx, None)
		seen.append(p.queue.mode)
	assert seen == [wavelink.QueueMode.loop, wavelink.QueueMode.loop_all, wavelink.QueueMode.normal]


async def test_seek_refuses_positions_outside_the_track(cog, ctx):
	p = player(playing=True, position=10_000)
	p.current.length = 60_000
	cog._get_player = AsyncMock(return_value=p)

	await cog.seek.callback(cog, ctx, -20)
	assert ctx.send.call_args.args[0] == "voice.seek.out_of_range"

	await cog.seek.callback(cog, ctx, 20)
	p.seek.assert_awaited_once_with(30_000)
	assert ctx.send.call_args.args[0] == "voice.seek.success"


async def test_get_player_requires_a_guild_voice_and_lavalink(cog, ctx):
	ctx.guild = None
	assert await cog._get_player(ctx) is None
	assert ctx.send.call_args.args[0] == "voice.errors.only_server"

	ctx.guild = MagicMock()
	ctx.author = MagicMock(spec=discord.Member)
	ctx.author.voice = None
	assert await cog._get_player(ctx) is None
	assert ctx.send.call_args.args[0] == "voice.errors.not_in_voice"


async def test_get_player_refuses_a_different_voice_channel(cog, ctx, monkeypatch):
	fake_wavelink = MagicMock()
	fake_wavelink.Pool.nodes = {"n": MagicMock()}
	monkeypatch.setattr("cogs.voice.wavelink", fake_wavelink)
	cog.client.lavalink = True
	ctx.author = MagicMock(spec=discord.Member)
	ctx.author.voice.channel.id = 1
	ctx.guild.voice_client = player(connected=True)
	ctx.guild.voice_client.channel.id = 2

	assert await cog._get_player(ctx) is None
	assert ctx.send.call_args.args[0] == "voice.errors.different_channel"
