from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest
from helpers.convert import ALLOWED_TABLES, convert_to_query, seconds_to_text, text_to_emoji, text_to_seconds


class TestTextToSeconds:
	def test_single_units(self):
		assert text_to_seconds("10s") == 10
		assert text_to_seconds("5m") == 300
		assert text_to_seconds("2h") == 7200
		assert text_to_seconds("3d") == 259200
		assert text_to_seconds("1w") == 604800
		assert text_to_seconds("1mo") == 2678400
		assert text_to_seconds("1y") == 31536000

	def test_compound_units(self):
		assert text_to_seconds("1h30m") == 5400
		assert text_to_seconds("2d4h15m30s") == (2 * 86400) + (4 * 3600) + (15 * 60) + 30
		assert text_to_seconds("1yr2months") == 31536000 + (2 * 60 * 60 * 24 * 31)

	def test_alternative_spellings(self):
		assert text_to_seconds("5mins") == 300
		assert text_to_seconds("10minutes") == 600
		assert text_to_seconds("3hours") == 10800
		assert text_to_seconds("4days") == 345600
		assert text_to_seconds("2weeks") == 1209600
		assert text_to_seconds("3secs") == 3
		assert text_to_seconds("1sec") == 1

	def test_base_and_prefixes(self):
		assert text_to_seconds("+10m", base=100) == 700
		assert text_to_seconds("-10m", base=1000) == 400
		assert text_to_seconds("5m", base=50) == 350

	def test_raw_integer_fallback(self):
		assert text_to_seconds("120") == 120
		assert text_to_seconds("+120", base=100) == 220
		assert text_to_seconds("-30", base=100) == 70

	def test_invalid_strings(self):
		with pytest.raises(ValueError, match="String doesn't contain time units"):
			text_to_seconds("hello world")

		with pytest.raises(ValueError, match="Malformed time string"):
			text_to_seconds("5m extra_tokens")

		with pytest.raises(ValueError, match="Malformed time string"):
			text_to_seconds("10m-invalid")


class TestSecondsToText:
	def test_zero_seconds(self):
		assert seconds_to_text(0) == "0s"

	def test_single_units(self):
		assert seconds_to_text(45) == "45s"
		assert seconds_to_text(300) == "5m"
		assert seconds_to_text(7200) == "2h"
		assert seconds_to_text(86400) == "1d"
		assert seconds_to_text(604800) == "1w"

	def test_compound_units(self):
		# 1 day + 2 hours + 3 minutes + 4 seconds
		total = 86400 + 7200 + 180 + 4
		assert seconds_to_text(total) == "1d 2h 3m 4s"

		# 1 year + 10 seconds
		total_year = (60 * 60 * 24 * 365) + 10
		assert seconds_to_text(total_year) == "1y 10s"


class TestConvertToQuery:
	def test_allowed_tables(self):
		for table in ALLOWED_TABLES:
			query, params = convert_to_query(table)
			assert query == f'SELECT * FROM "{table}" WHERE 1=1'
			assert params == []

	def test_disallowed_table(self):
		with pytest.raises(ValueError, match="Disallowed or invalid table name"):
			convert_to_query("users_passwords")

		with pytest.raises(ValueError, match="Disallowed or invalid table name"):
			convert_to_query("drop table users;--")

	def test_with_guild_filter(self):
		guild = MagicMock(spec=discord.Guild)
		guild.id = 987654321
		query, params = convert_to_query("cases", guild=guild)
		assert query == 'SELECT * FROM "cases" WHERE "guild_id" = $1'
		assert params == [987654321]

	def test_with_discord_objects_conversion(self):
		user = MagicMock(spec=discord.User)
		user.id = 1111
		member = MagicMock(spec=discord.Member)
		member.id = 2222
		message = MagicMock(spec=discord.Message)
		message.id = 3333

		query, params = convert_to_query("cases", user=user, moderator=member, target_message=message)
		assert '"user_id" = $1' in query
		assert '"moderator_id" = $2' in query
		assert '"target_message_id" = $3' in query
		assert params == [1111, 2222, 3333]

	def test_with_limit(self):
		query, params = convert_to_query("cases", state=True, limit=10)
		assert query == 'SELECT * FROM "cases" WHERE "state" = $1 LIMIT $2'
		assert params == [True, 10]

	def test_invalid_column_identifier(self):
		with pytest.raises(ValueError, match="Invalid column identifier"):
			convert_to_query("cases", **{"invalid-column!": "val"})  # type: ignore # the type error is expected


class TestTextToEmoji:
	def test_basic_conversion(self):
		emojis = text_to_emoji("abc")
		# Base regional indicator 'A' is \U0001f1e6
		assert emojis == ["\U0001f1e6", "\U0001f1e7", "\U0001f1e8"]

	def test_case_insensitivity(self):
		assert text_to_emoji("A") == text_to_emoji("a")

	def test_non_alpha_characters(self):
		result = text_to_emoji("a 1!")
		assert result[0] == "\U0001f1e6"
		assert result[1] == " "
		assert result[2] == "1"
		assert result[3] == "!"
