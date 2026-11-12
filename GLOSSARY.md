# Glossary

The words this codebase uses for its own concepts, and the decisions that shape it. Use these terms in code, issues and PRs.

## Terms

**Case**: one moderation action against a user in a guild: a warn, mute, kick or ban. Stored as a row in `cases`, identified by `case_id` (the ID of the message that triggered it). Represented by `Case` and its subclasses `Warn`, `Mute`, `Kick` and `Ban` in `cogs/mod/cases.py`.

**Active case**: a case that is still in force (`cases.active = true`). Closing a case makes it inactive or deletes it, depending on retention. An active case past its `expires` is *expired* until the scheduler closes it.

**Opening a case**: recording a new case and performing its Discord effect (timeout, kick, ban, DM). If the effect fails, the case is removed again.

**Closing a case**: ending an active case, either by hand (`unmute`, `unban`, `case remove`) or when it expires. Undoes the Discord effect (lifts the timeout or ban) and DMs the user. Closing an already inactive case has no side effects.

**Retention**: a guild's choice of what closing a case does: `keep` (mark it inactive, the default) or `delete` (remove the row). Stored in `mod_config.case_retention`. `case delete` always deletes, regardless of retention.

**Case store**: `CaseStore` in `cogs/mod/cases.py`, the only code that reads or writes `cases`. Commands and AutoMod open, close, edit and look up cases through it.

**Guild setting**: a per-guild configuration value (prefix, locale override, case retention, ...) behind a `GuildSetting` in `core/settings.py`. Read with `get` (or `cache` on hot synchronous paths), write with `set`; code that writes with targeted SQL calls `changed` afterwards instead. Writing persists it and announces an `INVALIDATE_SETTING` event so other bot instances reload it; callers never touch caches or the event bus. Settings with a meaningful default row (prefix, retention) create it from the column defaults on first load; feature settings (log, AutoMod, join/leave, leveling) treat a missing row as "not configured".

**Preloaded setting**: a guild setting whose values for every guild are loaded at startup (prefix, locale override), so synchronous code can read `cache`. Other settings load on first use.

**Locale override**: a guild's chosen bot language (`guild_locale_overrides`), set with `?!config locale`. It takes precedence over the user's Discord client locale and the guild's preferred locale; see `core/locale.py`.

**Log configuration**: a guild's event logging setup (`log` table, `LogConfig`, `LogSettings` in `cogs/log.py`): on/off, default channel, per-event channels, webhook and enabled modules. `modules = {'*'}` (the column default) means every module, including ones added later.

**Message buffering**: the bot keeps recent message content for guilds whose log configuration has message deletion or edit logging on (`Bot.message_logging_guilds`), so deleted and edited messages can be logged. Maintained automatically from the log configuration.

## Decisions

**Config commands are temporary.** The `?!config` command tree (`cogs/config_subcommands/`) exists only until the web dashboard replaces it, after which the bot, backend, website and dashboard move into one monorepo. Fix bugs there and let it reuse shared modules when that costs nothing, but don't put architecture work into it (localizing its strings, restructuring, new tests).

**Cache invalidation uses Redis pub/sub.** Instances tell each other about changed guild settings over the existing Redis event bus (`core/clustering/`). Postgres `LISTEN/NOTIFY` triggers were considered, so outside writers such as the dashboard backend would invalidate caches automatically, and rejected until the monorepo move.

**Message visibility is configured per message, not in code.** Whether a response is ephemeral (and whether it deletes itself) comes from its localization key, which the dashboard will make editable per message. Commands don't hard-code `ephemeral`, and the bot doesn't defer slash commands automatically (a deferred response's visibility can't be changed afterwards). Revisit deferring when the dashboard work starts.
