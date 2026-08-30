from core.config import Config
import argparse
import asyncio
import logging
import os

import yaml
from core.bot import Bot
from discord.utils import setup_logging
from dotenv import load_dotenv

setup_logging(level=logging.INFO, root=True)

try:
	import uvloop  # type: ignore

	asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
	if os.name == "nt":
		asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
	else:
		asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

client: Bot | None = None


async def main() -> None:
	logging.info("Starting the bot...")
	load_dotenv()

	global client
	config = Config.from_file()
	client = Bot(config=config)

	if client.debug:
		token = os.getenv("DEBUG_TOKEN")
		client.logger.setLevel(logging.DEBUG)
		client.logger.info("Running in debug mode")
	else:
		token = os.getenv("TOKEN")
		client.logger.setLevel(logging.INFO)
		client.logger.info("Running in production mode")

	if not token:
		raise ValueError("no token provided")

	async with client:
		await client.start(token)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass
