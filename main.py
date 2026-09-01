import logging
import time
from datetime import datetime, timedelta, timezone

import config
import strategy
from broker import Broker
from notifier import notify
import metrics_writer
import telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bot")


class RiskState:
    def __init__(self):
        self.trades_today = 0
        self.consecutive_losses = 0
        self.pnl_today = 0.0
        self.day = datetime.now(timezone.utc).date()
        self.cooldown_until = None  # datetime when cooldown ends

    def reset_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            log.info("New UTC day — resetting daily counters.")
            self.day = today
            self.trades_today = 0
            self.consecutive_losses = 0
            self.pnl_today = 0.0
            self.cooldown_until = None

    def can_trade(self):
        self.reset_if_new_day()
        if self.cooldown_until is not None:
            now = datetime.now(timezone.utc)
            if now < self.cooldown_until:
                remaining = (self.cooldown_until - now).total_seconds() / 60
                return False, f"cooldown ({remaining:.0f}m remaining) — bot still hunting"
            # Cooldown expired — resume trading
            log.info("Cooldown expired — resuming trading.")
            self.cooldown_until = None
            self.consecutive_losses = 0
        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            return False, "hit MAX_TRADES_PER_DAY"
        if self.pnl_today <= -abs(config.DAILY_LOSS_LIMIT):
            return False, "hit DAILY_LOSS_LIMIT"
        return True, None

    def record_trade(self, amount):
        self.trades_today += 1

    def record_result(self, result, amount):
        if result == "win":
            self.consecutive_losses = 0
            self.pnl_today += amount * 0.8  # approximate payout, adjust to your actual payout %
        elif result == "loss":
            self.consecutive_losses += 1
            self.pnl_today -= amount
            if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
                self.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=config.COOLDOWN_MINUTES)
                log.warning("Hit %d consecutive losses — %d-minute cooldown started. Bot keeps hunting.",
                           config.MAX_CONSECUTIVE_LOSSES, config.COOLDOWN_MINUTES)
                telegram_bot.send_cooldown_card(config.MAX_CONSECUTIVE_LOSSES, config.COOLDOWN_MINUTES)


def main():
    log.info("Starting bot | strategy=%s auto_trade=%s account=%s",
              config.STRATEGY, config.AUTO_TRADE, config.ACCOUNT_TYPE)

    if not config.IQ_EMAIL or not config.IQ_PASSWORD:
        log.error("IQ_EMAIL / IQ_PASSWORD are not set. Set them in Railway's Variables tab.")
        return

    broker = Broker()
    risk = RiskState()

    while True:
        try:
            broker.connect()
            break
        except Exception as e:
            log.error("Connection failed (%s). Retrying in 15s...", e)
            time.sleep(15)

    pairs = broker.get_available_pairs()
    log.info("Scanning %d pairs: %s", len(pairs), ", ".join(pairs))
    last_candle_ts = {}  # pair -> last processed candle timestamp
    warming_up = True  # first scan cycle observes only — no blind trades

    # Live metrics state
    metrics = metrics_writer.init_metrics()
    metrics["pairs"] = pairs
    metrics["strategy"] = config.STRATEGY
    metrics["auto_trade"] = config.AUTO_TRADE
    metrics["account_type"] = config.ACCOUNT_TYPE
    metrics["trade_amount"] = config.TRADE_AMOUNT
    metrics["max_consecutive_losses"] = config.MAX_CONSECUTIVE_LOSSES
    metrics_writer.write_metrics(metrics)

    # Start Telegram command controller
    tg = telegram_bot.TelegramController(broker, risk, metrics)
    tg.start()
    telegram_bot.send_started()

    while True:
        try:
            metrics["total_cycles"] += 1

            # Update live metrics from risk state for dashboard
            metrics["consecutive_losses"] = risk.consecutive_losses
            metrics["cooldown"] = risk.cooldown_until is not None and datetime.now(timezone.utc) < risk.cooldown_until
            metrics["pnl_today"] = round(risk.pnl_today, 2)
            metrics["trades_today"] = risk.trades_today
            metrics["max_trades_per_day"] = config.MAX_TRADES_PER_DAY
            metrics["expiration_minutes"] = config.EXPIRATION_MINUTES
            # Fetch balance every 20 cycles (~100s) to avoid API spam
            if metrics["total_cycles"] % 20 == 0:
                bal = broker.get_balance()
                if bal is not None:
                    metrics["balance"] = round(bal, 2)
                    metrics["balance_history"].append({"ts": datetime.now(timezone.utc).isoformat(), "balance": bal})
                    metrics["balance_history"] = metrics["balance_history"][-100:]

            # Update running status from Telegram/dashboard pause state
            if tg.is_paused():
                metrics["running"] = False
                metrics["status"] = "paused"
            else:
                metrics["running"] = True
                metrics["status"] = "connected"

            # Check dashboard controls every cycle (pause, account, stake, force scan)
            tg.check_dashboard_control()

            # Check if account switch requested via Telegram or dashboard
            if tg.check_reconnect():
                log.info("Account switch requested — reconnecting...")
                broker.api = None
                broker.connect()
                pairs = broker.get_available_pairs()
                warming_up = True
                log.info("Reconnected on %s account. Scanning %d pairs.", config.ACCOUNT_TYPE, len(pairs))

            for pair in pairs:
                df = broker.get_candles_df(pair=pair)
                if df.empty:
                    continue

                latest_ts = df["timestamp"].iloc[-1]
                if latest_ts == last_candle_ts.get(pair):
                    continue  # already processed this candle
                last_candle_ts[pair] = latest_ts

                # Warmup: observe the first candle of each pair without trading
                if warming_up:
                    continue

                direction, info = strategy.get_signal(df)

                if direction is None:
                    metrics["no_signal_count"] += 1
                    log.info("No signal. pair=%s %s", pair, _summarize(info))
                    metrics_writer.write_metrics(metrics)
                    continue

                # Record signal
                metrics["total_signals"] += 1
                if direction == "CALL":
                    metrics["call_signals"] += 1
                else:
                    metrics["put_signals"] += 1
                metrics["last_signal"] = {
                    "direction": direction, "pair": pair, "info": info,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                metrics["signal_history"].append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "direction": direction, "pair": pair,
                    "price": df["close"].iloc[-1],
                })
                # Keep last 50 signals
                metrics["signal_history"] = metrics["signal_history"][-50:]

                log.info("Signal: %s | pair=%s | %s", direction, pair, _summarize(info))

                # Telegram styled signal card
                telegram_bot.send_signal_card(direction, pair, info)

                if not config.AUTO_TRADE:
                    metrics_writer.write_metrics(metrics)
                    continue

                # Check Telegram/dashboard pause
                if tg.is_paused():
                    metrics["running"] = False
                    metrics["status"] = "paused"
                    metrics_writer.write_metrics(metrics)
                    continue

                # Sync config changes from dashboard/Telegram to metrics
                metrics["account_type"] = config.ACCOUNT_TYPE
                metrics["trade_amount"] = config.TRADE_AMOUNT
                metrics["running"] = not tg.is_paused()

                can_trade, reason = risk.can_trade()
                if not can_trade:
                    log.warning("Trade skipped — risk control: %s", reason)
                    metrics_writer.write_metrics(metrics)
                    continue  # keep scanning/hunting for signals

                balance_before = broker.get_balance()
                success, order_id = broker.place_trade(direction, pair=pair)
                risk.record_trade(config.TRADE_AMOUNT)

                if not success:
                    log.error("Trade failed: %s pair=%s", order_id, pair)
                    metrics_writer.write_metrics(metrics)
                    continue

                metrics["trades_placed"] += 1
                trade_entry = {
                    "pair": pair, "direction": direction, "amount": config.TRADE_AMOUNT,
                    "order_id": str(order_id), "status": "placed",
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                metrics["last_trade"] = trade_entry
                metrics["trade_history"].append(trade_entry)
                metrics["trade_history"] = metrics["trade_history"][-50:]
                metrics["placed_trades"].append(trade_entry)
                metrics["placed_trades"] = metrics["placed_trades"][-20:]

                log.info("Trade placed: %s pair=%s amount=%s order_id=%s",
                          direction, pair, config.TRADE_AMOUNT, order_id)
                metrics_writer.write_metrics(metrics)

                # Wait for trade to expire, then check result via balance diff
                wait_secs = config.EXPIRATION_MINUTES * 60 + 30
                log.info("Waiting %ds for trade result (order_id=%s)...", wait_secs, order_id)
                time.sleep(wait_secs)
                balance_after = broker.get_balance()
                profit = (balance_after - balance_before) if (balance_before is not None and balance_after is not None) else None
                result = broker.get_trade_result_by_balance(balance_before, config.TRADE_AMOUNT)
                risk.record_result(result, config.TRADE_AMOUNT)

                if result == "win":
                    log.info("Trade WON: %s pair=%s order_id=%s", direction, pair, order_id)
                elif result == "loss":
                    log.info("Trade LOST: %s pair=%s order_id=%s", direction, pair, order_id)
                else:
                    log.info("Trade result unknown: %s pair=%s order_id=%s", direction, pair, order_id)

                # Styled trade result card
                telegram_bot.send_trade_card(direction, pair, config.TRADE_AMOUNT, result, profit)

                metrics_writer.write_metrics(metrics)

            if warming_up:
                warming_up = False
                log.info("Warmup complete — now watching for confirmed signals.")

            if tg.check_force_scan():
                continue  # skip sleep, scan immediately
            time.sleep(config.POLL_SECONDS)

        except Exception as e:
            log.error("Error in main loop: %s. Reconnecting in 15s...", e)
            time.sleep(15)
            while True:
                try:
                    broker.api = None
                    broker.connect()
                    pairs = broker.get_available_pairs()
                    warming_up = True
                    log.info("Reconnected. Scanning %d pairs: %s", len(pairs), ", ".join(pairs))
                    break
                except Exception as e2:
                    log.error("Reconnect failed: %s. Retrying in 30s...", e2)
                    time.sleep(30)


def _summarize(info):
    if not isinstance(info, dict):
        return info
    keys_of_interest = ("price", "score", "reason", "upper_band", "lower_band")
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
