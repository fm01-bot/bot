import logging
import os

import winuvloop
from core.bot import Bot
from core.config import Config
from discord.utils import setup_logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


client: Bot | None = None


async def main() -> None:
	logger.info("Starting the bot...")
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
	setup_logging(level=logging.INFO, root=True)
	try:
		winuvloop.run(main())
	except KeyboardInterrupt:
		pass
