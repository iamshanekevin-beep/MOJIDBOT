"""
Wrapper around the unofficial IQ Option API.

IQ Option has no official public API. This uses the community library
'iqoptionapi'. That library is maintained outside of IQ Option and can
break when IQ Option changes their backend — if connect() or fetch/trade
calls start failing, this is the file to check/patch first.

Install: pip install iqoptionapi
"""
import logging
import time
from functools import wraps

import pandas as pd
from iqoptionapi.stable_api import IQ_Option

import config

log = logging.getLogger("broker")


class Broker:
    def __init__(self):
        self.api = None

    def connect(self):
        self.api = IQ_Option(config.IQ_EMAIL, config.IQ_PASSWORD)
        check, reason = self.api.connect()
        if not check:
            raise ConnectionError(f"IQ Option login failed: {reason}")

        self.api.change_balance(config.ACCOUNT_TYPE)  # "PRACTICE" or "REAL"
        log.info("Connected to IQ Option (%s account)", config.ACCOUNT_TYPE)
        return True

    def ensure_connected(self):
        if self.api is None or not self.api.check_connect():
            log.warning("Not connected — reconnecting...")
            self.connect()

    def get_candles_df(self, pair=None, timeframe_seconds=None, count=None) -> pd.DataFrame:
        pair = pair or config.PAIR
        timeframe_seconds = timeframe_seconds or config.TIMEFRAME_SECONDS
        count = count or config.CANDLE_COUNT

        self.ensure_connected()
        raw = self.api.get_candles(pair, timeframe_seconds, count, time.time())
        df = pd.DataFrame(raw)
        # iqoptionapi candle dicts typically have: open, close, min, max, from
        df = df.rename(columns={"min": "low", "max": "high", "from": "timestamp"})
        df = df[["timestamp", "open", "high", "low", "close"]]
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def is_asset_open(self, pair=None):
        """Check if the pair is currently open for trading. Returns True/False."""
        pair = pair or config.PAIR
        try:
            open_times = self.api.get_all_open_time()
            for instrument_type in ("turbo", "binary", "digital", "forex"):
                assets = open_times.get(instrument_type, {})
                if pair in assets and assets[pair].get("open"):
                    return True
            return False
        except Exception as e:
            log.warning("Could not check asset open time: %s — assuming open", e)
            return True

    def place_trade(self, direction: str, amount=None, pair=None, expiration_minutes=None):
        """
        direction: "CALL" or "PUT"
        Returns (success: bool, order_id_or_reason)
        """
        pair = pair or config.PAIR
        amount = amount or config.TRADE_AMOUNT
        expiration_minutes = expiration_minutes or config.EXPIRATION_MINUTES
        action = "call" if direction == "CALL" else "put"

        self.ensure_connected()

        if not self.is_asset_open(pair):
            return False, f"asset {pair} is currently suspended/closed — trade skipped"

        # Try binary/turbo first, fall back to digital spot if unavailable —
        # different iqoptionapi forks expose these slightly differently.
        buy_failed_reason = None
        try:
            check, order_id = self.api.buy(amount, pair, action, expiration_minutes)
            if check:
                return True, order_id
            buy_failed_reason = f"buy() returned False: {order_id}"
        except Exception as e:
            buy_failed_reason = f"buy() raised: {e}"

        # If the asset is suspended, don't attempt the digital spot fallback —
        # it hangs indefinitely on suspended assets.
        if buy_failed_reason and "suspended" in buy_failed_reason.lower():
            return False, buy_failed_reason

        log.warning("Classic buy() failed (%s), trying digital spot...", buy_failed_reason)

        try:
            check, order_id = self.api.buy_digital_spot(pair, amount, action, expiration_minutes)
            if check:
                return True, order_id
            return False, f"digital spot returned False: {order_id} (after {buy_failed_reason})"
        except Exception as e:
            return False, f"digital spot buy failed: {e} (after {buy_failed_reason})"

    def get_trade_result(self, order_id, timeout=5):
        """Best-effort win/loss check. Returns 'win', 'loss', 'unknown'."""
        try:
            result = self.api.check_win_v4(order_id) if hasattr(self.api, "check_win_v4") else None
            if result is None:
                return "unknown"
            profit, status = result if isinstance(result, tuple) else (result, None)
            if profit is not None and profit > 0:
                return "win"
            if profit is not None and profit < 0:
                return "loss"
            return "unknown"
        except Exception as e:
            log.warning("Could not fetch trade result: %s", e)
            return "unknown"
