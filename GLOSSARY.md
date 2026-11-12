# Glossary

The words this codebase uses for its own concepts, and the decisions that shape it. Use these terms in code, issues and PRs.

## Terms

**Case**: one moderation action against a user in a guild: a warn, mute, kick or ban. Stored as a row in `cases`, identified by `case_id` (the ID of the message that triggered it). Represented by `Case` and its subclasses `Warn`, `Mute`, `Kick` and `Ban` in `cogs/mod/cases.py`.

**Active case**: a case that is still in force (`cases.active = true`). Closing a case makes it inactive or deletes it, depending on retention. An active case past its `expires` is *expired* until the scheduler closes it.

**Opening a case**: recording a new case and performing its Discord effect (timeout, kick, ban, DM). If the effect fails, the case is removed again.

**Closing a case**: ending an active case, either by hand (`unmute`, `unban`, `case remove`) or when it expires. Undoes the Discord effect (lifts the timeout or ban) and DMs the user. Closing an already inactive case has no side effects.

**Retention**: a guild's choice of what closing a case does: `keep` (mark it inactive, the default) or `delete` (remove the row). Stored in `mod_config.case_retention`. `case delete` always deletes, regardless of retention.

**Case store**: `CaseStore` in `cogs/mod/cases.py`, the only code that reads or writes `cases`. Commands and AutoMod open, close, edit and look up cases through it.

## Decisions

**Config commands are temporary.** The `?!config` command tree (`cogs/config_subcommands/`) exists only until the web dashboard replaces it, after which the bot, backend, website and dashboard move into one monorepo. Fix bugs there and let it reuse shared modules when that costs nothing, but don't put architecture work into it (localizing its strings, restructuring, new tests).

**Cache invalidation uses Redis pub/sub.** Instances tell each other about changed guild settings over the existing Redis event bus (`core/clustering/`). Postgres `LISTEN/NOTIFY` triggers were considered, so outside writers such as the dashboard backend would invalidate caches automatically, and rejected until the monorepo move.
