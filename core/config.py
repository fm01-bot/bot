from dataclasses import dataclass
import yaml
from typing import Any
import logging


@dataclass
class Config:
	debug: bool
	owner_ids: list[int]
	modules: list[str]
	log_channel_id: int
	allowed_contexts: dict[str, bool]
	allowed_installs: dict[str, bool]
	allowed_mentions: dict[str, bool]

	@classmethod
	def from_file(cls, file: str = "config.yml"):
		try:
			with open(file, "r", encoding="utf-8") as f:
				return cls(**yaml.safe_load(f))
		except FileNotFoundError:
			logging.warning("No config.yml file found, defaults are applied")
			with open("config.yml.example", "r", encoding="utf-8") as f:
				return cls(**yaml.safe_load(f))

	def get(self, key: str, default: Any = None) -> Any:
		return getattr(self, key, default)
