import argparse
import asyncio
import logging
import os

from core.bot import Bot
from core.log import logger
from dotenv import load_dotenv

try:
	import uvloop  # type: ignore

	asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())  # type: ignore
except ImportError:
	if os.name == "nt":
		asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
	else:
		asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

parser = argparse.ArgumentParser(prog="fm01")
parser.add_argument("--debug", action="store_true")

client: Bot = None  # type: ignore


async def main(debug) -> None:
	logger.info("Starting the bot...")
	load_dotenv()

	global client
	client = Bot()
	client.debug = debug or bool(int(os.getenv("DEBUG", False)))

	if client.debug:
		token = os.getenv("DEBUG_TOKEN")
		logger.debug("Running in debug mode")
		client.logger.setLevel(logging.DEBUG)
	else:
		token = os.getenv("TOKEN")
		logger.info("Running in production mode")
		client.logger.setLevel(logging.INFO)

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
