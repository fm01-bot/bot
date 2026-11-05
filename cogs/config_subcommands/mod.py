from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

		if not raw_val:
			row = await ctx.bot.db.fetchrow("SELECT case_retention FROM mod_config WHERE guild_id = $1", ctx.guild.id)
			current = row["case_retention"] if row else "keep"
			return await ctx.send(content=f"```ansi\nModeration case retention: {current}\n```")

		normalized = raw_val.strip().lower()
		if normalized not in ("keep", "delete"):
			raise CLIParseError("`--retention` must be either 'keep' or 'delete'.", mod_node)

		await ctx.bot.db.execute(
			"""
			INSERT INTO mod_config (guild_id, case_retention)
			VALUES ($1, $2)
			ON CONFLICT (guild_id) DO UPDATE
			SET case_retention = $2
			""",
			ctx.guild.id,
			normalized,
		)

		# Notify Moderation cog cache if loaded
		mod_cog: Any = ctx.bot.get_cog("Moderation")
		if mod_cog and hasattr(mod_cog, "set_guild_retention"):
			mod_cog.set_guild_retention(ctx.guild.id, normalized)

		if hasattr(ctx.bot, "event_bus"):
			await ctx.bot.event_bus.publish(
				"fm01:events",
				{"type": "INVALIDATE_MOD_CONFIG", "guild_id": ctx.guild.id, "retention": normalized},
			)

		return await ctx.send(content=f"```ansi\n[+] Moderation case retention set to {normalized}\n```")

	mod_node.callback = mod_callback
	return mod_node
