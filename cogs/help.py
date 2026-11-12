import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

import discord
import emoji
from core import Bot, Command, Context, resolve_locale, slash_command_localization
from discord.ext import commands
from discord.ext.localization import Localization
from helpers import CustomResponse

CUSTOM_EMOJI_REGEX = re.compile(r"<a?:[a-zA-Z0-9_]+:\d+>")


def clean_module_name(name: str) -> str:
	"""Strips custom Discord emojis, Unicode emojis, and symbols from a module name."""
	no_custom = CUSTOM_EMOJI_REGEX.sub("", name)
	no_emoji = emoji.replace_emoji(no_custom, "")
	filtered = "".join(
		ch for ch in no_emoji if not unicodedata.category(ch).startswith("S") and unicodedata.category(ch) != "Mn"
	)
	return " ".join(filtered.split())


class HelpSelect(discord.ui.Select["HelpLayoutView"]):
	def __init__(
		self,
		help_command: "HelpCommand",
		options: list[discord.SelectOption],
		placeholder: str = "Select a module to view commands...",
	) -> None:
		super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
		self.help_command = help_command

	async def callback(self, interaction: discord.Interaction) -> None:
		assert self.view is not None
		help_view: HelpLayoutView = self.view

		if interaction.user.id != help_view.author_id:
			payload = await self.help_command.custom_response("help.errors.not_author", interaction)
			await interaction.response.send_message(**payload, ephemeral=True)
			return

		selected = self.values[0]

		if selected == "overview":
			payload = await self.help_command.build_bot_help_payload(help_view, active_value="overview")
		else:
			cog = self.help_command.resolve_cog(selected)
			if cog is None:
				await interaction.response.defer()
				return
			payload = await self.help_command.build_cog_help_payload(cog, help_view, active_value=selected)

		await interaction.response.edit_message(**payload)


class HelpLayoutView(discord.ui.LayoutView):
	message: discord.Message | None = None

	def __init__(
		self,
		help_command: "HelpCommand",
		author_id: int,
		timeout: float | None = 180.0,
	) -> None:
		super().__init__(timeout=timeout)
		self.help_command = help_command
		self.author_id = author_id

	async def on_timeout(self) -> None:
		for item in self.walk_children():
			if isinstance(item, discord.ui.Select):
				item.disabled = True
		if self.message:
			try:
				await self.message.edit(view=self)
			except (discord.HTTPException, AttributeError):
				pass


class HelpCommand(commands.HelpCommand):
	context: Context  # ty: ignore[invalid-mutable-override]
	custom_response: CustomResponse

	def __init__(self) -> None:
		super().__init__()
		self.name = "help"

	async def prepare_help_command(self, ctx: commands.Context[Any], command: str | None = None, /) -> None:
		if not hasattr(self, "custom_response"):
			self.custom_response = ctx.bot.custom_response  # type: ignore[attr-defined]

	async def filter_commands(
		self, commands: Iterable[commands.Command[Any, ..., Any]], /, *, sort: bool = False, key: Any = None
	) -> list[commands.Command[Any, ..., Any]]:
		filtered = [
			c
			for c in commands
			if not (getattr(c, "cog_name", None) and str(c.cog_name).lower() == "jishaku")
			and c.name.lower() not in ("jishaku", "jsk")
		]
		return await super().filter_commands(filtered, sort=sort, key=key)

	def get_context_locale(self) -> str:
		return resolve_locale(self.context, getattr(self.context.bot, "locale_cache", None))

	def resolve_cog(self, name: str) -> commands.Cog | None:
		target = name.strip()
		target_lower = target.lower()
		if target_lower in ("jishaku", "jsk"):
			return None

		target_clean = clean_module_name(target)
		target_clean_lower = target_clean.lower()
		targets = {target_lower, target_clean_lower} - {""}
		target_stems = {t.rstrip("s") for t in targets} - {""}

		bot = self.context.bot

		for cog_name, cog in bot.cogs.items():
			if cog_name.lower() == "jishaku":
				continue
			raw_name = getattr(cog, "name", None)
			cog_actual = raw_name if isinstance(raw_name, str) else cog_name
			cog_clean = clean_module_name(cog_actual)
			cog_candidates = {cog_actual.lower(), cog_name.lower(), cog_clean.lower()} - {""}
			cog_stems = {c.rstrip("s") for c in cog_candidates} - {""}
			if targets & cog_candidates or target_stems & cog_stems:
				return cog

		user_locale = self.get_context_locale()

		if hasattr(self, "custom_response") and self.custom_response:
			loc_data = self.custom_response.localizations.get(user_locale)
			if loc_data is None and user_locale != "en":
				loc_data = self.custom_response.localizations.get("en")

			if isinstance(loc_data, dict):
				cogs_dict = loc_data.get("cogs", {})
				if isinstance(cogs_dict, dict):
					for key, val in cogs_dict.items():
						key_s = str(key).lower()
						val_s = str(val).lower()
						key_clean = clean_module_name(str(key)).lower()
						val_clean = clean_module_name(str(val)).lower()

						candidates = {key_s, key_clean, val_s, val_clean} - {""}
						cand_stems = {c.rstrip("s") for c in candidates} - {""}

						if targets & candidates or target_stems & cand_stems:
							for cog_name, cog in bot.cogs.items():
								if cog_name.lower() == "jishaku":
									continue
								raw_cog_name = getattr(cog, "name", None)
								cog_actual = raw_cog_name if isinstance(raw_cog_name, str) else cog_name
								cog_cands = {
									cog_actual.lower(),
									cog_name.lower(),
									clean_module_name(cog_actual).lower(),
									clean_module_name(cog_name).lower(),
								} - {""}
								cog_c_stems = {c.rstrip("s") for c in cog_cands} - {""}
								if cog_cands & {key_s, key_clean} or cog_c_stems & {
									key_s.rstrip("s"),
									key_clean.rstrip("s"),
								}:
									return cog

		if slash_command_localization and slash_command_localization.file:
			loc_data = slash_command_localization.file.get(user_locale)
			if loc_data is None and user_locale != "en":
				loc_data = slash_command_localization.file.get("en")

			if isinstance(loc_data, dict):
				for k, v in loc_data.items():
					v_name = v if isinstance(v, str) else v.get("name", "") if isinstance(v, dict) else ""
					cand_clean = clean_module_name(v_name)
					candidates = {k.lower(), v_name.lower(), cand_clean.lower()} - {""}
					cand_stems = {c.rstrip("s") for c in candidates} - {""}
					if targets & candidates or target_stems & cand_stems:
						for cog_name, cog in bot.cogs.items():
							if cog_name.lower() == "jishaku":
								continue
							raw_cog_name = getattr(cog, "name", None)
							cog_actual = raw_cog_name if isinstance(raw_cog_name, str) else cog_name
							if cog_actual.lower() == k.lower() or cog_name.lower() == k.lower():
								return cog

		return None

	def resolve_command(self, name: str) -> commands.Command[Any, ..., Any] | None:
		target = name.strip()
		target_lower = target.lower()
		if target_lower in ("jishaku", "jsk"):
			return None

		bot = self.context.bot

		cmd = bot.get_command(target)
		if (
			cmd
			and not (cmd.cog_name and cmd.cog_name.lower() == "jishaku")
			and cmd.name.lower() not in ("jishaku", "jsk")
		):
			return cmd

		for c in bot.commands:
			if c.cog_name and c.cog_name.lower() == "jishaku":
				continue
			if c.name.lower() == target_lower or target_lower in [a.lower() for a in c.aliases]:
				return c

		target_stem = target_lower.rstrip("s")
		for c in bot.commands:
			if c.cog_name and c.cog_name.lower() == "jishaku":
				continue
			if c.name.lower().rstrip("s") == target_stem:
				return c

		user_locale = self.get_context_locale()
		if slash_command_localization and slash_command_localization.file:
			loc_data = slash_command_localization.file.get(user_locale)
			if loc_data is None and user_locale != "en":
				loc_data = slash_command_localization.file.get("en")

			if isinstance(loc_data, dict):
				for k, v in loc_data.items():
					v_name = v if isinstance(v, str) else v.get("name", "") if isinstance(v, dict) else ""
					if target_lower in (k.lower(), v_name.lower()) or (
						target_stem and target_stem in (k.lower().rstrip("s"), v_name.lower().rstrip("s"))
					):
						cmd = bot.get_command(k)
						if (
							cmd
							and not (cmd.cog_name and cmd.cog_name.lower() == "jishaku")
							and cmd.name.lower() not in ("jishaku", "jsk")
						):
							return cmd
						for c in bot.commands:
							if c.cog_name and c.cog_name.lower() == "jishaku":
								continue
							if getattr(c, "l10n_key", None) == k or c.name.lower() == k.lower():
								return c

		return None

	def resolve_subcommand(self, group: commands.Group, name: str) -> commands.Command[Any, ..., Any] | None:
		target = name.strip()
		target_lower = target.lower()

		cmd = group.all_commands.get(target)
		if cmd:
			return cmd

		for c in group.commands:
			if c.name.lower() == target_lower or target_lower in [a.lower() for a in c.aliases]:
				return c

		target_stem = target_lower.rstrip("s")
		for c in group.commands:
			if c.name.lower().rstrip("s") == target_stem:
				return c

		user_locale = self.get_context_locale()
		if slash_command_localization and slash_command_localization.file:
			loc_data = slash_command_localization.file.get(user_locale)
			if loc_data is None and user_locale != "en":
				loc_data = slash_command_localization.file.get("en")

			if isinstance(loc_data, dict):
				for k, v in loc_data.items():
					v_name = v if isinstance(v, str) else v.get("name", "") if isinstance(v, dict) else ""
					if target_lower in (k.lower(), v_name.lower()):
						for c in group.commands:
							if c.name.lower() == k.lower() or getattr(c, "l10n_key", None) == k:
								return c

		return None

	def get_command_obj(self, command: commands.Command[Any, ..., Any]) -> Command:
		cmd_obj = Command.from_command(command, self.context)
		if cmd_obj is not None:
			return cmd_obj
		return Command(
			name=command.qualified_name,
			description=command.description or command.help or "-",
			usage=f"{self.context.clean_prefix}{command.qualified_name}",
			prefix=self.context.clean_prefix,
			aliases=", ".join(command.aliases) if command.aliases else None,
		)

	async def get_localized_string(self, key: str, fallback: str) -> str:
		val = await self.custom_response(key, self.context)
		if isinstance(val, str) and not val.startswith(key.split(".")[0] + "."):
			return val
		val_en = await self.custom_response(key, "en")
		if isinstance(val_en, str) and not val_en.startswith(key.split(".")[0] + "."):
			return val_en
		return fallback

	async def get_localized_cog_name(self, cog: commands.Cog) -> str:
		raw_name = getattr(cog, "name", None)
		cog_name = raw_name if isinstance(raw_name, str) else cog.qualified_name
		key = getattr(cog, "l10n_key", None) or cog_name.lower()
		for candidate in (key, key.rstrip("s")):
			name = await self.custom_response(f"cogs.{candidate}", self.context)
			if isinstance(name, str) and not name.startswith("cogs."):
				return name
		return cog_name

	async def get_all_cog_options_data(self) -> list[tuple[commands.Cog, str, int]]:
		options_data: list[tuple[commands.Cog, str, int]] = []
		mapping = self.get_bot_mapping()

		for cog, cog_commands in mapping.items():
			if cog is None or cog.qualified_name.lower() in ("jishaku", "help", "status", "statesync"):
				continue
			filtered = await self.filter_commands(cog_commands, sort=True)
			if not filtered:
				continue

			cmd_count = len(filtered)
			if cmd_count == 1 and isinstance(filtered[0], commands.Group):
				base_cmds = await self.filter_commands([filtered[0]])
				sub_commands = await self.filter_commands(list(filtered[0].walk_commands()), sort=True)
				cmd_count = len(base_cmds + sub_commands)

			loc_name = await self.get_localized_cog_name(cog)
			options_data.append((cog, loc_name, cmd_count))

		return options_data

	async def create_help_select(
		self,
		cog_options_data: list[tuple[commands.Cog, str, int]],
		active_value: str = "overview",
	) -> HelpSelect:
		placeholder = await self.get_localized_string(
			"help.dropdown.placeholder", "Select a module to view commands..."
		)
		overview_label = await self.get_localized_string("help.dropdown.overview", "Overview")
		overview_desc = await self.get_localized_string("help.dropdown.overview_desc", "Return to the main help menu")
		cmd_template = await self.get_localized_string("help.dropdown.commands", "{commands} commands")

		options: list[discord.SelectOption] = [
			discord.SelectOption(
				label=overview_label,
				value="overview",
				description=overview_desc,
				emoji="🏠",
				default=(active_value == "overview"),
			)
		]

		for cog, loc_name, count in cog_options_data:
			cleaned_label = clean_module_name(loc_name)
			emoji_part = loc_name.replace(cleaned_label, "").strip() if cleaned_label else ""

			emoji_arg: str | discord.PartialEmoji | None = None
			if emoji_part:
				if CUSTOM_EMOJI_REGEX.match(emoji_part):
					try:
						emoji_arg = discord.PartialEmoji.from_str(emoji_part)
					except (ValueError, TypeError):
						emoji_arg = None
				else:
					emoji_arg = emoji_part

			opt_label = (cleaned_label or loc_name)[:100]
			raw_cog_name = getattr(cog, "name", None)
			cog_name = raw_cog_name if isinstance(raw_cog_name, str) else cog.qualified_name
			opt_desc = Localization.format_strings(cmd_template, commands=count)[:100]
			options.append(
				discord.SelectOption(
					label=opt_label,
					value=cog.qualified_name,
					description=opt_desc,
					emoji=emoji_arg or "📖",
					default=(
						cog.qualified_name.lower() == active_value.lower() or cog_name.lower() == active_value.lower()
					),
				)
			)

		return HelpSelect(self, options=options[:25], placeholder=placeholder[:100])

	async def build_bot_help_payload(
		self,
		view: HelpLayoutView | None = None,
		*,
		active_value: str = "overview",
	) -> dict[str, Any]:
		cog_options_data = await self.get_all_cog_options_data()

		message = await self.custom_response(
			"help.bot",
			self.context,
			prefix=self.context.clean_prefix,
		)

		if view is None:
			view = HelpLayoutView(self, author_id=self.context.author.id)

		select_item = await self.create_help_select(cog_options_data, active_value=active_value)

		if "view" in message and isinstance(message["view"], discord.ui.LayoutView):
			layout_view = message["view"]
			container = next((item for item in layout_view.children if isinstance(item, discord.ui.Container)), None)
			if container is not None:
				container.add_item(discord.ui.ActionRow(select_item))
			else:
				layout_view.add_item(discord.ui.ActionRow(select_item))
			view.clear_items()
			for child in list(layout_view.children):
				view.add_item(child)

		return {"view": view}

	async def build_group_help_payload(
		self,
		group: commands.Group,
		view: HelpLayoutView | None = None,
		*,
		active_value: str | None = None,
	) -> dict[str, Any]:
		base_commands = await self.filter_commands([group])
		sub_commands = await self.filter_commands(list(group.walk_commands()), sort=True)
		commands_list = base_commands + sub_commands

		cmd_lines: list[str] = []
		for command in commands_list:
			cmd_obj = self.get_command_obj(command)
			cmd_lines.append(f"**`{cmd_obj.usage}`**\n{cmd_obj.description}")

		commands_text = "\n\n".join(cmd_lines) if cmd_lines else "-"
		group_cmd_obj = self.get_command_obj(group)
		message = await self.custom_response(
			"help.group",
			self.context,
			group=group_cmd_obj,
			commands=len(commands_list),
			commands_list=commands_text,
		)

		if view is None:
			view = HelpLayoutView(self, author_id=self.context.author.id)

		cog_options_data = await self.get_all_cog_options_data()
		cog = group.cog
		raw_cog_name = getattr(cog, "name", None) if cog else None
		cog_name = raw_cog_name if isinstance(raw_cog_name, str) else (cog.qualified_name if cog else group.name)
		target_val = active_value or cog_name
		select_item = await self.create_help_select(cog_options_data, active_value=target_val)

		if "view" in message and isinstance(message["view"], discord.ui.LayoutView):
			layout_view = message["view"]
			container = next((item for item in layout_view.children if isinstance(item, discord.ui.Container)), None)
			if container is not None:
				container.add_item(discord.ui.ActionRow(select_item))
			else:
				layout_view.add_item(discord.ui.ActionRow(select_item))
			view.clear_items()
			for child in list(layout_view.children):
				view.add_item(child)

		return {"view": view}

	async def build_cog_help_payload(
		self,
		cog: commands.Cog,
		view: HelpLayoutView | None = None,
		*,
		active_value: str | None = None,
	) -> dict[str, Any]:
		filtered = await self.filter_commands(cog.get_commands(), sort=True)
		raw_cog_name = getattr(cog, "name", None)
		cog_name = raw_cog_name if isinstance(raw_cog_name, str) else cog.qualified_name
		if len(filtered) == 1 and isinstance(filtered[0], commands.Group):
			return await self.build_group_help_payload(
				filtered[0],
				view=view,
				active_value=active_value or cog_name,
			)

		loc_name = await self.get_localized_cog_name(cog)

		cmd_lines: list[str] = []
		for command in filtered:
			cmd_obj = self.get_command_obj(command)
			cmd_lines.append(f"**`{cmd_obj.usage}`**\n{cmd_obj.description}")

		commands_text = "\n\n".join(cmd_lines) if cmd_lines else "-"

		message = await self.custom_response(
			"help.cog",
			self.context,
			cog=loc_name,
			commands=len(filtered),
			commands_list=commands_text,
		)

		if view is None:
			view = HelpLayoutView(self, author_id=self.context.author.id)

		cog_options_data = await self.get_all_cog_options_data()
		target_val = active_value or cog.qualified_name
		select_item = await self.create_help_select(cog_options_data, active_value=target_val)

		if "view" in message and isinstance(message["view"], discord.ui.LayoutView):
			layout_view = message["view"]
			container = next((item for item in layout_view.children if isinstance(item, discord.ui.Container)), None)
			if container is not None:
				container.add_item(discord.ui.ActionRow(select_item))
			else:
				layout_view.add_item(discord.ui.ActionRow(select_item))
			view.clear_items()
			for child in list(layout_view.children):
				view.add_item(child)

		return {"view": view}

	async def command_callback(self, ctx: commands.Context[Any], /, *, command: str | None = None) -> None:
		await self.prepare_help_command(ctx, command)

		if command is None:
			mapping = self.get_bot_mapping()
			return await self.send_bot_help(mapping)

		query = command.strip()
		if query.lower() in ("jishaku", "jsk"):
			string = await discord.utils.maybe_coroutine(self.command_not_found, self.remove_mentions(query))
			return await self.send_error_message(string)

		found_cog = self.resolve_cog(query)
		if found_cog and len(clean_module_name(query).split()) <= 1:
			return await self.send_cog_help(found_cog)

		keys = query.split()
		if len(keys) == 1:
			name = keys[0]
			found_cog = self.resolve_cog(name)
			found_cmd = self.resolve_command(name)

			if found_cog and found_cmd:
				cog_cmds = await self.filter_commands(found_cog.get_commands(), sort=True)
				cog_count = len(cog_cmds)

				if isinstance(found_cmd, commands.Group):
					cmd_cmds = await self.filter_commands(list(found_cmd.commands), sort=True)
					cmd_count = len(cmd_cmds)
				else:
					cmd_count = 1

				if cog_count == 1 and cmd_count > 1 and isinstance(found_cmd, commands.Group):
					return await self.send_group_help(found_cmd)
				elif cmd_count == 1 and cog_count > 1:
					return await self.send_cog_help(found_cog)
				elif isinstance(found_cmd, commands.Group):
					return await self.send_group_help(found_cmd)
				else:
					return await self.send_cog_help(found_cog)

			if found_cog:
				return await self.send_cog_help(found_cog)

			if found_cmd:
				if isinstance(found_cmd, commands.Group):
					return await self.send_group_help(found_cmd)
				return await self.send_command_help(found_cmd)

			string = await discord.utils.maybe_coroutine(self.command_not_found, self.remove_mentions(name))
			return await self.send_error_message(string)

		cmd = self.resolve_command(keys[0])
		if cmd is None:
			string = await discord.utils.maybe_coroutine(self.command_not_found, self.remove_mentions(keys[0]))
			return await self.send_error_message(string)

		for key in keys[1:]:
			if not isinstance(cmd, commands.Group):
				string = await discord.utils.maybe_coroutine(self.subcommand_not_found, cmd, self.remove_mentions(key))
				return await self.send_error_message(string)

			sub = self.resolve_subcommand(cmd, key)
			if sub is None:
				string = await discord.utils.maybe_coroutine(self.subcommand_not_found, cmd, self.remove_mentions(key))
				return await self.send_error_message(string)
			cmd = sub

		if isinstance(cmd, commands.Group):
			return await self.send_group_help(cmd)
		return await self.send_command_help(cmd)

	async def send_bot_help(self, mapping: Mapping[commands.Cog | None, list[commands.Command]]) -> None:
		payload = await self.build_bot_help_payload()
		msg = await self.get_destination().send(**payload)
		if (view := payload.get("view")) and isinstance(view, HelpLayoutView):
			view.message = msg

	async def send_command_help(self, command: commands.Command[Any, ..., Any], /) -> None:
		if (command.cog_name and command.cog_name.lower() == "jishaku") or command.name.lower() in ("jishaku", "jsk"):
			string = await discord.utils.maybe_coroutine(self.command_not_found, command.name)
			return await self.send_error_message(string)

		cmd_obj = self.get_command_obj(command)
		await self.context.send("help.command", command=cmd_obj)

	async def send_cog_help(self, cog: commands.Cog) -> None:
		if cog.qualified_name.lower() == "jishaku":
			string = await discord.utils.maybe_coroutine(self.command_not_found, cog.qualified_name)
			return await self.send_error_message(string)

		filtered = await self.filter_commands(cog.get_commands(), sort=True)
		if len(filtered) == 1 and isinstance(filtered[0], commands.Group):
			return await self.send_group_help(filtered[0])

		payload = await self.build_cog_help_payload(cog)
		msg = await self.get_destination().send(**payload)
		if (view := payload.get("view")) and isinstance(view, HelpLayoutView):
			view.message = msg

	async def send_group_help(self, group: commands.Group) -> None:
		if (group.cog_name and group.cog_name.lower() == "jishaku") or group.name.lower() in ("jishaku", "jsk"):
			string = await discord.utils.maybe_coroutine(self.command_not_found, group.name)
			return await self.send_error_message(string)

		payload = await self.build_group_help_payload(group)
		msg = await self.get_destination().send(**payload)
		if (view := payload.get("view")) and isinstance(view, HelpLayoutView):
			view.message = msg

	async def send_error_message(self, error: str, /) -> None:
		await self.context.send("errors.command_not_found", command=Command.from_ctx(self.context))


class Help(commands.Cog, command_attrs={"hidden": True}):
	def __init__(self, client: Bot):
		self.client = client
		os.environ["JISHAKU_HIDE"] = "True"
		jsk = self.client.get_cog("Jishaku")
		if jsk:
			for cmd in jsk.get_commands():
				cmd.hidden = True
		help_command = HelpCommand()
		help_command.custom_response = client.custom_response
		help_command.cog = self
		self.client.help_command = help_command


async def setup(client: Bot):
	await client.add_cog(Help(client))
