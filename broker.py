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
        self._patch_api()
        log.info("Connected to IQ Option (%s account)", config.ACCOUNT_TYPE)
        return True

    def _patch_api(self):
        """Monkey-patch the library to remove infinite while-True blocking loops.

        get_candles, buy_digital_spot, and check_win_digital_v2 all have
        unbounded `while x == None: pass` loops that hang forever when the
        websocket is unresponsive.  Each is replaced with a timeout-bounded version.
        """
        from iqoptionapi.stable_api import OP_code
        from datetime import datetime, timedelta
        from iqoptionapi.expiration import get_expiration_time
        import logging as _logging
        iq = self.api

        # --- get_candles: 5s timeout ---
        def safe_get_candles(ACTIVES, interval, count, endtime):
            try:
                iq.api.candles.candles_data = None
                iq.api.getcandles(OP_code.ACTIVES[ACTIVES], interval, count, endtime)
                for _ in range(50):
                    if iq.api.candles.candles_data is not None:
                        return iq.api.candles.candles_data
                    time.sleep(0.1)
                return None
            except Exception:
                return None

        # --- buy_digital_spot: 10s timeout ---
        def safe_buy_digital_spot(active, amount, action, duration):
            if action == 'put':
                action = 'P'
            elif action == 'call':
                action = 'C'
            else:
                _logging.error('buy_digital_spot action error')
                return False, "invalid action"

            timestamp = int(iq.api.timesync.server_timestamp)
            if duration == 1:
                exp, _ = get_expiration_time(timestamp, duration)
            else:
                now_date = datetime.fromtimestamp(timestamp) + timedelta(minutes=1, seconds=30)
                while True:
                    if now_date.minute % duration == 0 and time.mktime(now_date.timetuple()) - timestamp > 30:
                        break
                    now_date = now_date + timedelta(minutes=1)
                exp = time.mktime(now_date.timetuple())

            date_formated = str(datetime.utcfromtimestamp(exp).strftime("%Y%m%d%H%M"))
            instrument_id = "do" + active + date_formated + "PT" + str(duration) + "M" + action + "SPT"
            iq.api.digital_option_placed_id = None
            iq.api.place_digital_option(instrument_id, amount)

            for _ in range(100):  # 10s timeout
                if iq.api.digital_option_placed_id is not None:
                    break
                time.sleep(0.1)

            if isinstance(iq.api.digital_option_placed_id, int):
                return True, iq.api.digital_option_placed_id
            return False, iq.api.digital_option_placed_id or "timeout"

        # --- check_win_digital_v2: 120s timeout ---
        def safe_check_win_digital_v2(buy_order_id):
            for _ in range(1200):  # 120s timeout
                try:
                    order = iq.get_async_order(buy_order_id)
                    if order and order.get("position-changed") != {}:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                return False, None  # timeout — trade still pending

            try:
                order_data = iq.get_async_order(buy_order_id)["position-changed"]["msg"]
            except Exception:
                return False, None

            if order_data is not None:
                if order_data.get("status") == "closed":
                    if order_data.get("close_reason") == "expired":
                        return True, order_data["close_profit"] - order_data["invest"]
                    elif order_data.get("close_reason") == "default":
                        return True, order_data["pnl_realized"]
                else:
                    return False, None
            return False, None

        # --- get_betinfo: 10s timeout (no infinite reconnect loop) ---
        def safe_get_betinfo(id_number):
            iq.api.game_betinfo.isSuccessful = None
            start = time.time()
            try:
                iq.api.get_betinfo(id_number)
            except Exception:
                return False, None
            while time.time() - start < 10:
                if iq.api.game_betinfo.isSuccessful is not None:
                    if iq.api.game_betinfo.isSuccessful:
                        return True, iq.api.game_betinfo.dict
                    return False, None
                time.sleep(0.5)
            return False, None  # timeout

        # --- check_win_v2: 60s timeout (binary trade result check) ---
        def safe_check_win_v2(id_number, polling_time=1):
            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    check, data = iq.get_betinfo(id_number)
                    if check and data:
                        win = data["result"]["data"][str(id_number)]["win"]
                        if win != "":
                            try:
                                profit = (data["result"]["data"][str(id_number)]["profit"]
                                          - data["result"]["data"][str(id_number)]["deposit"])
                                return profit
                            except (KeyError, TypeError):
                                pass
                except Exception:
                    pass
                time.sleep(polling_time)
            return None  # timeout

        iq.get_candles = safe_get_candles
        iq.buy_digital_spot = safe_buy_digital_spot
        iq.check_win_digital_v2 = safe_check_win_digital_v2
        iq.check_win_v2 = safe_check_win_v2
        iq.get_betinfo = safe_get_betinfo

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

        # Binary/turbo buy() — works for most OTC pairs.
        check, order_id = self.api.buy(amount, pair, action, expiration_minutes)
        if check:
            return True, order_id
        log.warning("buy() failed for %s: %s", pair, order_id)
        return False, str(order_id)

    def get_trade_result(self, order_id, timeout=5):
        """Check binary trade result. Returns 'win', 'loss', 'draw', 'unknown'."""
        try:
            profit = self.api.check_win_v2(order_id, 2)
            if profit is None:
                return "unknown"
            if profit > 0:
                return "win"
            if profit < 0:
                return "loss"
            return "draw"
        except Exception as e:
            log.warning("Could not fetch trade result: %s", e)
            return "unknown"
