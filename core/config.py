import logging
from typing import Any, ClassVar

import yaml

__all__ = ("Config",)

logger = logging.getLogger(__name__)


class _ConfigMeta(type):
	__FILE_CANDIDATES: ClassVar[set[str]] = {"config.yaml", "config.yml"}
	__FALLBACK: ClassVar[str] = "config.yml.example"

	def __init__(cls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]):
		super().__init__(name, bases, namespace)
		cls._load()

	def _load(cls) -> None:
		try:
			for file in cls.__FILE_CANDIDATES:
				with open(file, "r", encoding="utf-8") as f:
					data = yaml.safe_load(f) or {}
					return cls(**data)
		except FileNotFoundError:
			logger.warning("No config.yml file found, defaults are applied")
			with open("config.yml.example", "r", encoding="utf-8") as f:
				data = yaml.safe_load(f) or {}
				return cls(**data)


class Config(metaclass=_ConfigMeta):
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
