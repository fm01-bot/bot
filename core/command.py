import logging
from dataclasses import dataclass
from typing import Optional

from discord.ext import commands

logger = logging.getLogger(__name__)

from core import slash_localization


@dataclass
class Command:
	name: str
	description: str
	usage: str
	prefix: str
	aliases: Optional[str]

	@classmethod
	def from_ctx(cls, ctx: commands.Context):
		l10n = slash_localization.slash_command_localization
		if ctx.command and l10n:
			usage_attr = getattr(ctx.command, "usage", None)
			desc_attr = getattr(ctx.command, "description", None)
			logger.info(f"{usage_attr=} {desc_attr=}")
			usage = l10n(usage_attr, ctx) if usage_attr and ctx.guild else l10n(usage_attr, "en")
			description = l10n(desc_attr, ctx) if ctx.guild else l10n(desc_attr, "en")
			return cls(
				name=ctx.command.qualified_name,
				description=description if isinstance(description, str) and description else "-",
				usage=f"{ctx.clean_prefix}{usage}",
				prefix=ctx.clean_prefix,
				aliases=", ".join(ctx.command.aliases) if len(ctx.command.aliases) > 0 else None,
			)
		return None

	@classmethod
	def from_command(cls, command: commands.Command, ctx: commands.Context):
		l10n = slash_localization.slash_command_localization
		if l10n:
			usage_attr = getattr(command, "usage", None)
			desc_attr = getattr(command, "description", None)
			usage = l10n(usage_attr, ctx) if usage_attr and ctx.guild else l10n(usage_attr, "en")
			description = l10n(desc_attr, ctx) if ctx.guild else l10n(desc_attr, "en")
			usage_text = f"{ctx.clean_prefix}{command.qualified_name}" if usage == usage_attr else usage
			return cls(
				name=command.qualified_name,
				description=description if isinstance(description, str) and description else "-",
				usage=usage_text,
				prefix=ctx.clean_prefix,
				aliases=", ".join(command.aliases) if len(command.aliases) > 0 else None,
			)
		return None
