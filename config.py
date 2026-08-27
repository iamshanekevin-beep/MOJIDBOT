"""
Configuration loaded from environment variables.
Supports multi-pair trading, 1h trend + 1m entry, doji filtering, 24/7 operation.
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

def _get_list(key, default):
    val = os.getenv(key, default)
    if not val:
        return []
    return [p.strip() for p in val.split(",") if p.strip()]

# --- IQ Option account ---
IQ_EMAIL = os.getenv("IQ_EMAIL", "")
IQ_PASSWORD = os.getenv("IQ_PASSWORD", "")
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE", "PRACTICE")  # PRACTICE or REAL

# --- Market / instrument (multi-pair) ---
PAIRS = _get_list("PAIRS", "EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC,EURGBP-OTC,EURJPY-OTC,NZDUSD-OTC,USDCHF-OTC")
PAIR = PAIRS[0] if PAIRS else "EURUSD-OTC"  # backward compat
TIMEFRAME_SECONDS = _get_int("TIMEFRAME_SECONDS", 60)       # 1m entry candles
CANDLE_COUNT = _get_int("CANDLE_COUNT", 100)
EXPIRATION_MINUTES = _get_int("EXPIRATION_MINUTES", 1)    # trade expiry

# --- Higher timeframe for trend analysis (1h) ---
HIGHER_TIMEFRAME_SECONDS = _get_int("HIGHER_TIMEFRAME_SECONDS", 3600)  # 1h
HIGHER_TIMEFRAME_CANDLES = _get_int("HIGHER_TIMEFRAME_CANDLES", 50)

# --- Doji filter ---
DOJI_THRESHOLD = _get_float("DOJI_THRESHOLD", 0.1)  # body must be > 10% of candle range

# --- Strategy selection ---
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
POLE_POSITION_SCORE_THRESHOLD = _get_int("POLE_POSITION_SCORE_THRESHOLD", 3)

# --- Risk / money management ---
TRADE_AMOUNT = _get_float("TRADE_AMOUNT", 1.0)
MAX_CONSECUTIVE_LOSSES = _get_int("MAX_CONSECUTIVE_LOSSES", 0)   # 0 = disabled (no cooldown/gale)
MAX_TRADES_PER_DAY = _get_int("MAX_TRADES_PER_DAY", 0)           # 0 = unlimited, 24/7
DAILY_LOSS_LIMIT = _get_float("DAILY_LOSS_LIMIT", 0)             # 0 = no limit

# --- Behavior ---
AUTO_TRADE = _get_bool("AUTO_TRADE", True)
POLL_SECONDS = _get_int("POLL_SECONDS", 5)
