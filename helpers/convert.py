"""A helper for converting stuff."""

import re

import discord

from .regex import TIME


def text_to_seconds(time: str, base: int = 0) -> int:
	"""
	Converts text into seconds.

	Examples
	--------
	>>> text_to_seconds("5m")  # 300
	>>> text_to_seconds("1d3min")  # 86400

	Arguments
	---------
	time
		String containing the time(s). Examples are:

		- 3min2s (3 minutes and 2 seconds) = 182 seconds

		- 5h30m (5 hours and 30 minutes) = 19000

		Supported time units:

		- years (365d)

		- months (31d)

		- weeks

		- days

		- hours

		- minutes

		- seconds
	base
	    Base seconds to add the result to, or remove the result from, if ``time`` starts with a plus or minus sign
	    respectively.

	Returns
	-------
	int
	    Seconds.

	Raises
	------
	ValueError
	    If the string doesn't contain time units.
	"""
	time_units = {
		"y": 60 * 60 * 24 * 365,
		"yr": 60 * 60 * 24 * 365,
		"yrs": 60 * 60 * 24 * 365,
		"year": 60 * 60 * 24 * 365,
		"years": 60 * 60 * 24 * 365,
		"mo": 60 * 60 * 24 * 31,
		"mos": 60 * 60 * 24 * 31,
		"month": 60 * 60 * 24 * 31,
		"months": 60 * 60 * 24 * 31,
		"w": 60 * 60 * 24 * 7,
		"wk": 60 * 60 * 24 * 7,
		"wks": 60 * 60 * 24 * 7,
		"week": 60 * 60 * 24 * 7,
		"weeks": 60 * 60 * 24 * 7,
		"d": 60 * 60 * 24,
		"dy": 60 * 60 * 24,
		"dys": 60 * 60 * 24,
		"day": 60 * 60 * 24,
		"days": 60 * 60 * 24,
		"h": 60 * 60,
		"hr": 60 * 60,
		"hrs": 60 * 60,
		"hour": 60 * 60,
		"hours": 60 * 60,
		"m": 60,
		"mn": 60,
		"mns": 60,
		"min": 60,
		"mins": 60,
		"minutes": 60,
		"s": 1,
		"sec": 1,
		"secs": 1,
		"seconds": 1,
	}

	total_seconds = 0
	matches = TIME.findall(time)

	if not matches:
		try:
			return int(time) + base
		except ValueError:
			raise ValueError(f"String doesn't contain time units ('{time}')")

	for value, unit in matches:
		total_seconds += int(value) * time_units.get(unit)

	if time.startswith("-"):
		total_seconds = base - total_seconds
	elif time.startswith("+"):
		total_seconds = base + total_seconds

	return total_seconds


def seconds_to_text(seconds: int) -> str:
	"""
	Transforms seconds into an easily understandable representation.

	Example
	--------
	>>> seconds_to_text(300)  # 5 minutes
	>>> seconds_to_text(86400)  # 1 day

	Arguments
	---------
	seconds
		The number of seconds to be converted.

	Returns
	-------
	str
		A time format that is easy for humans to read.
	"""
	if seconds == 0:
		return "0s"
	time_units = {
		"y": 60 * 60 * 24 * 365,
		"mo": 60 * 60 * 24 * 31,
		"w": 60 * 60 * 24 * 7,
		"d": 60 * 60 * 24,
		"h": 60 * 60,
		"m": 60,
		"s": 1,
	}

	time = ""
	for unit, value in time_units.items():
		if seconds >= value:
			time += f"{seconds // value}{unit[0]} "
			seconds %= value

	return time.strip()


def convert_to_query(table: str, guild: discord.Guild | None = None, limit: int | None = None, **filters):
	"""Converts a set of filters to an SQL query.

	Parameters
	----------
	table
		The table to get the results from.
	guild
		The guild to get the results from.
	limit
		The number of results to return. If ``None``, all results will be returned.
	**filters
		The conditions to filter the results by.

	Returns
	-------
	(`str`, list[Any])
	    The query string and the query parameters.
	"""
	processed_filters = {}
	for key, value in filters.items():
		if isinstance(value, (discord.User, discord.Guild, discord.Member, discord.Message)):
			processed_filters[f"{key}_id"] = value.id
		else:
			processed_filters[key] = value

	if guild is not None:
		processed_filters["guild_id"] = guild.id

	# Construct WHERE clause from processed filters
	where_clauses = []
	query_parameters = []
	for idx, (key, value) in enumerate(processed_filters.items(), start=1):
		where_clauses.append(f"{key} = ${idx}")
		query_parameters.append(value)

	where_statement = " AND ".join(where_clauses) if where_clauses else "1=1"
	query = f"SELECT * FROM {table} WHERE {where_statement}"
	if limit is not None:
		query += f" LIMIT ${len(query_parameters) + 1}"
		query_parameters.append(limit)

	return query, query_parameters


def text_to_emoji(text: str) -> list[str]:
	"""Converts a string to an emoji."""
	base = 0x1F1E6
	result = []
	for char in text.upper():
		if "A" <= char <= "Z":
			result.append(chr(base + ord(char) - ord("A")))
		else:
			result.append(char)
	return result
