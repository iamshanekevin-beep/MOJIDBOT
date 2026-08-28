import logging
import time
from datetime import datetime, timezone

import config
import strategy
from broker import Broker

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
        self.paused = False

    def reset_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            log.info("New UTC day — resetting daily counters.")
            self.day = today
            self.trades_today = 0
            self.consecutive_losses = 0
            self.pnl_today = 0.0
            self.paused = False

    def can_trade(self):
        self.reset_if_new_day()
        if self.paused:
            return False, "paused after hitting a risk limit"
        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            return False, "hit MAX_TRADES_PER_DAY"
        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            self.paused = True
            return False, "hit MAX_CONSECUTIVE_LOSSES"
        if self.pnl_today <= -abs(config.DAILY_LOSS_LIMIT):
            self.paused = True
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

    while True:
        try:
            for pair in pairs:
                df = broker.get_candles_df(pair=pair)
                if df.empty:
                    continue

                latest_ts = df["timestamp"].iloc[-1]
                if latest_ts == last_candle_ts.get(pair):
                    continue  # already processed this candle
                last_candle_ts[pair] = latest_ts

                direction, info = strategy.get_signal(df)
                if direction is None:
                    log.info("No signal. pair=%s %s", pair, _summarize(info))
                    continue

                log.info("Signal: %s | pair=%s | %s", direction, pair, _summarize(info))

                if not config.AUTO_TRADE:
                    continue

                can_trade, reason = risk.can_trade()
                if not can_trade:
                    log.warning("Trade skipped — risk control: %s", reason)
                    break  # stop scanning if risk limit hit

                success, order_id = broker.place_trade(direction, pair=pair)
                risk.record_trade(config.TRADE_AMOUNT)

                if not success:
                    log.error("Trade failed: %s pair=%s", order_id, pair)
                    continue

                log.info("Trade placed: %s pair=%s amount=%s order_id=%s",
                          direction, pair, config.TRADE_AMOUNT, order_id)

            time.sleep(config.POLL_SECONDS)

        except Exception as e:
            log.error("Error in main loop: %s. Reconnecting in 15s...", e)
            time.sleep(15)
            while True:
                try:
                    broker.api = None
                    broker.connect()
                    pairs = broker.get_available_pairs()
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
