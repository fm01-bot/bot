import discord


def resolve_channel(guild: discord.Guild, value: str | int | None) -> discord.abc.GuildChannel | discord.Thread | None:
	"""Resolve a channel from mention, ID, or name."""
	if value is None:
		return None

	val_str = str(value).strip()
	if val_str.startswith("<#") and val_str.endswith(">"):
		val_str = val_str[2:-1]
	val_str = val_str.lstrip("#")

	if val_str.isdigit():
		ch = guild.get_channel_or_thread(int(val_str))
		if ch:
			return ch

	lower_val = val_str.lower()
	for channel in guild.channels:
		if channel.name.lower() == lower_val:
			return channel
	for thread in guild.threads:
		if thread.name.lower() == lower_val:
			return thread

	return None
