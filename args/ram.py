import psutil


class RAM:
	def __init__(self):
		self._memory = psutil.virtual_memory()

	@property
	def current(self):
		return round(self._memory.total / 1073741824, 2)

	@property
	def available(self):
		return round(self._memory.available / 1073741824, 2)

	@property
	def usage(self):
		return f"{self.current} GB / {self.available} GB"

	def __str__(self):
		return self.usage
