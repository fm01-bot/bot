from __future__ import annotations

from helpers.regex import DISCORD_INVITE, DISCORD_MESSAGE_URL, DISCORD_TEMPLATE, TIME


class TestRegexHelpers:
	def test_discord_invite(self):
		valid_invites = [
			"https://discord.gg/minecraft",
			"http://discord.gg/test123a",
			"discord.gg/awesome",
			"www.discord.gg/coolbot",
			"https://discord.me/community",
			"discord.io/server",
			"https://discordapp.com/invite/special",
		]
		for invite in valid_invites:
			assert DISCORD_INVITE.search(invite) is not None, f"Failed for {invite}"

		invalid_invites = ["https://google.com", "discord.com/login", "https://github.com/project"]
		for non_invite in invalid_invites:
			assert DISCORD_INVITE.search(non_invite) is None, f"Should not match {non_invite}"

	def test_discord_template(self):
		match = DISCORD_TEMPLATE.search("https://discord.new/abc123XYZ")
		assert match is not None
		assert match.group(1) == "abc123XYZ"

		assert DISCORD_TEMPLATE.search("https://discord.com/guilds") is None

	def test_discord_message_url(self):
		url = "https://discord.com/channels/123456789012345678/234567890123456789/345678901234567890"
		match = DISCORD_MESSAGE_URL.search(url)
		assert match is not None
		assert match.group(1) == "123456789012345678"
		assert match.group(2) == "234567890123456789"
		assert match.group(3) == "345678901234567890"

		url_short = "discordapp.com/channels/12345678901234567/23456789012345678/34567890123456789"
		match_short = DISCORD_MESSAGE_URL.search(url_short)
		assert match_short is not None

		assert DISCORD_MESSAGE_URL.search("https://discord.com/channels/invalid") is None

	def test_time_regex(self):
		matches = list(TIME.finditer("5d10h30m15s"))
		assert len(matches) == 4
		assert [(m.group(1), m.group(2)) for m in matches] == [("5", "d"), ("10", "h"), ("30", "m"), ("15", "s")]
