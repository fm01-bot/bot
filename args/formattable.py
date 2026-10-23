import discord


class Formattable:
	def __init__(self, data, *, style: discord.utils.TimestampStyle):
		"""A class that allows you to format a datetime object into a Discord timestamp.

		Args:
			data: The datetime object to format.
			style: The timestamp style to use.

		"""
		self._parent_data = data
		self._style = style

	@property
	def value(self) -> str:
		return discord.utils.format_dt(self._parent_data.data, style=self._style)

	def __repr__(self):
		return self.value

	__str__ = __repr__
