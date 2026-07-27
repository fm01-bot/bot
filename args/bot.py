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
		self.avatar = client.user.avatar.url
		self.name = client.user.name

	@property
	def provider(self):
		return VPSProvider()

	@property
	def processor(self):
		return CPU()

	cpu = processor

	@property
	def memory(self):
		return RAM()

	ram = memory

	@property
	def disk(self):
		return Disk()

	@property
	def boot_time(self):
		return FormatDateTime(datetime.datetime.fromtimestamp(psutil.boot_time()), "R")

	@property
	def network(self):
		return Network()

	@property
	def library_version(self):
		return discord.__version__
