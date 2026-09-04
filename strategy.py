"""
MOJIDTRADEBOT — FCB Breakout + Confirmation Layer

Entry trigger: clean FCB breakout on the latest 1m candle (price closes
decisively beyond the Fractal Chaos Band with a confirming body).

Confirmation filters (all three must pass, AND-gated):
  1. Trader Sentiment — reject if 80%+ skewed against signal direction
  2. Fractal Chaos Band — price must be outside the band in the signal direction
  3. Pole Position Confluence — RSI, CCI, Bollinger Bands, MA must agree
"""
import pandas as pd
import config
import indicators as ind


# ── Entry trigger: FCB breakout ───────────────────────────────────────

def fcb_breakout_signal(df):
    """Detect a clean FCB breakout on the latest closed candle.

    A clean breakout requires:
      1. Previous candle closed INSIDE the bands
      2. Current candle CLOSES beyond the band (not just wicking through)
      3. Candle body confirms direction (close > open for CALL, close < open for PUT)
      4. Breakout penetration >= 20% of band width (filters weak breakouts)

    Returns ("CALL", info) for an upside breakout, ("PUT", info) for a
    downside breakout, or (None, info).
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

    if pd.isna(up) or pd.isna(low) or pd.isna(prev_up) or pd.isna(prev_low):
        return None, {"reason": "bands not yet confirmed"}

    was_inside = prev_low <= prev_price <= prev_up
    band_width = up - low if up > low else 0

    if price > up and was_inside:
        if price <= open_price:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout but bearish candle body"}
        if band_width > 0 and (price - up) < 0.2 * band_width:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout too weak (< 20% band width)"}
        return "CALL", {"price": price, "upper_band": up, "lower_band": low}

    if price < low and was_inside:
        if price >= open_price:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout but bullish candle body"}
        if band_width > 0 and (low - price) < 0.2 * band_width:
            return None, {"price": price, "upper_band": up, "lower_band": low,
                          "reason": "breakout too weak (< 20% band width)"}
        return "PUT", {"price": price, "upper_band": up, "lower_band": low}

    if price > up:
        return None, {"price": price, "upper_band": up, "lower_band": low,
                      "reason": "above band but not a clean breakout"}
    if price < low:
        return None, {"price": price, "upper_band": up, "lower_band": low,
                      "reason": "below band but not a clean breakout"}
    return None, {"price": price, "upper_band": up, "lower_band": low,
                  "reason": "inside bands"}


# ── Confirmation filter 1: Trader Sentiment ───────────────────────────

def check_sentiment(mood_value, direction):
    """Reject if 80%+ of traders are against the signal direction."""
    if mood_value is None:
        return True, "sentiment unavailable — allowing"

    pct_higher = mood_value * 100 if mood_value <= 1 else mood_value

    if direction == "CALL" and pct_higher < 20:
        return False, f"80%+ traders Lower ({pct_higher:.0f}% Higher) — rejecting"
    if direction == "PUT" and pct_higher > 80:
        return False, f"80%+ traders Higher ({pct_higher:.0f}% Higher) — rejecting"
    return True, f"{pct_higher:.0f}% Higher — OK"


# ── Confirmation filter 2: Fractal Chaos Band ────────────────────────

def check_fcb(df, direction):
    """Price must be outside the FCB band in the same direction as the signal."""
    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    price = df["close"].iloc[-1]
    up, low = upper.iloc[-1], lower.iloc[-1]
    if pd.isna(up) or pd.isna(low):
        return False, "FCB bands not confirmed"

    if direction == "CALL" and price > up:
        return True, f"price {price:.5f} above upper band {up:.5f}"
    if direction == "PUT" and price < low:
        return True, f"price {price:.5f} below lower band {low:.5f}"
    return False, f"price {price:.5f} inside bands [{low:.5f}, {up:.5f}]"


# ── Confirmation filter 3: Pole Position Confluence ────────────────────

def check_pole_position(df, direction):
    """RSI, CCI, Bollinger Bands, and MA must all agree with the signal direction."""
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


# ── Combined signal ───────────────────────────────────────────────────

def get_signal(df, mood_value=None):
    """FCB breakout trigger + all three confirmation filters (AND-gated).

    Returns (direction, info_dict) where direction is "CALL", "PUT", or None.
    """
    direction, breakout_info = fcb_breakout_signal(df)
    if direction is None:
        return None, breakout_info

    info = {"breakout": breakout_info}

    # Filter 1 — Trader Sentiment
    ok, msg = check_sentiment(mood_value, direction)
    info["sentiment"] = msg
    if not ok:
        info["reason"] = f"sentiment: {msg}"
        return None, info

    # Filter 2 — Fractal Chaos Band
    ok, msg = check_fcb(df, direction)
    info["fcb"] = msg
    if not ok:
        info["reason"] = f"FCB: {msg}"
        return None, info

    # Filter 3 — Pole Position Confluence
    ok, msg = check_pole_position(df, direction)
    info["pole_position"] = msg
    if not ok:
        info["reason"] = f"PP: {msg}"
        return None, info

    info["reason"] = "confirmed"
    return direction, info
