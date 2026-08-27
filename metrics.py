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
        self.pair = ""
        self.strategy = ""
        self.auto_trade = False
        self.account_type = ""
        self.max_trades_per_day = 0
        self.max_consecutive_losses = 0
        self.total_signals = 0
        self.call_signals = 0
        self.put_signals = 0
        self.no_signal_count = 0
        self.trades_placed = 0
        self.wins = 0
        self.losses = 0
        self.unknown_results = 0
        self.pnl_today = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self.paused = False
        self.last_signal = None
        self.last_trade = None
        self.signal_history = []
        self.trade_history = []

    @property
    def total_cycles(self):
        return self.total_signals + self.no_signal_count

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
                "info": _safe_info(info),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if direction is not None:
                self.signal_history.append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "direction": direction,
                    "price": _extract_price(info),
                })
                if len(self.signal_history) > MAX_HISTORY:
                    self.signal_history = self.signal_history[-MAX_HISTORY:]

            self._write()

    def record_trade(self, direction, amount, order_id, success):
        with self._lock:
            if success:
                self.trades_placed += 1
                self.trades_today += 1
            self.last_trade = {
                "direction": direction,
                "amount": amount,
                "order_id": str(order_id),
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._write()

    def record_result(self, result, amount):
        with self._lock:
            if result == "win":
                self.wins += 1
                self.pnl_today += amount * 0.8
            elif result == "loss":
                self.losses += 1
                self.pnl_today -= amount
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
            self.trades_today = risk_state.trades_today
            self.consecutive_losses = risk_state.consecutive_losses
            self.pnl_today = round(risk_state.pnl_today, 2)
            self.paused = risk_state.paused
            self._write()

    def set_status(self, status):
        with self._lock:
            self.status = status
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
            "pair": self.pair,
            "strategy": self.strategy,
            "auto_trade": self.auto_trade,
            "account_type": self.account_type,
            "max_trades_per_day": self.max_trades_per_day,
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
            "pnl_today": round(self.pnl_today, 2),
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "paused": self.paused,
            "last_signal": self.last_signal,
            "last_trade": self.last_trade,
            "signal_history": self.signal_history,
            "trade_history": self.trade_history,
        }


# Module-level singleton for easy access from main.py
_instance = Metrics()


def set_config(**kwargs):
    _instance.set_config(**kwargs)


def set_status(status):
    _instance.set_status(status)


def record_signal(direction, info):
    _instance.record_signal(direction, info)


def record_trade(direction, amount, order_id, success):
    _instance.record_trade(direction, amount, order_id, success)


def record_result(result, amount):
    _instance.record_result(result, amount)


def update_risk(risk_state):
    _instance.update_risk(risk_state)


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
