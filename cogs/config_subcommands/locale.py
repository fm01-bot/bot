from __future__ import annotations

from typing import TYPE_CHECKING, Any

from helpers.cli_parser import CLINode, CLIParseError

if TYPE_CHECKING:
	from core import Context


def setup_locale_subcommands(parent_node: CLINode) -> CLINode:
	locale_node = parent_node.create_subcommand("locale", description="Override the locale used by the bot.")
	locale_node.add_option(
		"locale",
		"l",
		help="New locale code (e.g. 'en', 'hu')",
	)
	locale_node.add_option(
		"default",
		"d",
		is_flag=True,
		default=False,
		help="Clear custom locale override, use server locale instead",
	)
	locale_node.add_argument("locale_pos", required=False, help="New locale code positional")

	async def locale(
		ctx: Context,
		locale: str | None = None,
		locale_pos: str | None = None,
		default: bool = False,
		**kwargs: Any,
	):
		if not ctx.guild:
			raise CLIParseError("This command can only be used in a server.", locale_node)

		if default:
			await ctx.bot.locale_override.set(ctx.guild.id, None)
			server_locale = str(ctx.guild.preferred_locale)
			return await ctx.send(
				content=f"```ansi\n[+] Locale override cleared. Using server locale ({server_locale})\n```"
			)

		new_locale = locale or locale_pos
		if not new_locale:
			override = await ctx.bot.locale_override.get(ctx.guild.id)
			if override:
				return await ctx.send(
					content=f"```ansi\nLocale: {override} (override)\nServer: {ctx.guild.preferred_locale}\n```"
				)
			return await ctx.send(content=f"```ansi\nLocale: {ctx.guild.preferred_locale}\n```")

		new_locale = new_locale.strip().lower()
		if len(new_locale) != 2 or not new_locale.isalpha():
			raise CLIParseError(
				"Locales use two letter country codes. (i.e. 'en-US' and 'en-GB' are both under 'en')", locale_node
			)

		await ctx.bot.locale_override.set(ctx.guild.id, new_locale)
		return await ctx.send(content=f"```ansi\n[+] Locale set to {new_locale}\n```")

	locale_node.callback = locale
	return locale_node
