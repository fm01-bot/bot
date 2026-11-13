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

**Ledger**: `Ledger` in `cogs/economy.py`, the only code that changes `economy` balances. Each operation (`credit`, `debit`, `move`, `transfer`) is one transaction over row-locked accounts. Cash never goes negative; the bank goes negative only as **debt** (admin removals), and money credited while in debt pays it off first. A **Balance** is a member's `cash` and `bank` in one guild.

**List message**: a localized embed rendered with `CustomResponse.get_list`. Its first field is the **row template** (repeated per row), the remaining fields are the **empty state**, and `{page}`/`{pages}` work in the title, description and footer. Cogs pass rows, never edit rendered embeds. Optional parts of a message use a placeholder that is `None` when absent: the formatter drops that line, and a field left empty is dropped.

**Command key (`l10n_key`)**: the base under which a command's slash localization lives in `slash_localization/*.l10n.json`: `<key>-name`, `<key>-desc`, `<key>-usage`, `<key>-fallback` (a group's own callback, run as a subcommand) and `<key>-args-<param>-name|desc|<choice>`. It defaults to the command's name, and every subcommand has its own key, so subcommands with the same name are translated separately. The exception is `GroupCog` group names (`admin`, `economy`, `mod`, `voice`): discord.py builds those groups, so they use a top-level string. Built by `command_key` and read with `lookup` in `core/slash_localization.py`. `tests/test_slash_keys.py` fails when a key is missing. Groups need no description, because Discord never shows it.

## Decisions

**Config commands are temporary.** The `?!config` command tree (`cogs/config_subcommands/`) exists only until the web dashboard replaces it, after which the bot, backend, website and dashboard move into one monorepo. Fix bugs there and let it reuse shared modules when that costs nothing, but don't put architecture work into it (localizing its strings, restructuring, new tests).

**Cache invalidation uses Redis pub/sub.** Instances tell each other about changed guild settings over the existing Redis event bus (`core/clustering/`). Postgres `LISTEN/NOTIFY` triggers were considered, so outside writers such as the dashboard backend would invalidate caches automatically, and rejected until the monorepo move.

**Deploys restart the bot behind a gateway proxy.** Production runs [gateway-proxy](https://github.com/Gelbpunkt/gateway-proxy) (upstream image, pinned by digest, no fork for now), which keeps the shard connections open and replays a synthetic `READY` and `GUILD_CREATE`s from its cache when the bot connects, so a deploy sends no IDENTIFY. Resuming the old sessions from a fresh process was rejected: Discord sends no `READY` or `GUILD_CREATE` after a RESUME, so the new process starts with an empty cache. nirn-proxy was rejected because it only proxies REST. Voice sessions are not carried across restarts. Deploys stop the old bot before starting the new one; a blue-green handover would make both answer while they overlap, because the proxy sends every event to every client of a shard. Self-hosters connect to Discord directly.

**Message visibility is configured per message, not in code.** Whether a response is ephemeral (and whether it deletes itself) comes from its localization key, which the dashboard will make editable per message. Commands don't hard-code `ephemeral`, and the bot doesn't defer slash commands automatically (a deferred response's visibility can't be changed afterwards). Commands that can take longer than Discord's 3-second window (rank card, snapshots, `voice play`, `info ip`, `info template`) call `ctx.defer()` themselves, so their replies are public. Revisit deferring when the dashboard work starts.
