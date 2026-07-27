import re

DISCORD_INVITE = re.compile(r"(?:https?://)?(?:www\.)?(discord\.(gg|io|me|li)|discordapp\.com/invite)/.+[a-z]")
DISCORD_TEMPLATE = re.compile(r"(?:https?://)?discord\.new/([a-zA-Z0-9]+)")
DISCORD_MESSAGE_URL = re.compile(
	r"(?:https?://)?(?:www\.)?discord(?:app)?\.com/channels/(\d{17,19})/(\d{17,19})/(\d{17,19})"
)
TIME = re.compile(
	r"(\d+)(y|yr|yrs|year|years|mo|mos|month|months|w|wk|wks|week|weeks|d|dy|dys|day|days|h|hr|hrs|hour|hours|m|mn|mns|min|mins|minutes|s|sc|scs|sec|secs|seconds)"
)
