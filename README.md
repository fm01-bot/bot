# Archival notice
This repository is now under [fm01-bot/bot](https://github.com/fm01-bot/bot) for the sake of easier orchestration and project management.

# fm01

[![Crowdin](https://badges.crowdin.net/project-lumin/localized.svg)](https://crowdin.com/project/project-lumin)
[![GitHub Release](https://img.shields.io/github/v/release/fm01-bot/bot)](https://github.com/fm01-bot/bot/releases/latest)
![GitHub Stars](https://img.shields.io/github/stars/fm01-bot/bot?style=flat)
[![Discord](https://img.shields.io/discord/572077459189792769?label=discord)](https://discord.gg/s8zBYQk)
![Top Language](https://img.shields.io/github/languages/top/fm01-bot/bot)
![Commit Activity](https://img.shields.io/github/commit-activity/m/fm01-bot/bot)

**fm01** is a Discord bot built to replace and improve upon its predecessor, *FightMan01 bot*. It's a versatile bot
featuring moderation, utility, and fun commands.

## Self-hosting
### Requirements

- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin (`docker compose`)
- [Git](https://git-scm.com/)
- A Discord bot token from the [Developer Portal](https://discord.com/developers/applications)
  (enable all three privileged intents: **Presence**, **Server Members**, and **Message Content**)
- Optional: [`just`](https://github.com/casey/just) for the shortcut recipes in `justfile`

### 1. Clone the repository

```bash
git clone https://github.com/fm01-bot/bot.git
cd bot
```

### 2. Create `.env`

```bash
cp .env.example .env
```

Fill in at least:

| Variable            | Description                                                       |
|---------------------|-------------------------------------------------------------------|
| `TOKEN`             | Your bot token                                                    |
| `DB_PASSWORD`       | Any strong password; used to create the PostgreSQL database       |
| `LAVALINK_PASSWORD` | Any strong password; shared between the bot and Lavalink          |

Leave `DB_HOST=db`, `LAVALINK_URI=http://lavalink:2333` and the Redis URLs as they are because they point to the Compose
services. `DEBUG_TOKEN` is only needed for debug mode, `SENTRY_DSN` is optional, and the clustering settings should
stay at `BOT_MODE=standalone` for self-hosting.

### 3. Create `config.yml`

```bash
cp config.yml.example config.yml
```

Then edit it:

- `owner_ids`: replace with your own Discord user ID(s)
- `emojis`: set to emoji markdown your bot can use (e.g. `<:check:123456789012345678>`)
- `log_channel_id`: a **private** channel ID for runtime error reports if a `SENTRY_DSN` was not configured in `.env`
- `modules`: the cogs to load (`"*"` loads all of them)

### 4. Start the bot

```bash
docker compose up -d --build
```

Database migrations are applied automatically on every bot start (unless `MIGRATE_ON_START=false`).

Check that it's running:

```bash
docker compose logs -f bot
```

### Managing the bot

| Task             | Command                         | `just` shortcut   |
|------------------|---------------------------------|-------------------|
| Start            | `docker compose up -d`          | `just up`         |
| Stop             | `docker compose down`           | `just down`       |
| Restart the bot  | `docker compose restart bot`    | `just restart bot`|
| View logs        | `docker compose logs -f bot`    | `just logs bot`   |
| Delete all data  | `docker compose down -v`        | `just destroy`    |

> [!WARNING]
> `docker compose down -v` / `just destroy` permanently deletes the database volume. Only use it in debug environments!

### Gateway proxy (production)

Production runs a [gateway proxy](https://github.com/Gelbpunkt/gateway-proxy) that holds the shard connections to
Discord. The bot connects to the proxy instead, so restarting it replays the guild state from the proxy's cache instead
of identifying every shard again (Discord allows one IDENTIFY per 5 seconds). Self-hosters don't need it: leave
`DISCORD_GATEWAY_URL` unset and the bot connects to Discord directly.

To enable it, set in `.env`:

```bash
COMPOSE_PROFILES=gateway-proxy
DISCORD_GATEWAY_URL=ws://gateway-proxy:7878
SHARD_COUNT=32          # must match the proxy; the bot refuses to start otherwise
MIGRATE_ON_START=false  # `just deploy` runs migrations itself
```

The proxy's shard count comes from Discord's recommendation; `curl localhost:7878/shard-count` prints it. Its intents
in `gateway-proxy.json` must match the bot's (`discord.Intents.all()`), since the bot's own IDENTIFY never reaches
Discord.

- `just deploy` checks out the latest release, then rebuilds and restarts only the bot; the proxy keeps the shards
  connected. `just deploy v0.9.0` deploys (or rolls back to) a given release, and `just deploy main` the testing branch.
- `just deploy-proxy` recreates the proxy, which reconnects every shard. Use it for proxy upgrades and shard count
  changes only, and update `SHARD_COUNT` first when the count changes.

Voice sessions don't survive a bot restart: players that were playing stop and have to be started again.

### Debug mode

Set `debug: true` in `config.yml` and provide `DEBUG_TOKEN` in `.env`. The bot will log in with the debug token and
log errors verbosely. `just debug` starts the stack (or restarts the bot if it's already running) and tails its logs.

## Development

Development tooling runs on the host via [`uv`](https://docs.astral.sh/uv/), but the bot itself still runs in Docker.

```bash
uv sync                     # install dev dependencies
uv run ruff format .        # format
uv run ruff check .         # lint
uv run ty check             # type check
uv run pytest               # tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for coding standards.

## Versioning & Releasing

Version numbers follow **MAJOR.MINOR.PATCH**:

- **MAJOR**: Breaking changes (e.g., full module overhauls)
    - Resets MINOR and PATCH to `0`
- **MINOR**: New features or updated command sets
    - Resets PATCH to `0`
- **PATCH**: Bugfixes, internal tweaks, or localization updates
