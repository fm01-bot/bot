"""Audit-log reasons are localized plain strings; check the ones the moderation code formats with a moderator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

EN = json.loads((Path(__file__).resolve().parent.parent / "localization" / "en.l10n.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
	"path", ["mod.mute.reason", "mod.kick.reason", "mod.ban.reason", "mod.unban.reason", "mod.unmute.reason"]
)
def test_moderation_reasons_name_the_moderator(path):
	node: object = EN
	for part in path.split("."):
		assert isinstance(node, dict)
		node = node[part]
	assert isinstance(node, str) and "{moderator.name}" in node
