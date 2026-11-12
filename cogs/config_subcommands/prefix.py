from __future__ import annotations

from typing import TYPE_CHECKING, Any

from helpers.cli_parser import CLINode, CLIParseError

if TYPE_CHECKING:
	from core import Context


def setup_prefix_subcommands(parent_node: CLINode) -> CLINode:
	prefix_node = parent_node.create_subcommand("prefix", description="Configure server command prefix.")
	prefix_node.add_option("prefix", "p", help="New command prefix")
	prefix_node.add_option("mention", "m", is_flag=True, default=True, help="Allow bot mention as prefix")
	prefix_node.add_argument("prefix_pos", required=False, help="New command prefix positional")

	async def prefix(
		ctx: Context, prefix: str | None = None, prefix_pos: str | None = None, mention: bool = True, **kwargs: Any
	):
		assert ctx.guild is not None
		new_prefix = prefix or prefix_pos
		if not new_prefix:
			current, _ = await ctx.bot.prefix.get(ctx.guild.id)
			return await ctx.send(content=f"```ansi\nPrefix: {current}\n```")

		if len(new_prefix) > 10:
			raise CLIParseError("The prefix can only be up to 10 characters long!", prefix_node)

		await ctx.bot.prefix.set(ctx.guild.id, (new_prefix, mention))
		return await ctx.send(content=f"```ansi\n[+] Prefix set to {new_prefix}\n```")

	prefix_node.callback = prefix
	return prefix_node
