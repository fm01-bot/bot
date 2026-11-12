# fm01 Codebase Agent Guidelines (`AGENTS.md`)

This document defines architectural standards, technical conventions, and operational directives for AI agents and automated tools working on the fm01 Discord bot codebase.

---

## 1. Environment & Technical Stack

- **Runtime**: Python `>=3.12,<3.14`
- **Package & Environment Manager**: `uv`
- **Core Framework**: `discord.py >=2.3.2`, `discord-localization >=1.1.5`
- **Data & Storage**: PostgreSQL 16 (`asyncpg`), Alembic (`migrations/`), Redis 7 (`redis-py`)
- **Media & Voice**: Lavalink v4 (`wavelink >=3.5.2`), Pillow (`pillow >=11.3.0`)
- **Code Quality**:
  - Linter & Formatter: `ruff` (indent: tabs `\t`, line-length: 120, quotes: double `"`)
  - Type Checker: `ty` (`uv run ty check`)
  - Test Suite: `pytest` with `pytest-asyncio` (`uv run pytest`)
- **Task Runner**: `just` (see `justfile`)

---

## 2. Repository Layout & Module Index

```
.
├── args/                 # Dataclasses wrapping discord.py objects for safe string formatting
├── assets/               # Static assets (fonts, images, badges)
├── cogs/                 # Modular command sets and event listeners (extensions)
│   └── config_subcommands/ # Modular CLI dispatchers for the ?!config command tree
├── core/                 # Framework core, custom abstractions, and clustering
│   └── clustering/       # Distributed shard coordination, Redis event bus, state stores
├── helpers/              # Cross-module utility functions and algorithmic helpers
├── localization/         # User-facing message templates (JSON format)
├── migrations/           # Database schema versioning via Alembic
├── slash_localization/   # Slash command metadata (command names, param descriptions)
├── tests/                # Automated pytest test suites and mocking fixtures
├── justfile              # Automation recipes for development, linting, and testing
├── pyproject.toml        # Project dependencies, tool settings, and metadata
└── main.py               # Bot entry point and runtime initializer
```

### Module Breakdown

#### `core/` (Foundational Abstractions)

- `bot.py` (`Bot`): Subclasses `commands.AutoShardedBot`. Manages database connection pool (`self.db`), prefix cache, clustering coordinator, event bus, message logging buffer, and global error handling.
- `context.py` (`Context`): Subclasses `commands.Context`. Overrides `send()` to automatically intercept localization keys and format variables via `CustomResponse`.
- `hybrid.py` (`command`, `group`, `HybridCommand`, `HybridGroup`): Custom command decorators automatically linking commands to the slash command localization tree.
- `slash_localization.py` (`SlashCommandLocalizer`): Subclasses `app_commands.Translator` to dynamically translate slash command names and descriptions from `slash_localization/`.
- `argument.py` & `command.py`: Serialization helpers converting Discord contexts/commands for formatted messages.
- `config.py` (`Config`): Runtime configuration parser loading `config.yml`.
- `settings.py` (`GuildSettings`, `GuildSetting`): Cached per-guild settings with cross-instance invalidation. Register feature settings here instead of keeping a cog-level cache.
- `locale.py` (`resolve_locale`): The single rule for which locale a response uses.
- `clustering/`: Shard coordination (`ShardCoordinator`), session resumption (`SessionPersister`), distributed state (`StateStore`), event pub/sub (`EventBus`), and audit log buffers (`MessageBuffer`).

#### `args/` (Safe String Formatting Wrappers)

Dataclasses decorated with `@dataclass(slots=True)` that wrap Discord objects (e.g. `User`, `Member`, `Guild`, `Role`, `TextChannel`, `Emoji`, `Track`).

- Must provide a `from_<object>` classmethod (e.g. `User.from_user(user)`).
- Exposes sanitised properties (strings, URLs, IDs) rather than raw Discord internal models so localization strings can cleanly reference attributes (e.g. `{member.mention}`, `{user.name}`).

#### `helpers/` (Shared Utility Modules)

- `custom_response.py` (`CustomResponse`): Core localization interpolation engine. Translates dot-delimited message keys, formats embed dictionaries, and maps Discord models via `KWARG_MAPPING` to `args/` wrappers.
- `cli_parser.py`: Robust command-line parsing engine powering the `?!config` tree.
- `convert.py`: Converters for time durations, colors, booleans, and channel lookups.
- `leveling.py` & `level_card.py`: Level math algorithms and Pillow-based rank card canvas generation.
- `regex.py` & `random_helper.py`: Compiled pattern matching and randomization helpers.

#### `cogs/` (Feature Modules)

- `admin.py`: Developer commands (extension reloading, evaluation, synchronization).
- `afk.py`: AFK presence tracking, auto-nicknames, and mention notifications.
- `automod.py`: Server protection rule engine (invite blocking, links, caps, spam, word filters).
- `basic.py`: Core utility commands (`ping`, `uptime`).
- `config.py` & `config_subcommands/`: Hierarchical CLI server settings management (`automod`, `join`, `leave`, `level`, `log`, `prefix`, `ticket`).
- `economy.py`: Virtual economy system (`EconomyHelper`, `ShopItem`, balances, transactions).
- `help.py`: Dynamic help system subclassing `commands.HelpCommand` with paginated views.
- `info.py`: Server, user, role, and bot diagnostic inspection commands.
- `join_leave.py`: Welcome/leave announcement handlers and autorole assignment.
- `level.py`: Message XP awarding, rank card generator (`?!level`), leaderboards (`?!levels`), and level role rewards.
- `log.py`: Server event audit logger (message edits/deletions, member changes, channel updates).
- `mod/`: Moderation command suite (`ban`, `kick`, `mute`, `warn`, `case`). `mod/cases.py` is the Case module: `CaseStore` owns every query on `cases`, retention, and expiry.
- `say.py`: Echo and Minecraft achievement message generators.
- `setup.py`: Interactive first-time server setup helper.
- `snapshot.py`: Guild structural backup and restoration system.
- `state_sync.py`: Distributed cluster sync listeners (invalidating prefix/log caches across instances).
- `status.py`: Presence and bot activity status cycler.
- `ticket.py`: Interactive support ticket system with components, modals, and transcript export.
- `voice.py`: Lavalink v4 music playback controls via Wavelink.

---

## 3. Mandatory Architectural & Coding Rules

### 1. Command Definition

- Always import `Context`, `command`, and optionally, `group` from `core`:
  ```python
  from core import Context, command, group
  from discord.ext import commands
  ```
- All commands must be hybrid commands by default unless strictly restricted to developer or guild-event only.
- Do not import `command` or `group` directly from `discord.ext.commands` or `discord.app_commands`.

### 2. Localization First

- **Zero Hardcoded Strings**: Never hardcode user-facing text, error messages, or default strings in Python files.
- **Message Responses**: Call `ctx.send("path.to.key", **kwargs)` using dot notation. Strings must be placed in `localization/en.l10n.json`.
- **Slash Command Metadata**: Slash command names and descriptions must be registered in `slash_localization/en.l10n.json`:
  - Command Name: `<command>-name`
  - Command Description: `<command>-desc`
  - Parameter Name: `<command>-args-<parameter>-name`
  - Parameter Description: `<command>-args-<parameter>-desc`
- **English-Only Policy**: Add or modify only English (`en`) localizations. Non-English localizations are managed through Crowdin; do not generate AI translations in other languages.

### 3. Argument Passing & Formatting

- Pass Discord models directly into `ctx.send("key", user=user, guild=guild)`. The `CustomResponse` pipeline will automatically map them using `KWARG_MAPPING` to their corresponding `args/` dataclass.
- If introducing custom variables or non-standard objects, create a new `@dataclass(slots=True)` wrapper in `args/` with a `from_<object>` classmethod.

### 4. Helper Scope

- Only place utilities in `helpers/` if they are reused across multiple cogs or core subsystems.
- Cog-specific models or helper functions must remain within their respective cog file.

### 5. Database Schema & Migrations

- All database operations use `self.bot.db` (`asyncpg.Pool`).
- Any table or column addition, modification, or removal requires an Alembic migration under `migrations/versions/`.
- Ensure migrations include both `upgrade()` and `downgrade()` steps.

### 6. Code Style & Typing

- **Indentation**: Tabs (`\t`), never spaces.
- **Line Length**: Max 120 characters.
- **Quotes**: Double quotes (`"`).
- **Docstrings**: Google-style docstrings for public classes and non-command functions.
- **Typing**: Use Python 3.12+ syntax (e.g. `X | Y`, `type Alias = ...`). All code must pass `uv run ty check`.

---

## 4. Mandatory Verification Pipeline

Before completing any task, running checks is mandatory. Execute the following commands in order:

```bash
# 1. Check code formatting (must produce zero diffs)
uv run ruff format --check .

# 2. Run Ruff linter (must produce zero warnings/errors)
uv run ruff check .

# 3. Static type analysis (must pass cleanly)
uv run ty check

# 4. Automated tests (all tests must pass)
uv run pytest
```

If any check fails, fix the underlying issue immediately before presenting results.

---

## 5. Agent Operational & Behavioral Directives

- **Conciseness**: Give short, direct, and concise answers. Avoid filler, small talk, social pleasantries, and reassurance.
- **Zero Trust**: Always verify codebase facts against the current repository files before acting. Never rely on unverified assumptions or hallucinated APIs.
- **Negative Audits**: Counter-search and cross-verify findings against actual implementations before committing changes.
- **No Follow-up Questions**: Do not ask unprompted follow-up questions unless the user request is genuinely blocked or critically ambiguous.
- **Anti-Vibe-Coding / Anti-AI-Slop**: Reject unprincipled code generation. Maintain strict architectural discipline, appropriate typing, modular structure, and error resilience.
- **Token Efficiency**: Strive to minimize output tokens while conveying complete, accurate technical solutions.
- **Prime Directive**: Provide an accurate, unvarnished reality grounded in verified code.

---

## Agent skills

### Issue tracker

GitHub Issues on `fm01-bot/bot`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Reuses existing repo labels where possible (`question`, `help wanted`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` holds both the domain terms and the settled decisions (no `docs/adr/`). See `docs/agents/domain.md`.
