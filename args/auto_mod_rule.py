import datetime
from dataclasses import dataclass, field

import discord
from helpers import seconds_to_text

from args.format_date_time import FormatDateTime
from args.guild import Guild
from args.member import Member
from args.user import User


@dataclass(slots=True)
class AutoModRule:
	name: str
	"""The rule's name."""
	id: int
	"""The rule's ID."""
	enabled: bool
	"""Whether the rule is enabled."""
	trigger_type: str
	"""The rule's trigger type."""
	_creator: discord.Member | discord.User | None = field(repr=False)
	_guild: discord.Guild = field(repr=False)
	_actions: list[discord.AutoModRuleAction] = field(repr=False)
	_exempt_roles: list[discord.Role] = field(repr=False)
	_exempt_channels: list[discord.abc.GuildChannel | discord.Thread] = field(repr=False)
	_created_at: datetime.datetime = field(repr=False)

	_creator_id: int = field(repr=False, default=0)

	@classmethod
	async def from_rule(cls, rule: discord.AutoModRule):
		creator = rule.guild.get_member(rule.creator_id)
		if creator is None:
			try:
				creator = await rule.guild.fetch_member(rule.creator_id)
			except (discord.NotFound, discord.HTTPException):
				creator = None
		return cls(
			name=rule.name,
			id=rule.id,
			enabled=rule.enabled,
			trigger_type=rule.trigger.type.name,
			_creator=creator,
			_guild=rule.guild,
			_actions=rule.actions,
			_exempt_roles=rule.exempt_roles,
			_exempt_channels=rule.exempt_channels,
			_created_at=discord.utils.snowflake_time(rule.id),
			_creator_id=rule.creator_id,
		)

	@property
	def creator(self) -> Member | User:
		"""The rule's creator."""
		if isinstance(self._creator, discord.Member):
			return Member.from_member(self._creator)
		if isinstance(self._creator, discord.User):
			return User.from_user(self._creator)
		return User(
			_name="Unknown",
			id=self._creator_id,
			_discriminator=None,
			global_name="Unknown",
			display_name="Unknown",
			bot=False,
			_color=None,
			_avatar="",
			_decoration=None,
			_banner=None,
			_created_at=datetime.datetime.now(datetime.UTC),
			mention=f"<@{self._creator_id}>" if self._creator_id else "Unknown",
		)

	@property
	def guild(self) -> Guild:
		"""The rule's guild."""
		return Guild.from_guild(self._guild)

	@property
	def actions(self) -> str:
		"""The rule's actions."""
		if not self._actions:
			return "None"

		action_strings = []
		for action in self._actions:
			if action.type == discord.AutoModRuleActionType.send_alert_message and action.channel_id is not None:
				channel = self._guild.get_channel(action.channel_id)
				if channel:
					action_strings.append(f"🔔 {channel.mention}")
				else:
					action_strings.append("🔔")
			elif action.type == discord.AutoModRuleActionType.timeout and action.duration is not None:
				duration_str = seconds_to_text(int(action.duration.total_seconds()))
				action_strings.append(f"⏰ {duration_str}")
			else:
				action_strings.append(action.type.name.upper())

		return ", ".join(action_strings)

	@property
	def exempt_roles(self) -> str:
		"""The rule's exempt roles."""
		return ", ".join([role.mention for role in self._exempt_roles]) if self._exempt_roles else "None"

	@property
	def exempt_channels(self) -> str:
		"""The rule's exempt channels."""
		return ", ".join([channel.mention for channel in self._exempt_channels]) if self._exempt_channels else "None"

	@property
	def created_at(self) -> FormatDateTime:
		"""When the rule was created."""
		return FormatDateTime(self._created_at, "f")

	def __str__(self) -> str:
		return self.name
