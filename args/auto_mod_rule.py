import datetime
from dataclasses import dataclass, field

import discord

from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.member import Member


@dataclass(slots=True)
class AutoModRule:
	name: str
	"""Returns the rule's name."""
	id: int
	"""Returns the rule's ID."""
	enabled: bool
	"""Returns whether the rule is enabled."""
	trigger_type: str
	"""Returns the rule's trigger type."""
	_creator: discord.Member = field(repr=False)
	_guild: discord.Guild = field(repr=False)
	_actions: list[discord.AutoModRuleAction] = field(repr=False)
	_exempt_roles: list[discord.Role] = field(repr=False)
	_exempt_channels: list[discord.abc.GuildChannel] = field(repr=False)
	_created_at: datetime.datetime = field(repr=False)

	@classmethod
	async def from_rule(cls, rule: discord.AutoModRule):
		creator = rule.guild.get_member(rule.creator_id) or await rule.guild.fetch_member(rule.creator_id)
		return cls(
			name=rule.name,
			id=rule.id,
			enabled=rule.enabled,
			trigger_type=rule.trigger.type.name,  # type: ignore
			_creator=creator,
			_guild=rule.guild,
			_actions=rule.actions,
			_exempt_roles=rule.exempt_roles,
			_exempt_channels=rule.exempt_channels,
			_created_at=discord.utils.snowflake_time(rule.id),
		)

	@property
	def creator(self) -> Member:
		"""Returns the rule's creator."""
		return Member.from_member(self._creator)

	@property
	def guild(self) -> Guild:
		"""Returns the rule's guild."""
		return Guild.from_guild(self._guild)

	@property
	def actions(self) -> str:
		"""Returns the rule's actions."""
		if not self._actions:
			return "None"

		action_strings = []
		for action in self._actions:
			if action.type.name == "send_alert_message":  # type: ignore
				channel = self._guild.get_channel(action.channel_id)
				if channel:
					action_strings.append(f"Send Alert to {channel.mention}")
				else:
					action_strings.append("Send Alert (Channel not found)")
			elif action.type.name == "timeout":  # type: ignore
				duration_seconds = action.duration.total_seconds()
				minutes, seconds = divmod(duration_seconds, 60)
				hours, minutes = divmod(minutes, 60)
				days, hours = divmod(hours, 24)

				duration_str = ""
				if days > 0:
					duration_str += f"{int(days)}d "
				if hours > 0:
					duration_str += f"{int(hours)}h "
				if minutes > 0:
					duration_str += f"{int(minutes)}m "
				if seconds > 0:
					duration_str += f"{int(seconds)}s"

				action_strings.append(f"Timeout ({duration_str.strip()})")
			else:
				action_strings.append(action.type.name.replace("_", " ").title())  # type: ignore

		return ", ".join(action_strings)

	@property
	def exempt_roles(self) -> str:
		"""Returns the rule's exempt roles."""
		return ", ".join([role.mention for role in self._exempt_roles]) if self._exempt_roles else "None"

	@property
	def exempt_channels(self) -> str:
		"""Returns the rule's exempt channels."""
		return ", ".join([channel.mention for channel in self._exempt_channels]) if self._exempt_channels else "None"

	@property
	def created_at(self) -> FormatDateTime:
		"""Returns when the rule was created."""
		return FormatDateTime(self._created_at, "f")

	def __str__(self) -> str:
		return self.name
