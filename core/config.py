import logging
from dataclasses import dataclass
from typing import Self

import yaml

__all__ = ("Config",)

logger = logging.getLogger(__name__)


@dataclass
class Config:
	debug: bool
	owner_ids: list[int]
	modules: list[str]
	log_channel_id: int
	allowed_contexts: dict[str, bool]
	allowed_installs: dict[str, bool]
	allowed_mentions: dict[str, bool]
	emojis: dict[str, str]
	twitch_client_id: str | None = None
	twitch_client_secret: str | None = None
	rsshub_url: str | None = None

	@classmethod
	def from_file(cls, file: str | None = None) -> Self:
		candidates = [file] if file else ["config.yaml", "config.yml"]
		for candidate in candidates:
			try:
				with open(candidate, "r", encoding="utf-8") as f:
					data = yaml.safe_load(f) or {}
					return cls(**data)
			except FileNotFoundError:
				continue
		logger.warning("No config.yml file found, defaults are applied")
		with open("config.yml.example", "r", encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
			return cls(**data)
