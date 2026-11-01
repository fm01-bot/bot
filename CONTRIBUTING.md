# Contributing to fm01

Thank you for your interest in contributing to fm01! This document provides instructions and guidelines for setting up your local environment, adhering to project conventions, and submitting pull requests.

All contributors are expected to uphold the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Table of Contents

- [Prerequisites & Development Setup](#prerequisites--development-setup)
  - [Prerequisites](#prerequisites)
  - [Setup Steps](#setup-steps)
  - [Task Runner (`just`) Recipes](#task-runner-just-recipes)
- [Architecture & Conventions](#architecture--conventions)
  - [1. Context & Hybrid Commands](#1-context--hybrid-commands)
  - [2. Localization System](#2-localization-system)
  - [3. Argument Dataclasses (`args/`)](#3-argument-dataclasses-args)
  - [4. Helpers & Utilities (`helpers/`)](#4-helpers--utilities-helpers)
  - [5. Database & Migrations (`migrations/`)](#5-database--migrations-migrations)
  - [6. Clustering & Distributed Services](#6-clustering--distributed-services)
- [Code Quality & Standards](#code-quality--standards)
  - [Formatting & Linting](#formatting--linting)
  - [Type Checking](#type-checking)
  - [Docstring Style](#docstring-style)
  - [Testing](#testing)
- [Contribution Workflow](#contribution-workflow)
  - [Branching Strategy](#branching-strategy)
  - [Commit Messages](#commit-messages)
  - [Pre-Commit Hooks (`prek`)](#pre-commit-hooks-prek)
  - [Pull Request Checklist](#pull-request-checklist)
  - [AI Contributions Policy](#ai-contributions-policy)

---

## Prerequisites & Development Setup

### Prerequisites

- **Python**: 3.12 or 3.13 managed via [`uv`](https://docs.astral.sh/uv/)
- **Docker & Docker Compose**: For containerized dependencies (PostgreSQL 16, Redis 7, Lavalink v4)
- **Task Runner**: [`just`](https://just.systems/) (recommended) or `uv run just`
- **Discord Application**: A bot created on the [Discord Developer Portal](https://discord.com/developers/applications) with all Privileged Gateway Intents enabled (Server Members, Message Content, Presence)

### Setup Steps

1. **Clone the repository**:

   ```bash
   git clone https://github.com/fm01-bot/bot.git
   cd bot
   ```

2. **Configure environment variables**:

   ```bash
   cp .env.example .env
   ```

   Fill in your Discord bot token (`DEBUG_TOKEN` and/or `TOKEN`), database credentials, and optional service keys.

3. **Configure bot settings**:

   ```bash
   cp config.yml.example config.yml
   ```

   Set `debug: true` for local development. Add your Discord user ID to `owner_ids` to test admin commands.

4. **Launch dependencies & run in debug mode**:
   Using `just`:

   ```bash
   just debug
   ```

   This synchronizes dependencies via `uv`, starts PostgreSQL (`db`), applies database migrations with Alembic, and starts the bot.

   Alternatively, start services and run manually:

   ```bash
   docker compose up -d db redis lavalink
   uv sync
   uv run alembic upgrade head
   docker compose up -d bot
   ```

5. **Stop background containers when finished**:
   ```bash
   just down
   ```

### Task Runner (`just`) Recipes

| Command                 | Action                                                           |
| :---------------------- | :--------------------------------------------------------------- |
| `just debug`            | Sync dependencies, start database, run migrations, and start bot |
| `just format`           | Format code using `ruff format`                                  |
| `just lint`             | Lint code using `ruff check`                                     |
| `just test`             | Run test suite using `pytest`                                    |
| `just migrate`          | Run database migrations up to HEAD                               |
| `just up` / `just down` | Start or stop Docker Compose service stack                       |
| `just logs`             | Docker Compose container logs                                    |

---

## Architecture & Conventions

### 1. Context & Hybrid Commands

All commands should be hybrid (usable both as a prefix command e.g. `?!ping` and as a slash command `/ping`) unless strictly developer-only or message-only.

- Always import `Context`, `command`, and optionally, `group` from `core`:

  ```python
  from core import Context, command, group
  from discord.ext import commands


  class MyCog(commands.Cog):
  	def __init__(self, bot):
  		self.bot = bot

  	@command()
  	async def mycommand(self, ctx: Context) -> None:
  		await ctx.send("mycommand.success")
  ```

- Do not import `command` or `group` directly from `discord.ext.commands` or `discord.app_commands` unless building non-hybrid low-level utilities.

### 2. Localization System

The codebase strictly enforces localized responses:

- **User-facing messages**: Stored in `localization/en.l10n.json`.
  Send messages using the localization key path:
  ```python
  await ctx.send("moderation.kick.success", member=member, reason=reason)
  ```
  Keys support dot notation (e.g. `category.action.status`). Add keyword arguments to insert variables for templating.
- **Slash command names and descriptions**: Stored in `slash_localization/en.l10n.json`.
  Follow the naming scheme:
  - Command name: `<command>-name`
  - Command description: `<command>-desc`
  - Parameter name: `<command>-args-<parameter>-name`
  - Parameter description: `<command>-args-<parameter>-desc`
- **English-Only Policy in Repository**: Only submit English (`en`) strings in PRs. Non-English translations are managed collaboratively through our [Crowdin Project](https://crowdin.com/project/project-lumin).
- **No Hardcoded Strings**: Never hardcode English strings directly in commands, views, or embed definitions.

### 3. Argument Dataclasses (`args/`)

When variables are passed into `ctx.send("key", ...)`, they are formatted against template placeholders (e.g. `{user.mention}`).

- Built-in types (`discord.User`, `discord.Member`, `discord.Role`, `discord.Guild`, `discord.TextChannel`, `discord.Emoji`, `wavelink.Playable`) are automatically converted to their respective dataclasses in `args/` via `CustomResponse`.
- When creating a new format argument class, place it in `args/` with `@dataclass(slots=True)` and include a `from_<object>` classmethod.
- Expose safe, sanitised string representations and properties rather than raw Discord objects.

### 4. Helpers & Utilities (`helpers/`)

- Reusable, cross-module logic belongs in `helpers/` (e.g., `helpers/convert.py`, `helpers/cli_parser.py`, `helpers/leveling.py`).
- Cog-specific utilities should stay private to that cog (e.g. `EconomyHelper` and `ShopItem` in `cogs/economy.py`).
- Favor standalone functions over unnecessary single-instance classes.

### 5. Database & Migrations (`migrations/`)

- The project uses PostgreSQL with asynchronous access via `asyncpg` (`bot.db`).
- Any database schema changes (tables, columns, indexes, constraints) must include an Alembic migration:
  ```bash
  uv run alembic revision -m "add_feature_table"
  ```
  Implement both `upgrade()` and `downgrade()` in the generated migration file under `migrations/versions/`.
- Test migrations locally before submitting:
  ```bash
  uv run alembic upgrade head
  uv run alembic downgrade -1
  uv run alembic upgrade head
  ```

### 6. Clustering & Distributed Services

- The bot supports both standalone execution and multi-process clustering with Redis-backed state stores, message buffers, shard coordination, and event buses (`core/clustering/`).
- State mutations that affect other clusters (such as prefix updates or audit log configuration changes) must publish cache invalidation events via `bot.event_bus.publish("fm01:events", ...)`.

---

## Code Quality & Standards

### Formatting & Linting

We enforce strict formatting and linting via [Ruff](https://docs.astral.sh/ruff/):

- **Indentation**: Tabs (`\t`)
- **Line Length**: 120 characters max
- **Quotes**: Double quotes (`"`)

Run the formatters and linters:

```bash
# Auto-format files
uv run ruff format . # `just format`

# Check lint rules and auto-fix issues where possible
uv run ruff check --fix . # `just lint`
```

### Type Checking

We use `ty` for static type analysis:

```bash
uv run ty check
```

Ensure all new functions and methods have clear type hints.

### Docstring Style

- Follow **Google-style docstrings**.
- All public helper functions, classes, and non-trivial methods require docstrings explaining arguments, returns, and raised exceptions.

### Testing

Tests live in `tests/` and use `pytest` with `pytest-asyncio`:

```bash
# Run the test suite
uv run pytest
```

When introducing new features or fixing bugs, write unit tests in `tests/` leveraging `AsyncMock` and `MagicMock` to isolate Discord API interactions and database calls.

---

## Contribution Workflow

### Branching Strategy

- **`main`**: Production-ready releases.
- **`dev`**: Active development branch. All feature branches and pull requests should target `dev`.
- Branch naming: `feature/<short-desc>`, `fix/<short-desc>`, `refactor/<short-desc>`.

### Commit Messages

Use clear, descriptive commit messages adhering to [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: add level role reward multipliers`
- `fix: handle edge case in timeout duration parsing`
- `refactor: simplify ticket transcript generation`
- `test: add unit tests for automod invite detection`
- `docs: update setup instructions in README`

### Pre-Commit Hooks (`prek`)

This project supports `prek` for fast git hook validation (`prek.toml`). If you have `prek` installed, configure hooks via:

```bash
prek install
```

### Pull Request Checklist

Before submitting your PR, ensure:

1. [ ] Dependencies sync cleanly (`uv sync`).
2. [ ] Code is formatted with Ruff (`uv run ruff format --check .`).
3. [ ] Ruff lint checks pass without errors (`uv run ruff check .`).
4. [ ] Type checking passes (`uv run ty check`).
5. [ ] All unit tests pass (`uv run pytest`).
6. [ ] Any new strings are added to `localization/en.l10n.json` and `slash_localization/en.l10n.json`.
7. [ ] Database schema changes include valid Alembic migration scripts.
8. [ ] Pull request targets the `dev` branch.

### AI Contributions Policy

- **Understanding & Ownership**: You are 100% accountable for any code submitted, including code written with AI assistance. Never submit "vibe-coded" solutions that you cannot explain or maintain.
- **Conventions & Consistency**: Generated code must strictly follow repository conventions (tabs, 120 char limit, `core` hybrid imports, English-only localization, `args/` dataclasses).
- **Check Passing**: PRs that fail linting, type checks, or tests will not be reviewed.

---

Need assistance or have architectural questions? Join our Discord server or reach out to **@pearoo**.
