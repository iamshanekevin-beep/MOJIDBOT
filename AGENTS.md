# Base44 Dev Environment

## What this app is
An IQ Option OTC trading bot — a headless Python worker (`python main.py`) that connects
to IQ Option via the unofficial `iqoptionapi` community library, computes trading signals
(Fractal Chaos Bands + Pole Position multi-indicator scoring), and optionally places trades.

There is **no web server** in the bot itself. A separate `log_viewer.py` stdlib HTTP server
serves a dashboard on port 3000 that tails the bot's log.

## How it runs in Base44
- **`docker-compose.base44.yml`** — two services:
  - `bot` — `python:3.11-slim` with source bind-mounted; installs deps and runs
    `python -u main.py`, piping output to a shared `logs` volume at `/logs/bot.log`.
  - `web` — `python:3.11-slim` running `log_viewer.py`, a stdlib-only HTTP server on
    port 3000 that tails `/logs/bot.log` and auto-refreshes. This is what the preview shows.
- **`.env.base44-defaults`** — placeholder config so the app boots; real IQ Option credentials
  come from `/run/base44/app.env` (delivered by the platform, overrides defaults).

## Key fix: the iqoptionapi dependency
The PyPI `iqoptionapi` package (v0.5) does **not** ship the `stable_api` submodule that
`broker.py` imports (`from iqoptionapi.stable_api import IQ_Option`). Without the fix the bot
crashes on import in a restart loop (looks like it is "hanging").
`requirements.txt` therefore installs the library from the GitHub source archive instead:
`iqoptionapi @ https://github.com/Lu-Yi-Hsun/iqoptionapi/archive/refs/heads/master.zip`.
If import/startup fails again, this is the first thing to check.

## This branch (replace-suspended-assets)
`broker.py` fetches the list of open (non-suspended) assets once after connecting and caches
it. If the configured `PAIR` is suspended/unavailable, it auto-switches to the first available
binary/turbo asset. The connection is established once at startup; reconnection only happens
when the websocket actually drops (`ensure_connected`).

## Verify it works
- `docker compose -f docker-compose.base44.yml up -d`
- `docker compose -f docker-compose.base44.yml logs -f bot` — expect a connection line, an
  "Found N open assets" line, then a "Trading pair: …" line, then signal logs every POLL_SECONDS.
- The preview (port 3000) shows the dashboard tailing `/logs/bot.log`.
