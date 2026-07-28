from dataclasses import dataclass, field
from typing import Optional

import discord

from args.guild import Guild
from args.member import Member
from args.rule_action import RuleAction


@dataclass(slots=True)
class AutoModAction:
	_action: discord.AutoModRuleAction = field(repr=False)
	rule_trigger_type: str = field(repr=False)
	"""The trigger type of the rule that was executed."""
	rule_id: int = field(repr=False)
	"""The ID of the rule that was executed."""
	_guild: discord.Guild = field(repr=False)
	_member: discord.Member | None = field(repr=False)
	channel: str | None = field(repr=False)
	"""The channel where the action was executed."""
	message_id: int | None = field(repr=False)
	"""The ID of the message that triggered the action."""
	matched_keyword: str | None = field(repr=False)
	"""The keyword that was matched."""
	matched_content: str | None = field(repr=False)
	"""The content that was matched."""

	@classmethod
	def from_action(cls, execution: discord.AutoModAction):
		return cls(
			_action=execution.action,
			rule_trigger_type=execution.rule_trigger_type.name,
			rule_id=execution.rule_id,
			_guild=execution.guild,
			_member=execution.member,
			channel=execution.channel.mention if execution.channel else None,
			message_id=execution.message_id,
			matched_keyword=execution.matched_keyword,
			matched_content=execution.matched_content,
		)

	@property
	def action(self) -> RuleAction:
		"""The action that was taken."""
		return RuleAction.from_action(self._action, self._guild)

	@property
	def guild(self) -> Guild:
		"""The guild where the action was executed."""
		return Guild.from_guild(self._guild)

	@property
	def member(self) -> Member | None:
		"""The member who triggered the action."""
		if self._member is None:
			return None
		return Member.from_member(self._member)
