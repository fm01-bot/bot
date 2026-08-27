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

parser = argparse.ArgumentParser(prog="fm01")
parser.add_argument("--debug", action="store_true")

client: Bot = None  # type: ignore


def load_config() -> dict:
	try:
		with open("config.yml", "r", encoding="utf-8") as f:
			return yaml.safe_load(f)
	except FileNotFoundError:
		logging.warning("No config.yml file found, defaults are applied")
		return {"debug": None, "owner_ids": [], "modules": ["*"], "log_channel_id": None}


async def main(debug) -> None:
	logging.info("Starting the bot...")
	load_dotenv()

	global client
	config = load_config()
	client = Bot(config=config)
	client.debug = client.debug if client.debug is not None else debug

	if client.debug:
		token = os.getenv("DEBUG_TOKEN")
		client.logger.setLevel(logging.DEBUG)
		client.logger.info("Running in debug mode")
	else:
		token = os.getenv("TOKEN")
		client.logger.setLevel(logging.INFO)
		client.logger.info("Running in production mode")

	if token:
		await client.start(token)
	else:
		raise ValueError("no token provided")


if __name__ == "__main__":
	args = parser.parse_args()
	try:
		asyncio.run(main(args.debug))
	except:
		if client.db:
			asyncio.run(client.db.close())
		asyncio.run(client.close())
		client.logger.error("An error occurred while running the bot", exc_info=True)
