# IQ Option OTC Trading Bot — Fractal Chaos Bands + Pole Position

Auto-trading bot for IQ Option OTC pairs, combining two strategies:

**Fractal Chaos Bands (FCB)** — single clean-entry indicator:
- price above the high band → trend up → CALL
- price inside the bands → no trade
- price below the low band → trend down → PUT

**Pole Position** — multi-indicator scoring system (EMA cross, RSI, CCI,
Bollinger Bands). Each indicator casts a vote; if enough agree, that's the
signal.

By default (`STRATEGY=BOTH`), a trade only fires when **both** strategies
agree — this is stricter and produces fewer, higher-conviction signals than
running either one alone. You can switch to just one via the `STRATEGY` env
variable.

## ⚠️ Before you run this for real

- IQ Option has no official public API. This bot uses the unofficial
  `iqoptionapi` community library, which can break without warning if IQ
  Option changes their platform. If trades stop firing, check `broker.py`
  first.
- **Start on `ACCOUNT_TYPE=PRACTICE`.** Watch it run for a while — check the
  logs, sanity-check the signals — before ever switching to `REAL`.
- No strategy or indicator combination guarantees profit. The risk controls
  below (daily loss limit, consecutive-loss pause, max trades/day) are there
  to contain damage from a bad session, not to prevent losses entirely.
- The bot approximates payout at 80% for tracking daily P&L in `main.py`
  (`RiskState.record_result`) — adjust that to your actual OTC payout % so
  the daily loss limit is accurate.

## Files

| File | Purpose |
|---|---|
| `main.py` | Main loop: fetch candles, get signal, place trade, track risk |
| `strategy.py` | FCB and Pole Position signal logic |
| `indicators.py` | EMA, RSI, CCI, Bollinger Bands, Fractal Chaos Bands math |
| `broker.py` | IQ Option connection + order placement (isolated — patch here if the API breaks) |
| `config.py` | All settings, read from environment variables |
| `.env.example` | Template for local testing |

## Deploy on Railway

1. Push this project to a new GitHub repo (don't commit a `.env` file — it's gitignored).
2. On [railway.app](https://railway.app), **New Project → Deploy from GitHub repo** → select this repo.
3. Open the service → **Variables** tab → add every variable from `.env.example` with your real values.
   - Set `ACCOUNT_TYPE=PRACTICE` and `AUTO_TRADE=false` first to confirm the bot connects and logs signals correctly before it ever places a trade.
4. Railway should auto-detect the `Procfile` and run `python main.py`. If not, set the **Start Command** manually in Settings to `python main.py`.
5. Watch the **Deployments → Logs** tab. You should see connection confirmation, then candle/signal logs every `POLL_SECONDS`.
6. Once you're confident in the signals, set `AUTO_TRADE=true` (and only move to `ACCOUNT_TYPE=REAL` when you're ready to risk real funds).

## Key settings to tune

- `PAIR` — e.g. `EURUSD-OTC`, `GBPJPY-OTC`
- `TIMEFRAME_SECONDS` — candle size (60 = M1)
- `EXPIRATION_MINUTES` — trade duration
- `STRATEGY` — `FCB`, `POLE_POSITION`, or `BOTH`
- `TRADE_AMOUNT`, `MAX_TRADES_PER_DAY`, `MAX_CONSECUTIVE_LOSSES`, `DAILY_LOSS_LIMIT`

## Local testing

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
export $(cat .env | xargs)   # or use a tool like python-dotenv
python main.py
```
