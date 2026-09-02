"""
Strategy logic. Each function returns one of "CALL", "PUT", or None (no trade).

FCB strategy (from the spec):
    price above the high band  -> trend is up   -> CALL
    price inside the bands     -> no trade      -> None
    price below the low band   -> trend is down -> PUT

Pole Position strategy:
    Scores four indicators (EMA cross, RSI, CCI, Bollinger Bands position),
    each casts a vote of +1 (bullish), -1 (bearish), or 0 (neutral).
    If the summed score meets the threshold in either direction, that's the signal.
"""
import pandas as pd
import config
import indicators as ind


def fcb_signal(df):
    upper, lower = ind.fractal_chaos_bands(df, period=config.FCB_FRACTAL_PERIOD)
    price = df["close"].iloc[-1]
    prev_price = df["close"].iloc[-2]
    up = upper.iloc[-1]
    low = lower.iloc[-1]
    prev_up = upper.iloc[-2]
    prev_low = lower.iloc[-2]

    if pd.isna(up) or pd.isna(low) or pd.isna(prev_up) or pd.isna(prev_low):
        return None, {"reason": "bands not yet confirmed"}

    # FCB breakout: price closes outside the band.
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
        score += 1
        votes["ema"] = 1
    elif ema_fast < ema_slow:
        score -= 1
        votes["ema"] = -1
    else:
        votes["ema"] = 0

    # 2. Momentum: RSI
    if rsi_val >= config.RSI_UP:
        score += 1
        votes["rsi"] = 1
    elif rsi_val <= config.RSI_DOWN:
        score -= 1
        votes["rsi"] = -1
    else:
        votes["rsi"] = 0

    # 3. Momentum: CCI
    if cci_val >= config.CCI_UP:
        score += 1
        votes["cci"] = 1
    elif cci_val <= config.CCI_DOWN:
        score -= 1
        votes["cci"] = -1
    else:
        votes["cci"] = 0

    # 4. Volatility / position: Bollinger Bands
    #    price pushing above upper band with trend up = continuation vote,
    #    price pushing below lower band with trend down = continuation vote
    if price >= bb_upper.iloc[-1]:
        score += 1
        votes["bb"] = 1
    elif price <= bb_lower.iloc[-1]:
        score -= 1
        votes["bb"] = -1
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
    Returns (direction, info_dict) where direction is "CALL", "PUT", or None,
    according to config.STRATEGY.
    """
    if config.STRATEGY == "FCB":
        return fcb_signal(df)

    if config.STRATEGY == "POLE_POSITION":
        return pole_position_signal(df)

    # BOTH: FCB breakout triggers, Pole Position confirms before execution.
    fcb_dir, fcb_info = fcb_signal(df)
    pole_dir, pole_info = pole_position_signal(df)

    info = {"fcb": fcb_info, "pole_position": pole_info}
    if fcb_dir is not None and fcb_dir == pole_dir:
        return fcb_dir, info
    if fcb_dir is not None:
        info["reason"] = f"FCB breakout [{fcb_dir}] but Pole Position not confirmed (score={pole_info.get('score', 0)})"
    return None, info
