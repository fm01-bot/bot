"""A helper for custom messages."""

from __future__ import annotations

import datetime
import json
import logging
import pathlib
import random
import time
from typing import TYPE_CHECKING, Any, overload

import discord
import wavelink
from args._emoji import Emoji
from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.member import Member
from args.partial_emoji import PartialEmoji
from args.role import Role
from args.track import Track
from args.user import User
from core.context import Context
from discord.ext import commands, localization

if TYPE_CHECKING:
	from core.bot import Bot

logger = logging.getLogger(__name__)

KWARG_MAPPING = {
	discord.Guild: Guild.from_guild,
	discord.Member: Member.from_member,
	discord.User: User.from_user,
	discord.Role: Role.from_role,
	discord.Emoji: Emoji.from_emoji,
	discord.PartialEmoji: PartialEmoji.from_emoji,
	wavelink.Playable: Track.from_track,
}


class CustomResponse:
	def __init__(self, client: Bot, name: str | None = None) -> None:
		"""A class to handle custom responses with localization.

		Parameters
		----------
		client
			The client object with a ``db`` attribute.
		name
			The name of the cog that uses this class.
		"""
		self.client = client
		self.name = name
		self.localizations: dict[str, dict] = {}
		self._localizer: localization.Localization | None = None
		self._last_debug_reload: float = 0

		self.load_localizations()

	def convert_embeds(self, data: Any) -> Any:
		"""Converts ``data``'s embed (dict) or embeds (list) keys' values into a ``discord.Embed``.

		This converts in a smart way: if there are both an ``embed`` and ``embeds`` key, ``embed`` will be merged into ``embeds``.

		Parameters
		----------
		data
			The data that might contain an ``embed`` or an ``embeds`` key. Conversion is only performed if this is a ``dict``.

		Returns
		-------
		Any
			The original data, but with usable ``discord.Embed``s.

		Raises
		------
		ValueError
			If there are more than 10 embeds.
		"""
		if isinstance(data, dict) and (data.get("embed") or data.get("embeds")):
			if len(data.get("embeds", [])) > 10:
				raise ValueError(f"The maximum number of embeds is 10. You have {len(data['embeds'])} embeds.")
			if data.get("embed") and not data.get("embeds"):
				data["embeds"] = [data.pop("embed")]

			cleaned_embeds = []
			for embed_dict in data.get("embeds", []):
				if not isinstance(embed_dict, dict):
					continue
				fields = embed_dict.get("fields", [])
				cleaned_fields = []

				for field in fields:
					value = field.get("value")
					if value in ("None", "0", ""):
						continue  # skip empty fields
					if value == "True":
						field["value"] = self.client.config.emojis.get("check")
					if value == "False":
						field["value"] = self.client.config.emojis.get("x")
					cleaned_fields.append(field)

				embed_dict["fields"] = cleaned_fields
				cleaned_embeds.append(discord.Embed.from_dict(embed_dict))

			data["embeds"] = cleaned_embeds
		return data

	@overload
	def update_localizations(self, data: dict): ...

	@overload
	def update_localizations(self, path: str): ...

	def update_localizations(self, data: dict | str):
		if isinstance(data, dict):
			for lang, translations in data.items():
				if isinstance(translations, dict):
					self.localizations.setdefault(lang, {}).update(translations)
				else:
					self.localizations[lang] = translations
			self._localizer = localization.Localization(self.localizations, default_locale="en")
		elif isinstance(data, str):
			self.load_localizations(data)

	def load_localizations(self, path: str = "./localization"):
		localization_path = pathlib.Path(path)
		for file_path in localization_path.glob("*.l10n.json"):
			lang = file_path.stem.removesuffix(".l10n")
			try:
				with open(file_path, encoding="utf-8") as f:
					data = json.load(f)
					if not isinstance(data, dict):
						raise TypeError(f"Expected dict in {file_path}, got {type(data).__name__}")
					self.localizations.setdefault(lang, {}).update(data)
			except (OSError, json.JSONDecodeError) as e:
				logger.warning(f"Failed to load {file_path}: {e}")

		self._localizer = localization.Localization(self.localizations, default_locale="en")

	async def get_message(
		self,
		name: str,
		locale: str | discord.Locale | discord.Guild | discord.Interaction | commands.Context | Context,
		/,
		*,
		convert_embeds: bool = True,
		**kwargs,
	) -> dict | str | list | int | float | bool:
		"""Returns a custom message from the database, or if not found, returns the default message.

		Parameters
		----------
		name
			The name of the message.
		locale
			The locale to use or the context to derive it.
		convert_embeds
		    Whether to convert the embeds in the message to discord.Embeds.

		Returns
		-------
		Union[dict, str, list, int, float, bool]
		    The message payload.
		"""
		original = locale

		if isinstance(locale, (discord.Interaction, commands.Context)):
			locale = locale.guild.preferred_locale if (locale.guild and locale.guild.preferred_locale) else "en"
		elif isinstance(locale, discord.Guild):
			locale = locale.preferred_locale or "en"
		elif isinstance(locale, discord.Message):
			locale = locale.guild.preferred_locale or "en" if locale.guild else "en"
		else:
			locale = str(locale)

		# these are variables that are always inserted into commands IF there is a context
		context_formatting = {
			"author": (
				Member.from_member(original.author)
				if original.guild and isinstance(original.author, discord.Member)
				else User.from_user(original.author)
			)
			if isinstance(original, commands.Context)
			else (
				Member.from_member(original.user)
				if original.guild and isinstance(original.user, discord.Member)
				else User.from_user(original.user)
			)
			if isinstance(original, discord.Interaction)
			else None,
			"guild": (
				Guild.from_guild(original.guild)
				if isinstance(original, (discord.Interaction, commands.Context)) and original.guild
				else Guild.from_guild(original)
				if isinstance(original, discord.Guild)
				else None
			),
			"now": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
		}

		logger.debug(context_formatting)

		# these are kwargs that are passed in but they're converted into custom args
		for key, value in kwargs.items():
			for _type, converter in KWARG_MAPPING.items():
				if isinstance(value, _type):
					kwargs[key] = converter(value)
				elif isinstance(value, datetime.datetime):
					kwargs[key] = FormatDateTime(value, default_style="F")

		if self.client.debug:
			now = time.time()
			if now - self._last_debug_reload > 5:
				self.load_localizations("../localization")
				self._last_debug_reload = now

		if not self._localizer:
			return "localizer not initialized!"

		payload = self._localizer.localize(name, locale, **kwargs, random=r"{random}", **context_formatting)

		if isinstance(payload, dict):
			if random_value := payload.get("random"):
				payload = localization.Localization.format_strings(payload, random=random.choice(random_value))
			payload.pop("random", None)
			payload = self.convert_embeds(payload) if convert_embeds else payload

			if payload.get("reply"):
				payload["reference"] = (
					original.message if isinstance(original, (discord.Interaction, commands.Context)) else None
				)
			payload.pop("reply", None)

			if allowed_mentions := payload.get("allowed_mentions"):
				if "all" in allowed_mentions:
					payload["allowed_mentions"] = discord.AllowedMentions.all()
				elif "none" in allowed_mentions:
					payload["allowed_mentions"] = discord.AllowedMentions.none()
				else:
					payload["allowed_mentions"] = discord.AllowedMentions(**allowed_mentions)

			if payload.get("ephemeral") or payload.get("delete_after"):
				if not isinstance(original, discord.Interaction):
					payload.pop("ephemeral", None)
				else:
					payload.pop("delete_after", None)
		return payload

	__call__ = get_message
