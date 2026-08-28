"""Writes live bot metrics to /logs/metrics.json for the dashboard."""
import json
import os
from datetime import datetime, timezone

METRICS_FILE = os.environ.get("BOT_METRICS_FILE", "/logs/metrics.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_metrics():
    """Return a fresh metrics dict."""
    return {
        "started_at": _now(),
        "last_update": _now(),
        "status": "connected",
        "running": True,
        "cooldown": False,
        "pending_trades": 0,
        "pair": "",
        "pairs": [],
        "strategy": "",
        "auto_trade": True,
        "account_type": "",
        "trade_amount": 0,
        "max_consecutive_losses": 0,
        "total_cycles": 0,
        "total_signals": 0,
        "call_signals": 0,
        "put_signals": 0,
        "no_signal_count": 0,
        "trades_placed": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "unknown_results": 0,
        "pnl_total": 0.0,
        "consecutive_losses": 0,
        "last_signal": {"direction": "NONE"},
        "last_trade": None,
        "signal_history": [],
        "trade_history": [],
        "placed_trades": [],
        "balance_history": [],
        "pair_stats": {},
        "signal_engine": {},
    }


def write_metrics(metrics):
    """Persist metrics dict to the JSON file."""
    metrics["last_update"] = _now()
    tmp = METRICS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(metrics, f, indent=2)
    os.replace(tmp, METRICS_FILE)
