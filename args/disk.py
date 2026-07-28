import psutil


class Disk:
	def __init__(self):
		self._disk = psutil.disk_usage("/")

	@property
	def percent(self):
		"""The percentage representation of the disk usage."""
		return self._disk.percent

	@property
	def total(self):
		"""The total amount of disk space in gigabytes."""
		return self._disk.total / 1073741824

	@property
	def used(self):
		"""The amount of used disk space in gigabytes."""
		return self._disk.used / 1073741824

	@property
	def free(self):
		"""The amount of free disk space in gigabytes."""
		return self._disk.free / 1073741824

	def __str__(self):
		return f"{self.percent}%"
