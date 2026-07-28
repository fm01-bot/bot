import datetime

import discord
import psutil

from args.cpu import CPU
from args.disk import Disk
from args.format_date_time import FormatDateTime
from args.network import Network
from args.ram import RAM
from args.vps_provider import VPSProvider


class Bot:
	def __init__(self, client: discord.Client):
		self.avatar = client.user.avatar.url if client.user is not None and client.user.avatar is not None else None
		self.name = client.user.name if client.user is not None else None

	@property
	def provider(self):
		"""The company that provides our servers."""
		return VPSProvider()

	@property
	def processor(self):
		"""The CPU the bot uses."""
		return CPU()

	cpu = processor

	@property
	def memory(self):
		"""The RAM the bot uses."""
		return RAM()

	ram = memory

	@property
	def disk(self):
		"""The server's disk usage."""
		return Disk()

	@property
	def boot_time(self):
		"""The time since the server was booted up."""
		return FormatDateTime(datetime.datetime.fromtimestamp(psutil.boot_time()), "R")

	@property
	def network(self):
		"""Analytics about our network."""
		return Network()

	@property
	def library_version(self):
		"""The version of discord.py the bot is running on."""
		return discord.__version__
