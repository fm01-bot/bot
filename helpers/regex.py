import re

__all__ = ("DISCORD_INVITE", "DISCORD_MESSAGE_URL", "DISCORD_TEMPLATE", "TIME")

DISCORD_INVITE = re.compile(
	r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite)/[a-zA-Z0-9-]+"
)
DISCORD_TEMPLATE = re.compile(r"(?:https?://)?discord\.new/([a-zA-Z0-9]+)")
DISCORD_MESSAGE_URL = re.compile(
	r"(?:https?://)?(?:www\.)?discord(?:app)?\.com/channels/(\d{17,19})/(\d{17,19})/(\d{17,19})"
)
TIME = re.compile(
	r"(\d+)(years|year|yrs|yr|y|months|month|mos|mo|weeks|week|wks|wk|w|days|day|dys|dy|d|hours|hour|hrs|hr|h|minutes|mins|min|mns|mn|m|seconds|secs|sec|scs|sc|s)"
)
