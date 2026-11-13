from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cogs.mod.cases import retention_setting
from helpers.cli_parser import CLINode, CLIParseError

if TYPE_CHECKING:
	from core import Context


def setup_mod_subcommands(parent_node: CLINode) -> CLINode:
	"""Set up CLI commands for moderation system configuration."""
	mod_node = parent_node.create_subcommand("mod", description="Configure moderation system settings.")
	mod_node.add_option("retention", "r", help="Case retention policy on expiration: 'keep' or 'delete'")
	mod_node.add_argument("retention_pos", required=False, help="Case retention policy positional argument")

	async def mod_callback(
		ctx: Context,
		retention: str | None = None,
		retention_pos: str | None = None,
		**kwargs: Any,
	):
		assert ctx.guild is not None
		raw_val = retention or retention_pos

		setting = retention_setting(ctx.bot.settings)
		if not raw_val:
			current = await setting.get(ctx.guild.id)
			return await ctx.send(content=f"```ansi\nModeration case retention: {current}\n```")

		normalized = raw_val.strip().lower()
		if normalized not in ("keep", "delete"):
			raise CLIParseError("`--retention` must be either 'keep' or 'delete'.", mod_node)

		await setting.set(ctx.guild.id, normalized)

		return await ctx.send(content=f"```ansi\n[+] Moderation case retention set to {normalized}\n```")

	mod_node.callback = mod_callback
	return mod_node
