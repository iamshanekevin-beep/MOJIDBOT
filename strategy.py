"""
Strategy logic with multi-timeframe analysis and doji filtering.

Each signal function returns (direction, info_dict) where direction is "CALL", "PUT", or None.

FCB strategy:
    price above the high band  -> trend is up   -> CALL
    price inside the bands     -> no trade      -> None
    price below the low band   -> trend is down -> PUT

Pole Position strategy:
    Scores four indicators (EMA cross, RSI, CCI, Bollinger Bands),
    each casts a vote of +1 (bullish), -1 (bearish), or 0 (neutral).
    If the summed score meets the threshold, that's the signal.
"""
import pandas as pd
import config
import indicators as ind


# ─── Multi-timeframe helpers ───────────────────────────────────────

def is_doji(df, threshold=None):
    """Check if the latest candle is a doji (body too small relative to range)."""
    threshold = threshold or config.DOJI_THRESHOLD
    if len(df) < 1:
        return True
    row = df.iloc[-1]
    body = abs(row["close"] - row["open"])
    rng = row["high"] - row["low"]
    if rng == 0:
        return True
    return (body / rng) < threshold


def get_trend(df):
    """
    Determine the trend direction on a higher timeframe (e.g. 1h).
    Uses EMA cross + FCB band position.
    Returns ('CALL' | 'PUT' | None, info_dict).
    """
    if len(df) < config.EMA_SLOW + 1:
        return None, {"reason": "not enough candles for trend"}

    close = df["close"]
    ema_fast = ind.ema(close, config.EMA_FAST).iloc[-1]
    ema_slow = ind.ema(close, config.EMA_SLOW).iloc[-1]
    price = close.iloc[-1]

    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    up = upper.iloc[-1]
    low = lower.iloc[-1]

    info = {"price": price, "ema_fast": ema_fast, "ema_slow": ema_slow,
            "upper_band": up, "lower_band": low}

    if pd.isna(up) or pd.isna(low):
        # Fall back to EMA cross only
        if ema_fast > ema_slow:
            return "CALL", info
        if ema_fast < ema_slow:
            return "PUT", info
        return None, info

    # Strong trend: EMA cross + price beyond FCB bands
    if price > up and ema_fast > ema_slow:
        return "CALL", info
    if price < low and ema_fast < ema_slow:
        return "PUT", info
    # Weaker trend: EMA cross alone
    if ema_fast > ema_slow:
        return "CALL", info
    if ema_fast < ema_slow:
        return "PUT", info
    return None, info


def is_clean_breakout(df, direction):
    """
    Check if the latest candle is a clean breakout — used to resume
    trading after a cooldown.  Requires:
      - non-doji candle (strong body)
      - body > 50% of candle range
      - price breaks FCB bands in the expected direction
    """
    if is_doji(df):
        return False

    row = df.iloc[-1]
    body = abs(row["close"] - row["open"])
    rng = row["high"] - row["low"]
    if rng == 0:
        return False
    body_ratio = body / rng
    if body_ratio < 0.5:
        return False

    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    up = upper.iloc[-1]
    low = lower.iloc[-1]
    price = row["close"]

    if pd.isna(up) or pd.isna(low):
        return False

    if direction == "CALL" and price > up:
        return True
    if direction == "PUT" and price < low:
        return True
    return False


# ─── Signal functions (1m entry) ───────────────────────────────────

def fcb_signal(df):
    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    price = df["close"].iloc[-1]
    up = upper.iloc[-1]
    low = lower.iloc[-1]

    if pd.isna(up) or pd.isna(low):
        return None, {"reason": "bands not yet confirmed"}

    if price > up:
        return "CALL", {"price": price, "upper_band": up, "lower_band": low}
    if price < low:
        return "PUT", {"price": price, "upper_band": up, "lower_band": low}
    return None, {"price": price, "upper_band": up, "lower_band": low, "reason": "inside bands"}


def pole_position_signal(df):
    close = df["close"]

    ema_fast = ind.ema(close, config.EMA_FAST).iloc[-1]
    ema_slow = ind.ema(close, config.EMA_SLOW).iloc[-1]
    rsi_val = ind.rsi(close, config.RSI_PERIOD).iloc[-1]
    cci_val = ind.cci(df, config.CCI_PERIOD).iloc[-1]
    bb_upper, bb_mid, bb_lower = ind.bollinger_bands(close, config.BB_PERIOD, config.BB_STD)
    price = close.iloc[-1]

    score = 0
    votes = {}

    # 1. Trend: EMA fast vs slow
    if ema_fast > ema_slow:
        score += 1; votes["ema"] = 1
    elif ema_fast < ema_slow:
        score -= 1; votes["ema"] = -1
    else:
        votes["ema"] = 0

    # 2. Momentum: RSI
    if rsi_val >= config.RSI_UP:
        score += 1; votes["rsi"] = 1
    elif rsi_val <= config.RSI_DOWN:
        score -= 1; votes["rsi"] = -1
    else:
        votes["rsi"] = 0

    # 3. Momentum: CCI
    if cci_val >= config.CCI_UP:
        score += 1; votes["cci"] = 1
    elif cci_val <= config.CCI_DOWN:
        score -= 1; votes["cci"] = -1
    else:
        votes["cci"] = 0

    # 4. Volatility / position: Bollinger Bands
    if price >= bb_upper.iloc[-1]:
        score += 1; votes["bb"] = 1
    elif price <= bb_lower.iloc[-1]:
        score -= 1; votes["bb"] = -1
    else:
        votes["bb"] = 0

    details = {
        "price": price, "ema_fast": ema_fast, "ema_slow": ema_slow,
        "rsi": rsi_val, "cci": cci_val,
        "bb_upper": bb_upper.iloc[-1], "bb_lower": bb_lower.iloc[-1],
        "score": score, "votes": votes,
    }

    if score >= config.POLE_POSITION_SCORE_THRESHOLD:
        return "CALL", details
    if score <= -config.POLE_POSITION_SCORE_THRESHOLD:
        return "PUT", details
    return None, details


def get_signal(df):
    """
    Returns (direction, info_dict) according to config.STRATEGY.
    """
    if config.STRATEGY == "FCB":
        return fcb_signal(df)
    if config.STRATEGY == "POLE_POSITION":
        return pole_position_signal(df)

    # BOTH: require agreement
    fcb_dir, fcb_info = fcb_signal(df)
    pole_dir, pole_info = pole_position_signal(df)

    info = {"fcb": fcb_info, "pole_position": pole_info}
    if fcb_dir is not None and fcb_dir == pole_dir:
        return fcb_dir, info
    return None, info
