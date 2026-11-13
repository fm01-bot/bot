"""Every literal message key the code sends must exist in localization/en.l10n.json.

A missing key only shows up when someone runs the command, so this scans the source instead. It finds calls such as
``ctx.send("mod.warn.response", ...)``, ``custom_response.get_message("leaderboard", ...)``, ``get_list(...)`` and
``self.custom_response("mod.slowmode.reason", ...)`` whose first argument is a string literal that looks like a key.
Keys built at runtime (f-strings) are not checked.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ("cogs", "core", "helpers")
KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")
SENDERS = {"send", "reply", "get_message", "get_list"}


def _is_message_call(node: ast.Call) -> bool:
	func = node.func
	if isinstance(func, ast.Attribute):
		return func.attr in SENDERS or func.attr == "custom_response"
	return isinstance(func, ast.Name) and func.id == "custom_response"


def _literal_keys() -> Iterator[tuple[str, int, str]]:
	for folder in SOURCES:
		for path in sorted((ROOT / folder).rglob("*.py")):
			tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
			for node in ast.walk(tree):
				if not (isinstance(node, ast.Call) and _is_message_call(node) and node.args):
					continue
				first = node.args[0]
				if isinstance(first, ast.Constant) and isinstance(first.value, str) and KEY.match(first.value):
					yield str(path.relative_to(ROOT)), node.lineno, first.value


def _exists(tree: object, key: str) -> bool:
	for part in key.split("."):
		if not isinstance(tree, dict) or part not in tree:
			return False
		tree = tree[part]
	return True


def test_every_literal_message_key_exists_in_english():
	en = json.loads((ROOT / "localization" / "en.l10n.json").read_text(encoding="utf-8"))
	found = list(_literal_keys())
	assert len(found) > 100, "the scan stopped finding message keys; update _is_message_call"

	missing = sorted({f"{path}:{line}: {key}" for path, line, key in found if not _exists(en, key)})
	assert not missing, "Message keys missing from localization/en.l10n.json:\n" + "\n".join(missing)
