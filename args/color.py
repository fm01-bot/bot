from typing import Optional

import discord


class Color:
	"""Custom colors for formatting purposes.

	Operations
	----------
	`str(x)`: Returns the color in hex format.

	Examples
	--------
	>>> color = Color(discord.Color.red())
	>>> color
	#FF0000

	>>> color.image  # type: ignore
	'https://dummyimage.com/500x500/FF0000/000000&text=+'
	"""

	def __init__(self, color: Optional[discord.Color]):
		self.__color = color or discord.Color.light_grey()

	def __str__(self):
		return f"#{self.__color.value:0>6X}"  # '#RRGGBB' - '#AB12CD'

	@property
	def color(self) -> str:
		"""The color in hex format."""
		return str(self)

	colour = color

	@property
	def rgb(self) -> str:
		"""The color in RGB format."""
		colors = self.__color.to_rgb()
		return f"({colors[0]}, {colors[1]}, {colors[2]})"

	@property
	def image(self):
		return f"https://dummyimage.com/500x500/{self.__color.value:0>6X}/000000&text=+"

	pic = picture = image

	__repr__ = __str__
