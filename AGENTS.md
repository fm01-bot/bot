# fm01 Discord bot codebase outline

## 1. Project setup

- This project uses the `uv` package manager.
- Python 3.12 and 3.13 are supported.
- All dependencies can be seen in `pyproject.toml`.
- To run the bot in the virtual environment, use `uv run main.py`.
- The project consists of a runner file (`main.py`) and four main directories (`core`, `args`, `cogs`, `helpers`).
- We use `ty` for type checking and `ruff` for formatting.

## 2. Project goal

- This is the code for a large-scale bot.
- The bot can support multiple languages.
- It is an all-in-one, open source bot.

## 3. Modules

### Helpers

Helpers are utilities that are used multiple times in the whole project or in one cog. If it is a project-wide helper, it should be placed under the `helpers/` directory with a short and descriptive name. Unless needed, don't add a class in any of the folders.

Because users usually ask for a specific feature, you usually won't need a helper. You can easily create a standalone function in a cog file for something that you only need once.

### Core

The core directory is the bare minimum required for the bot to function properly, even if there are no cogs loaded. It includes the bot class (`bot.py`) alongside some formatting classes (`argument.py`, `command.py`).

The bot can be configured before runtime using a `Config` object (`config.py`). You can get configuration keys using the `Config.get()` method. You can edit the configuration using the `config.yml` file.

The project uses a subclassed `commands.Context` class in order to support localization automatically at every message send. This takes advantage of the `custom_response` helper, which is used to actually retreive localized messages from the `localization/` and `slash_localization/` directories. This subclass can be found in `context.py`.

Commands are hybrid, which means they can be used with prefixes (e.g. `?!` or `?`) or with Slash Commands. However, because we also localize slash commands, we have to subclass `commands.HybridCommand` and its corresponding decorator in order to automatically retreive localized strings without the need to manually type `@app_commands.rename` or `@app_commands.description` for every command. This hybrid command subclass can be found in `hybrid.py`.

Slash commands need an automatic localizer class, which takes strings from `slash_localization/` and uses them to localize the slash command. This can be found in `slash_localization.py`.

### Cogs

Cogs are what regular users would call "modules". Each cog (each `.py` file in the `cogs/` folder) contains a collection of commands related to a specific functionallity. For example, the `mod` cog contains moderation-related commands such as `ban`, `kick`, and `warn`, and also contains the commands related to viewing case information.

- **Admin:** administrative commands that can only be used by the developers, i.e. reloading cogs.
- **AFK:** the `?!afk` command and its related listeners.
- **Basic:** a collection of basic, general-purpose commands.
- **Economy:** this contains an `EconomyHelper` and a `ShopItem`, which are classes that you can use to retreive a user's balance or to convert a database shop item into an object that you can later use during formatting.
- **Giveaway:** commands and event loops related to giveaways.
- **Help:** contains the `?!help` command, a subclass of `discord.ext.commands.HelpCommand`.
- **Info:** commands under the `?!info` group, such as `?!info @user`, `?!info server`, etc.
- **Log:** commands and listeners for server logging.
- **Mod:** commands for server moderation and case management (each moderation action creates a case).
- **Say:** commands under the `?!say` group.
- **Setup:** commands for configuring the bot's basic functionality.
- **Snapshot:** a snapshot is a backup of the server, this module creates and restores server snapshots.
- **Status:** basic cog for switching the bot's status.

### Args

Because the bot uses localization, we need to provide a way to include variables within responses. Every file in `args/` is a dataclass that we can convert `discord.py` objects into so that we can later pass those objects into the custom response functions (usually as kwargs in `ctx.send()`).

## 4. Response directives

- Always give short, direct and concise answers to the user.
- Don't ask follow-up questions.
- Be objective, avoid social niceties, reassurance or filler.
- Operate under a mandatory "Zero Trust" approach, where you always override training data with live web searches for topics requiring up-to-date information.
- Run negative audits (counter-search) to test your findings before presenting them.
- The project should not be filled with "AI slop", and if the user asks for something that sounds like vibe-coding new features without having necessary prior knowledge about how Python works, you should politely decline and explain why it is not a good idea.
- Try to minimize output tokens if possible.
- If the user says something vague, ask for clarification instead of hallucinating instructions.

Your prime directive is to provide an accurate, unvarnished reality, ensuring every output is factually grounded and free of distortion.