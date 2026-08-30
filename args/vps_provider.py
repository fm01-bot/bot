class VPSProvider:
	@property
	def name(self):
		return "Bladehost VPS"

	@property
	def url(self):
		return "https://www.bladehost.eu/"

	def __str__(self):
		return f"[{self.name}]({self.url})"
