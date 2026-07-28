import time
import datetime

import discord
from args.formattable import Formattable


class FormatDateTime:
	"""Formats a datetime object into a dynamic Discord timestamp."""

	def __init__(self, data: datetime.datetime, default_style: discord.utils.TimestampStyle):
		self.data = data
		self.default_style = default_style

	@property
	def timestamp(self) -> str:
		return self.data.astimezone(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

	@property
	def time(self) -> Formattable:
		"""The hours and minutes of the timestamp.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").time
		22:57
		"""
		return Formattable(self, style="t")

	t = time

	@property
	def seconds(self) -> Formattable:
		"""The seconds of the timestamp.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").seconds
		22:57:43
		"""
		return Formattable(self, style="T")

	T = seconds

	@property
	def date(self) -> Formattable:
		"""The date of the timestamp.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").date
		2022-02-17
		"""
		return Formattable(self, style="d")

	d = date

	@property
	def date_long(self) -> Formattable:
		"""The date version of the timestamp with the month as text.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").date_long
		17 February 2022
		"""
		return Formattable(self, style="D")

	D = date_long

	@property
	def long(self) -> Formattable:
		"""The long version of the timestamp.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").long
		Thursday, 17 February 2022
		"""
		return Formattable(self, style="f")

	f = long

	@property
	def longer(self) -> Formattable:
		"""The long version of the timestamp with the day shown.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").longer
		Thursday, 17 February 2022 at 22:57
		"""
		return Formattable(self, style="F")

	F = longer

	@property
	def relative(self) -> Formattable:
		"""The relative version of the timestamp.

		Examples
		--------
		>>> FormatDateTime(datetime.datetime.now(), "F").relative
		1 minute ago
		"""
		return Formattable(self, style="R")

	R = relative

	def __repr__(self) -> str:
		return Formattable(self, style=self.default_style).value
