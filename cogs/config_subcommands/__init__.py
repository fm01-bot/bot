from __future__ import annotations

from helpers.cli_parser import CLINode

from .join import setup_join_subcommands
from .leave import setup_leave_subcommands
from .log import setup_log_subcommands
from .prefix import setup_prefix_subcommands


def register_all_subcommands(root_node: CLINode) -> None:
	setup_log_subcommands(root_node)
	setup_join_subcommands(root_node)
	setup_leave_subcommands(root_node)
	setup_prefix_subcommands(root_node)
