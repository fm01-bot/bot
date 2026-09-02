import psutil
from cpuinfo import get_cpu_info


class CPU:
	@property
	def name(self):
		"""The full name of the CPU."""
		return get_cpu_info().get("brand_raw")

	@property
	def usage(self):
		"""The CPU usage in percentages."""
		return psutil.cpu_percent()

	@property
	def cores(self):
		"""The amount of cores in the CPU."""
		return psutil.cpu_count(logical=False)

	@property
	def logical_cores(self):
		"""The amount of logical cores in the CPU."""
		return psutil.cpu_count(logical=True)

	def __str__(self):
		return self.name
