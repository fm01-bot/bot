from dataclasses import dataclass
from typing import Any

from discord.ext import commands

from core.slash_localization import slash_command_localization

__all__ = ("Argument",)


@dataclass
class Argument:
	name: str
	description: str
	default: Any
	annotation: Any
	required: bool

	@classmethod
	def from_param(cls, param: commands.Parameter, ctx: commands.Context):
		if slash_command_localization:
			localized_name = slash_command_localization(param.displayed_name or param.name, ctx)
			description = slash_command_localization(param.description, ctx) if param.description else "-"
			return cls(
				name=localized_name if isinstance(localized_name, str) else "arg",
				description=description if isinstance(description, str) and description else "-",
				default=param.default,
				annotation=param.annotation,
				required=param.required,
			)
		return None
