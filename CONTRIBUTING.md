# Contributing to fm01

Thank you for your interest in contributing to fm01! Please review the guidelines and conventions below before opening a pull request.

---

## Prerequisites & Development Setup

Before running the bot locally, ensure you have:
- **Python**: 3.12 or 3.13 managed via [`uv`](https://docs.astral.sh/uv/)
- **Docker**: For running the PostgreSQL database container
- **Command Runner**: [`just`](https://just.systems/man/en/pre-built-binaries.html) (or `uv run just`)
- **Discord Application**: A bot created on the [Discord Developer Portal](https://discord.com/developers/applications) with privileged intents enabled and invited to a development/testing server

### Setup Steps

1. **Environment Configuration**:
   - Copy `.env.example` to `.env` and fill in your bot token and database credentials:
     ```bash
     cp .env.example .env
     ```
   - Copy `config.yml.example` to `config.yml` and ensure `debug: true` is set.

2. **Start the Development Environment**:
   Run the debug recipe to sync dependencies via `uv`, start the database container, apply Alembic migrations, and launch the bot:
   ```bash
   just debug
   ```

3. **Stopping Containers**:
   Once finished, stop all active containers:
   ```bash
   just down
   ```

---

## Architecture & Code Conventions

### 1. Context & Hybrid Commands
- The bot subclasses `commands.Context` to handle automatic localization.
- Always import `Context`, `command`, and `group` from `core`:
  ```python
  from core import Context, command, group
  ```
- Commands are hybrid by default (usable via prefix or slash command). Avoid using raw `discord.ext.commands.command` or `discord.app_commands.command` directly unless strictly necessary.

### 2. Localization
- The default language is **English**. All new commands, messages, and parameters must provide English strings.
- Localization strings are split into two directories:
  - `localization/en.l10n.json`: User-facing responses sent via `ctx.send("key", ...)`.
  - `slash_localization/en.l10n.json`: Slash command names and descriptions.
- Read more about [`discord-localization`](https://pypi.org/project/discord-localization).
- For non-English translations, please contribute via our [Crowdin project](https://crowdin.com/project/project-lumin).

### 3. Argument Classes (`args/`)
- Formatting variables passed into localized messages must use custom argument dataclasses (e.g., `args.User`, `args.Role`, `args.Guild`).
- New argument classes must include a `from_<object>` classmethod (e.g., `User.from_user(...)`).
- These classes sanitize data and provide safe properties (e.g., `User.avatar` returns a URL string rather than an `Asset` object).

### 4. Helpers (`helpers/`)
- Project-wide reusable utilities live in the `helpers/` directory.
- Cog-specific utilities should stay within their cog file (e.g., `ShopItem` and `EconomyHelper` in `cogs/economy.py`).
- Prefer standalone functions over creating unnecessary utility classes.

### 5. Docstring Style
- Follow **Google-style docstrings**.
- All non-command functions and public helper methods should include docstrings unless completely self-explanatory.

---

## Code Quality & Verification

Always run all formatters, linters, type checks, and tests before opening a pull request:

```bash
# Format code using Ruff
just format

# Lint code using Ruff
just lint

# Run static type checking
uv run ty check

# Run automated tests
just test
```

---

## Pull Requests & AI Contributions Policy

- **Understanding Over Generation**: AI assistance is permitted, but blind "vibe-coding" is not. Do not submit pull requests containing code you do not fully understand or cannot explain during review.
- **Reference Documentation**: An [`AGENTS.md`](file:///c:/Users/Pearoo/Documents/GitHub/bot/AGENTS.md) file is provided in the repository with an overview of codebase conventions for both human and agentic contributors.
- **Ownership**: You are responsible for every line of code in your pull request. Ensure all contributions follow existing project patterns, pass lint and type checks, and include corresponding tests and localization keys where applicable.

---

> Questions or need help? Reach out to **@pearoo** on Discord.
