from typing import Optional, Union

import discord
from args.forum_channel import ForumChannel
from args.stage_channel import StageChannel
from args.text_channel import TextChannel
from args.voice_channel import VoiceChannel

Channel = Union[TextChannel, VoiceChannel, StageChannel, ForumChannel]


def convert_to_custom_channel(channel: Optional[discord.abc.GuildChannel]):
	if channel:
		if isinstance(channel, discord.TextChannel):
			return TextChannel.from_channel(channel)
		elif isinstance(channel, discord.VoiceChannel):
			return VoiceChannel.from_channel(channel)
		elif isinstance(channel, discord.StageChannel):
			return StageChannel.from_channel(channel)
		elif isinstance(channel, discord.ForumChannel):
			return ForumChannel.from_channel(channel)
	return None
