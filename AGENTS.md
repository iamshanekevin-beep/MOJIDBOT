# Base44 Dev Environment

## What this app is
An IQ Option OTC trading bot — a headless Python worker (`python main.py`) that connects
to IQ Option via the unofficial `iqoptionapi` community library, computes trading signals
(Fractal Chaos Bands + Pole Position multi-indicator scoring), and optionally places trades.

There is **no web server** — the app is a CLI/worker loop logging to stdout.

## How it runs in Base44
- **`docker-compose.base44.yml`** — two services:
  - `bot` — `python:3.11-slim` with source bind-mounted; installs deps and runs `python main.py`,
    piping output to a shared `logs` volume at `/logs/bot.log`.
  - `web` — `python:3.11-slim` running `log_viewer.py`, a stdlib-only HTTP server on port 3000
    that tails `/logs/bot.log` and auto-refreshes. This is what the preview shows.
- **`.env.base44-defaults`** — placeholder config so the app boots; real IQ Option credentials
  come from `/run/base44/app.env` (delivered by the platform, overrides defaults).

## Key fix applied
The PyPI `iqoptionapi` package (v0.5) has a completely different API from what the code expects.
The code uses `from iqoptionapi.stable_api import IQ_Option`, which only exists in the GitHub
version (`Lu-Yi-Hsun/iqoptionapi`, v6.8.9.1). `requirements.txt` installs from the GitHub ZIP
URL instead of PyPI.

## Secrets required
- `IQ_EMAIL` — IQ Option account email
- `IQ_PASSWORD` — IQ Option account password

## Verifying it works
1. `docker compose -f docker-compose.base44.yml up -d`
2. Check `docker compose -f docker-compose.base44.yml logs bot` — should show
   "Connected to IQ Option" then signal logs every ~5s.
3. Preview on port 3000 shows live bot logs.

## Safety defaults
- `AUTO_TRADE=false` — bot logs signals only, does NOT place trades.
- `ACCOUNT_TYPE=PRACTICE` — practice account, not real money.
