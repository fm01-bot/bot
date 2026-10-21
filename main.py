import logging
import os

import sentry_sdk
import winuvloop
from core.bot import Bot
from core.config import Config
from discord.utils import setup_logging
from dotenv import load_dotenv
from sentry_sdk.integrations.logging import LoggingIntegration

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

	sentry_dsn = os.getenv("SENTRY_DSN")
	if sentry_dsn and not client.debug:
		sentry_sdk.init(dsn=sentry_dsn, integrations=[LoggingIntegration(level=logging.INFO, event_level=None)])
		client._sentry_enabled = True

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
