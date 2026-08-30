from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union, TYPE_CHECKING

import discord

from args.format_date_time import FormatDateTime

if TYPE_CHECKING:
	from args.channel import Channel
	from args.member import Member
	from args.role import Role


@dataclass(slots=True)
class Guild:
	name: str
	"""The guild's name."""
	id: int
	"""The guild's ID."""
	_icon: Optional[discord.Asset] = field(repr=False)
	_banner: Optional[discord.Asset] = field(repr=False)
	_splash: Optional[discord.Asset] = field(repr=False)
	_discovery_splash: Optional[discord.Asset] = field(repr=False)
	description: Optional[str] = field(repr=False)
	"""The guild's description, if it has one."""
	members: Optional[int] = field(repr=False)
	"""The number of members in the guild."""
	_owner: discord.Member | None = field(repr=False)
	boosts: int = field(repr=False)
	"""How many boosts the guild has."""
	_created_at: datetime.datetime = field(repr=False)
	_verification_level: discord.VerificationLevel = field(repr=False)
	_default_notifications: discord.NotificationLevel = field(repr=False)
	_explicit_content_filter: discord.ContentFilter = field(repr=False)
	_mfa_level: discord.MFALevel = field(repr=False)
	_system_channel: Optional[discord.TextChannel] = field(repr=False)
	_rules_channel: Optional[discord.TextChannel] = field(repr=False)
	_public_updates_channel: Optional[discord.TextChannel] = field(repr=False)
	_preferred_locale: discord.Locale = field(repr=False)
	_afk_channel: Optional[Union[discord.VoiceChannel, discord.StageChannel]] = field(repr=False)
	"""The guild's AFK channel."""
	_afk_timeout: int = field(repr=False)
	"""The guild's AFK timeout."""
	_vanity_url: Optional[str] = field(repr=False)
	_premium_tier: int = field(repr=False)
	_premium_subscribers: list[discord.Member] = field(repr=False)
	_premium_subscriber_role: Optional[discord.Role] = field(repr=False)
	_nsfw_level: discord.NSFWLevel = field(repr=False)
	_channels: Sequence[discord.abc.GuildChannel] = field(repr=False)
	_voice_channels: list[discord.VoiceChannel] = field(repr=False)
	_stage_channels: list[discord.StageChannel] = field(repr=False)
	_text_channels: list[discord.TextChannel] = field(repr=False)
	_categories: list[discord.CategoryChannel] = field(repr=False)
	_forums: list[discord.ForumChannel] = field(repr=False)
	_threads: Sequence[discord.Thread] = field(repr=False)
	_roles: Sequence[discord.Role] = field(repr=False)
	_emojis: tuple[discord.Emoji, ...] = field(repr=False)
	emoji_limit: int = field(repr=False)
	"""The max amount of emojis the guild can have."""
	_stickers: tuple[discord.GuildSticker, ...] = field(repr=False)
	_sticker_limit: int = field(repr=False)
	_bitrate_limit: float = field(repr=False)
	_filesize_limit: int = field(repr=False)
	_scheduled_events: Sequence[discord.ScheduledEvent] = field(repr=False)
	_shard_id: int = field(repr=False)

	@classmethod
	def from_guild(cls, guild: discord.Guild):
		return cls(
			name=guild.name,
			id=guild.id,
			_icon=guild.icon,
			_banner=guild.banner,
			_splash=guild.splash,
			_discovery_splash=guild.discovery_splash,
			description=guild.description,
			members=guild.member_count,
			_owner=guild.owner,
			boosts=guild.premium_subscription_count,
			_created_at=guild.created_at,
			_verification_level=guild.verification_level,
			_default_notifications=guild.default_notifications,
			_explicit_content_filter=guild.explicit_content_filter,
			_mfa_level=guild.mfa_level,
			_system_channel=guild.system_channel,
			_rules_channel=guild.rules_channel,
			_public_updates_channel=guild.public_updates_channel,
			_preferred_locale=guild.preferred_locale,
			_afk_channel=guild.afk_channel,
			_afk_timeout=guild.afk_timeout,
			_vanity_url=guild.vanity_url,
			_premium_tier=guild.premium_tier,
			_premium_subscribers=guild.premium_subscribers,
			_premium_subscriber_role=guild.premium_subscriber_role,
			_nsfw_level=guild.nsfw_level,
			_channels=guild.channels,
			_voice_channels=guild.voice_channels,
			_stage_channels=guild.stage_channels,
			_text_channels=guild.text_channels,
			_categories=guild.categories,
			_forums=guild.forums,
			_threads=guild.threads,
			_roles=guild.roles,
			_emojis=guild.emojis,
			emoji_limit=guild.emoji_limit,
			_stickers=guild.stickers,
			_sticker_limit=guild.sticker_limit,
			_bitrate_limit=guild.bitrate_limit,
			_filesize_limit=guild.filesize_limit,
			_scheduled_events=guild.scheduled_events,
			_shard_id=guild.shard_id,
		)

	@property
	def owner(self) -> Member | None:
		if self._owner is None:
			return None
		from args.member import Member

		return Member.from_member(self._owner)

	@property
	def icon(self) -> Optional[str]:
		"""The guild's icon URL."""
		return self._icon.url if self._icon else ""

	@property
	def banner(self) -> Optional[str]:
		"""The guild's banner URL."""
		return self._banner.url if self._banner else ""

	@property
	def splash(self) -> Optional[str]:
		"""The guild's splash URL."""
		return self._splash.url if self._splash else ""

	@property
	def discovery_splash(self) -> Optional[str]:
		"""The guild's discovery splash URL."""
		return self._discovery_splash.url if self._discovery_splash else ""

	@property
	def created_at(self):
		"""The date the guild was created as a Discord timestamp."""
		return FormatDateTime(self._created_at, "F")

	created = created_at

	@property
	def verification_level(self) -> str:
		"""The guild's verification level."""
		return r"{verification." + self._verification_level.name + r"}"

	@property
	def default_notifications(self) -> str:
		"""The guild's default notification level."""
		return r"{notification." + self._default_notifications.name + r"}"

	@property
	def explicit_content_filter(self) -> str:
		"""The guild's explicit content filter level."""
		return r"{content_filter." + self._explicit_content_filter.name + r"}"

	@property
	def mfa_level(self) -> str:
		"""The guild's MFA level."""
		return r"{mfa." + self._mfa_level.name + r"}"

	@property
	def system_channel(self) -> Channel:
		"""The guild's system channel."""
		from args.channel import convert_to_custom_channel

		return convert_to_custom_channel(self._system_channel)

	@property
	def rules_channel(self) -> Channel:
		"""The guild's rules channel."""
		from args.channel import convert_to_custom_channel

		return convert_to_custom_channel(self._rules_channel)

	@property
	def public_updates_channel(self) -> Channel:
		"""The guild's public updates channel."""
		from args.channel import convert_to_custom_channel

		return convert_to_custom_channel(self._public_updates_channel)

	@property
	def preferred_locale(self) -> str:
		"""The guild's preferred locale."""
		return str(self._preferred_locale)

	locale = language = preferred_locale

	@property
	def afk_channel(self) -> Channel:
		"""The guild's AFK channel."""
		from args.channel import convert_to_custom_channel

		return convert_to_custom_channel(self._afk_channel)

	@property
	def vanity_url(self) -> str | None:
		"""The guild's vanity URL."""
		return self._vanity_url

	@property
	def premium_tier(self) -> int:
		"""The guild's premium tier."""
		return self._premium_tier

	boost_tier = premium_tier

	@property
	def premium_subscribers(self) -> int:
		"""The guild's premium subscribers."""
		return len(self._premium_subscribers)

	boosters = premium_subscribers

	@property
	def premium_subscriber_role(self) -> Role | None:
		"""The guild's premium subscriber role."""
		if not self._premium_subscriber_role:
			return None
		from args.role import Role

		return Role.from_role(self._premium_subscriber_role)

	boost_role = premium_subscriber_role

	@property
	def nsfw_level(self) -> str:
		"""The guild's NSFW level."""
		return r"{nsfw." + self._nsfw_level.name + r"}"

	@property
	def channels(self) -> int:
		"""The number of channels in the guild."""
		return len(self._channels)

	@property
	def voice_channels(self) -> int:
		"""The number of voice channels in the guild."""
		return len(self._voice_channels)

	@property
	def stage_channels(self) -> int:
		"""The number of stage channels in the guild."""
		return len(self._stage_channels)

	@property
	def text_channels(self) -> int:
		"""The number of text channels in the guild."""
		return len(self._text_channels)

	@property
	def categories(self) -> int:
		"""The number of categories in the guild."""
		return len(self._categories)

	@property
	def forums(self) -> int:
		"""The number of forums in the guild."""
		return len(self._forums)

	@property
	def threads(self) -> int:
		"""The number of threads in the guild."""
		return len(self._threads)

	@property
	def roles(self) -> int:
		"""The number of roles in the guild."""
		return len(self._roles)

	@property
	def emojis(self) -> int:
		"""The number of emojis in the guild."""
		return len(self._emojis)

	@property
	def stickers(self) -> int:
		"""The number of stickers in the guild."""
		return len(self._stickers)

	@property
	def bitrate_limit(self) -> int:
		"""The bitrate limit of the guild."""
		return int(self._bitrate_limit / 1000)

	bitrate = max_bitrate = bitrate_limit

	@property
	def filesize_limit(self) -> int:
		"""The filesize limit of the guild in megabytes."""
		return int(self._filesize_limit / 1048576)  # Converts bytes to megabytes

	upload_limit = file_limit = file_size = max_file_size = filesize_limit

	@property
	def shard_id(self) -> int:
		"""The shard ID of the guild."""
		return self._shard_id

	shard = shard_id

	@property
	def scheduled_events(self) -> int:
		"""The number of scheduled events in the guild."""
		return len(self._scheduled_events)

	def __str__(self):
		return self.name

	def __int__(self):
		return self.id

	def __len__(self):
		return self.members
