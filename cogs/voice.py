import logging
import math
import os
from typing import Literal, cast

import discord
import wavelink
from core import Bot, Context
from core.hybrid import command
from discord.ext import commands

logger = logging.getLogger(__name__)


class LuminPlayer(wavelink.Player):
	home: int | None = None
	is_shuffle: bool = False


def format_ms(ms: int) -> str:
	total_seconds = max(0, ms // 1000)
	minutes, seconds = divmod(total_seconds, 60)
	hours, minutes = divmod(minutes, 60)
	if hours > 0:
		return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
	return f"{minutes:02d}:{seconds:02d}"


def make_progress_bar(position_ms: int, duration_ms: int, length: int = 14) -> str:
	if duration_ms <= 0:
		return "🔴 `Live`"
	ratio = max(0.0, min(1.0, position_ms / duration_ms))
	filled = int(ratio * length)
	bar = "▬" * filled + "🔘" + "▬" * (length - filled)
	return f"`{format_ms(position_ms)}` {bar} `{format_ms(duration_ms)}`"


class Voice(commands.GroupCog, name="Voice", group_name="voice"):
	def __init__(self, client: Bot):
		self.client: Bot = client

	async def cog_load(self) -> None:
		if not self.client.lavalink:
			await self._init_lavalink()

	async def cog_unload(self) -> None:
		await wavelink.Pool.close()
		self.client.lavalink = None
		logger.info("[Lavalink] ~> Connection closed.")

	async def _init_lavalink(self) -> None:
		node_uri = os.getenv("LAVALINK_URI")
		node_password = os.getenv("LAVALINK_PASSWORD")
		if not node_uri or not node_password:
			logger.error("LAVALINK_URI or LAVALINK_PASSWORD not set")
			return
		try:
			nodes = [wavelink.Node(uri=node_uri, password=node_password)]
			pool = await wavelink.Pool.connect(nodes=nodes, client=self.client)
			self.client.lavalink = pool
			logger.info(f"Connected to {node_uri}")
		except Exception:
			logger.exception("Connection failed")

	async def _get_player(self, ctx: Context, *, connect: bool = False) -> LuminPlayer | None:
		if not ctx.guild:
			await ctx.send("voice.errors.only_server")
			return None

		if not isinstance(ctx.author, discord.Member) or not ctx.author.voice or not ctx.author.voice.channel:
			await ctx.send("voice.errors.not_in_voice")
			return None

		if not self.client.lavalink or not wavelink.Pool.nodes:
			await ctx.send("voice.errors.not_connected")
			return None

		player = cast(LuminPlayer | None, ctx.guild.voice_client)
		if not player or not player.connected:
			if connect:
				player = await ctx.author.voice.channel.connect(cls=LuminPlayer, self_deaf=True)
			else:
				await ctx.send("voice.errors.not_connected")
				return None

		if ctx.author.voice.channel.id != player.channel.id:
			await ctx.send("voice.errors.different_channel")
			return None

		if not player.home and ctx.channel:
			player.home = ctx.channel.id

		return player

	@commands.Cog.listener()
	async def on_voice_state_update(
		self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
	):
		if not member.guild or not member.guild.voice_client:
			return
		player = cast(LuminPlayer, member.guild.voice_client)
		if not player or not player.playing or not player.channel:
			return

		if (
			before.channel
			and after.channel is None
			and player.channel.id == before.channel.id
			and len(before.channel.members) <= 1
		):
			await player.disconnect()
			if player.home:
				ch = member.guild.get_channel(player.home)
				if ch and isinstance(ch, discord.TextChannel):
					msg = await self.client.custom_response.get_message(
						"voice.listener.disconnected_empty", member.guild
					)
					if isinstance(msg, dict):
						await ch.send(**msg)
					elif isinstance(msg, str):
						await ch.send(msg)

	@command(user=False)
	async def play(self, ctx: Context, *, query: str):
		player = await self._get_player(ctx, connect=True)
		if not player:
			return

		results: wavelink.Search = await wavelink.Playable.search(query, source=wavelink.TrackSource.YouTubeMusic)
		if not results:
			await ctx.send("voice.errors.no_results", query=query)
			return

		player.autoplay = wavelink.AutoPlayMode.partial

		if isinstance(results, wavelink.Playlist):
			await player.queue.put_wait(results)
			await ctx.send("voice.play.playlist_enqueued", name=results.name, url=query, count=len(results.tracks))
		else:
			track = results[0]
			was_playing = player.playing or len(player.queue) > 0
			await player.queue.put_wait(track)
			if was_playing:
				await ctx.send("voice.play.track_enqueued", track=track, position=len(player.queue))
			else:
				await ctx.send("voice.play.now_playing", track=track)

		if not player.playing and len(player.queue) > 0:
			await player.play(player.queue.get())

	@command(user=False)
	async def pause(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		if not player.playing:
			await ctx.send("voice.errors.not_playing")
			return
		if player.paused:
			await ctx.send("voice.pause.already_paused")
			return
		await player.pause(True)
		await ctx.send("voice.pause.success")

	@command(user=False)
	async def resume(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		if not player.paused:
			await ctx.send("voice.resume.not_paused")
			return
		await player.pause(False)
		await ctx.send("voice.resume.success")

	@command(user=False)
	async def stop(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		player.queue.clear()
		await player.disconnect()
		await ctx.send("voice.stop.success")

	@command(user=False)
	async def skip(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		if not player.playing:
			await ctx.send("voice.errors.not_playing")
			return
		await player.skip(force=True)
		if player.current:
			await ctx.send("voice.skip.success_next", track=player.current)
		else:
			await ctx.send("voice.skip.success_empty")

	@command(user=False)
	async def volume(self, ctx: Context, level: commands.Range[int, 0, 150] | None = None):
		player = await self._get_player(ctx)
		if not player:
			return
		if level is None:
			await ctx.send("voice.volume.current", volume=player.volume)
			return
		await player.set_volume(level)
		await ctx.send("voice.volume.set", volume=player.volume)

	@command(user=False)
	async def seek(self, ctx: Context, seconds: int):
		player = await self._get_player(ctx)
		if not player:
			return
		if not player.playing or not player.current:
			await ctx.send("voice.errors.not_playing")
			return
		new_pos = player.position + (seconds * 1000)
		if new_pos < 0 or (player.current.length > 0 and new_pos > player.current.length):
			await ctx.send("voice.seek.out_of_range")
			return
		await player.seek(new_pos)
		await ctx.send("voice.seek.success", position=format_ms(new_pos))

	@command(user=False)
	async def shuffle(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		if len(player.queue) == 0:
			await ctx.send("voice.errors.empty_queue")
			return
		player.queue.shuffle()
		player.is_shuffle = True
		await ctx.send("voice.shuffle.success", count=len(player.queue))

	@command(user=False)
	async def loop(self, ctx: Context, mode: Literal["off", "track", "queue"] | None = None):
		player = await self._get_player(ctx)
		if not player:
			return
		if mode == "track":
			player.queue.mode = wavelink.QueueMode.loop
		elif mode == "queue":
			player.queue.mode = wavelink.QueueMode.loop_all
		elif mode == "off":
			player.queue.mode = wavelink.QueueMode.normal
		else:
			if player.queue.mode == wavelink.QueueMode.normal:
				player.queue.mode = wavelink.QueueMode.loop
			elif player.queue.mode == wavelink.QueueMode.loop:
				player.queue.mode = wavelink.QueueMode.loop_all
			else:
				player.queue.mode = wavelink.QueueMode.normal

		mode_names = {
			wavelink.QueueMode.normal: "❌",
			wavelink.QueueMode.loop: "🔁",
			wavelink.QueueMode.loop_all: "🔁🔁",
		}
		await ctx.send("voice.loop.set", mode=mode_names.get(player.queue.mode, "Off"))

	@command(user=False)
	async def np(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		if not player.current:
			await ctx.send("voice.errors.not_playing")
			return

		track = player.current
		loop_name = (
			"Track"
			if player.queue.mode == wavelink.QueueMode.loop
			else ("Queue" if player.queue.mode == wavelink.QueueMode.loop_all else "Off")
		)
		await ctx.send(
			"voice.np",
			track=track,
			progress_bar=make_progress_bar(player.position, track.length),
			volume=player.volume,
			loop=loop_name,
		)

	@command(user=False)
	async def queue(self, ctx: Context, page: commands.Range[int, 1] = 1):
		player = await self._get_player(ctx)
		if not player:
			return
		if len(player.queue) == 0:
			await ctx.send("voice.errors.empty_queue")
			return

		items_per_page = 10
		total_pages = max(1, math.ceil(len(player.queue) / items_per_page))
		page = min(page, total_pages)
		start = (page - 1) * items_per_page
		end = start + items_per_page

		lines = []
		for i, track in enumerate(player.queue[start:end], start=start + 1):
			dur = "Live" if track.is_stream else format_ms(track.length)
			lines.append(f"`{i}.` **[{track.title}]({track.uri})** ({dur})")

		await ctx.send(
			"voice.queue", tracks="\n".join(lines), page=page, total_pages=total_pages, total_tracks=len(player.queue)
		)

	@command(name="remove", l10n_key="voice_remove", user=False)
	async def remove(self, ctx: Context, index: commands.Range[int, 1]):
		player = await self._get_player(ctx)
		if not player:
			return
		if len(player.queue) == 0:
			await ctx.send("voice.errors.empty_queue")
			return
		if index > len(player.queue):
			await ctx.send("voice.remove.out_of_range", max=len(player.queue))
			return
		target = player.queue[index - 1]
		player.queue.delete(index - 1)
		await ctx.send("voice.remove.success", track=target)

	@command(user=False)
	async def clear(self, ctx: Context):
		player = await self._get_player(ctx)
		if not player:
			return
		if len(player.queue) == 0:
			await ctx.send("voice.clear.already_empty")
			return
		count = len(player.queue)
		player.queue.clear()
		await ctx.send("voice.clear.success", count=count)


async def setup(client: Bot):
	await client.add_cog(Voice(client))
