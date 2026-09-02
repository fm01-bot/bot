from typing import Any, Literal, Optional, get_args, get_origin, Mapping

import discord
from core import Bot, Command, Context
from discord.ext import commands
from discord.ext.localization import Localization
from helpers import CustomResponse


class HelpCommand(commands.HelpCommand):
	context: Context
	custom_response: CustomResponse

	def __init__(self):
		super().__init__()
		self.name = "help"

	async def prepare_help_command(self, ctx: Context, command: Optional[str] = None, /) -> None:
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
				filtered = await self.filter_commands(cog_commands, sort=True)
				command_signatures = [self.get_command_signature(command) for command in filtered]
				if not command_signatures or cog is None:
					continue

				formatted = Localization.format_strings(
					template, module=cog.qualified_name or "-", commands=len(filtered)
				)
				embeds[0].add_field(**formatted)
			message["embeds"] = CustomResponse.convert_embeds(embeds)  # type: ignore

		await self.get_destination().send(**message)  # type: ignore

	async def send_command_help(self, command: commands.Command[Any, ..., Any], /) -> None:
		await self.context.send("help.command", command=Command.from_command(command, self.context))

	async def send_group_or_cog_help(self, group_or_cog: commands.Group | commands.Cog):
		if isinstance(group_or_cog, commands.Cog):
			cog_name = await self.custom_response(f"cogs.{group_or_cog.qualified_name.lower()}", self.context)
			message = await self.custom_response(
				"help.cog",
				self.context,
				cog=cog_name,
				commands=len(await self.filter_commands(group_or_cog.get_commands(), sort=True)),
			)
		elif isinstance(group_or_cog, commands.Group):
			message = await self.custom_response(
				"help.group",
				self.context,
				group=Command.from_command(group_or_cog, self.context),
				commands=len(await self.filter_commands(group_or_cog.commands, sort=True)),
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

			if isinstance(group_or_cog, commands.Group):
				commands_list = group_or_cog.walk_commands()
			else:
				commands_list = await self.filter_commands(group_or_cog.get_commands(), sort=True)

			for command in commands_list:
				if len(embeds[0].fields) >= 25:
					break
				formatted = Localization.format_strings(template, command=Command.from_command(command, self.context))
				embeds[0].add_field(**formatted)
			message["embeds"] = CustomResponse.convert_embeds(embeds)  # type: ignore

		await self.get_destination().send(**message)  # type: ignore

	async def send_cog_help(self, cog: commands.Cog):
		await self.send_group_or_cog_help(cog)

	async def send_group_help(self, group: commands.Group):
		await self.send_group_or_cog_help(group)

	async def send_error_message(self, error: str, /) -> None:
		await self.context.send("errors.command_not_found", command=Command.from_ctx(self.context))


class Help(commands.Cog, command_attrs=dict(hidden=True)):
	def __init__(self, client: Bot):
		self.client = client
		help_command = HelpCommand()
		help_command.custom_response = client.custom_response
		help_command.cog = self
		self.client.help_command = help_command


async def setup(client: Bot):
	await client.add_cog(Help(client))
