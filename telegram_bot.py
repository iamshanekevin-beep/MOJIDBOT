"""
Telegram command handler + styled signal cards for MOJIDTRADEBOT v3.

Sends HTML-formatted signal/trade/cooldown cards and runs a background
thread that listens for keyboard commands (pause, resume, status, etc.).
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger("telegram_bot")

BOT_TOKEN = os.getenv("TELEGRAM", "")
CHAT_ID = os.getenv("TELEGRAM_USER_ID", "")

# --- Control keyboard (persistent ReplyKeyboardMarkup) ---
KEYBOARD = {
    "keyboard": [
        [{"text": "⏸ Pause"}, {"text": "▶️ Resume"}],
        [{"text": "📊 Status"}, {"text": "📈 Pairs"}],
        [{"text": "⏰ Timeframe"}, {"text": "💰 Amount"}],
        [{"text": "🎯 Demo"}, {"text": "🔴 Live"}],
        [{"text": "🧠 Strategy"}, {"text": "🔥 Fire"}],
        [{"text": "❓ Help"}],
    ],
    "resize_keyboard": True,
}


# ── low-level send ──────────────────────────────────────────────────────────

def _send_message(text, reply_markup=None):
    if not BOT_TOKEN or not CHAT_ID:
        return
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload, timeout=10,
        )
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


def _now_utc():
    return datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")


# ── card builders ───────────────────────────────────────────────────────────

def _extract_metrics(info):
    """Pull RSI, score, price out of the info dict for any strategy mode."""
    rsi = score = price = None
    if not isinstance(info, dict):
        return rsi, score, price

    if "pole_position" in info and isinstance(info["pole_position"], dict):
        pole = info["pole_position"]
        rsi = pole.get("rsi")
        score = pole.get("score")
        price = pole.get("price")
    elif "fcb" in info and isinstance(info["fcb"], dict):
        price = info["fcb"].get("price")

    if rsi is None:
        rsi = info.get("rsi")
    if score is None:
        score = info.get("score")
    if price is None:
        price = info.get("price")
    return rsi, score, price


def _confidence_bar(pct):
    filled = round(pct / 10)
    return "▰" * filled + "▱" * (10 - filled)


def _rsi_label(rsi):
    if rsi is None:
        return "N/A", "N/A"
    if rsi >= 55:
        return f"{rsi:.1f}", "BULLISH"
    if rsi <= 45:
        return f"{rsi:.1f}", "BEARISH"
    return f"{rsi:.1f}", "NEUTRAL"


def send_signal_card(direction, pair, info):
    """Styled signal alert card (green for CALL, red for PUT)."""
    import config
    rsi, score, price = _extract_metrics(info)

    if direction == "CALL":
        icon, setup = "🟢", "bullish order-flow CALL"
    else:
        icon, setup = "🔴", "bearish order-flow PUT"

    confidence = min(95, abs(score) * 20 + 25) if score is not None else 85
    rsi_str, rsi_lbl = _rsi_label(rsi)
    price_str = f"{price:.5f}" if price is not None else "N/A"
    rsi_suffix = f" (RSI {rsi:.1f})" if rsi is not None else ""

    msg = (
        f"<b>{icon} MOJIDTRADEBOT v3</b>\n"
        f"<i>Forex OTC Signal</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{icon} {direction}</b> · STRONG SIGNAL\n\n"
        f"<b>{pair}</b>\n\n"
        f"CONFIDENCE: <b>{confidence}%</b>\n"
        f"{_confidence_bar(confidence)}\n\n"
        f"📊 RSI: <b>{rsi_str}</b>  {rsi_lbl}\n"
        f"💵 ENTRY: <b>{price_str}</b>  PRICE\n"
        f"⏱ EXPIRY: <b>{config.EXPIRATION_MINUTES} MIN</b>  TURBO\n\n"
        f"SETUP: {setup}{rsi_suffix}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"MOJIDTRADEBOT · {_now_utc()}"
    )
    _send_message(msg)


def send_trade_card(direction, pair, amount, result, profit=None):
    """Styled trade result card (WON = green, LOST = red)."""
    import config
    acct = "REAL" if config.ACCOUNT_TYPE == "REAL" else "DEMO"

    if result == "win":
        icon, result_text, label = "🟢", "TRADE WON", "WIN"
        profit_str = f"+${profit:.2f}" if profit is not None else f"+${amount * 0.8:.2f}"
    elif result == "loss":
        icon, result_text, label = "🔴", "TRADE LOST", "LOSS"
        profit_str = f"-${amount:.2f}" if profit is not None else f"-${amount:.2f}"
    else:
        icon, result_text, label, profit_str = "⚪", "RESULT PENDING", "PENDING", "—"

    msg = (
        f"<b>{icon} MOJIDTRADEBOT v3</b>\n"
        f"<i>{result_text}</i>  ·  <code>{config.EXPIRATION_MINUTES}M</code>  <code>{acct}</code>\n\n"
        f"<b>{profit_str}</b>\n"
        f"{result_text}\n\n"
        f"<b>{pair}</b>\n\n"
        f"PAIR: {pair}\n"
        f"STAKE: ${amount:.1f}  AMOUNT\n"
        f"RESULT: {label}  CLOSED\n\n"
        f"MOJIDTRADEBOT · {_now_utc()}"
    )
    _send_message(msg)


def send_cooldown_card(losses, minutes):
    """Cooldown notification card."""
    msg = (
        f"<b>⏸ MOJIDTRADEBOT v3</b>\n"
        f"<i>COOLDOWN ACTIVE</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⛔ {losses} consecutive losses\n"
        f"⏱ {minutes}m cooldown started\n"
        f"🔍 Bot still hunting for signals\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"MOJIDTRADEBOT · {_now_utc()}"
    )
    _send_message(msg)


def send_started():
    """Startup message with control keyboard attached."""
    import config
    acct = "REAL" if config.ACCOUNT_TYPE == "REAL" else "DEMO"
    msg = (
        f"<b>🤖 MOJIDTRADEBOT v3</b>\n"
        f"<i>Bot started and scanning</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Strategy: <b>{config.STRATEGY}</b> (FCB + Pole Position)\n"
        f"Account: <b>{acct}</b>\n"
        f"Stake: <b>${config.TRADE_AMOUNT:.2f}</b>\n"
        f"Pairs: <b>{len(config.PAIRS.split(','))}</b> active\n\n"
        f"Use the keyboard below to control the bot."
    )
    _send_message(msg, reply_markup=KEYBOARD)


# ── command controller (background thread) ──────────────────────────────────

class TelegramController:
    """Listens for Telegram commands and controls the bot at runtime."""

    def __init__(self, broker, risk, metrics):
        self.broker = broker
        self.risk = risk
        self.metrics = metrics
        self.paused = False
        self.need_reconnect = False
        self.force_scan = False
        self._lock = threading.Lock()
        self._offset = 0

    def start(self):
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()
        log.info("Telegram command listener started")

    # ── main poll loop ────────────────────────────────────────────────────

    def _listen(self):
        while True:
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                    timeout=35,
                )
                for update in resp.json().get("result", []):
                    self._offset = update["update_id"] + 1
                    text = (update.get("message") or {}).get("text", "").strip()
                    if text:
                        self._handle_command(text)
            except Exception as e:
                log.warning("Telegram poll failed: %s", e)
                time.sleep(5)

    # ── command dispatch ──────────────────────────────────────────────────

    def _handle_command(self, text):
        # Numeric input → set stake amount
        try:
            val = float(text.replace("$", "").replace(",", ""))
            if val > 0:
                import config
                config.TRADE_AMOUNT = val
                _send_message(f"✅ Stake set to <b>${val:.2f}</b>")
                return
        except ValueError:
            pass

        handlers = {
            "⏸ Pause": self._cmd_pause,
            "▶️ Resume": self._cmd_resume,
            "📊 Status": self._cmd_status,
            "📈 Pairs": self._cmd_pairs,
            "⏰ Timeframe": self._cmd_timeframe,
            "💰 Amount": self._cmd_amount,
            "🎯 Demo": self._cmd_demo,
            "🔴 Live": self._cmd_live,
            "🧠 Strategy": self._cmd_strategy,
            "🔥 Fire": self._cmd_fire,
            "❓ Help": self._cmd_help,
            "/start": self._cmd_start,
        }
        handler = handlers.get(text)
        if handler:
            handler()

    # ── individual commands ───────────────────────────────────────────────

    def _cmd_pause(self):
        with self._lock:
            self.paused = True
        _send_message("⏸ <b>Bot Paused</b>\nBot stops trading but keeps scanning for signals.")

    def _cmd_resume(self):
        with self._lock:
            self.paused = False
        _send_message("▶️ <b>Bot Resumed</b>\nBot is trading again.")

    def _cmd_status(self):
        import config
        balance = self.broker.get_balance() if self.broker else None
        bal_str = f"${balance:.2f}" if balance is not None else "N/A"
        state = "⏸ PAUSED" if self.paused else "▶️ RUNNING"

        cooldown_str = ""
        if self.risk and self.risk.cooldown_until:
            now = datetime.now(timezone.utc)
            if now < self.risk.cooldown_until:
                remaining = (self.risk.cooldown_until - now).total_seconds() / 60
                cooldown_str = f"\n⏱ Cooldown: <b>{remaining:.0f}m remaining</b>"

        pnl = self.risk.pnl_today if self.risk else 0
        losses = self.risk.consecutive_losses if self.risk else 0
        trades = self.risk.trades_today if self.risk else 0

        msg = (
            f"<b>📊 BOT STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"State: <b>{state}</b>\n"
            f"Account: <b>{config.ACCOUNT_TYPE}</b>\n"
            f"Balance: <b>{bal_str}</b>\n"
            f"Stake: <b>${config.TRADE_AMOUNT:.2f}</b>\n"
            f"Strategy: <b>{config.STRATEGY}</b>\n\n"
            f"Trades Today: <b>{trades}</b>\n"
            f"P&L Today: <b>${pnl:.2f}</b>\n"
            f"Consecutive Losses: <b>{losses}</b>{cooldown_str}"
        )
        _send_message(msg)

    def _cmd_pairs(self):
        import config
        _send_message(f"<b>📈 ACTIVE PAIRS</b>\n━━━━━━━━━━━━━━━━━━\n{config.PAIRS}")

    def _cmd_timeframe(self):
        import config
        label = "1 MIN" if config.TIMEFRAME_SECONDS == 60 else f"{config.TIMEFRAME_SECONDS}s"
        _send_message(
            f"<b>⏰ TIMEFRAME</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Candle: <b>{label}</b>\nExpiry: <b>{config.EXPIRATION_MINUTES} MIN</b>"
        )

    def _cmd_amount(self):
        import config
        _send_message(
            f"<b>💰 TRADE AMOUNT</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Current stake: <b>${config.TRADE_AMOUNT:.2f}</b>\n\n"
            f"Send a number to change (e.g. <code>50</code>)"
        )

    def _cmd_demo(self):
        import config
        config.ACCOUNT_TYPE = "PRACTICE"
        with self._lock:
            self.need_reconnect = True
        _send_message("🎯 <b>Switched to DEMO account</b>\nReconnecting...")

    def _cmd_live(self):
        import config
        config.ACCOUNT_TYPE = "REAL"
        with self._lock:
            self.need_reconnect = True
        _send_message("🔴 <b>Switched to LIVE account</b>\nReconnecting...")

    def _cmd_strategy(self):
        import config
        _send_message(
            f"<b>🧠 STRATEGY</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Current: <b>{config.STRATEGY}</b>\n\n"
            f"FCB + Pole Position agreement required"
        )

    def _cmd_fire(self):
        with self._lock:
            self.force_scan = True
        _send_message("🔥 <b>Force Scan</b>\nTriggering immediate scan...")

    def _cmd_help(self):
        _send_message(
            "<b>❓ HELP — MOJIDTRADEBOT v3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⏸ <b>Pause</b> — Stop trading, keep scanning\n"
            "▶️ <b>Resume</b> — Resume trading\n"
            "📊 <b>Status</b> — Show bot stats\n"
            "📈 <b>Pairs</b> — Show active pairs\n"
            "⏰ <b>Timeframe</b> — Show candle/expiry\n"
            "💰 <b>Amount</b> — Show/set stake\n"
            "🎯 <b>Demo</b> — Switch to practice\n"
            "🔴 <b>Live</b> — Switch to real\n"
            "🧠 <b>Strategy</b> — Show strategy\n"
            "🔥 <b>Fire</b> — Force scan now\n\n"
            "Send a number to change stake amount."
        )

    def _cmd_start(self):
        send_started()

    # ── state accessors (called from main loop) ────────────────────────────

    def is_paused(self):
        with self._lock:
            return self.paused

    def check_reconnect(self):
        with self._lock:
            if self.need_reconnect:
                self.need_reconnect = False
                return True
            return False

    def check_force_scan(self):
        with self._lock:
            if self.force_scan:
                self.force_scan = False
                return True
            return False
