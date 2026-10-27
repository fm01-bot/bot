"""CLI subcommands for configuring server auto-moderation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from helpers.cli_parser import CLINode, CLIParseError

from .helpers import resolve_category, resolve_channel, resolve_member_or_user, resolve_role

if TYPE_CHECKING:
	from cogs.automod import AutoMod, AutoModConfig
	from core import Context

SUPPORTED_FEATURES = ("phrase", "link", "invite", "spam", "mention", "lines")


async def _get_cog_and_config(ctx: Context, node: CLINode) -> tuple[AutoMod, AutoModConfig]:
	if not ctx.guild:
		raise CLIParseError("This command can only be used in a server.", node)
	cog: Any = ctx.bot.get_cog("AutoMod")
	if not cog:
		raise CLIParseError("AutoMod module is not currently loaded.", node)
	config = await cog.get_config(ctx.guild.id)
	return cog, config


def _validate_feature(feature: str | None, node: CLINode) -> str | None:
	if feature is None:
		return None
	feat = feature.strip().lower()
	if feat not in SUPPORTED_FEATURES:
		raise CLIParseError(f"Unknown feature `{feature}`. Supported features: {', '.join(SUPPORTED_FEATURES)}.", node)
	return feat


def _parse_bool(val: str | None, node: CLINode, opt_name: str) -> bool:
	if val is None:
		return True
	low = val.strip().lower()
	if low in ("on", "true", "yes", "1", "enable", "enabled"):
		return True
	if low in ("off", "false", "no", "0", "disable", "disabled"):
		return False
	raise CLIParseError(f"`--{opt_name}` must be 'on'/'off' or 'true'/'false'.", node)


def setup_automod_subcommands(parent_node: CLINode) -> CLINode:
	"""Set up automod configuration subcommands on the CLI parser root."""
	automod_node = parent_node.create_subcommand("automod", description="Configure server auto-moderation.")

	status_node = automod_node.create_subcommand("status", description="Show server auto-moderation status.")

	async def automod_status(ctx: Context, **kwargs: Any):
		assert ctx.guild is not None
		_, config = await _get_cog_and_config(ctx, status_node)
		rules = config.settings.get("rules", {})
		bypasses = config.settings.get("bypasses", {})
		actions = config.settings.get("actions", {}).get("default", {})

		lines = [
			f"Auto Moderation Configuration ({ctx.guild.name})\n",
			f"Master Status: {'[+] Enabled' if config.is_on else '[-] Disabled'}\n",
			"Rules:",
		]

		for feat in SUPPORTED_FEATURES:
			r = rules.get(feat, {})
			enabled = "[+]" if (config.is_on and r.get("enabled", False)) else "[-]"
			details = ""
			if feat == "phrase":
				count = len(r.get("phrases", []))
				details = f"({count} banned phrase{'s' if count != 1 else ''})"
			elif feat == "link":
				count = len(r.get("allowlist", []))
				details = f"({count} allowed domain{'s' if count != 1 else ''})"
			elif feat == "invite":
				count = len(r.get("allowlist", []))
				details = f"({count} allowed invite{'s' if count != 1 else ''})"
			elif feat == "spam":
				max_m = r.get("max_messages", 5)
				win = r.get("window_seconds", 6.0)
				details = f"(max {max_m} msgs in {win}s)"
			elif feat == "mention":
				limit = r.get("limit", 5)
				details = f"(max {limit} mentions)"
			elif feat == "lines":
				limit = r.get("limit", 15)
				details = f"(max {limit} lines)"

			lines.append(f"  {enabled} {feat:<8} {details}")

		glob = bypasses.get("global", {})
		g_ch = len(glob.get("channels", []))
		g_cat = len(glob.get("categories", []))
		g_usr = len(glob.get("users", []))
		g_rol = len(glob.get("roles", []))

		lines.append("\nGlobal Bypasses:")
		lines.append(f"  Channels: {g_ch} | Categories: {g_cat} | Users: {g_usr} | Roles: {g_rol}")

		lines.append("\nDefault Action:")
		lines.append(
			f"  Delete: {'yes' if actions.get('delete', True) else 'no'} | "
			f"Notify: {'yes' if actions.get('notify', True) else 'no'} ({actions.get('notify_duration', 5)}s) | "
			f"Case: {actions.get('case') or 'none'}"
		)

		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	status_node.callback = automod_status

	enable_node = automod_node.create_subcommand("enable", description="Enable automod globally or for a feature.")
	enable_node.add_argument("feature", required=False, default=None, help="Target feature name (or omit for master)")

	async def automod_enable(ctx: Context, feature: str | None = None, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, enable_node)
		feat = _validate_feature(feature, enable_node)
		if feat is None:
			config.is_on = True
			await cog.save_config(config)
			return await ctx.send(content="```ansi\n[+] Auto Moderation master system enabled\n```")

		config.settings.setdefault("rules", {}).setdefault(feat, {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Auto Moderation rule `{feat}` enabled\n```")

	enable_node.callback = automod_enable

	disable_node = automod_node.create_subcommand("disable", description="Disable automod globally or for a feature.")
	disable_node.add_argument("feature", required=False, default=None, help="Target feature name (or omit for master)")

	async def automod_disable(ctx: Context, feature: str | None = None, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, disable_node)
		feat = _validate_feature(feature, disable_node)
		if feat is None:
			config.is_on = False
			await cog.save_config(config)
			return await ctx.send(content="```ansi\n[-] Auto Moderation master system disabled\n```")

		config.settings.setdefault("rules", {}).setdefault(feat, {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[-] Auto Moderation rule `{feat}` disabled\n```")

	disable_node.callback = automod_disable

	phrase_node = automod_node.create_subcommand("phrase", description="Manage forbidden phrase filter.")

	phrase_enable_node = phrase_node.create_subcommand("enable", description="Enable phrase filter.")

	async def phrase_enable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, phrase_enable_node)
		config.settings.setdefault("rules", {}).setdefault("phrase", {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[+] Phrase filter enabled\n```")

	phrase_enable_node.callback = phrase_enable

	phrase_disable_node = phrase_node.create_subcommand("disable", description="Disable phrase filter.")

	async def phrase_disable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, phrase_disable_node)
		config.settings.setdefault("rules", {}).setdefault("phrase", {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] Phrase filter disabled\n```")

	phrase_disable_node.callback = phrase_disable

	phrase_add_node = phrase_node.create_subcommand("add", description="Add forbidden phrases.")
	phrase_add_node.add_argument("phrases", nargs="+", required=True, help="Phrases to block")

	async def phrase_add(ctx: Context, phrases: list[str], **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, phrase_add_node)
		existing = config.settings.setdefault("rules", {}).setdefault("phrase", {}).setdefault("phrases", [])
		added = []
		for p in phrases:
			cleaned = p.strip()
			if cleaned and cleaned.lower() not in [x.lower() for x in existing]:
				existing.append(cleaned)
				added.append(cleaned)
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Added {len(added)} phrase(s): {', '.join(added)}\n```")

	phrase_add_node.callback = phrase_add

	phrase_remove_node = phrase_node.create_subcommand("remove", description="Remove forbidden phrases.")
	phrase_remove_node.add_argument("phrases", nargs="+", required=True, help="Phrases to remove")

	async def phrase_remove(ctx: Context, phrases: list[str], **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, phrase_remove_node)
		existing = config.settings.setdefault("rules", {}).setdefault("phrase", {}).setdefault("phrases", [])
		targets = {p.strip().lower() for p in phrases}
		removed = [p for p in existing if p.lower() in targets]
		config.settings["rules"]["phrase"]["phrases"] = [p for p in existing if p.lower() not in targets]
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[-] Removed {len(removed)} phrase(s): {', '.join(removed)}\n```")

	phrase_remove_node.callback = phrase_remove

	phrase_list_node = phrase_node.create_subcommand("list", description="List forbidden phrases.")

	async def phrase_list(ctx: Context, **kwargs: Any):
		_, config = await _get_cog_and_config(ctx, phrase_list_node)
		phrases = config.settings.get("rules", {}).get("phrase", {}).get("phrases", [])
		if not phrases:
			return await ctx.send(content="```ansi\nNo forbidden phrases configured.\n```")
		lines = [f"Forbidden Phrases ({len(phrases)}):\n"]
		for p in sorted(phrases):
			lines.append(f"  - {p}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	phrase_list_node.callback = phrase_list

	phrase_clear_node = phrase_node.create_subcommand("clear", description="Clear all forbidden phrases.")

	async def phrase_clear(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, phrase_clear_node)
		config.settings.setdefault("rules", {}).setdefault("phrase", {})["phrases"] = []
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] All forbidden phrases cleared\n```")

	phrase_clear_node.callback = phrase_clear

	link_node = automod_node.create_subcommand("link", description="Manage link filter and allowlist.")

	link_enable_node = link_node.create_subcommand("enable", description="Enable link filtering.")

	async def link_enable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, link_enable_node)
		config.settings.setdefault("rules", {}).setdefault("link", {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[+] Link filtering enabled\n```")

	link_enable_node.callback = link_enable

	link_disable_node = link_node.create_subcommand("disable", description="Disable link filtering.")

	async def link_disable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, link_disable_node)
		config.settings.setdefault("rules", {}).setdefault("link", {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] Link filtering disabled\n```")

	link_disable_node.callback = link_disable

	link_allow_node = link_node.create_subcommand("allow", description="Add domains to link allowlist.")
	link_allow_node.add_argument("domains", nargs="+", required=True, help="Domains to allow (e.g. youtube.com)")

	async def link_allow(ctx: Context, domains: list[str], **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, link_allow_node)
		existing = config.settings.setdefault("rules", {}).setdefault("link", {}).setdefault("allowlist", [])
		added = []
		for d in domains:
			clean = re.sub(r"^(?:https?://)?(?:www\.)?", "", d.strip().lower()).split("/")[0]
			if clean and clean not in [x.lower() for x in existing]:
				existing.append(clean)
				added.append(clean)
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Added to link allowlist: {', '.join(added)}\n```")

	link_allow_node.callback = link_allow

	link_disallow_node = link_node.create_subcommand("disallow", description="Remove domains from link allowlist.")
	link_disallow_node.add_argument("domains", nargs="+", required=True, help="Domains to remove from allowlist")

	async def link_disallow(ctx: Context, domains: list[str], **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, link_disallow_node)
		existing = config.settings.setdefault("rules", {}).setdefault("link", {}).setdefault("allowlist", [])
		targets = {re.sub(r"^(?:https?://)?(?:www\.)?", "", d.strip().lower()).split("/")[0] for d in domains}
		removed = [d for d in existing if d.lower() in targets]
		config.settings["rules"]["link"]["allowlist"] = [d for d in existing if d.lower() not in targets]
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[-] Removed from link allowlist: {', '.join(removed)}\n```")

	link_disallow_node.callback = link_disallow

	link_list_node = link_node.create_subcommand("list", description="List allowed domains.")

	async def link_list(ctx: Context, **kwargs: Any):
		_, config = await _get_cog_and_config(ctx, link_list_node)
		domains = config.settings.get("rules", {}).get("link", {}).get("allowlist", [])
		if not domains:
			return await ctx.send(content="```ansi\nNo domains are currently allowlisted.\n```")
		lines = [f"Allowed Domains ({len(domains)}):\n"]
		for d in sorted(domains):
			lines.append(f"  - {d}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	link_list_node.callback = link_list

	link_clear_node = link_node.create_subcommand("clear", description="Clear all allowlisted domains.")

	async def link_clear(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, link_clear_node)
		config.settings.setdefault("rules", {}).setdefault("link", {})["allowlist"] = []
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] All allowed domains cleared\n```")

	link_clear_node.callback = link_clear

	invite_node = automod_node.create_subcommand("invite", description="Manage Discord invite filtering.")

	invite_enable_node = invite_node.create_subcommand("enable", description="Enable invite filtering.")

	async def invite_enable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, invite_enable_node)
		config.settings.setdefault("rules", {}).setdefault("invite", {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[+] Discord invite filtering enabled\n```")

	invite_enable_node.callback = invite_enable

	invite_disable_node = invite_node.create_subcommand("disable", description="Disable invite filtering.")

	async def invite_disable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, invite_disable_node)
		config.settings.setdefault("rules", {}).setdefault("invite", {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] Discord invite filtering disabled\n```")

	invite_disable_node.callback = invite_disable

	invite_allow_node = invite_node.create_subcommand("allow", description="Add invite codes to allowlist.")
	invite_allow_node.add_argument("codes", nargs="+", required=True, help="Invite codes or links to allow")

	async def invite_allow(ctx: Context, codes: list[str], **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, invite_allow_node)
		existing = config.settings.setdefault("rules", {}).setdefault("invite", {}).setdefault("allowlist", [])
		added = []
		for c in codes:
			code = c.strip().rstrip("/").split("/")[-1].lower()
			if code and code not in [x.lower() for x in existing]:
				existing.append(code)
				added.append(code)
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Added to invite allowlist: {', '.join(added)}\n```")

	invite_allow_node.callback = invite_allow

	invite_disallow_node = invite_node.create_subcommand("disallow", description="Remove invite codes from allowlist.")
	invite_disallow_node.add_argument("codes", nargs="+", required=True, help="Invite codes to remove")

	async def invite_disallow(ctx: Context, codes: list[str], **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, invite_disallow_node)
		existing = config.settings.setdefault("rules", {}).setdefault("invite", {}).setdefault("allowlist", [])
		targets = {c.strip().rstrip("/").split("/")[-1].lower() for c in codes}
		removed = [c for c in existing if c.lower() in targets]
		config.settings["rules"]["invite"]["allowlist"] = [c for c in existing if c.lower() not in targets]
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[-] Removed from invite allowlist: {', '.join(removed)}\n```")

	invite_disallow_node.callback = invite_disallow

	invite_list_node = invite_node.create_subcommand("list", description="List allowed invite codes.")

	async def invite_list(ctx: Context, **kwargs: Any):
		_, config = await _get_cog_and_config(ctx, invite_list_node)
		codes = config.settings.get("rules", {}).get("invite", {}).get("allowlist", [])
		if not codes:
			return await ctx.send(content="```ansi\nNo invite codes are currently allowlisted.\n```")
		lines = [f"Allowed Invite Codes ({len(codes)}):\n"]
		for c in sorted(codes):
			lines.append(f"  - {c}")
		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	invite_list_node.callback = invite_list

	invite_clear_node = invite_node.create_subcommand("clear", description="Clear all allowlisted invite codes.")

	async def invite_clear(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, invite_clear_node)
		config.settings.setdefault("rules", {}).setdefault("invite", {})["allowlist"] = []
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] All allowed invite codes cleared\n```")

	invite_clear_node.callback = invite_clear

	spam_node = automod_node.create_subcommand("spam", description="Configure anti-spam message rate limiting.")

	spam_enable_node = spam_node.create_subcommand("enable", description="Enable anti-spam.")

	async def spam_enable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, spam_enable_node)
		config.settings.setdefault("rules", {}).setdefault("spam", {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[+] Anti-spam enabled\n```")

	spam_enable_node.callback = spam_enable

	spam_disable_node = spam_node.create_subcommand("disable", description="Disable anti-spam.")

	async def spam_disable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, spam_disable_node)
		config.settings.setdefault("rules", {}).setdefault("spam", {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] Anti-spam disabled\n```")

	spam_disable_node.callback = spam_disable

	spam_limit_node = spam_node.create_subcommand("limit", description="Set maximum allowed messages in window.")
	spam_limit_node.add_argument("count", type=int, help="Max messages allowed (e.g. 5)")

	async def spam_limit(ctx: Context, count: int, **kwargs: Any):
		if count < 1:
			raise CLIParseError("Max messages count must be at least 1.", spam_limit_node)
		cog, config = await _get_cog_and_config(ctx, spam_limit_node)
		config.settings.setdefault("rules", {}).setdefault("spam", {})["max_messages"] = count
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Anti-spam message limit set to {count} messages\n```")

	spam_limit_node.callback = spam_limit

	spam_window_node = spam_node.create_subcommand("window", description="Set window duration in seconds.")
	spam_window_node.add_argument("seconds", type=float, help="Window duration in seconds (e.g. 6.0)")

	async def spam_window(ctx: Context, seconds: float, **kwargs: Any):
		if seconds <= 0:
			raise CLIParseError("Window duration must be greater than 0.", spam_window_node)
		cog, config = await _get_cog_and_config(ctx, spam_window_node)
		config.settings.setdefault("rules", {}).setdefault("spam", {})["window_seconds"] = seconds
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Anti-spam window duration set to {seconds}s\n```")

	spam_window_node.callback = spam_window

	mention_node = automod_node.create_subcommand("mention", description="Configure mention spam limit.")

	mention_enable_node = mention_node.create_subcommand("enable", description="Enable mention spam limit.")

	async def mention_enable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, mention_enable_node)
		config.settings.setdefault("rules", {}).setdefault("mention", {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[+] Mention limit enabled\n```")

	mention_enable_node.callback = mention_enable

	mention_disable_node = mention_node.create_subcommand("disable", description="Disable mention spam limit.")

	async def mention_disable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, mention_disable_node)
		config.settings.setdefault("rules", {}).setdefault("mention", {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] Mention limit disabled\n```")

	mention_disable_node.callback = mention_disable

	mention_limit_node = mention_node.create_subcommand("limit", description="Set mention threshold per message.")
	mention_limit_node.add_argument("count", type=int, help="Maximum allowed mentions (e.g. 5)")

	async def mention_limit(ctx: Context, count: int, **kwargs: Any):
		if count < 1:
			raise CLIParseError("Mention limit must be at least 1.", mention_limit_node)
		cog, config = await _get_cog_and_config(ctx, mention_limit_node)
		config.settings.setdefault("rules", {}).setdefault("mention", {})["limit"] = count
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Mention threshold set to {count}\n```")

	mention_limit_node.callback = mention_limit

	lines_node = automod_node.create_subcommand("lines", description="Configure maximum message lines limit.")

	lines_enable_node = lines_node.create_subcommand("enable", description="Enable message lines limit.")

	async def lines_enable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, lines_enable_node)
		config.settings.setdefault("rules", {}).setdefault("lines", {})["enabled"] = True
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[+] Message lines limit enabled\n```")

	lines_enable_node.callback = lines_enable

	lines_disable_node = lines_node.create_subcommand("disable", description="Disable message lines limit.")

	async def lines_disable(ctx: Context, **kwargs: Any):
		cog, config = await _get_cog_and_config(ctx, lines_disable_node)
		config.settings.setdefault("rules", {}).setdefault("lines", {})["enabled"] = False
		await cog.save_config(config)
		return await ctx.send(content="```ansi\n[-] Message lines limit disabled\n```")

	lines_disable_node.callback = lines_disable

	lines_limit_node = lines_node.create_subcommand("limit", description="Set line count threshold.")
	lines_limit_node.add_argument("count", type=int, help="Maximum allowed lines (e.g. 15)")

	async def lines_limit(ctx: Context, count: int, **kwargs: Any):
		if count < 1:
			raise CLIParseError("Line count limit must be at least 1.", lines_limit_node)
		cog, config = await _get_cog_and_config(ctx, lines_limit_node)
		config.settings.setdefault("rules", {}).setdefault("lines", {})["limit"] = count
		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Message lines threshold set to {count}\n```")

	lines_limit_node.callback = lines_limit

	bypass_node = automod_node.create_subcommand("bypass", description="Manage global and per-feature bypasses.")

	bypass_add_node = bypass_node.create_subcommand(
		"add", description="Add bypasses for channels, categories, users, or roles."
	)
	bypass_add_node.add_option("feature", "f", help="Target rule to bypass (omit for global bypass)")
	bypass_add_node.add_option("channel", "c", help="Target channel")
	bypass_add_node.add_option("category", help="Target category")
	bypass_add_node.add_option("user", "u", help="Target user or member")
	bypass_add_node.add_option("role", "r", help="Target role")

	async def bypass_add(
		ctx: Context,
		feature: str | None = None,
		channel: str | None = None,
		category: str | None = None,
		user: str | None = None,
		role: str | None = None,
		**kwargs: Any,
	):
		if not any((channel, category, user, role)):
			raise CLIParseError(
				"Please specify at least one entity to bypass: `--channel`, `--category`, `--user`, or `--role`.",
				bypass_add_node,
			)

		feat = _validate_feature(feature, bypass_add_node)
		cog, config = await _get_cog_and_config(ctx, bypass_add_node)

		if feat:
			dest = (
				config.settings.setdefault("bypasses", {})
				.setdefault("features", {})
				.setdefault(
					feat,
					{
						"channels": [],
						"categories": [],
						"users": [],
						"roles": [],
					},
				)
			)
			scope_label = f"feature `{feat}`"
		else:
			dest = config.settings.setdefault("bypasses", {}).setdefault(
				"global",
				{
					"channels": [],
					"categories": [],
					"users": [],
					"roles": [],
				},
			)
			scope_label = "global"

		added_items = []
		if channel:
			ch_obj = resolve_channel(ctx.guild, channel)
			if not ch_obj:
				raise CLIParseError(f"Channel `{channel}` not found.", bypass_add_node)
			if ch_obj.id not in dest["channels"]:
				dest["channels"].append(ch_obj.id)
			added_items.append(f"Channel #{ch_obj.name}")

		if category:
			cat_obj = resolve_category(ctx.guild, category)
			if not cat_obj:
				raise CLIParseError(f"Category `{category}` not found.", bypass_add_node)
			if cat_obj.id not in dest["categories"]:
				dest["categories"].append(cat_obj.id)
			added_items.append(f"Category {cat_obj.name}")

		if user:
			user_obj = resolve_member_or_user(ctx.guild, user)
			if not user_obj:
				raise CLIParseError(f"User `{user}` not found.", bypass_add_node)
			if user_obj.id not in dest["users"]:
				dest["users"].append(user_obj.id)
			added_items.append(f"User @{user_obj.name}")

		if role:
			role_obj = resolve_role(ctx.guild, role)
			if not role_obj:
				raise CLIParseError(f"Role `{role}` not found.", bypass_add_node)
			if role_obj.id not in dest["roles"]:
				dest["roles"].append(role_obj.id)
			added_items.append(f"Role @{role_obj.name}")

		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[+] Added bypass for {scope_label}: {', '.join(added_items)}\n```")

	bypass_add_node.callback = bypass_add

	bypass_remove_node = bypass_node.create_subcommand("remove", description="Remove bypasses.")
	bypass_remove_node.add_option("feature", "f", help="Target rule to bypass (omit for global bypass)")
	bypass_remove_node.add_option("channel", "c", help="Target channel")
	bypass_remove_node.add_option("category", help="Target category")
	bypass_remove_node.add_option("user", "u", help="Target user or member")
	bypass_remove_node.add_option("role", "r", help="Target role")

	async def bypass_remove(
		ctx: Context,
		feature: str | None = None,
		channel: str | None = None,
		category: str | None = None,
		user: str | None = None,
		role: str | None = None,
		**kwargs: Any,
	):
		if not any((channel, category, user, role)):
			raise CLIParseError(
				"Please specify at least one entity to remove: `--channel`, `--category`, `--user`, or `--role`.",
				bypass_remove_node,
			)

		feat = _validate_feature(feature, bypass_remove_node)
		cog, config = await _get_cog_and_config(ctx, bypass_remove_node)

		if feat:
			dest = (
				config.settings.setdefault("bypasses", {})
				.setdefault("features", {})
				.setdefault(
					feat,
					{
						"channels": [],
						"categories": [],
						"users": [],
						"roles": [],
					},
				)
			)
			scope_label = f"feature `{feat}`"
		else:
			dest = config.settings.setdefault("bypasses", {}).setdefault(
				"global",
				{
					"channels": [],
					"categories": [],
					"users": [],
					"roles": [],
				},
			)
			scope_label = "global"

		removed_items = []
		if channel:
			ch_obj = resolve_channel(ctx.guild, channel)
			target_id = ch_obj.id if ch_obj else (int(channel) if channel.isdigit() else None)
			if target_id and target_id in dest["channels"]:
				dest["channels"].remove(target_id)
				removed_items.append(f"Channel {target_id}")

		if category:
			cat_obj = resolve_category(ctx.guild, category)
			target_id = cat_obj.id if cat_obj else (int(category) if category.isdigit() else None)
			if target_id and target_id in dest["categories"]:
				dest["categories"].remove(target_id)
				removed_items.append(f"Category {target_id}")

		if user:
			user_obj = resolve_member_or_user(ctx.guild, user)
			target_id = user_obj.id if user_obj else (int(user) if user.isdigit() else None)
			if target_id and target_id in dest["users"]:
				dest["users"].remove(target_id)
				removed_items.append(f"User {target_id}")

		if role:
			role_obj = resolve_role(ctx.guild, role)
			target_id = role_obj.id if role_obj else (int(role) if role.isdigit() else None)
			if target_id and target_id in dest["roles"]:
				dest["roles"].remove(target_id)
				removed_items.append(f"Role {target_id}")

		await cog.save_config(config)
		return await ctx.send(content=f"```ansi\n[-] Removed bypass for {scope_label}: {', '.join(removed_items)}\n```")

	bypass_remove_node.callback = bypass_remove

	bypass_list_node = bypass_node.create_subcommand("list", description="List active bypasses.")
	bypass_list_node.add_option("feature", "f", help="Target feature name (omit for global and all features)")

	async def bypass_list(ctx: Context, feature: str | None = None, **kwargs: Any):
		assert ctx.guild is not None
		_, config = await _get_cog_and_config(ctx, bypass_list_node)
		feat = _validate_feature(feature, bypass_list_node)

		bypasses = config.settings.get("bypasses", {})

		def _format_scope(title: str, data: dict[str, Any]) -> list[str]:
			assert ctx.guild is not None
			out = [f"=== {title} ==="]
			channels = data.get("channels", [])
			categories = data.get("categories", [])
			users = data.get("users", [])
			roles = data.get("roles", [])

			ch_names = []
			for cid in channels:
				ch = ctx.guild.get_channel(cid)
				ch_names.append(f"#{ch.name}" if ch else str(cid))
			out.append(f"  Channels:   {', '.join(ch_names) if ch_names else 'None'}")

			cat_names = []
			for cid in categories:
				cat = ctx.guild.get_channel(cid)
				cat_names.append(cat.name if cat else str(cid))
			out.append(f"  Categories: {', '.join(cat_names) if cat_names else 'None'}")

			usr_names = []
			for uid in users:
				m = ctx.guild.get_member(uid)
				usr_names.append(f"@{m.name}" if m else str(uid))
			out.append(f"  Users:      {', '.join(usr_names) if usr_names else 'None'}")

			role_names = []
			for rid in roles:
				r = ctx.guild.get_role(rid)
				role_names.append(f"@{r.name}" if r else str(rid))
			out.append(f"  Roles:      {', '.join(role_names) if role_names else 'None'}")
			return out

		lines = []
		if feat:
			data = bypasses.get("features", {}).get(feat, {})
			lines.extend(_format_scope(f"Bypasses for feature `{feat}`", data))
		else:
			lines.extend(_format_scope("Global Bypasses", bypasses.get("global", {})))
			for f_name, data in bypasses.get("features", {}).items():
				if any(data.get(k) for k in ("channels", "categories", "users", "roles")):
					lines.append("")
					lines.extend(_format_scope(f"Feature: {f_name}", data))

		return await ctx.send(content="```ansi\n" + "\n".join(lines) + "\n```")

	bypass_list_node.callback = bypass_list

	action_node = automod_node.create_subcommand("action", description="Configure enforcement actions on violation.")
	action_node.add_option("feature", "f", help="Target rule to configure action for (omit for default action)")
	action_node.add_option("delete", help="Toggle message deletion: on/off or true/false")
	action_node.add_option("notify", help="Toggle channel notification: on/off or true/false")
	action_node.add_option(
		"notify-duration", "d", type=int, help="Notification auto-delete duration in seconds (default 5)"
	)
	action_node.add_option("case", help="Moderation case to issue: none, warn, mute")
	action_node.add_option("mute-duration", "m", help="Mute timeout duration (e.g. 5m, 1h, 1d)")

	async def automod_action(
		ctx: Context,
		feature: str | None = None,
		delete: str | None = None,
		notify: str | None = None,
		notify_duration: int | None = None,
		case: str | None = None,
		mute_duration: str | None = None,
		**kwargs: Any,
	):
		if all(v is None for v in (delete, notify, notify_duration, case, mute_duration)):
			raise CLIParseError(
				"Please specify at least one action setting: `--delete`, `--notify`, `--notify-duration`, `--case`, or `--mute-duration`.",
				action_node,
			)

		feat = _validate_feature(feature, action_node)
		cog, config = await _get_cog_and_config(ctx, action_node)

		if feat:
			dest = config.settings.setdefault("actions", {}).setdefault("features", {}).setdefault(feat, {})
			scope_label = f"feature `{feat}`"
		else:
			dest = config.settings.setdefault("actions", {}).setdefault("default", {})
			scope_label = "default"

		updated = []
		if delete is not None:
			dest["delete"] = _parse_bool(delete, action_node, "delete")
			updated.append(f"delete={'yes' if dest['delete'] else 'no'}")

		if notify is not None:
			dest["notify"] = _parse_bool(notify, action_node, "notify")
			updated.append(f"notify={'yes' if dest['notify'] else 'no'}")

		if notify_duration is not None:
			if notify_duration < 1:
				raise CLIParseError("`--notify-duration` must be at least 1 second.", action_node)
			dest["notify_duration"] = notify_duration
			updated.append(f"notify_duration={notify_duration}s")

		if case is not None:
			case_low = case.strip().lower()
			if case_low in ("none", "off", "disable", "disabled"):
				dest["case"] = None
				updated.append("case=none")
			elif case_low in ("warn", "mute"):
				dest["case"] = case_low
				updated.append(f"case={case_low}")
			else:
				raise CLIParseError("`--case` must be 'none', 'warn', or 'mute'.", action_node)

		if mute_duration is not None:
			dest["mute_duration"] = mute_duration.strip()
			updated.append(f"mute_duration={mute_duration.strip()}")

		await cog.save_config(config)
		return await ctx.send(
			content=f"```ansi\n[+] Updated action settings for {scope_label}: {', '.join(updated)}\n```"
		)

	action_node.callback = automod_action

	return automod_node
