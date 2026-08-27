"""
Metrics tracker for the trading bot.
Writes a JSON snapshot to /logs/metrics.json that the dashboard reads.
Thread-safe singleton — imported by main.py, read by log_viewer.py.
"""
import json
import os
import threading
from datetime import datetime, timezone

METRICS_FILE = os.environ.get("BOT_METRICS_FILE", "/logs/metrics.json")
MAX_HISTORY = 100


class Metrics:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.status = "starting"
        self.running = True
        self.cooldown = False
        self.pending_trades = 0
        self.pair = ""
        self.pairs = []
        self.strategy = ""
        self.auto_trade = False
        self.account_type = ""
        self.trade_amount = 0.0
        self.max_consecutive_losses = 0
        self.total_signals = 0
        self.call_signals = 0
        self.put_signals = 0
        self.no_signal_count = 0
        self.trades_placed = 0
        self.wins = 0
        self.losses = 0
        self.unknown_results = 0
        self.pnl_total = 0.0
        self.consecutive_losses = 0
        self.last_signal = None
        self.last_trade = None
        self.signal_history = []
        self.trade_history = []
        self.pair_stats = {}
        self.signal_engine = {}  # {pair: {state, candle_open, candle_close, price, trend_1h, direction}}

    @property
    def total_cycles(self):
        return self.total_signals + self.no_signal_count

    # ─── Per-pair tracking ──────────────────────────────────────

    def _ensure_pair(self, pair):
        if pair not in self.pair_stats:
            self.pair_stats[pair] = {"signals": 0, "trades": 0, "wins": 0, "losses": 0}

    def record_pair_signal(self, pair, direction):
        with self._lock:
            self._ensure_pair(pair)
            if direction is not None:
                self.pair_stats[pair]["signals"] += 1

    def record_pair_trade(self, pair):
        with self._lock:
            self._ensure_pair(pair)
            self.pair_stats[pair]["trades"] += 1

    def record_pair_result(self, pair, result):
        with self._lock:
            self._ensure_pair(pair)
            if result == "win":
                self.pair_stats[pair]["wins"] += 1
            elif result == "loss":
                self.pair_stats[pair]["losses"] += 1

    # ─── Overall tracking ───────────────────────────────────────

    def record_signal(self, direction, info):
        with self._lock:
            if direction is None:
                self.no_signal_count += 1
            else:
                self.total_signals += 1
                if direction == "CALL":
                    self.call_signals += 1
                else:
                    self.put_signals += 1

            self.last_signal = {
                "direction": direction or "NONE",
                "pair": (info or {}).get("pair", ""),
                "info": _safe_info(info),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if direction is not None:
                self.signal_history.append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "direction": direction,
                    "pair": (info or {}).get("pair", ""),
                    "price": _extract_price(info),
                })
                if len(self.signal_history) > MAX_HISTORY:
                    self.signal_history = self.signal_history[-MAX_HISTORY:]

            self._write()

    def record_trade(self, direction, amount, order_id, success, pair=None):
        with self._lock:
            if success:
                self.trades_placed += 1
            self.last_trade = {
                "direction": direction,
                "amount": amount,
                "order_id": str(order_id),
                "success": success,
                "pair": pair or "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._write()

    def record_result(self, result, amount):
        with self._lock:
            if result == "win":
                self.wins += 1
                self.pnl_total += amount * 0.8
            elif result == "loss":
                self.losses += 1
                self.pnl_total -= amount
            else:
                self.unknown_results += 1

            self.trade_history.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "result": result,
                "amount": amount,
            })
            if len(self.trade_history) > MAX_HISTORY:
                self.trade_history = self.trade_history[-MAX_HISTORY:]
            self._write()

    def update_risk(self, risk_state):
        with self._lock:
            self.consecutive_losses = risk_state.consecutive_losses
            self.pnl_total = round(risk_state.pnl_total, 2)
            self.cooldown = risk_state.cooldown
            self._write()

    # ─── State setters ──────────────────────────────────────────

    def set_status(self, status):
        with self._lock:
            self.status = status
            self._write()

    def set_running(self, running):
        with self._lock:
            self.running = running
            self._write()

    def set_cooldown(self, cooldown):
        with self._lock:
            self.cooldown = cooldown
            self._write()

    def set_pending_trades(self, count):
        with self._lock:
            self.pending_trades = count
            self._write()

    def set_pairs(self, pairs):
        with self._lock:
            self.pairs = list(pairs)
            self._write()

    def set_signal_engine(self, pair, state, candle_open, candle_close, price, trend_1h, direction):
        with self._lock:
            self.signal_engine[pair] = {
                "state": state,
                "candle_open": candle_open,
                "candle_close": candle_close,
                "price": price,
                "trend_1h": trend_1h,
                "direction": direction,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write()

    def set_config(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)
            self._write()

    def _write(self):
        try:
            tmp = METRICS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.to_dict(), f)
            os.replace(tmp, METRICS_FILE)
        except Exception:
            pass

    def to_dict(self):
        return {
            "started_at": self.started_at,
            "last_update": datetime.now(timezone.utc).isoformat(),
            "status": self.status,
            "running": self.running,
            "cooldown": self.cooldown,
            "pending_trades": self.pending_trades,
            "pair": self.pair,
            "pairs": self.pairs,
            "strategy": self.strategy,
            "auto_trade": self.auto_trade,
            "account_type": self.account_type,
            "max_consecutive_losses": self.max_consecutive_losses,
            "total_cycles": self.total_cycles,
            "total_signals": self.total_signals,
            "call_signals": self.call_signals,
            "put_signals": self.put_signals,
            "no_signal_count": self.no_signal_count,
            "trades_placed": self.trades_placed,
            "wins": self.wins,
            "losses": self.losses,
            "unknown_results": self.unknown_results,
            "pnl_total": round(self.pnl_total, 2),
            "consecutive_losses": self.consecutive_losses,
            "last_signal": self.last_signal,
            "last_trade": self.last_trade,
            "signal_history": self.signal_history,
            "trade_history": self.trade_history,
            "pair_stats": self.pair_stats,
            "signal_engine": self.signal_engine,
        }


# ─── Module-level singleton wrappers ──────────────────────────────

_instance = Metrics()

def set_config(**kwargs):       _instance.set_config(**kwargs)
def set_status(status):         _instance.set_status(status)
def set_running(running):       _instance.set_running(running)
def set_cooldown(cooldown):     _instance.set_cooldown(cooldown)
def set_pending_trades(count):  _instance.set_pending_trades(count)
def set_pairs(pairs):           _instance.set_pairs(pairs)
def record_signal(d, info):     _instance.record_signal(d, info)
def record_trade(d, a, oid, s, pair=None): _instance.record_trade(d, a, oid, s, pair)
def record_result(r, a):        _instance.record_result(r, a)
def update_risk(rs):            _instance.update_risk(rs)
def record_pair_signal(p, d):   _instance.record_pair_signal(p, d)
def record_pair_trade(p):      _instance.record_pair_trade(p)
def record_pair_result(p, r):   _instance.record_pair_result(p, r)
def set_signal_engine(pair, state, candle_open, candle_close, price, trend_1h, direction):
    _instance.set_signal_engine(pair, state, candle_open, candle_close, price, trend_1h, direction)


# ─── Helpers ──────────────────────────────────────────────────────

def _safe_info(info):
    if not isinstance(info, dict):
        return str(info)
    safe = {}
    for k, v in info.items():
        if isinstance(v, (int, float, str, bool, type(None))):
            safe[k] = v
        elif isinstance(v, dict):
            safe[k] = _safe_info(v)
        else:
            safe[k] = str(v)
    return safe


def _extract_price(info):
    if isinstance(info, dict):
        if "price" in info and isinstance(info["price"], (int, float)):
            return info["price"]
        for k in ("fcb", "pole_position"):
            if k in info and isinstance(info[k], dict) and "price" in info[k]:
                p = info[k]["price"]
                if isinstance(p, (int, float)):
                    return p
    return None
