# IQ Option OTC Trading Bot

## Setup

Headless Python worker (no web frontend). Runs `python main.py` in a Docker container via `docker-compose.base44.yml`.

### Dependencies

- `requirements.txt` installs `iqoptionapi` from **GitHub** (not PyPI). The PyPI package (v0.5) is an old, different package that lacks the `stable_api` module. The GitHub version (7.1.x) has `iqoptionapi.stable_api.IQ_Option` which the code imports.
- Other deps: pandas, numpy.

### Secrets

- `IQ_EMAIL` and `IQ_PASSWORD` — IQ Option account credentials. Required at boot. Delivered via `/run/base44/app.env`.
- Default `ACCOUNT_TYPE=PRACTICE` and `AUTO_TRADE=true` are set in compose `environment:`.

### Running

```bash
docker compose -f docker-compose.base44.yml up -d
docker compose -f docker-compose.base44.yml logs -f
```

### Key findings

- **OTC pairs (e.g. EURUSD-OTC) are suspended on weekdays.** IQ Option only offers OTC pairs on weekends. On weekdays, use real pairs (e.g. `EURUSD` without the `-OTC` suffix). The bot logs "active is suspended" when trying to trade a suspended asset.
- **The `buy_digital_spot` API call hangs indefinitely on suspended assets.** The broker now checks `is_asset_open()` before trading and skips the digital spot fallback when `buy()` reports "suspended".
- **STRATEGY=BOTH is very strict** — requires both FCB and Pole Position to agree. Most candles produce "No signal". Switch to `FCB` or `POLE_POSITION` alone for more signals.
- No web frontend — the preview shows a loading screen. Bot output is in `docker compose logs`.

### Verify it works

```bash
docker compose -f docker-compose.base44.yml logs --tail=20
# Should see: "Connected to IQ Option (PRACTICE account)" then signal/no-signal logs every POLL_SECONDS.
```
