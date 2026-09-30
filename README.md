# fm01

[![Crowdin](https://badges.crowdin.net/project-lumin/localized.svg)](https://crowdin.com/project/project-lumin)
[![GitHub Release](https://img.shields.io/github/v/release/project-lumin/closed-beta)](https://github.com/project-lumin/closed-beta/releases/latest)
![GitHub Stars](https://img.shields.io/github/stars/project-lumin/closed-beta?style=flat)
[![Discord](https://img.shields.io/discord/572077459189792769?label=discord
)](https://discord.gg/s8zBYQk)
![Top Language](https://img.shields.io/github/languages/top/project-lumin/closed-beta)
![Commit Activity](https://img.shields.io/github/commit-activity/m/project-lumin/closed-beta)

**fm01** is a Discord bot built to replace and improve upon its predecessor, *FightMan01 bot*. It's a versatile bot
featuring moderation, utility, and fun commands.

## Self-hosting
### Setup Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/fm01-bot/bot.git
   cd bot
   ```

2. **Create a `.env` file** in the project root (follow the `.env.example` template)

3. **Create a `config.yml` file** following the structure of `config.yml.example`

4. **Install PostgreSQL** (if not running with docker), then:
    - Create a user named `lumin` with the password you defined above
    - Create a database named `lumin`, preferably owned by the `lumin` user
    - Apply database migrations:
      ```bash
      uv run alembic upgrade head
      ```

5. **Run the bot**
   ```bash
   uv run main.py
   ```
   `uv run` will automatically set up the virtual environment for you and download required dependencies from
   pyproject.toml.

   If you want to run the bot in **debug mode**, change the `debug` value in `config.yml` to `true`.

## Using Docker

We've provided a Dockerfile and a compose file in the Github repo. You can simply run `docker compose up -d --build`
to start the bot in a Docker container. Make sure to follow until step 3, because the bot still needs
the `.env` and `config.yml` files to function properly.

## Versioning & Releasing

Version numbers follow **MAJOR.MINOR.PATCH**:

- **MAJOR** → Breaking changes (e.g., full module overhauls)
    - Resets MINOR and PATCH to `0`
- **MINOR** → New features or updated command sets
    - Resets PATCH to `0`
- **PATCH** → Bugfixes, internal tweaks, or localization updates

> ⚠️ Version suffixes (e.g., `-beta`, `-dev`) will **not** be present in the live bot.
