import asyncio
import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
	fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
	x_args = context.get_x_argument(as_dictionary=True)
	if "url" in x_args:
		return x_args["url"]

	ini_url = config.get_main_option("sqlalchemy.url")
	if ini_url and ini_url != "driver://user:pass@localhost/dbname":
		return ini_url

	database_url = os.getenv("DATABASE_URL")
	if database_url:
		if database_url.startswith("postgresql://"):
			return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
		return database_url

	user = os.getenv("DB_USER", "lumin")
	password = os.getenv("DB_PASSWORD", "")
	host = os.getenv("DB_HOST", "localhost")
	port = os.getenv("DB_PORT", "5432")
	database = os.getenv("DB_NAME", "lumin_beta")

	auth = f"{quote_plus(user)}:{quote_plus(password)}"
	return f"postgresql+asyncpg://{auth}@{host}:{port}/{database}"


def run_migrations_offline() -> None:
	"""Run migrations in 'offline' mode.

	This configures the context with just a URL
	and not an Engine, though an Engine is acceptable
	here as well.  By skipping the Engine creation
	we don't even need a DBAPI to be available.

	Calls to context.execute() here emit the given string to the
	script output.
	"""
	url = get_url()
	context.configure(
		url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
	)

	with context.begin_transaction():
		context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
	context.configure(connection=connection, target_metadata=target_metadata)

	with context.begin_transaction():
		context.run_migrations()


async def run_async_migrations() -> None:
	"""In this scenario we need to create an Engine
	and associate a connection with the context.
	"""
	configuration = config.get_section(config.config_ini_section, {})
	configuration["sqlalchemy.url"] = get_url()

	connectable = async_engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

	async with connectable.connect() as connection:
		await connection.run_sync(do_run_migrations)

	await connectable.dispose()


def run_migrations_online() -> None:
	"""Run migrations in 'online' mode."""
	asyncio.run(run_async_migrations())


if context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()
