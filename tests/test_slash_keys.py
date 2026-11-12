"""Every slash command's localization keys must resolve in slash_localization/en.l10n.json.

Discord falls back to the code name when a key is missing, so a missing or mistyped key shows up as an untranslatable
command in every language. This test reads the commands from the cog classes; no bot is started.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterator
from pathlib import Path

import pytest
from core import slash_localization
from core.bot import discover_cogs
from discord import app_commands
from discord.ext import commands


def _app_commands() -> Iterator[tuple[str, app_commands.Command | app_commands.Group]]:
	for name in discover_cogs(Path("cogs")):
		module = importlib.import_module(f"cogs.{name}")
		for cog in vars(module).values():
			if not (inspect.isclass(cog) and issubclass(cog, commands.Cog)) or cog.__module__ != module.__name__:
				continue
			for command in cog.__cog_commands__:
				app = getattr(command, "app_command", None)
				if app is not None:
					yield from _walk(app, f"{cog.__name__}.{command.qualified_name}")


def _walk(
	app: app_commands.Command | app_commands.Group, path: str
) -> Iterator[tuple[str, app_commands.Command | app_commands.Group]]:
	yield path, app
	if isinstance(app, app_commands.Group):
		for child in app.commands:
			yield from _walk(child, f"{path} {child.name}")


def _keys(app: app_commands.Command | app_commands.Group) -> Iterator[tuple[str, str]]:
	strings: list[tuple[str, object]] = [("name", app._locale_name)]
	if isinstance(app, app_commands.Command):  # group descriptions are never shown: groups run through a fallback
		strings.append(("description", app._locale_description))
		for param in app._params.values():
			strings += [("param name", param._rename), ("param description", param.description)]
			strings += [("choice", choice._locale_name) for choice in (param.choices or [])]
	for label, value in strings:
		if isinstance(value, app_commands.locale_str):
			yield label, value.extras.get("key") or value.message


def test_every_slash_key_resolves_in_english():
	slash_localization.update_slash_localizations()
	missing = [
		f"{path}: {label} -> {key}"
		for path, app in _app_commands()
		for label, key in _keys(app)
		if slash_localization.lookup(key, "en") is None
	]
	assert not missing, "Missing slash localization keys:\n" + "\n".join(missing)


@pytest.mark.parametrize(
	("key", "expected"),
	[("caserem-name", "remove"), ("caserem-args-case_id-name", "case_id"), ("not-a-key", None), ("mod", "mod")],
)
def test_lookup_resolves_nested_keys(key, expected):
	slash_localization.update_slash_localizations()
	assert slash_localization.lookup(key, "en") == expected
