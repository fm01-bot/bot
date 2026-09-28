import discord

from args.category import Category
from args.forum_channel import ForumChannel
from args.stage_channel import StageChannel
from args.text_channel import TextChannel
from args.voice_channel import VoiceChannel

Channel = TextChannel | VoiceChannel | StageChannel | ForumChannel | Category


def convert_to_custom_channel(
	channel: discord.abc.GuildChannel | discord.Thread | discord.abc.Messageable | None,
):
	if channel:
		if isinstance(channel, discord.TextChannel):
			return TextChannel.from_channel(channel)
		elif isinstance(channel, discord.VoiceChannel):
			return VoiceChannel.from_channel(channel)
		elif isinstance(channel, discord.StageChannel):
			return StageChannel.from_channel(channel)
		elif isinstance(channel, discord.ForumChannel):
			return ForumChannel.from_channel(channel)
		elif isinstance(channel, discord.CategoryChannel):
			return Category.from_category(channel)
	return None
