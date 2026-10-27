import discord


def resolve_channel(
	guild: discord.Guild | None, value: str | int | None
) -> discord.abc.GuildChannel | discord.Thread | None:
	"""Resolve a channel from mention, ID, or name."""
	if value is None or guild is None:
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


def resolve_role(guild: discord.Guild | None, value: str | int | None) -> discord.Role | None:
	"""Resolve a role from mention, ID, or name."""
	if value is None or guild is None:
		return None

	val_str = str(value).strip()
	if val_str.startswith("<@&") and val_str.endswith(">"):
		val_str = val_str[3:-1]
	val_str = val_str.lstrip("@")

	if val_str.isdigit():
		role = guild.get_role(int(val_str))
		if role:
			return role

	lower_val = val_str.lower()
	for role in guild.roles:
		if role.name.lower() == lower_val:
			return role

	return None


def resolve_category(guild: discord.Guild | None, value: str | int | None) -> discord.CategoryChannel | None:
	"""Resolve a category from ID or name."""
	if value is None or guild is None:
		return None

	val_str = str(value).strip()
	if val_str.isdigit():
		cat = guild.get_channel(int(val_str))
		if isinstance(cat, discord.CategoryChannel):
			return cat

	lower_val = val_str.lower()
	for cat in guild.categories:
		if cat.name.lower() == lower_val:
			return cat

	return None


def resolve_member_or_user(
	guild: discord.Guild | None, value: str | int | None
) -> discord.Member | discord.User | None:
	"""Resolve a member or user from mention, ID, or username."""
	if value is None or guild is None:
		return None

	val_str = str(value).strip()
	if val_str.startswith("<@") and val_str.endswith(">"):
		val_str = val_str[2:-1].lstrip("!")

	if val_str.isdigit():
		user_id = int(val_str)
		member = guild.get_member(user_id)
		if member:
			return member
		return guild._state.get_user(user_id)

	lower_val = val_str.lower().lstrip("@")
	for member in guild.members:
		if member.name.lower() == lower_val or (member.nick and member.nick.lower() == lower_val):
			return member

	return None
