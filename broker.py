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

import pandas as pd
from iqoptionapi.stable_api import IQ_Option

import config

log = logging.getLogger("broker")


class Broker:
    def __init__(self):
        self.api = None
        self.open_assets = set()
        self.actives_opcode = set()
        self.active_pair = None

    def connect(self):
        self.api = IQ_Option(config.IQ_EMAIL, config.IQ_PASSWORD)
        check, reason = self.api.connect()
        if not check:
            raise ConnectionError(f"IQ Option login failed: {reason}")

        self.api.change_balance(config.ACCOUNT_TYPE)  # "PRACTICE" or "REAL"
        log.info("Connected to IQ Option (%s account)", config.ACCOUNT_TYPE)

        # Fetch the list of currently-open assets ONCE and cache it, then
        # resolve which pair to trade: keep the configured PAIR when it is
        # open, otherwise auto-switch to the first available pair.
        self._fetch_open_assets()
        self.active_pair = self._resolve_pair()
        return True

    def _fetch_open_assets(self):
        """Query IQ Option once for which binary/turbo assets are open (not suspended)."""
        self.open_assets = set()
        try:
            # get_all_init_v2() returns binary+turbo actives with enabled/is_suspended
            # flags. We avoid get_all_open_time() here because it also pulls the
            # digital list, which can stall ~30s and abort the whole call.
            init = self.api.get_all_init_v2()
            if not init:
                log.warning("Open-asset list unavailable — falling back to configured pair.")
                return
            for option in ("binary", "turbo"):
                actives = init.get(option, {}).get("actives", {})
                for active in actives.values():
                    if active.get("enabled") and not active.get("is_suspended"):
                        name = str(active.get("name", "")).split(".")[-1]
                        if name:
                            self.open_assets.add(name)
            # Cache the opcode table (active name -> id) so we only ever hand
            # get_candles() a pair it can actually resolve — handing it a name
            # that is absent from this table makes it KeyError into an infinite
            # "need reconnect" loop.
            try:
                self.actives_opcode = set(self.api.get_all_ACTIVES_OPCODE().keys())
            except Exception:
                self.actives_opcode = set()
            log.info("Found %d open assets (binary/turbo).", len(self.open_assets))
        except Exception as e:
            log.warning("Could not fetch open-asset list (%s). "
                        "Will fall back to the configured pair.", e)

    def _resolve_pair(self):
        """Use the configured PAIR if open & tradeable, else an available tradeable pair."""
        pair = config.PAIR
        # Only consider pairs the candle/trade calls can resolve (in the opcode
        # table); otherwise get_candles() KeyErrors into an infinite reconnect loop.
        usable = [p for p in sorted(self.open_assets)
                  if not self.actives_opcode or p in self.actives_opcode]
        if pair in self.open_assets and (not self.actives_opcode or pair in self.actives_opcode):
            return pair
        if usable:
            chosen = usable[0]
            log.warning("Configured pair %s is suspended/unavailable — "
                        "switching to available pair %s.", pair, chosen)
            return chosen
        log.warning("No tradeable open asset found — falling back to configured pair %s.", pair)
        return pair

    def get_active_pair(self):
        return self.active_pair or config.PAIR

    def ensure_connected(self):
        if self.api is None or not self.api.check_connect():
            log.warning("Connection dropped — reconnecting...")
            self._reconnect()

    def _reconnect(self):
        """Discard the dead websocket and create a fresh connection."""
        self.api = None
        self.connect()

    def _call_with_retry(self, fn, *args, **kwargs):
        """Call an IQ Option API method; on connection failure, reconnect and retry once."""
        try:
            self.ensure_connected()
            return fn(*args, **kwargs)
        except Exception as e:
            log.warning("API call failed (%s) — reconnecting and retrying...", e)
            self._reconnect()
            return fn(*args, **kwargs)

    def get_candles_df(self, pair=None, timeframe_seconds=None, count=None) -> pd.DataFrame:
        pair = pair or self.get_active_pair()
        timeframe_seconds = timeframe_seconds or config.TIMEFRAME_SECONDS
        count = count or config.CANDLE_COUNT

        raw = self._call_with_retry(
            self.api.get_candles, pair, timeframe_seconds, count, time.time()
        )
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
        pair = pair or self.get_active_pair()
        amount = amount or config.TRADE_AMOUNT
        expiration_minutes = expiration_minutes or config.EXPIRATION_MINUTES
        action = "call" if direction == "CALL" else "put"

        # Try binary/turbo first, fall back to digital spot if unavailable —
        # different iqoptionapi forks expose these slightly differently.
        try:
            check, order_id = self._call_with_retry(
                self.api.buy, amount, pair, action, expiration_minutes
            )
            if check:
                return True, order_id
            return False, f"buy() returned False: {order_id}"
        except Exception as e:
            log.warning("Classic buy() failed (%s), trying digital spot...", e)

        try:
            check, order_id = self._call_with_retry(
                self.api.buy_digital_spot, pair, amount, action, expiration_minutes
            )
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
