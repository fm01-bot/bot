from __future__ import annotations

from pathlib import Path

from core.bot import discover_cogs


def test_discovers_modules_and_extension_packages_only():
	names = discover_cogs(Path("cogs"))

	assert "basic" in names
	assert "mod" in names  # package with setup()
	assert "config_subcommands" not in names  # package without setup()
