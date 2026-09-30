from __future__ import annotations

import argparse
import inspect
import shlex
from collections.abc import Callable, Sequence
from typing import Any, NoReturn


class CLIParseError(Exception):
	"""Raised when command-line arguments cannot be parsed."""

	def __init__(self, message: str, node: CLINode | None = None):
		super().__init__(message)
		self.message = message
		self.node = node
		self.parser = node


class HelpRequested(Exception):
	"""Raised when help (-h / --help) is requested."""

	def __init__(self, help_text: str, node: CLINode | None = None):
		super().__init__(help_text)
		self.help_text = help_text
		self.node = node
		self.parser = node


class CLINode(argparse.ArgumentParser):
	"""An ArgumentParser subclass tailored for Discord bot command routing."""

	def __init__(self, *args: Any, callback: Callable[..., Any] | None = None, **kwargs: Any):
		super().__init__(*args, **kwargs)
		self.callback = callback
		self._subparsers_action: argparse._SubParsersAction | None = None

	@property
	def name(self) -> str:
		return self.prog.split()[-1]

	def _print_message(self, message: str, file: Any = None) -> None:
		# Suppress printing directly to stdout/stderr
		pass

	def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
		if status == 0:
			raise HelpRequested(self.format_help(), self)
		raise CLIParseError(message or self.format_help(), self)

	def error(self, message: str) -> NoReturn:
		if "invalid choice:" in message:
			import re

			match = re.search(r"invalid choice:\s*('[^']+'|\S+)\s*\((?:choose from\s*)?([^)]+)\)", message)
			if match:
				choice, choices = match.groups()
				message = f"Unknown subcommand {choice}. Available subcommands: {choices}."
		raise CLIParseError(message, self)

	def add_option(
		self,
		name: str,
		short: str | None = None,
		*,
		type: Any = str,
		is_flag: bool = False,
		default: Any = None,
		required: bool = False,
		help: str = "",
		nargs: int | str | None = None,
	) -> argparse.Action:
		"""Add an option / flag (e.g. `--channel` or `-c`)."""
		flags = []
		if short:
			clean_s = short.lstrip("-")
			flags.append(f"-{clean_s}")
		clean_l = name.lstrip("-")
		flags.append(f"--{clean_l}")
		dest = clean_l.replace("-", "_")

		if is_flag:
			return super().add_argument(*flags, dest=dest, action="store_true", default=default or False, help=help)

		opt_kwargs: dict[str, Any] = {"dest": dest, "default": default, "required": required, "help": help}
		if type is not None and type is not str:
			opt_kwargs["type"] = type
		if nargs is not None:
			opt_kwargs["nargs"] = nargs

		return super().add_argument(*flags, **opt_kwargs)

	def add_argument(  # type: ignore[override]
		self,
		*args: Any,
		required: bool = True,
		nargs: int | str | None = None,
		default: Any = None,
		help: str = "",
		type: Any = str,
		**kwargs: Any,
	) -> argparse.Action:
		"""Add a positional argument or standard argument."""
		if args and not args[0].startswith("-"):
			dest_name = args[0]
			if not required and nargs is None:
				nargs = "?"
			kwargs["nargs"] = nargs
			kwargs["default"] = default
			kwargs["help"] = help
			if type is not None and type is not str:
				kwargs["type"] = type
			return super().add_argument(dest_name, **kwargs)
		return super().add_argument(*args, **kwargs)

	def create_subcommand(
		self, name: str, description: str = "", callback: Callable[..., Any] | None = None
	) -> CLINode:
		"""Create a child subcommand parser."""
		if self._subparsers_action is None:
			self._subparsers_action = self.add_subparsers(
				dest=f"_{self.prog.replace(' ', '_')}_sub", parser_class=CLINode
			)
		subparser: CLINode = self._subparsers_action.add_parser(
			name, help=description, description=description, callback=callback
		)
		subparser.set_defaults(_active_parser=subparser)
		return subparser

	def add_subcommand(
		self, child_or_name: CLINode | str, description: str = "", callback: Callable[..., Any] | None = None
	) -> CLINode:
		"""Add or create a child subcommand parser."""
		if isinstance(child_or_name, CLINode):
			return child_or_name
		return self.create_subcommand(child_or_name, description=description, callback=callback)

	def subcommand(self, name: str, description: str = "") -> Callable[[Callable[..., Any]], CLINode]:
		"""Decorator to register a subcommand callback."""

		def decorator(func: Callable[..., Any]) -> CLINode:
			desc = description or (func.__doc__ or "").strip()
			return self.create_subcommand(name, description=desc, callback=func)

		return decorator


class CLIParser:
	"""Bash-like CLI argument parser wrapping argparse and shlex."""

	def __init__(self, root_name: str, description: str = ""):
		self.root = CLINode(prog=root_name, description=description)
		self.root.set_defaults(_active_parser=self.root)

	@staticmethod
	def split_args(cmdline: str) -> list[str]:
		"""Split a command-line string into bash tokens respecting quotes and escapes."""
		if not cmdline.strip():
			return []
		return shlex.split(cmdline, posix=True)

	def parse(self, tokens: Sequence[str]) -> tuple[CLINode, dict[str, Any]]:
		"""Parse tokens and return the active subcommand node and option dictionary."""
		args = self.root.parse_args(list(tokens))
		active: CLINode = getattr(args, "_active_parser", self.root)
		opts = {k: v for k, v in vars(args).items() if not k.startswith("_")}
		return active, opts

	async def execute(self, cmdline: str | Sequence[str], *extra_args: Any, **extra_kwargs: Any) -> Any:
		"""Parse tokens and invoke the active subcommand's callback."""
		tokens = self.split_args(cmdline) if isinstance(cmdline, str) else list(cmdline)
		if not tokens:
			raise HelpRequested(self.root.format_help(), self.root)

		args = self.root.parse_args(tokens)
		active: CLINode = getattr(args, "_active_parser", self.root)
		if active.callback is None:
			raise HelpRequested(active.format_help(), active)

		sig = inspect.signature(active.callback)
		parsed = {k: v for k, v in vars(args).items() if not k.startswith("_")}
		kwargs_to_pass: dict[str, Any] = {}

		for param_name, param in sig.parameters.items():
			if param_name in parsed:
				kwargs_to_pass[param_name] = parsed[param_name]
			elif param_name in extra_kwargs:
				kwargs_to_pass[param_name] = extra_kwargs[param_name]
			elif param.default != inspect.Parameter.empty:
				kwargs_to_pass[param_name] = param.default

		res = active.callback(*extra_args, **kwargs_to_pass)
		if inspect.isawaitable(res):
			return await res
		return res
