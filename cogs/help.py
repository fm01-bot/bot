import os
from collections.abc import Iterable, Mapping
from typing import Any, Literal, get_args, get_origin

import discord
from core import Bot, Command, Context, slash_command_localization
from discord.ext import commands
from discord.ext.localization import Localization
from helpers import CustomResponse


class HelpCommand(commands.HelpCommand):
	context: Context
	custom_response: CustomResponse

	def __init__(self):
		super().__init__()
		self.name = "help"

	async def prepare_help_command(self, ctx: Context, command: str | None = None, /) -> None:
		if not hasattr(self, "custom_response"):
			self.custom_response = ctx.bot.custom_response

	def get_command_signature(self, command: commands.Command[Any, ..., Any], /) -> str:
		signature = []
		for param in command.clean_params.values():
			annotation = param.annotation
			param_str = param.name

			if get_origin(annotation) is Literal:
				literals = get_args(annotation)
				param_str = "|".join(map(str, literals))

			elif get_origin(annotation) is commands.Range:
				args = get_args(annotation)
				if len(args) == 3:
					typ, start, end = args
					if typ is int:
						param_str = f"{param.name}: {start}...{end}"
					elif typ is str:
						param_str = f"{param.name}: ...{end}"
				elif len(args) == 2:
					typ, end = args
					if typ is int:
						param_str = f"{param.name}: >{end}"
					elif typ is str:
						param_str = f"{param.name}: {end}..."

			if param.default is param.empty:  # required parameter
				param_str = f"[{param_str}]"
			else:  # optional parameter
				param_str = f"({param_str})"

			signature.append(param_str)
		return f"{command.qualified_name} {' '.join(signature)}"

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

	def resolve_cog(self, name: str) -> commands.Cog | None:
		target = name.strip()
		target_lower = target.lower()
		if target_lower in ("jishaku", "jsk"):
			return None

		bot = self.context.bot

		for cog_name, cog in bot.cogs.items():
			if cog_name.lower() == "jishaku":
				continue
			if cog_name.lower() == target_lower:
				return cog

		target_stem = target_lower.rstrip("s")
		for cog_name, cog in bot.cogs.items():
			if cog_name.lower() == "jishaku":
				continue
			if cog_name.lower().rstrip("s") == target_stem:
				return cog

		if hasattr(self, "custom_response") and self.custom_response:
			for loc_data in self.custom_response.localizations.values():
				if not isinstance(loc_data, dict):
					continue
				cogs_dict = loc_data.get("cogs", {})
				if isinstance(cogs_dict, dict):
					for key, val in cogs_dict.items():
						key_s = str(key).lower()
						val_s = str(val).lower()
						if target_lower in (key_s, val_s) or (
							target_stem and target_stem in (key_s.rstrip("s"), val_s.rstrip("s"))
						):
							for cog_name, cog in bot.cogs.items():
								if cog_name.lower() == "jishaku":
									continue
								if cog_name.lower() in (key_s, val_s) or (
									cog_name.lower().rstrip("s") in (key_s.rstrip("s"), val_s.rstrip("s"))
								):
									return cog

		if slash_command_localization and slash_command_localization.file:
			for loc_data in slash_command_localization.file.values():
				if not isinstance(loc_data, dict):
					continue
				for k, v in loc_data.items():
					v_name = v if isinstance(v, str) else v.get("name", "") if isinstance(v, dict) else ""
					if target_lower in (k.lower(), v_name.lower()):
						for cog_name, cog in bot.cogs.items():
							if cog_name.lower() == "jishaku":
								continue
							if cog_name.lower() == k.lower() or (
								k.lower() == "mod" and cog_name.lower() == "moderation"
							):
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

		if slash_command_localization and slash_command_localization.file:
			for loc_data in slash_command_localization.file.values():
				if not isinstance(loc_data, dict):
					continue
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

		if slash_command_localization and slash_command_localization.file:
			for loc_data in slash_command_localization.file.values():
				if not isinstance(loc_data, dict):
					continue
				for k, v in loc_data.items():
					v_name = v if isinstance(v, str) else v.get("name", "") if isinstance(v, dict) else ""
					if target_lower in (k.lower(), v_name.lower()):
						for c in group.commands:
							if c.name.lower() == k.lower() or getattr(c, "l10n_key", None) == k:
								return c

		return None

	async def command_callback(self, ctx: Context, /, *, command: str | None = None) -> None:
		await self.prepare_help_command(ctx, command)

		if command is None:
			mapping = self.get_bot_mapping()
			return await self.send_bot_help(mapping)

		query = command.strip()
		if query.lower() in ("jishaku", "jsk"):
			string = await discord.utils.maybe_coroutine(self.command_not_found, self.remove_mentions(query))
			return await self.send_error_message(string)

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

	async def send_bot_help(self, mapping: Mapping[commands.Cog | None, list[commands.Command]]):
		message = await self.custom_response("help.bot", self.context, prefix=self.context.clean_prefix)
		embeds: list[discord.Embed] = message.get("embeds")  # type: ignore # it's gonna be a list i promise

		if embeds:
			template = embeds[0].to_dict().get("fields", [None])[0]
			if not template:
				await self.get_destination().send(**message)  # type: ignore
				return
			embeds[0].clear_fields()
			for cog, cog_commands in mapping.items():
				if len(embeds[0].fields) >= 25:
					break
				if cog is None or cog.qualified_name.lower() == "jishaku":
					continue
				filtered = await self.filter_commands(cog_commands, sort=True)
				command_signatures = [self.get_command_signature(command) for command in filtered]
				if not command_signatures:
					continue

				cmd_count = len(filtered)
				if cmd_count == 1 and isinstance(filtered[0], commands.Group):
					base_cmds = await self.filter_commands([filtered[0]])
					sub_commands = await self.filter_commands(list(filtered[0].walk_commands()), sort=True)
					cmd_count = len(base_cmds + sub_commands)

				formatted = Localization.format_strings(template, module=cog.qualified_name or "-", commands=cmd_count)
				embeds[0].add_field(**formatted)
			message["embeds"] = self.custom_response.convert_embeds(embeds)  # type: ignore

		await self.get_destination().send(**message)  # type: ignore

	async def send_command_help(self, command: commands.Command[Any, ..., Any], /) -> None:
		if (command.cog_name and command.cog_name.lower() == "jishaku") or command.name.lower() in ("jishaku", "jsk"):
			string = await discord.utils.maybe_coroutine(self.command_not_found, command.name)
			return await self.send_error_message(string)

		await self.context.send("help.command", command=Command.from_command(command, self.context))

	async def send_group_or_cog_help(self, group_or_cog: commands.Group | commands.Cog):
		if isinstance(group_or_cog, commands.Cog):
			cog_name = await self.custom_response(f"cogs.{group_or_cog.qualified_name.lower()}", self.context)
			if isinstance(cog_name, str) and cog_name.startswith("cogs."):
				cog_name = group_or_cog.qualified_name
			commands_list = await self.filter_commands(group_or_cog.get_commands(), sort=True)
			message = await self.custom_response("help.cog", self.context, cog=cog_name, commands=len(commands_list))
		elif isinstance(group_or_cog, commands.Group):
			base_commands = await self.filter_commands([group_or_cog])
			sub_commands = await self.filter_commands(list(group_or_cog.walk_commands()), sort=True)
			commands_list = base_commands + sub_commands
			message = await self.custom_response(
				"help.group",
				self.context,
				group=Command.from_command(group_or_cog, self.context),
				commands=len(commands_list),
			)
		else:
			raise commands.BadArgument
		embeds: list[discord.Embed] = message.get("embeds")  # type: ignore

		if embeds:
			template = embeds[0].to_dict().get("fields", [None])[0]
			if not template:
				await self.get_destination().send(**message)  # type: ignore
				return

			embeds[0].clear_fields()

			for command in commands_list:
				if len(embeds[0].fields) >= 25:
					break
				formatted = Localization.format_strings(template, command=Command.from_command(command, self.context))
				embeds[0].add_field(**formatted)
			message["embeds"] = self.custom_response.convert_embeds(embeds)  # type: ignore

		await self.get_destination().send(**message)  # type: ignore

	async def send_cog_help(self, cog: commands.Cog):
		if cog.qualified_name.lower() == "jishaku":
			string = await discord.utils.maybe_coroutine(self.command_not_found, cog.qualified_name)
			return await self.send_error_message(string)

		filtered = await self.filter_commands(cog.get_commands(), sort=True)
		if len(filtered) == 1 and isinstance(filtered[0], commands.Group):
			return await self.send_group_help(filtered[0])

		await self.send_group_or_cog_help(cog)

	async def send_group_help(self, group: commands.Group):
		if (group.cog_name and group.cog_name.lower() == "jishaku") or group.name.lower() in ("jishaku", "jsk"):
			string = await discord.utils.maybe_coroutine(self.command_not_found, group.name)
			return await self.send_error_message(string)

		await self.send_group_or_cog_help(group)

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
