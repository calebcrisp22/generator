# Generator Bot — Discord Account Generator

## Overview
A Python (discord.py 2.4) Discord bot that manages tiered "account generation" (free / free+ / premium), stock, timed drops, subscriptions, invite tracking, and owner admin tooling. Built as a Cog-based bot with a lightweight JSON-file persistence layer — no external database required.

## Running the bot
- Workflow **"Discord Bot"** runs `python3 main.py` and is set to auto-start.
- Requires two secrets (already configured in this Repl): `BOT_TOKEN` (Discord bot token) and `OWNER_ID` (your Discord user ID — grants full owner-only command access).
- On startup the bot loads all cogs (`generate`, `stock`, `drops`, `subscriptions`, `admin`, `profile`, `blacklist`, `stats`, `utility`) and syncs ~45 slash commands globally. Check the workflow console for `✅ Logged in as ...` / `✅ Bot is ready!` to confirm a clean start.
- Data is stored as JSON files under `data/` (or `$DATA_DIR` if set) — `config.json`, `stock.json`, `users.json`, etc. Writes are atomic (temp file + rename) so a crash mid-write won't corrupt a file.
- `/help` in Discord lists every command; `(Owner)` sections are gated to `OWNER_ID`.

## Architecture
- `main.py` — bot bootstrap, event handlers (member join/invite tracking, message counting), background loops (subscription expiry sweep, presence refresh), global error handler.
- `database.py` — all JSON persistence (config, users, stock, drop stock, invites, blacklist, generate log, stock alerts, banner image).
- `utils.py` — access-control helpers (`has_generate_access`, `owner_only`, tier ranking) and the shared `fetch_text()` helper (size-capped download used by stock/drop file uploads).
- `generate.py` — `/generate`, account parsing (pipe-delimited stock format), DM delivery cascade with stock restore on failure.
- `stock.py`, `drops.py` — stock management, low-stock alerts, the auto-drop loop.
- `subscriptions.py`, `profile.py`, `blacklist.py`, `stats.py`, `admin.py`, `utility.py` — the remaining command groups.

## Recent changes (2026-07-11)
- Imported from GitHub and set up to run on Replit (installed `discord.py`, `python-dotenv`, `aiohttp`; configured secrets and the `Discord Bot` workflow).
- Hardened the JSON persistence layer with atomic writes to prevent corruption from a crash/restart mid-save.
- Deduplicated the `.txt` stock-file downloader into `utils.fetch_text()` and added a 5 MB size cap to avoid an OOM from an oversized upload.
- Fixed `/generate` offline mode: it now replies with a clear "Generator Offline" notice instead of leaving the interaction stuck at "thinking…" forever.
- Made the simulated "processing" delay in `/generate` configurable via the new `/setgendelay` command (0–30s, default 10s) instead of a hardcoded sleep.
- Added `.env.example` documenting the required environment variables.
- Switched all `print()` diagnostics to Python's `logging` module (timestamped, leveled) for real production observability.
- `/setroles` and `/checkchannel` now surface a warning when a tier still falls back to matching roles by **name** instead of a configured role ID — protects against an unrelated same-named role accidentally granting generate access.
- `/announce` and `/dm` now validate text length against Discord's embed limits up front instead of failing with an API error.
- Added a data safety net: `/backup` (zip + download) and `/backups` (list), plus an automatic rolling backup every 6 hours into `backups/` (kept out of `data/` so it's never backed up into itself, and gitignored since both hold live account credentials).
- Deduplicated `TIER_RANK` (was defined separately in `utils.py` and `subscriptions.py`) into a single source of truth in `utils.py`.
- Added `.gitignore` so `data/`, `backups/`, and `.env` are never committed.

## User preferences
None recorded yet.
