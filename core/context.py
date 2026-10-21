from collections.abc import Sequence

import discord
from discord.ext import commands


class Context(commands.Context):
	async def send(  # type: ignore
		self,
		key: str | None = None,
		*,
		content: str | None = None,
		tts: bool = False,
		embed: discord.Embed | None = None,
		embeds: Sequence[discord.Embed] | None = None,
		file: discord.File | None = None,
		files: Sequence[discord.File] | None = None,
		stickers: Sequence[discord.GuildSticker | discord.StickerItem] | None = None,
		delete_after: float | None = None,
		nonce: str | int | None = None,
		allowed_mentions: discord.AllowedMentions | None = None,
		reference: discord.Message | discord.MessageReference | discord.PartialMessage | None = None,
		mention_author: bool | None = None,
		view: discord.ui.View | None = None,
		suppress_embeds: bool = False,
		ephemeral: bool = False,
		silent: bool = False,
		poll: discord.Poll | None = None,
		**format_kwargs: object,
	) -> discord.Message:
		"""Sends a localized message.

		This is done by merging the arguments passed to send with a
		localized payload (if a localization key is provided) and then delegating to
		super().send.

		Exactly one of the following must be provided:
		  - A localization key as the first positional argument (key)
		  - A raw message string via the keyword-only argument `content`
		"""
		base_args = {
			"content": content,
			"tts": tts,
			"embed": embed,
			"embeds": embeds,
			"file": file,
			"files": files,
			"stickers": stickers,
			"nonce": nonce,
			"allowed_mentions": allowed_mentions,
			"reference": reference,
			"mention_author": mention_author,
			"view": view,
			"suppress_embeds": suppress_embeds,
			"ephemeral": ephemeral,
			"silent": silent,
			"poll": poll,
		}

		if key is not None:
			localized_payload = await self.bot.custom_response.get_message(key, self, **format_kwargs)
		else:
			localized_payload = content

		if isinstance(localized_payload, dict):
			base_args.update(localized_payload)
		else:
			base_args["content"] = localized_payload

		merged_args = {k: v for k, v in base_args.items() if v is not None}

		msg = await super().send(**merged_args)  # type: ignore
		if delete_after is not None:
			await msg.delete(delay=delete_after)
		return msg

	async def reply(self, *args, **kwargs) -> discord.Message:
		"""Behaves like send, but automatically sets reference to self.message. Don't use this unless it's necessary."""
		kwargs.setdefault("reference", self.message)
		return await self.send(*args, **kwargs)

	def __repr__(self) -> str:
		author_str = f"{self.author} (id={getattr(self.author, 'id', None)})" if self.author else "None"
		guild_str = f"{self.guild} (id={getattr(self.guild, 'id', None)})" if self.guild else "None"
		channel_str = f"{self.channel} (id={getattr(self.channel, 'id', None)})" if self.channel else "None"
		command_str = getattr(self.command, "qualified_name", None)
		return f"Context(author={author_str}, guild={guild_str}, channel={channel_str}, command={command_str})"

	__str__ = __repr__
