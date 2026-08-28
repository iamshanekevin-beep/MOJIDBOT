"""Telegram notification helper — sends trade/signal alerts."""
import logging
import os

import requests

log = logging.getLogger("notifier")

BOT_TOKEN = os.getenv("TELEGRAM", "")
CHAT_ID = os.getenv("TELEGRAM_USER_ID", "")


def notify(message: str):
    """Send a message to the configured Telegram chat. Fails silently."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning("Telegram notify failed: %s", e)
