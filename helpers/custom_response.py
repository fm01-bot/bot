"""A helper for custom messages."""

from __future__ import annotations

import contextlib
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
from args.channel import convert_to_custom_channel
from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.member import Member
from args.partial_emoji import PartialEmoji
from args.role import Role
from args.text_channel import TextChannel
from args.track import Track
from args.user import User
from core.context import Context
from core.locale import resolve_locale
from discord.ext import commands, localization

if TYPE_CHECKING:
	from core.bot import Bot

__all__ = ("DEFAULT_COLOR", "DEFAULT_EMBED_COLOR", "CustomResponse")

logger = logging.getLogger(__name__)

DEFAULT_COLOR = 0x6094EB
DEFAULT_EMBED_COLOR = DEFAULT_COLOR

KWARG_MAPPING = {
	discord.Guild: Guild.from_guild,
	discord.Member: Member.from_member,
	discord.User: User.from_user,
	discord.Role: Role.from_role,
	discord.Emoji: Emoji.from_emoji,
	discord.PartialEmoji: PartialEmoji.from_emoji,
	discord.TextChannel: TextChannel.from_channel,
	wavelink.Playable: Track.from_track,
}


def _parse_color(color: Any) -> discord.Color | int | None:
	"""Parses a color value from an int, hex string, or discord.Color.

	Args:
		color: The color representation, such as an int, hex string (e.g. ``"#6094EB"``,
			``"0x6094EB"``), named color, or ``discord.Color``.

	Returns:
		discord.Color | int | None: The parsed color as a ``discord.Color`` or ``int``, or ``None`` if invalid.

	"""
	if color is None or isinstance(color, bool):
		return None
	if isinstance(color, (discord.Color, int)):
		return color
	if isinstance(color, str):
		c = color.strip()
		if c.startswith("#"):
			c = c[1:]
		elif c.startswith(("0x", "0X")):
			c = c[2:]
		if len(c) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in c):
			c = "".join(ch * 2 for ch in c)
		try:
			return discord.Color(int(c, 16))
		except ValueError:
			if hasattr(discord.Color, c.lower()):
				color_fn = getattr(discord.Color, c.lower())
				if callable(color_fn):
					return color_fn()
	return None


def _parse_button_style(style: Any) -> discord.ButtonStyle:
	if isinstance(style, discord.ButtonStyle):
		return style
	if isinstance(style, int):
		try:
			return discord.ButtonStyle(style)
		except ValueError:
			return discord.ButtonStyle.secondary
	if isinstance(style, str):
		match style.lower().strip():
			case "primary" | "blurple":
				return discord.ButtonStyle.primary
			case "secondary" | "gray" | "grey":
				return discord.ButtonStyle.secondary
			case "success" | "green":
				return discord.ButtonStyle.success
			case "danger" | "red":
				return discord.ButtonStyle.danger
			case "link" | "url":
				return discord.ButtonStyle.link
			case "premium":
				return discord.ButtonStyle.premium
	return discord.ButtonStyle.secondary


class CustomResponseFormatter(localization.CustomFormatter):
	def format(self, format_string: str, /, *args: Any, **kwargs: Any) -> Any:
		lines = format_string.split("\n")
		kept_lines: list[str] = []
		for line in lines:
			has_none = False
			for _, field_name, _, _ in self.parse(line):
				if field_name is not None:
					with contextlib.suppress(KeyError, AttributeError, IndexError):
						val, _ = self.get_field(field_name, args, kwargs)
						if val is None:
							has_none = True
							break
			if not has_none:
				kept_lines.append(line)

		while kept_lines and not kept_lines[-1].strip():
			kept_lines.pop()

		new_format_string = "\n".join(kept_lines)
		return super().format(new_format_string, *args, **kwargs)


class CustomLocalization(localization.Localization):
	_custom_formatter = CustomResponseFormatter()

	@classmethod
	def format_strings(cls, data: Any, *, placeholders: bool = True, **kwargs: Any) -> Any:
		if isinstance(data, dict):
			return {key: cls.format_strings(value, placeholders=placeholders, **kwargs) for key, value in data.items()}
		elif isinstance(data, list):
			return [cls.format_strings(item, placeholders=placeholders, **kwargs) for item in data]
		elif isinstance(data, str):
			return cls._custom_formatter.format(data, **kwargs) if placeholders else data.format(**kwargs)
		else:
			return data


class CustomResponse:
	def __init__(self, client: Bot, name: str | None = None) -> None:
		"""A class to handle custom responses with localization.

		Args:
			client: The client object with a ``db`` attribute.
			name: The name of the cog that uses this class.

		"""
		self.client = client
		self.name = name
		self.localizations: dict[str, dict] = {}
		self._localizer: CustomLocalization | None = None
		self._last_debug_reload: float = 0

		self.load_localizations()

	def convert_embeds(self, data: Any) -> Any:
		"""Converts ``data``'s embed (dict) or embeds (list) keys' values into a ``discord.Embed``.

		This converts in a smart way: if there are both an ``embed`` and ``embeds`` key, ``embed`` will be merged into ``embeds``.
		Embeds without a color are assigned a default color (0x6094EB), and hex code strings (e.g. ``"#6094EB"`` or
		``"0x6094EB"``) are supported.

		Args:
			data: The data that might contain an ``embed`` or an ``embeds`` key. Conversion is only performed if this is a ``dict``.

		Returns:
			Any: The original data, but with usable ``discord.Embed``s.

		Raises:
			ValueError: If there are more than 10 embeds.

		"""
		if isinstance(data, dict) and (data.get("embed") or data.get("embeds")):
			if data.get("embed"):
				single_embed = data.pop("embed")
				if not data.get("embeds"):
					data["embeds"] = [single_embed]
				elif isinstance(data["embeds"], list):
					data["embeds"].append(single_embed)

			if len(data.get("embeds", [])) > 10:
				raise ValueError(f"The maximum number of embeds is 10. You have {len(data['embeds'])} embeds.")

			cleaned_embeds = []
			for embed_dict in data.get("embeds", []):
				if isinstance(embed_dict, discord.Embed):
					if embed_dict.color is None:
						embed_dict.color = discord.Color(DEFAULT_COLOR)
					cleaned_embeds.append(embed_dict)
					continue
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

				raw_color = embed_dict.pop("colour", None)
				if "color" in embed_dict:
					raw_color = embed_dict.pop("color")

				parsed_color = _parse_color(raw_color) if raw_color is not None else None
				if parsed_color is None:
					parsed_color = DEFAULT_COLOR

				embed_dict["color"] = parsed_color.value if isinstance(parsed_color, discord.Color) else parsed_color
				cleaned_embeds.append(discord.Embed.from_dict(embed_dict))

			data["embeds"] = cleaned_embeds
		return data

	@staticmethod
	def convert_component(comp: Any) -> discord.ui.Item | None:
		"""Converts a dictionary representation into a ``discord.ui.Item``.

		Args:
			comp: The component dictionary or already-instantiated ``Item``.

		Returns:
			discord.ui.Item | None: The constructed Discord UI component item, or ``None`` if invalid.

		"""
		if isinstance(comp, discord.ui.Item):
			return comp
		if not isinstance(comp, dict):
			return None

		raw_type = comp.get("type", 10)
		if isinstance(raw_type, discord.ComponentType):
			raw_type = raw_type.value
		if isinstance(raw_type, str):
			raw_type = raw_type.lower().strip()

		if raw_type in (17, "container"):
			accent = _parse_color(comp.get("accent_color", comp.get("accent_colour")))
			spoiler = bool(comp.get("spoiler", False))
			children: list[discord.ui.Item] = []
			pending_row: list[discord.ui.Item] = []
			for c in comp.get("components", []):
				ci = CustomResponse.convert_component(c)
				if ci is None:
					if children and isinstance(children[-1], discord.ui.Separator):
						children.pop()
					continue
				if isinstance(
					ci,
					(
						discord.ui.Button,
						discord.ui.Select,
						discord.ui.ChannelSelect,
						discord.ui.RoleSelect,
						discord.ui.UserSelect,
						discord.ui.MentionableSelect,
					),
				):
					pending_row.append(ci)
				else:
					if pending_row:
						for i in range(0, len(pending_row), 5):
							children.append(discord.ui.ActionRow(*pending_row[i : i + 5]))
						pending_row = []
					if (
						isinstance(ci, discord.ui.Separator)
						and children
						and isinstance(children[-1], discord.ui.Separator)
					):
						continue
					children.append(ci)
			if pending_row:
				for i in range(0, len(pending_row), 5):
					children.append(discord.ui.ActionRow(*pending_row[i : i + 5]))

			return discord.ui.Container(*children, accent_color=accent, spoiler=spoiler)

		elif raw_type in (9, "section"):
			accessory = CustomResponse.convert_component(comp.get("accessory")) if comp.get("accessory") else None
			if accessory is None:
				raise ValueError("Section component requires an 'accessory' item.")
			children_list: list[discord.ui.Item | str] = []
			for c in comp.get("components", []):
				converted = CustomResponse.convert_component(c)
				if converted:
					children_list.append(converted)
			if not children_list and "text" in comp:
				children_list = [discord.ui.TextDisplay(str(comp["text"]))]
			return discord.ui.Section(*children_list, accessory=accessory)

		elif raw_type in (10, "text_display", "text"):
			raw_content = str(comp.get("content", comp.get("text", "")))
			if not raw_content.strip():
				return None
			return discord.ui.TextDisplay(raw_content)

		elif raw_type in (14, "separator"):
			visible = bool(comp.get("visible", comp.get("divider", True)))
			sp_raw = comp.get("spacing", 1)
			sp = (
				discord.SeparatorSpacing.large
				if (sp_raw == 2 or str(sp_raw).lower() == "large")
				else discord.SeparatorSpacing.small
			)
			return discord.ui.Separator(visible=visible, spacing=sp)

		elif raw_type in (11, "thumbnail"):
			return discord.ui.Thumbnail(
				media=comp.get("media", comp.get("url", "")),
				description=comp.get("description"),
				spoiler=bool(comp.get("spoiler", False)),
			)

		elif raw_type in (12, "media_gallery"):
			items: list[discord.MediaGalleryItem] = []
			for item in comp.get("items", []):
				if isinstance(item, dict):
					items.append(
						discord.MediaGalleryItem(
							media=item.get("media", item.get("url", "")),
							description=item.get("description", ...),
							spoiler=item.get("spoiler", ...),
						)
					)
				elif isinstance(item, str):
					items.append(discord.MediaGalleryItem(media=item))
			return discord.ui.MediaGallery(*items)

		elif raw_type in (1, "action_row"):
			row_children = [
				CustomResponse.convert_component(c)
				for c in comp.get("components", [])
				if CustomResponse.convert_component(c) is not None
			]
			return discord.ui.ActionRow(*row_children)  # type: ignore

		elif raw_type in (2, "button"):
			return discord.ui.Button(
				style=_parse_button_style(comp.get("style", "secondary")),
				label=comp.get("label"),
				custom_id=comp.get("custom_id"),
				url=comp.get("url"),
				emoji=comp.get("emoji"),
				disabled=bool(comp.get("disabled", False)),
			)

		elif raw_type in (13, "file"):
			return discord.ui.File(
				media=comp.get("media", comp.get("url", "")),
				spoiler=bool(comp.get("spoiler", False)),
			)

		return None

	def convert_components(self, data: Any) -> Any:
		"""Converts ``data``'s components or layout definition into a ``discord.ui.LayoutView``.

		Args:
			data: The data that might contain a ``components`` or ``layout`` key.

		Returns:
			Any: The data with components converted into a ``discord.ui.LayoutView`` under the ``view`` key.

		Raises:
			ValueError: If the total number of components exceeds 40.

		"""
		if isinstance(data, list):
			layout_view = discord.ui.LayoutView(timeout=None)
			for raw_comp in data:
				item = self.convert_component(raw_comp)
				if item is not None:
					layout_view.add_item(item)
			return layout_view

		if isinstance(data, dict) and ("components" in data or "layout" in data):
			raw_components = data.pop("components", None)
			if raw_components is None:
				raw_components = data.pop("layout", None)

			if not isinstance(raw_components, list):
				raw_components = [raw_components]

			layout_view = discord.ui.LayoutView(timeout=None)
			existing_view = data.pop("view", None)

			for raw_comp in raw_components:
				item = self.convert_component(raw_comp)
				if item is not None:
					layout_view.add_item(item)

			if existing_view is not None:
				layout_view = self.merge_views(layout_view, existing_view)

			data["view"] = layout_view
			data.pop("embed", None)
			data.pop("embeds", None)
			data.pop("content", None)

		return data

	@staticmethod
	def merge_views(
		view_a: discord.ui.View | discord.ui.LayoutView | None,
		view_b: discord.ui.View | discord.ui.LayoutView | None,
	) -> discord.ui.View | discord.ui.LayoutView | None:
		"""Merges two views into a single view, prioritizing LayoutView if present.

		Args:
			view_a: The first view (e.g. from localization or caller).
			view_b: The second view (e.g. from caller or localization).

		Returns:
			discord.ui.View | discord.ui.LayoutView | None: The merged view.

		"""
		if view_a is None:
			return view_b
		if view_b is None:
			return view_a

		if isinstance(view_a, discord.ui.LayoutView):
			if isinstance(view_b, discord.ui.LayoutView):
				for child in list(view_b.children):
					view_a.add_item(child)
			elif isinstance(view_b, discord.ui.View):
				items = list(view_b.children)
				if items:
					container = next((c for c in view_a.children if isinstance(c, discord.ui.Container)), None)
					action_rows: list[discord.ui.ActionRow] = []
					pending_row: list[discord.ui.Item] = []
					for item in items:
						if isinstance(item, discord.ui.ActionRow):
							if pending_row:
								for i in range(0, len(pending_row), 5):
									action_rows.append(discord.ui.ActionRow(*pending_row[i : i + 5]))
								pending_row = []
							action_rows.append(item)
						else:
							pending_row.append(item)
					if pending_row:
						for i in range(0, len(pending_row), 5):
							action_rows.append(discord.ui.ActionRow(*pending_row[i : i + 5]))

					if container is not None:
						for ar in action_rows:
							container.add_item(ar)
					else:
						for ar in action_rows:
							view_a.add_item(ar)
			return view_a

		elif isinstance(view_b, discord.ui.LayoutView):
			return CustomResponse.merge_views(view_b, view_a)

		elif isinstance(view_a, discord.ui.View) and isinstance(view_b, discord.ui.View):
			for child in list(view_b.children):
				view_a.add_item(child)
			return view_a

		return view_a or view_b

	@overload
	def update_localizations(self, data_or_path: dict): ...

	@overload
	def update_localizations(self, data_or_path: str): ...

	def update_localizations(self, data_or_path: dict | str):
		if isinstance(data_or_path, dict):
			for lang, translations in data_or_path.items():
				if isinstance(translations, dict):
					self.localizations.setdefault(lang, {}).update(translations)
				else:
					self.localizations[lang] = translations
			self._localizer = CustomLocalization(self.localizations, default_locale="en")
		elif isinstance(data_or_path, str):
			self.load_localizations(data_or_path)

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

		self._localizer = CustomLocalization(self.localizations, default_locale="en")

	async def get_message(
		self,
		name: str,
		locale: str
		| discord.Locale
		| discord.Guild
		| discord.Interaction
		| commands.Context
		| Context
		| discord.Message
		| None = "en",
		/,
		*,
		convert_embeds: bool = True,
		convert_components: bool = True,
		**kwargs,
	) -> Any:
		"""Returns a custom message from the database, or if not found, returns the default message.

		Args:
			name: The name of the message.
			locale: The locale to use or the context to derive it.
			convert_embeds: Whether to convert the embeds in the message to discord.Embeds.
			convert_components: Whether to convert components/layout in the message to a discord.ui.LayoutView.
			**kwargs: Formatting keyword arguments to pass into the localized template.

		Returns:
			dict | str | list | int | float | bool: The message payload.

		"""
		if locale is None:
			locale = "en"
		original = locale

		locale = resolve_locale(locale, getattr(self.client, "locale_cache", None))

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
				if isinstance(original, (discord.Interaction, commands.Context, discord.Message)) and original.guild
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
					break
			else:
				if isinstance(value, datetime.datetime):
					kwargs[key] = FormatDateTime(value, default_style="F")
				elif isinstance(value, (discord.abc.GuildChannel, discord.Thread)):
					kwargs[key] = convert_to_custom_channel(value)

		if self.client.debug:
			now = time.time()
			if now - self._last_debug_reload > 5:
				self.load_localizations("../localization")
				self._last_debug_reload = now

		if not self._localizer:
			return "localizer not initialized!"

		formatting: dict[str, Any] = {**context_formatting, **kwargs, "random": r"{random}"}
		payload = self._localizer.localize(name, locale, **formatting)  # type: ignore[arg-type]

		if isinstance(payload, dict):
			if random_value := payload.get("random"):
				payload = localization.Localization.format_strings(payload, random=random.choice(random_value))
			payload.pop("random", None)
			payload = self.convert_embeds(payload) if convert_embeds else payload
			payload = self.convert_components(payload) if convert_components else payload

			if payload.get("reply"):
				payload["reference"] = (
					original.message
					if isinstance(original, (discord.Interaction, commands.Context))
					else (original if isinstance(original, discord.Message) else None)
				)
			payload.pop("reply", None)

			if allowed_mentions := payload.get("allowed_mentions"):
				if "all" in allowed_mentions:
					payload["allowed_mentions"] = discord.AllowedMentions.all()
				elif "none" in allowed_mentions:
					payload["allowed_mentions"] = discord.AllowedMentions.none()
				else:
					payload["allowed_mentions"] = discord.AllowedMentions(**allowed_mentions)

			# Ephemeral only exists for interaction responses (slash commands via a Context included);
			# a raw Interaction response can't take delete_after.
			if isinstance(original, discord.Interaction):
				payload.pop("delete_after", None)
			elif not (isinstance(original, commands.Context) and getattr(original, "interaction", None)):
				payload.pop("ephemeral", None)
		return payload

	__call__ = get_message
