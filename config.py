"""
Configuration loaded from environment variables.
On Railway: set these under your service's "Variables" tab.
Locally: copy .env.example to .env and fill it in.
"""
import os

def _get_bool(key, default=False):
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

def _get_float(key, default):
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return float(default)

def _get_int(key, default):
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return int(default)

# --- IQ Option account ---
IQ_EMAIL = os.getenv("IQ_EMAIL", "")
IQ_PASSWORD = os.getenv("IQ_PASSWORD", "")
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE", "PRACTICE")  # PRACTICE or REAL — start on PRACTICE

# --- Market / instrument ---
PAIR = os.getenv("PAIR", "EURUSD-OTC")
PAIRS = os.getenv("PAIRS", "EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC,USDCHF-OTC,EURGBP-OTC")
TIMEFRAME_SECONDS = _get_int("TIMEFRAME_SECONDS", 60)     # candle size, e.g. 60 = M1
CANDLE_COUNT = _get_int("CANDLE_COUNT", 100)              # how many candles to pull each cycle
EXPIRATION_MINUTES = _get_int("EXPIRATION_MINUTES", 1)    # trade expiry

# --- Strategy selection ---
# FCB           = Fractal Chaos Bands only
# POLE_POSITION = RSI + CCI + Bollinger Bands + MAs scoring system
# BOTH          = require agreement from both strategies (stricter, fewer trades)
STRATEGY = os.getenv("STRATEGY", "BOTH").upper()

# Fractal Chaos Bands
FCB_FRACTAL_PERIOD = _get_int("FCB_FRACTAL_PERIOD", 2)

# Pole Position indicator settings
EMA_FAST = _get_int("EMA_FAST", 9)
EMA_SLOW = _get_int("EMA_SLOW", 21)
RSI_PERIOD = _get_int("RSI_PERIOD", 14)
RSI_UP = _get_float("RSI_UP", 55)
RSI_DOWN = _get_float("RSI_DOWN", 45)
CCI_PERIOD = _get_int("CCI_PERIOD", 14)
CCI_UP = _get_float("CCI_UP", 100)
CCI_DOWN = _get_float("CCI_DOWN", -100)
BB_PERIOD = _get_int("BB_PERIOD", 20)
BB_STD = _get_float("BB_STD", 2.0)
POLE_POSITION_SCORE_THRESHOLD = _get_int("POLE_POSITION_SCORE_THRESHOLD", 3)  # out of 4 votes

# --- Risk / money management ---
TRADE_AMOUNT = _get_float("TRADE_AMOUNT", 1.0)
MAX_TRADES_PER_DAY = _get_int("MAX_TRADES_PER_DAY", 20)
MAX_CONSECUTIVE_LOSSES = _get_int("MAX_CONSECUTIVE_LOSSES", 3)   # bot cooldowns after this many losses in a row
COOLDOWN_MINUTES = _get_int("COOLDOWN_MINUTES", 15)              # cooldown duration after consecutive losses
DAILY_LOSS_LIMIT = _get_float("DAILY_LOSS_LIMIT", 20.0)          # bot stops trading for the day past this loss

# --- Trade continuation ---
# After a winning trade, check Pole Position: if it confirms the same
# direction, place a follow-up trade.  Ride the trend until PP disagrees,
# a loss, or the limit is hit.
MAX_CONTINUATION_TRADES = _get_int("MAX_CONTINUATION_TRADES", 3)

# --- Behavior ---
AUTO_TRADE = _get_bool("AUTO_TRADE", True)   # False = log signals only, no orders placed
POLL_SECONDS = _get_int("POLL_SECONDS", 5)   # how often to check for a new closed candle
