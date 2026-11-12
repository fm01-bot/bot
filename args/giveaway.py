from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from args.format_date_time import FormatDateTime


@dataclass(slots=True)
class Giveaway:
	id: int
	"""The giveaway's internal ID."""
	prize: str
	"""The prize being given away."""
	winners: int
	"""How many winners the giveaway draws."""
	entries: int
	"""How many members have entered the giveaway."""
	ends: FormatDateTime
	"""When the giveaway ends (or ended)."""
	created: FormatDateTime
	"""When the giveaway was started."""
	channel: str
	"""A mention of the channel the giveaway is hosted in."""
	jump_url: str
	"""A link to the giveaway message, or an empty string if it hasn't been sent yet."""

	@classmethod
	def from_record(cls, record: Mapping[str, Any], entries: int = 0) -> Giveaway:
		"""Build a formatting wrapper from a ``giveaways`` database row.

		Args:
			record: The ``giveaways`` row.
			entries: The current number of entries.

		Returns:
			Giveaway: The formatting wrapper.
		"""
		guild_id, channel_id = int(record["guild_id"]), int(record["channel_id"])
		message_id = record["message_id"]
		ends_at: datetime.datetime = record["ends_at"]
		created_at: datetime.datetime = record["created_at"]
		return cls(
			id=int(record["id"]),
			prize=str(record["prize"]),
			winners=int(record["winner_count"]),
			entries=entries,
			ends=FormatDateTime(ends_at, "F"),
			created=FormatDateTime(created_at, "F"),
			channel=f"<#{channel_id}>",
			jump_url=f"https://discord.com/channels/{guild_id}/{channel_id}/{int(message_id)}" if message_id else "",
		)
