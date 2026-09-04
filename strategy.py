"""
MOJIDTRADEBOT — FCB Close Breakout + Pole Position

ENTRY — ALL 3 must be true, no exceptions:
1. CANDLE CLOSE TEST — last candle CLOSED fully above upper FCB band (UP)
   or fully below lower FCB band (DOWN). Not wick, not touch — CLOSE.
   Close inside the bands = NO TRADE.
2. NEXT CANDLE ONLY — enter on the candle immediately AFTER the breakout
   candle.  The bot detects the breakout on the just-closed candle and
   places a 1-minute trade — that IS the next candle.
3. POLE POSITION MATCH — all 4 must agree with direction:
   RSI:   above 50 for UP, below 50 for DOWN
   CCI:   above 0 for UP,  below 0 for DOWN
   MA:    price above MA for UP, price below MA for DOWN
   BB:    price not touching the OPPOSITE outer band
   If even ONE disagrees → NO TRADE.

EXIT / STOP CONTINUING:
   Keep entering next candles in the same direction ONLY while each new
   candle keeps closing in that direction.  The moment a candle CLOSES
   in the opposite direction → stop, flat, wait for a new Rule 1 signal.
"""
import pandas as pd
import config
import indicators as ind


# ── Rule 1: Candle Close Test ────────────────────────────────────────

def fcb_close_breakout(df):
    """Last candle must CLOSE fully outside the FCB band.

    Returns ("CALL", info) if close > upper band,
            ("PUT", info) if close < lower band,
            (None, info) if close is inside the bands.
    """
    if len(df) < 2:
        return None, {"reason": "not enough candles"}

    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    close = df["close"].iloc[-1]
    up, low = upper.iloc[-1], lower.iloc[-1]

    if pd.isna(up) or pd.isna(low):
        return None, {"reason": "FCB bands not available"}

    if close > up:
        return "CALL", {"close": close, "upper_band": up, "lower_band": low,
                        "reason": "close above upper FCB band"}
    if close < low:
        return "PUT", {"close": close, "upper_band": up, "lower_band": low,
                       "reason": "close below lower FCB band"}

    return None, {"close": close, "upper_band": up, "lower_band": low,
                  "reason": "close inside FCB bands — no breakout"}


# ── Rule 3: Pole Position Match (all 4 must agree) ───────────────────

def check_pole_position(df, direction):
    """All 4 indicators must agree with the signal direction.

    RSI:   above 50 for CALL, below 50 for PUT
    CCI:   above 0 for CALL,  below 0 for PUT
    MA:    price above MA for CALL, price below MA for PUT
    BB:    price not touching the OPPOSITE outer band
    """
    close = df["close"]
    price = close.iloc[-1]
    reasons = []

    # RSI
    rsi_val = ind.rsi(close, config.RSI_PERIOD).iloc[-1]
    if direction == "CALL" and rsi_val <= 50:
        reasons.append(f"RSI {rsi_val:.1f} <= 50")
    elif direction == "PUT" and rsi_val >= 50:
        reasons.append(f"RSI {rsi_val:.1f} >= 50")

    # CCI
    cci_val = ind.cci(df, config.CCI_PERIOD).iloc[-1]
    if direction == "CALL" and cci_val <= 0:
        reasons.append(f"CCI {cci_val:.1f} <= 0")
    elif direction == "PUT" and cci_val >= 0:
        reasons.append(f"CCI {cci_val:.1f} >= 0")

    # MA (EMA)
    ma_val = ind.ema(close, config.EMA_FAST).iloc[-1]
    if direction == "CALL" and price <= ma_val:
        reasons.append(f"price {price:.5f} <= MA {ma_val:.5f}")
    elif direction == "PUT" and price >= ma_val:
        reasons.append(f"price {price:.5f} >= MA {ma_val:.5f}")

    # Bollinger — price must not touch the OPPOSITE outer band
    bb_upper, bb_mid, bb_lower = ind.bollinger_bands(close, config.BB_PERIOD, config.BB_STD)
    if direction == "CALL" and price <= bb_lower.iloc[-1]:
        reasons.append(f"price touching lower BB {bb_lower.iloc[-1]:.5f}")
    elif direction == "PUT" and price >= bb_upper.iloc[-1]:
        reasons.append(f"price touching upper BB {bb_upper.iloc[-1]:.5f}")

    if reasons:
        return False, "; ".join(reasons)
    return True, "all 4 indicators aligned"


# ── Combined signal (Rules 1 + 3, AND-gated) ──────────────────────────

def get_signal(df, mood_value=None):
    """Rule 1 (FCB close breakout) AND Rule 3 (Pole Position all 4 agree).

    Returns (direction, info_dict) where direction is "CALL", "PUT", or None.
    """
    # Rule 1 — FCB close breakout
    direction, breakout_info = fcb_close_breakout(df)
    if direction is None:
        return None, breakout_info

    info = {"breakout": breakout_info}

    # Rule 3 — Pole Position (all 4 must agree)
    ok, msg = check_pole_position(df, direction)
    info["pole_position"] = msg
    if not ok:
        info["reason"] = f"PP: {msg}"
        return None, info

    info["reason"] = "confirmed"
    return direction, info


# ── Continuation check (used by main.py after a winning trade) ────────

def should_continue(df, direction):
    """Keep entering same direction while each new candle closes in that
    direction.  Stop when a candle CLOSES in the opposite direction.

    Returns True if the latest candle closed in the same direction.
    """
    if len(df) < 1:
        return False

    c = df.iloc[-1]
    close, open_p = c["close"], c["open"]

    if direction == "CALL":
        return close > open_p   # bullish candle — keep going UP
    else:
        return close < open_p    # bearish candle — keep going DOWN
