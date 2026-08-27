"""
Wrapper around the unofficial IQ Option API.

IQ Option has no official public API. This uses the community library
'iqoptionapi'. That library can break when IQ Option changes their backend.

Key fix: the library's get_candles() has an infinite while-True loop that
calls its own broken self.connect() when the websocket dies, hanging forever.
We monkey-patch it to return None on failure so the broker can force a clean
reconnect (new IQ_Option object).
"""
import logging
import time

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
        self._patch_get_candles()
        log.info("Connected to IQ Option (%s account)", config.ACCOUNT_TYPE)
        return True

    def _patch_get_candles(self):
        """Monkey-patch the library's get_candles to remove its infinite while-True loop.

        The original hangs forever calling its own broken self.connect() when the
        websocket dies.  This version tries once, waits up to 5s for data, and
        returns None on failure — so get_candles_df can force a clean reconnect.
        """
        from iqoptionapi.stable_api import OP_code
        iq = self.api  # the IQ_Option instance

        def safe_get_candles(ACTIVES, interval, count, endtime):
            try:
                iq.api.candles.candles_data = None
                iq.api.getcandles(OP_code.ACTIVES[ACTIVES], interval, count, endtime)
                for _ in range(50):  # wait up to 5 seconds
                    if iq.api.candles.candles_data is not None:
                        return iq.api.candles.candles_data
                    time.sleep(0.1)
                return None  # timeout — websocket likely dead
            except Exception:
                return None

        iq.get_candles = safe_get_candles

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
        if raw is None:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        # iqoptionapi candle dicts typically have: open, close, min, max, from
        df = df.rename(columns={"min": "low", "max": "high", "from": "timestamp"})
        df = df[["timestamp", "open", "high", "low", "close"]]
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

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

        # Try binary/turbo first, fall back to digital spot if unavailable —
        # different iqoptionapi forks expose these slightly differently.
        try:
            check, order_id = self.api.buy(amount, pair, action, expiration_minutes)
            if check:
                return True, order_id
            return False, f"buy() returned False: {order_id}"
        except Exception as e:
            log.warning("Classic buy() failed (%s), trying digital spot...", e)

        try:
            check, order_id = self.api.buy_digital_spot(pair, amount, action, expiration_minutes)
            return check, order_id
        except Exception as e:
            return False, f"digital spot buy failed: {e}"

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
