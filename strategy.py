"""
MOJIDTRADEBOT — FCB Breakout Entry + Pole Position Continuation

Entry trigger: clean FCB breakout — candle fully CLOSES outside the band
(not just poking through).  Fake breakouts (poke through, close back inside)
are detected and abandoned.  Entry needs ONLY the breakout — no PP gate.

Continuation: after a winning trade, Pole Position (RSI, CCI, Bollinger
Bands, MA) decides whether to ride the trend.  Keep opening in the same
direction as long as PP confirms.  Stop at the first PP disagreement or
rejection candle.

1m candle / 1m expiry.  Scans all available pairs.
"""
import pandas as pd
import config
import indicators as ind


def fcb_breakout_signal(df):
    """Detect a clean FCB breakout on the latest closed candle.

    Clean breakout requires:
      1. Previous candle closed INSIDE the bands
      2. Current candle CLOSES beyond the band (not just wicking through)
      3. Candle body confirms direction (close > open for CALL, close < open for PUT)
      4. Breakout penetration >= 20% of band width (filters weak breakouts)

    Fake breakout (poked through band but closed back inside) is detected
    and rejected — the setup is abandoned, not chased.

    Returns ("CALL", info), ("PUT", info), or (None, info).
    """
    if len(df) < 2:
        return None, {"reason": "not enough candles"}

    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    price = df["close"].iloc[-1]
    prev_price = df["close"].iloc[-2]
    up = upper.iloc[-1]
    low = lower.iloc[-1]
    prev_up = upper.iloc[-2]
    prev_low = lower.iloc[-2]
    open_price = df["open"].iloc[-1]
    high = df["high"].iloc[-1]
    low_wick = df["low"].iloc[-1]

    if pd.isna(up) or pd.isna(low) or pd.isna(prev_up) or pd.isna(prev_low):
        return None, {"reason": "bands not yet confirmed"}

    was_inside = prev_low <= prev_price <= prev_up
    band_width = up - low if up > low else 0

    # ── Fake breakout detection ────────────────────────────────────
    # Price poked through the band (high above upper or low below lower)
    # but closed back INSIDE the bands → fake breakout, abandon.
    if low <= price <= up:
        if high > up:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "FAKE breakout — poked above band, closed back inside"}
        if low_wick < low:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "FAKE breakout — poked below band, closed back inside"}
        return None, {"price": price, "upper_band": up, "lower_band": low,
                      "reason": "inside bands"}

    # ── Clean breakout checks ───────────────────────────────────────
    if price > up:
        if not was_inside:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "above band but not a clean breakout (prev not inside)"}
        if price <= open_price:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout but bearish candle body"}
        if band_width > 0 and (price - up) < 0.2 * band_width:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout too weak (< 20% band width)"}
        return "CALL", {"price": price, "upper_band": up, "lower_band": low}

    if price < low:
        if not was_inside:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "below band but not a clean breakout (prev not inside)"}
        if price >= open_price:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout but bullish candle body"}
        if band_width > 0 and (low - price) < 0.2 * band_width:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout too weak (< 20% band width)"}
        return "PUT", {"price": price, "upper_band": up, "lower_band": low}

    return None, {"price": price, "upper_band": up, "lower_band": low,
                  "reason": "inside bands"}


def check_pole_position(df, direction):
    """RSI, CCI, Bollinger Bands, and MA must all agree with the signal direction.

    - RSI and CCI must not contradict signal direction (no overbought on CALL,
      no oversold on PUT, no bearish CCI on CALL, no bullish CCI on PUT)
    - Price must not be pinned at the outer Bollinger Band against the signal
    - Moving Average (EMA fast vs slow) trend must agree with signal direction
    """
    close = df["close"]
    price = close.iloc[-1]
    reasons = []

    # RSI — must not show exhaustion against signal
    rsi_val = ind.rsi(close, config.RSI_PERIOD).iloc[-1]
    if direction == "CALL" and rsi_val > 70:
        reasons.append(f"RSI overbought ({rsi_val:.1f})")
    elif direction == "PUT" and rsi_val < 30:
        reasons.append(f"RSI oversold ({rsi_val:.1f})")

    # CCI — must not contradict signal direction
    cci_val = ind.cci(df, config.CCI_PERIOD).iloc[-1]
    if direction == "CALL" and cci_val < -100:
        reasons.append(f"CCI bearish ({cci_val:.1f})")
    elif direction == "PUT" and cci_val > 100:
        reasons.append(f"CCI bullish ({cci_val:.1f})")

    # Bollinger Bands — price must not be pinned at the outer BB against signal
    bb_upper, bb_mid, bb_lower = ind.bollinger_bands(close, config.BB_PERIOD, config.BB_STD)
    if direction == "CALL" and price <= bb_lower.iloc[-1]:
        reasons.append("price pinned at lower BB")
    elif direction == "PUT" and price >= bb_upper.iloc[-1]:
        reasons.append("price pinned at upper BB")

    # Moving Average — trend must agree
    ema_fast = ind.ema(close, config.EMA_FAST).iloc[-1]
    ema_slow = ind.ema(close, config.EMA_SLOW).iloc[-1]
    if direction == "CALL" and ema_fast <= ema_slow:
        reasons.append(f"EMA bearish (fast {ema_fast:.5f} <= slow {ema_slow:.5f})")
    elif direction == "PUT" and ema_fast >= ema_slow:
        reasons.append(f"EMA bullish (fast {ema_fast:.5f} >= slow {ema_slow:.5f})")

    if reasons:
        return False, "; ".join(reasons)
    return True, "all indicators aligned"


def get_signal(df, mood_value=None):
    """FCB breakout trigger ONLY — entry fires on a clean breakout.

    Pole Position is NOT checked here; it's used separately for trend
    continuation after a winning trade (see check_pole_position).

    Returns (direction, info_dict) where direction is "CALL", "PUT", or None.
    """
    direction, breakout_info = fcb_breakout_signal(df)
    if direction is None:
        return None, breakout_info

    info = {"breakout": breakout_info, "reason": "confirmed breakout"}
    return direction, info
