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
        self.active_ids = {}  # pair_name -> active_id (from IQ Option runtime)
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
            # Inject runtime active IDs into the library's static ACTIVES dict so
            # get_candles/buy can resolve pair names the library doesn't know about.
            from iqoptionapi.constants import ACTIVES
            for option in ("binary", "turbo"):
                actives = init.get(option, {}).get("actives", {})
                for active in actives.values():
                    name = str(active.get("name", "")).split(".")[-1]
                    active_id = active.get("id")
                    if name and active_id is not None:
                        self.active_ids[name] = active_id
                        if name not in ACTIVES:
                            ACTIVES[name] = active_id
                    if active.get("enabled") and not active.get("is_suspended"):
                        if name:
                            self.open_assets.add(name)
            log.info("Found %d open assets (binary/turbo). %d total active IDs cached.",
                     len(self.open_assets), len(self.active_ids))
        except Exception as e:
            log.warning("Could not fetch open-asset list (%s). "
                        "Will fall back to the configured pair.", e)

    def _resolve_pair(self):
        """Use the configured PAIR if open & tradeable, else an available tradeable pair."""
        pair = config.PAIR
        if pair in self.open_assets and pair in self.active_ids:
            return pair
        usable = [p for p in sorted(self.open_assets) if p in self.active_ids]
        if usable:
            chosen = usable[0]
            log.warning("Configured pair %s is suspended/unavailable — "
                        "switching to available pair %s.", pair, chosen)
            return chosen
        log.warning("No tradeable open asset found — falling back to configured pair %s.", pair)
        return pair

    def get_active_pair(self):
        return self.active_pair or config.PAIR

    def get_available_pairs(self):
        """Return up to 10 tradeable pairs that are currently open AND resolvable by ID."""
        configured = [p.strip() for p in config.PAIRS.split(",") if p.strip()]
        # Use the runtime ID map (active_ids) instead of the static library constant,
        # since the library's opcode table is outdated and misses many OTC pairs.
        if self.open_assets:
            # Try configured pairs first (preserve user's preferred order)
            usable = [p for p in configured if p in self.open_assets and p in self.active_ids]
            if len(usable) >= 10:
                return usable[:10]
            # Fewer than 10 configured pairs available — fill with other open OTC pairs
            forex_otc = sorted([p for p in self.open_assets
                                if "OTC" in p and p in self.active_ids
                                and p not in usable
                                and len(p.replace("-OTC", "")) == 6
                                and p.replace("-OTC", "").isalpha()])
            combined = usable + forex_otc
            if len(combined) >= 10:
                return combined[:10]
            if combined:
                log.info("Using %d available pairs: %s", len(combined), ", ".join(combined[:10]))
                return combined[:10]
            # None of the configured pairs are open — fill up to 10 from available assets:
            # prefer forex OTC pairs (6-char base + -OTC), then regular OTC, then non-OTC forex
            forex_otc = sorted([p for p in self.open_assets
                                if "OTC" in p and p in self.active_ids
                                and len(p.replace("-OTC", "")) == 6
                                and p.replace("-OTC", "").isalpha()])
            other_otc = sorted([p for p in self.open_assets
                                if "OTC" in p and p in self.active_ids and p not in forex_otc])
            non_otc = sorted([p for p in self.open_assets
                              if "OTC" not in p and p in self.active_ids
                              and len(p) == 6 and p.isalpha()])
            combined = forex_otc + other_otc + non_otc
            if combined:
                log.info("Fallback: using %d available pairs: %s",
                         min(10, len(combined)), ", ".join(combined[:10]))
                return combined[:10]
        # Last resort: configured pairs that have IDs
        with_ids = [p for p in configured if p in self.active_ids]
        return with_ids if with_ids else [config.PAIR]

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
            result = fn(*args, **kwargs)
            if not result:
                raise ConnectionError(f"{fn.__name__} returned empty — reconnecting")
            return result
        except Exception as e:
            log.warning("API call failed (%s) — reconnecting and retrying...", e)
            self._reconnect()
            result = fn(*args, **kwargs)
            if not result:
                raise ConnectionError(f"{fn.__name__} returned empty after reconnect")
            return result

    def get_candles_df(self, pair=None, timeframe_seconds=None, count=None) -> pd.DataFrame:
        pair = pair or self.get_active_pair()
        timeframe_seconds = timeframe_seconds or config.TIMEFRAME_SECONDS
        count = count or config.CANDLE_COUNT

        raw = self._call_with_retry(
            self.api.get_candles, pair, timeframe_seconds, count, time.time()
        )
        if not raw:
            raise ConnectionError("get_candles returned empty/None — forcing reconnect")
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

    def get_balance(self):
        """Get current account balance."""
        try:
            self.ensure_connected()
            return self.api.get_balance()
        except Exception as e:
            log.warning("Could not get balance: %s", e)
            return None

    def get_trade_result_by_balance(self, balance_before, amount):
        """Determine win/loss by comparing balance before and after trade."""
        balance_after = self.get_balance()
        if balance_before is None or balance_after is None:
            return "unknown"
        diff = balance_after - balance_before
        if diff > 0:
            return "win"
        elif diff < 0:
            return "loss"
        return "unknown"
