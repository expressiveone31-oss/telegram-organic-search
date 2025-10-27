
# Telegram Organic Search Bot (Telemetr-only)

Searches Telegram posts via Telemetr API by exact phrases within a date range.
No VK/TGStat; only Telemetr.

## Env vars

- `BOT_TOKEN` — Telegram bot token
- `TELEMETR_TOKEN` — Telemetr API bearer token
- `TELEMETR_PAGES` — how many pages to fetch (default 3), each 50 items
- `TELEMETR_USE_QUOTES` — `"1"` to wrap each seed in quotes for Telemetr (recommended)
- `TELEMETR_REQUIRE_EXACT` — `"1"` to require exact phrase match in post text
- `TELEMETR_MAX_GAP_WORDS` — integer, allow up to N words between seed words (default 0)
- `TELEMETR_FUZZY_THRESHOLD` — float 0..1 (default 0.72) for fallback fuzzy ratio
- `ORGANIC_DEBUG` — `"1"` to print diagnostic block

## Commands

- `/organic` — start a guided flow: pick date range then paste seeds (one per line).

## Deploy

1. Push these files, set env vars
2. `Procfile` uses `worker: python -m bot.main`
