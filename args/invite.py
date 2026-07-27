import datetime
from dataclasses import dataclass, field
from typing import Optional

import discord

from args.channel import Channel, convert_to_custom_channel
from args.format_date_time import FormatDateTime
from args.user import User


@dataclass(slots=True)
class Invite:
	code: str
	"""Returns the invite's code."""
	url: str
	"""Returns the invite's URL."""
	_inviter: Optional[discord.User] = field(repr=False)
	_created_at: Optional[datetime.datetime] = field(repr=False)
	_max_age: Optional[int] = field(repr=False)
	max_uses: Optional[int]
	"""Returns the maximum number of uses for the invite."""
	temporary: Optional[bool]
	"""Returns whether the invite is temporary."""
	_channel: Optional[discord.abc.GuildChannel]
	uses: Optional[int]
	"""Returns the number of times the invite has been used."""

	@classmethod
	def from_invite(cls, invite: discord.Invite):
		return cls(
			code=invite.code,
			url=invite.url,
			_inviter=invite.inviter,
			_created_at=invite.created_at,
			_max_age=invite.max_age,
			max_uses=invite.max_uses,
			temporary=invite.temporary,
			_channel=invite.channel,
			uses=invite.uses,
		)

	@classmethod
	def from_audit_log_diff(cls, audit_data: discord.AuditLogDiff):
		return cls(
			code=audit_data.code,
			url=f"https://discord.gg/{audit_data.code}",
			_inviter=audit_data.inviter,
			_created_at=None,  # Not available in audit log diff for deletes
			_max_age=audit_data.max_age,
			max_uses=audit_data.max_uses,
			temporary=audit_data.temporary,
			_channel=audit_data.channel,
			uses=audit_data.uses,
		)

	@property
	def max_age(self) -> Optional[FormatDateTime]:
		"""Returns the invite's max age as a relative timestamp or a human-readable duration."""
		if self._max_age == 0:
			return None

		if self._created_at:
			expires = self._created_at + datetime.timedelta(seconds=self._max_age)
			return FormatDateTime(expires, "R")

		return None

	expires = max_age

	@property
	def inviter(self) -> Optional[User]:
		"""Returns the user who created the invite."""
		return User.from_user(self._inviter) if self._inviter else None

	author = inviter

	@property
	def created_at(self) -> Optional[FormatDateTime]:
		"""Returns the date the invite was created as a Discord timestamp. This is not available in ``on_invite_delete`` events."""
		return FormatDateTime(self._created_at, "f") if self._created_at else None

	created = created_at

	@property
	def channel(self) -> Optional[Channel]:
		"""Returns the channel the invite is for."""
		return convert_to_custom_channel(self._channel)

	def __str__(self) -> str:
		return self.code
