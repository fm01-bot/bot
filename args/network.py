import psutil


class Network:
	def __init__(self):
		self._network = psutil.net_io_counters()

	@property
	def sent(self):
		return round(self._network.bytes_sent / 1073741824, 2)

	@property
	def received(self):
		return round(self._network.bytes_recv / 1073741824, 2)

	def __str__(self):
		return f"{self.sent} GB / {self.received} GB"
