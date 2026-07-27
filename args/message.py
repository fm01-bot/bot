import datetime
from dataclasses import dataclass, field
from typing import Optional

import discord

from args.channel import Channel, convert_to_custom_channel
from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.member import Member
from args.user import User


@dataclass(slots=True)
class Message:
	"""A class that represents a Discord message with useful formatting properties.

	This class is designed to be used in localization strings and provides
	easy access to message properties that are commonly used in logs.
	"""

	id: int
	"""Returns the message's ID."""
	content: str
	"""Returns the message's content."""
	_embeds: list[discord.Embed] = field(repr=False)
	_attachments: list[discord.Attachment] = field(repr=False)
	_stickers: list[discord.StickerItem] = field(repr=False)
	_author: discord.User | discord.Member = field(repr=False)
	_channel: Optional[discord.TextChannel] = field(repr=False)
	_guild: Optional[discord.Guild] = field(repr=False)
	_created_at: datetime.datetime = field(repr=False)
	_edited_at: Optional[datetime.datetime] = field(repr=False)
	_pinned: bool = field(repr=False)
	_tts: bool = field(repr=False)
	_mention_everyone: bool = field(repr=False)
	_mentions: list[discord.Member] = field(repr=False)
	_role_mentions: list[discord.Role] = field(repr=False)
	_channel_mentions: list[discord.abc.GuildChannel | discord.Thread] = field(repr=False)
	_reference: Optional[discord.MessageReference] = field(repr=False)
	_flags: discord.MessageFlags = field(repr=False)
	_components: list[discord.ActionRow | discord.ui.Button | discord.SelectMenu | discord.ui.TextInput] = field(
		repr=False
	)
	_jump_url: str = field(repr=False)
	_poll: Optional[discord.Poll] = field(repr=False)

	@classmethod
	def from_message(cls, message: discord.Message):
		"""Creates a CustomMessage from a discord.Message object."""
		return cls(
			id=message.id,
			content=message.content,
			_embeds=message.embeds,
			_attachments=message.attachments,
			_stickers=message.stickers,
			_author=message.author,
			_channel=message.channel,
			_guild=message.guild,
			_created_at=message.created_at,
			_edited_at=message.edited_at,
			_pinned=message.pinned,
			_tts=message.tts,
			_mention_everyone=message.mention_everyone,
			_mentions=message.mentions,
			_role_mentions=message.role_mentions,
			_channel_mentions=message.channel_mentions,  # type: ignore
			_reference=message.reference,
			_flags=message.flags,
			_components=message.components,
			_jump_url=message.jump_url,
			_poll=message.poll,
		)

	@property
	def jump_url(self) -> str:
		"""Returns the message's jump URL."""
		return self._jump_url

	url = jump_url

	@property
	def embeds(self) -> int:
		"""Returns the number of embeds in the message."""
		return len(self._embeds)

	@property
	def attachments(self) -> int:
		"""Returns the number of attachments in the message."""
		return len(self._attachments)

	@property
	def stickers(self) -> int:
		"""Returns the number of stickers in the message."""
		return len(self._stickers)

	@property
	def author(self) -> Member:
		"""Returns the message's author."""
		return (
			Member.from_member(self._author)
			if isinstance(self._author, discord.Member)
			else User.from_user(self._author)
		)

	@property
	def channel(self) -> Optional[Channel]:
		"""Returns the message's channel mention."""
		return convert_to_custom_channel(self._channel)

	@property
	def guild(self) -> Guild:
		"""Returns the message's guild."""
		return Guild.from_guild(self._guild) if self._guild else None

	@property
	def created_at(self):
		"""Returns the date the message was created as a Discord timestamp."""
		return FormatDateTime(self._created_at, "F")

	created = created_at

	@property
	def edited_at(self):
		"""Returns the date the message was edited as a Discord timestamp."""
		return FormatDateTime(self._edited_at, "F") if self._edited_at else None

	edited = edited_at

	@property
	def pinned(self) -> bool:
		"""Returns whether the message is pinned."""
		return self._pinned

	@property
	def tts(self) -> bool:
		"""Returns whether the message is TTS."""
		return self._tts

	@property
	def mention_everyone(self) -> bool:
		"""Returns whether the message mentions everyone."""
		return self._mention_everyone

	@property
	def mentions(self) -> int:
		"""Returns the number of user mentions in the message."""
		return len(self._mentions)

	@property
	def role_mentions(self) -> int:
		"""Returns the number of role mentions in the message."""
		return len(self._role_mentions)

	@property
	def channel_mentions(self) -> int:
		"""Returns the number of channel mentions in the message."""
		return len(self._channel_mentions)

	@property
	def reference(self) -> Optional[str]:
		"""Returns the message's reference if it exists."""
		return self._reference.jump_url if self._reference else None

	@property
	def flags(self) -> int:
		"""Returns the message's flags as an integer."""
		return self._flags.value

	@property
	def components(self) -> int:
		"""Returns the number of components in the message."""
		return len(self._components)

	@property
	def poll(self) -> bool:
		"""Returns whether the message has a poll."""
		return bool(self._poll)

	def __str__(self):
		return self.content

	def __int__(self):
		return self.id
