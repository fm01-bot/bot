from __future__ import annotations

import argparse
import inspect
import shlex
from collections.abc import Callable, Sequence
from typing import Any, NoReturn

__all__ = ("CLINode", "CLIParseError", "CLIParser", "HelpRequested")


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

	def get_positional_placeholders(self) -> list[str]:
		"""Return formatted placeholder strings for positional arguments."""
		parts: list[str] = []
		for a in self._actions:
			if a.option_strings or a.dest == "help" or a.dest.startswith("_") or a.dest.endswith("_pos"):
				continue
			if a.choices:
				ph = f"<{'|'.join(str(c) for c in a.choices)}>"
			elif a.dest == "stack":
				ph = "<true|false>"
			elif a.required:
				ph = f"<{a.dest}...>" if a.nargs in ("+", "*") else f"<{a.dest}>"
			else:
				ph = f"[{a.dest}...]" if a.nargs in ("+", "*") else f"[{a.dest}]"
			parts.append(ph)
		return parts

	def get_option_presets(self) -> list[tuple[str, str, str]]:
		"""Return a list of (flag_with_placeholder, flag_name, help_text) for options/flags."""
		res: list[tuple[str, str, str]] = []
		for a in self._actions:
			if not a.option_strings or a.dest == "help" or a.dest.startswith("_"):
				continue
			flag: str = str(max(a.option_strings, key=len))
			help_text: str = str(getattr(a, "help", "") or "")
			if isinstance(a, argparse._StoreTrueAction) or a.nargs == 0:
				res.append((flag, flag, help_text))
			else:
				if a.choices:
					ph = f"<{'|'.join(str(c) for c in a.choices)}>"
				else:
					ph = f"<{a.dest}>"
				res.append((f"{flag} {ph}", flag, help_text))
		return res


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

	def collect_presets(
		self, node: CLINode | None = None, prefix_path: list[str] | None = None
	) -> list[tuple[list[str], str, CLINode]]:
		"""Recursively collect all executable subcommand paths and argument presets."""
		if node is None:
			node = self.root
		if prefix_path is None:
			prefix_path = []

		presets: list[tuple[list[str], str, CLINode]] = []
		sub = getattr(node, "_subparsers_action", None)
		choices: dict[str, CLINode] = sub.choices if sub else {}

		pos = node.get_positional_placeholders()
		opts = node.get_option_presets()

		preset_parts: list[str] = []
		if pos:
			preset_parts.extend(pos)
		if opts:
			preset_parts.extend([o[0] for o in opts])
		preset_str = " ".join(preset_parts)

		if node.callback is not None or (not choices and prefix_path):
			presets.append((prefix_path, preset_str, node))

		for name, child in choices.items():
			presets.extend(self.collect_presets(child, prefix_path + [name]))

		return presets

	def resolve_node(self, tokens: Sequence[str]) -> tuple[CLINode, list[str]]:
		"""Resolve the deepest reachable CLINode for a sequence of tokens."""
		curr = self.root
		consumed: list[str] = []
		for t in tokens:
			sub = getattr(curr, "_subparsers_action", None)
			if sub and t in sub.choices:
				curr = sub.choices[t]
				consumed.append(t)
			else:
				break
		return curr, consumed

	def autocomplete(self, current: str) -> list[tuple[str, str]]:
		"""Generate (label, value) choices for slash command autocomplete presets."""
		sub = getattr(self.root, "_subparsers_action", None)
		root_choices: dict[str, CLINode] = sub.choices if sub else {}

		clean = current.strip()
		if clean.lower().startswith(self.root.prog.lower() + " "):
			clean = clean[len(self.root.prog) :].lstrip()

		parts = clean.split()

		# 1. Empty or typing a single word without trailing space (not yet entered into category)
		if not clean or (len(parts) == 1 and not current.endswith(" ")):
			results: list[tuple[str, str]] = []
			token = clean.lower()

			cat_matches: list[tuple[str, str]] = []
			for cat_name in root_choices:
				if not token or cat_name.lower().startswith(token) or token in cat_name.lower():
					cat_matches.append((cat_name[:100], f"{cat_name} "))

			results.extend(cat_matches)

			# If token doesn't match an exact category, also perform global search
			if token and token not in root_choices:
				all_presets = self.collect_presets(self.root, [])
				for path, args, node in all_presets:
					full_cmd = " ".join(path)
					if args:
						full_cmd += " " + args
					if token in full_cmd.lower():
						results.append((full_cmd[:100], full_cmd[:100]))

			# Also if token exactly matches a category, include its subcommands
			if token in root_choices:
				cat_node = root_choices[token]
				for path, args, node in self.collect_presets(cat_node, [token]):
					rel_path = " ".join(path[1:])
					full_rel = f"{rel_path} {args}".strip() if args else rel_path
					full_val = f"{token} {full_rel}".strip()
					results.append((full_val[:100], full_val[:100]))

			seen: set[str] = set()
			unique_results: list[tuple[str, str]] = []
			for lbl, val in results:
				if val not in seen and lbl and val:
					seen.add(val)
					unique_results.append((lbl, val))
			return unique_results[:25]

		# 2. Inside a command string (category entered with trailing space or args)
		first_token = parts[0].lower() if parts else ""
		if first_token in root_choices:
			cat_node = root_choices[first_token]
			cat_name = first_token
			remainder = clean[len(parts[0]) :].lstrip()

			# Flag typing: e.g. current ends with '--...' or previous ends with space and has '--'
			last_token = parts[-1] if parts else ""
			if last_token.startswith("--") or (current.endswith(" ") and "--" in current):
				target_node, _ = self.resolve_node(parts)
				opts = target_node.get_option_presets()
				if opts:
					flag_filter = last_token.lower() if last_token.startswith("--") else ""
					if last_token.startswith("--"):
						prefix_before_flag = current[: current.rfind(last_token)]
						used_flags = {t.lower() for t in parts[:-1] if t.startswith("-")}
					else:
						prefix_before_flag = current if current.endswith(" ") else current + " "
						used_flags = {t.lower() for t in parts if t.startswith("-")}

					flag_results: list[tuple[str, str]] = []
					for flag_with_ph, flag_name, _help_text in opts:
						if flag_name.lower() in used_flags:
							continue
						if (
							not flag_filter
							or flag_name.lower().startswith(flag_filter)
							or flag_filter in flag_name.lower()
						):
							val = f"{prefix_before_flag}{flag_with_ph}"
							flag_results.append((val[:100], val[:100]))
					if flag_results:
						return flag_results[:25]

			# Subcommands under category
			cat_presets = self.collect_presets(cat_node, [cat_name])
			sub_filter = remainder.lower().strip()

			sub_results: list[tuple[str, str]] = []
			for path, args, node in cat_presets:
				rel_path = " ".join(path[1:])
				full_rel = f"{rel_path} {args}".strip() if args else rel_path
				full_val = f"{cat_name} {full_rel}".strip()

				if not sub_filter or sub_filter in full_rel.lower() or sub_filter in full_val.lower():
					sub_results.append((full_val[:100], full_val[:100]))

			# Also if an active executable node has options, suggest individual flags
			target_node, consumed = self.resolve_node(parts)
			if target_node != self.root and target_node != cat_node:
				opts = target_node.get_option_presets()
				if opts and len(consumed) >= 2:
					cmd_prefix = " ".join(consumed) + " "
					for flag_with_ph, _flag_name, _help_text in opts:
						val = f"{cmd_prefix}{flag_with_ph}"
						if (val[:100], val[:100]) not in sub_results:
							sub_results.append((val[:100], val[:100]))

			seen_sub: set[str] = set()
			unique_sub: list[tuple[str, str]] = []
			for lbl, val in sub_results:
				if val not in seen_sub and lbl and val:
					seen_sub.add(val)
					unique_sub.append((lbl, val))
			return unique_sub[:25]

		# 3. Not starting with category -> Global search
		query = clean.lower()
		all_presets = self.collect_presets(self.root, [])
		global_results: list[tuple[str, str]] = []
		for path, args, node in all_presets:
			full_cmd = " ".join(path)
			if args:
				full_cmd += " " + args
			if query in full_cmd.lower():
				global_results.append((full_cmd[:100], full_cmd[:100]))

		seen_global: set[str] = set()
		unique_global: list[tuple[str, str]] = []
		for lbl, val in global_results:
			if val not in seen_global and lbl and val:
				seen_global.add(val)
				unique_global.append((lbl, val))
		return unique_global[:25]
