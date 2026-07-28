from typing import Optional, Sequence, Union

import discord
from discord.ext import commands


class Context(commands.Context):
	async def send(  # type: ignore
		self,
		key: Optional[str] = None,
		*,
		content: Optional[str] = None,
		tts: bool = False,
		embed: Optional[discord.Embed] = None,
		embeds: Optional[Sequence[discord.Embed]] = None,
		file: Optional[discord.File] = None,
		files: Optional[Sequence[discord.File]] = None,
		stickers: Optional[Sequence[Union[discord.GuildSticker, discord.StickerItem]]] = None,
		delete_after: Optional[float] = None,
		nonce: Optional[Union[str, int]] = None,
		allowed_mentions: Optional[discord.AllowedMentions] = None,
		reference: Optional[Union[discord.Message, discord.MessageReference, discord.PartialMessage]] = None,
		mention_author: Optional[bool] = None,
		view: Optional[discord.ui.View] = None,
		suppress_embeds: bool = False,
		ephemeral: bool = False,
		silent: bool = False,
		poll: Optional[discord.Poll] = None,
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

		locale_str = self.guild.preferred_locale if self.guild and self.guild.preferred_locale else "en"

		if key is not None:
			localized_payload = await self.bot.custom_response.get_message(key, locale_str, **format_kwargs)
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
