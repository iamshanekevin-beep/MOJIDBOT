"""
Main bot loop — 24/7 multi-pair trading with:
  - 1h timeframe trend analysis + 1m candle entry
  - Doji candle filtering
  - Cooldown after 3 consecutive losses, resume on clean breakout
  - Non-blocking trade tracking (scans all pairs while trades are pending)
  - Dashboard control via /logs/control.json (pause/resume + pair list)
  - No daily trade limit
"""
import json
import logging
import os
import time

import config
import metrics
import strategy
from broker import Broker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bot")

CONTROL_FILE = os.environ.get("BOT_CONTROL_FILE", "/logs/control.json")


class RiskState:
    """Simplified risk: cooldown after N consecutive losses, resume on clean breakout."""

    def __init__(self):
        self.consecutive_losses = 0
        self.pnl_total = 0.0
        self.cooldown = False

    def can_trade(self):
        if self.cooldown:
            return False, "cooldown after %d consecutive losses" % self.consecutive_losses
        return True, None

    def record_result(self, result, amount):
        if result == "win":
            self.consecutive_losses = 0
            self.pnl_total += amount * 0.8
        elif result == "loss":
            self.consecutive_losses += 1
            self.pnl_total -= amount
            if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
                self.cooldown = True
                log.warning("Entered cooldown after %d consecutive losses", self.consecutive_losses)

    def resume(self):
        self.cooldown = False
        self.consecutive_losses = 0
        log.info("Cooldown lifted — clean breakout detected, resuming trading")


class TradeTracker:
    """Track pending trades and check results without blocking the scan loop."""

    def __init__(self):
        self.pending = []

    def add(self, order_id, pair, direction, amount):
        self.pending.append({
            "order_id": order_id,
            "pair": pair,
            "direction": direction,
            "amount": amount,
            "placed_at": time.time(),
        })

    def check_completed(self, broker):
        completed = []
        still_pending = []
        min_wait = config.EXPIRATION_MINUTES * 60 + 5
        max_wait = min_wait + 120

        for t in self.pending:
            elapsed = time.time() - t["placed_at"]
            if elapsed < min_wait:
                still_pending.append(t)
                continue
            result = broker.get_trade_result(t["order_id"])
            if result != "unknown" or elapsed > max_wait:
                completed.append((t, result))
            else:
                still_pending.append(t)

        self.pending = still_pending
        return completed

    @property
    def count(self):
        return len(self.pending)


def read_control():
    """Read control file → (running, pairs)."""
    try:
        with open(CONTROL_FILE, "r") as f:
            data = json.load(f)
            return data.get("running", True), data.get("pairs", config.PAIRS)
    except (FileNotFoundError, json.JSONDecodeError):
        return True, config.PAIRS


def write_default_control():
    """Create default control file on first run."""
    try:
        os.makedirs(os.path.dirname(CONTROL_FILE), exist_ok=True)
        if not os.path.exists(CONTROL_FILE):
            with open(CONTROL_FILE, "w") as f:
                json.dump({"running": True, "pairs": config.PAIRS}, f, indent=2)
    except Exception:
        pass


def main():
    log.info("Starting bot | pairs=%s strategy=%s auto_trade=%s account=%s",
              config.PAIRS, config.STRATEGY, config.AUTO_TRADE, config.ACCOUNT_TYPE)
    metrics.set_config(pairs=config.PAIRS, strategy=config.STRATEGY,
                       auto_trade=config.AUTO_TRADE, account_type=config.ACCOUNT_TYPE,
                       max_consecutive_losses=config.MAX_CONSECUTIVE_LOSSES)
    metrics.set_status("connecting")

    if not config.IQ_EMAIL or not config.IQ_PASSWORD:
        log.error("IQ_EMAIL / IQ_PASSWORD are not set.")
        return

    write_default_control()

    broker = Broker()
    risk = RiskState()
    tracker = TradeTracker()
    last_candle_ts = {}

    # Connect to IQ Option
    while True:
        try:
            broker.connect()
            metrics.set_status("connected")
            break
        except Exception as e:
            log.error("Connection failed (%s). Retrying in 15s...", e)
            time.sleep(15)

    log.info("Bot connected — entering 24/7 trading loop (1h trend → 1m entry)")

    # Main 24/7 loop
    while True:
        try:
            # ── Read control file ──
            running, pairs = read_control()
            metrics.set_running(running)
            metrics.set_pairs(pairs)

            if not running:
                metrics.set_status("paused")
                time.sleep(config.POLL_SECONDS)
                continue

            metrics.set_status("connected")

            # ── Check pending trades for results (non-blocking) ──
            completed = tracker.check_completed(broker)
            for trade, result in completed:
                risk.record_result(result, trade["amount"])
                metrics.record_result(result, trade["amount"])
                metrics.record_pair_result(trade["pair"], result)
                log.info("Trade result: %s pair=%s direction=%s | P&L: %.2f",
                         result, trade["pair"], trade["direction"], risk.pnl_total)

                if risk.cooldown:
                    metrics.set_cooldown(True)
                    log.warning("Bot in cooldown — waiting for clean breakout to resume")
                else:
                    metrics.set_cooldown(False)

            metrics.set_pending_trades(tracker.count)
            metrics.update_risk(risk)

            if not config.AUTO_TRADE:
                time.sleep(config.POLL_SECONDS)
                continue

            # ── Scan all pairs ──
            for pair in pairs:
                try:
                    # Get 1h trend
                    df_1h = broker.get_candles_df(
                        pair=pair,
                        timeframe_seconds=config.HIGHER_TIMEFRAME_SECONDS,
                        count=config.HIGHER_TIMEFRAME_CANDLES,
                    )
                    if df_1h.empty:
                        continue
                    trend, trend_info = strategy.get_trend(df_1h)

                    # Get 1m candles
                    df = broker.get_candles_df(
                        pair=pair,
                        timeframe_seconds=config.TIMEFRAME_SECONDS,
                        count=config.CANDLE_COUNT,
                    )
                    if df.empty:
                        continue

                    latest_ts = df["timestamp"].iloc[-1]
                    if latest_ts == last_candle_ts.get(pair):
                        continue  # no new closed candle yet
                    last_candle_ts[pair] = latest_ts

                    # ── Doji filter ──
                    if strategy.is_doji(df):
                        log.info("[%s] Doji candle — skipping", pair)
                        metrics.record_signal(None, {"pair": pair, "reason": "doji", "trend_1h": trend})
                        metrics.record_pair_signal(pair, None)
                        continue

                    # ── 1m signal ──
                    direction, info = strategy.get_signal(df)
                    info["pair"] = pair
                    info["trend_1h"] = trend
                    metrics.record_signal(direction, info)
                    metrics.record_pair_signal(pair, direction)

                    if direction is None:
                        log.info("[%s] No signal. trend_1h=%s", pair, trend)
                        continue

                    # ── Trend alignment: 1m signal must match 1h trend ──
                    if trend is not None and direction != trend:
                        log.info("[%s] Signal %s doesn't match 1h trend %s — skipping",
                                 pair, direction, trend)
                        continue

                    log.info("[%s] Clean signal: %s | trend_1h=%s | %s",
                             pair, direction, trend, _summarize(info))

                    # ── Cooldown check ──
                    can_trade, reason = risk.can_trade()
                    if not can_trade:
                        if strategy.is_clean_breakout(df, direction):
                            risk.resume()
                            metrics.set_cooldown(False)
                            log.info("[%s] Clean breakout detected — resuming trading", pair)
                        else:
                            log.info("[%s] In cooldown — waiting for clean breakout", pair)
                            continue

                    # ── Place trade ──
                    success, order_id = broker.place_trade(direction, pair=pair)
                    metrics.record_trade(direction, config.TRADE_AMOUNT, order_id, success, pair=pair)
                    metrics.record_pair_trade(pair)

                    if not success:
                        log.error("[%s] Trade failed: %s", pair, order_id)
                        continue

                    tracker.add(order_id, pair, direction, config.TRADE_AMOUNT)
                    log.info("[%s] Trade placed: %s amount=%s order_id=%s",
                             pair, direction, config.TRADE_AMOUNT, order_id)

                except Exception as e:
                    log.error("[%s] Error: %s", pair, e)

            time.sleep(config.POLL_SECONDS)

        except Exception as e:
            log.error("Error in main loop: %s. Reconnecting in 15s...", e)
            metrics.set_status("error")
            time.sleep(15)
            try:
                broker.connect()
                metrics.set_status("connected")
            except Exception as e2:
                log.error("Reconnect failed: %s", e2)


def _summarize(info):
    if not isinstance(info, dict):
        return info
    keys_of_interest = ("price", "score", "reason", "upper_band", "lower_band", "trend_1h", "pair")
    parts = []
    for k in keys_of_interest:
        if k in info:
            v = info[k]
            parts.append(f"{k}={v:.5f}" if isinstance(v, float) else f"{k}={v}")
    if "fcb" in info:
        parts.append(f"fcb={_summarize(info['fcb'])}")
    if "pole_position" in info:
        parts.append(f"pole_position={_summarize(info['pole_position'])}")
    return " ".join(parts) if parts else str(info)


if __name__ == "__main__":
    main()
