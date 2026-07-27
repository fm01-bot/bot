import datetime
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

import discord

from args.format_date_time import FormatDateTime
from args.member import Member


@dataclass(slots=True)
class Guild:
	name: str
	"""Returns the guild's name."""
	id: int
	"""Returns the guild's ID."""
	_icon: Optional[discord.Asset] = field(repr=False)
	_banner: Optional[discord.Asset] = field(repr=False)
	_splash: Optional[discord.Asset] = field(repr=False)
	_discovery_splash: Optional[discord.Asset] = field(repr=False)
	description: Optional[str] = field(repr=False)
	"""Returns the guild's description, if it has one."""
	members: Optional[int] = field(repr=False)
	"""Returns the number of members in the guild."""
	_owner: discord.Member = field(repr=False)
	boosts: int = field(repr=False)
	"""Returns how many boosts the guild has."""
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
	"""Returns the guild's AFK channel."""
	_afk_timeout: int = field(repr=False)
	"""Returns the guild's AFK timeout."""
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
	"""Returns the max amount of emojis the guild can have."""
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
	def owner(self) -> Member:
		return Member.from_member(self._owner)

	@property
	def icon(self) -> Optional[str]:
		"""Returns the guild's icon URL."""
		return self._icon.url if self._icon else ""

	@property
	def banner(self) -> Optional[str]:
		"""Returns the guild's banner URL."""
		return self._banner.url if self._banner else ""

	@property
	def splash(self) -> Optional[str]:
		"""Returns the guild's splash URL."""
		return self._splash.url if self._splash else ""

	@property
	def discovery_splash(self) -> Optional[str]:
		"""Returns the guild's discovery splash URL."""
		return self._discovery_splash.url if self._discovery_splash else ""

	@property
	def created_at(self):
		"""Returns the date the guild was created as a Discord timestamp."""
		return FormatDateTime(self._created_at, "F")

	created = created_at

	@property
	def verification_level(self) -> str:
		"""Returns the guild's verification level."""
		mapping = {
			discord.VerificationLevel.none: r"{verification.none}",
			discord.VerificationLevel.low: r"{verification.low}",
			discord.VerificationLevel.medium: r"{verification.medium}",
			discord.VerificationLevel.high: r"{verification.high}",
			discord.VerificationLevel.highest: r"{verification.highest}",
		}
		return mapping.get(mapping)  # type: ignore

	@property
	def default_notifications(self) -> str:
		"""Returns the guild's default notification level."""
		mapping = {
			discord.NotificationLevel.all_messages: r"{notification.all_messages}",
			discord.NotificationLevel.only_mentions: r"{notification.only_mentions}",
		}
		return mapping.get(mapping)  # type: ignore

	@property
	def explicit_content_filter(self) -> str:
		"""Returns the guild's explicit content filter level."""
		mapping = {
			discord.ContentFilter.disabled: r"{content_filter.disabled}",
			discord.ContentFilter.no_role: r"{content_filter.no_role}",
			discord.ContentFilter.all_members: r"{content_filter.all_members}",
		}
		return mapping.get(mapping)  # type: ignore

	@property
	def mfa_level(self) -> str:
		"""Returns the guild's MFA level."""
		mapping = {discord.MFALevel.disabled: r"{mfa.disabled}", discord.MFALevel.require_2fa: r"{mfa.require_2fa}"}
		return mapping.get(mapping)  # type: ignore

	@property
	def system_channel(self) -> str:
		"""Returns the guild's system channel."""
		return self._system_channel.mention

	@property
	def rules_channel(self) -> str:
		"""Returns the guild's rules channel."""
		return self._rules_channel.mention

	@property
	def public_updates_channel(self) -> str:
		"""Returns the guild's public updates channel."""
		return self._public_updates_channel.mention

	@property
	def preferred_locale(self) -> str:
		"""Returns the guild's preferred locale."""
		return str(self._preferred_locale)

	locale = language = preferred_locale

	@property
	def afk_channel(self) -> str:
		"""Returns the guild's AFK channel."""
		return self._afk_channel.mention

	@property
	def vanity_url(self) -> str:
		"""Returns the guild's vanity URL."""
		return self._vanity_url

	@property
	def premium_tier(self) -> int:
		"""Returns the guild's premium tier."""
		return self._premium_tier

	boost_tier = premium_tier

	@property
	def premium_subscribers(self) -> int:
		"""Returns the guild's premium subscribers."""
		return len(self._premium_subscribers)

	boosters = premium_subscribers

	@property
	def premium_subscriber_role(self) -> str:
		"""Returns the guild's premium subscriber role."""
		return self._premium_subscriber_role.mention if self._premium_subscriber_role else None

	boost_role = premium_subscriber_role

	@property
	def nsfw_level(self) -> str:
		"""Returns the guild's NSFW level."""
		mapping = {
			discord.NSFWLevel.default: r"{nsfw.default}",
			discord.NSFWLevel.explicit: r"{nsfw.explicit}",
			discord.NSFWLevel.safe: r"{nsfw.safe}",
			discord.NSFWLevel.age_restricted: r"{nsfw.age_restricted}",
		}
		return mapping.get(mapping)  # type: ignore

	@property
	def channels(self) -> int:
		"""Returns the number of channels in the guild."""
		return len(self._channels)

	@property
	def voice_channels(self) -> int:
		"""Returns the number of voice channels in the guild."""
		return len(self._voice_channels)

	@property
	def stage_channels(self) -> int:
		"""Returns the number of stage channels in the guild."""
		return len(self._stage_channels)

	@property
	def text_channels(self) -> int:
		"""Returns the number of text channels in the guild."""
		return len(self._text_channels)

	@property
	def categories(self) -> int:
		"""Returns the number of categories in the guild."""
		return len(self._categories)

	@property
	def forums(self) -> int:
		"""Returns the number of forums in the guild."""
		return len(self._forums)

	@property
	def threads(self) -> int:
		"""Returns the number of threads in the guild."""
		return len(self._threads)

	@property
	def roles(self) -> int:
		"""Returns the number of roles in the guild."""
		return len(self._roles)

	@property
	def emojis(self) -> int:
		"""Returns the number of emojis in the guild."""
		return len(self._emojis)

	@property
	def stickers(self) -> int:
		"""Returns the number of stickers in the guild."""
		return len(self._stickers)

	@property
	def bitrate_limit(self) -> int:
		"""Returns the bitrate limit of the guild."""
		return int(self._bitrate_limit / 1000)

	bitrate = max_bitrate = bitrate_limit

	@property
	def filesize_limit(self) -> int:
		"""Returns the filesize limit of the guild in megabytes."""
		return int(self._filesize_limit / 1048576)  # Converts bytes to megabytes

	upload_limit = file_limit = file_size = max_file_size = filesize_limit

	@property
	def shard_id(self) -> int:
		"""Returns the shard ID of the guild."""
		return self._shard_id

	shard = shard_id

	@property
	def scheduled_events(self) -> int:
		"""Returns the number of scheduled events in the guild."""
		return len(self._scheduled_events)

	def __str__(self):
		return self.name

	def __int__(self):
		return self.id

	def __len__(self):
		return self.members
