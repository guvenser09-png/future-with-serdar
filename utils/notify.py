"""Telegram bildirimi — OPSİYONEL.

TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ayarlı değilse sessizce atlar.
"""
from __future__ import annotations

from .config_loader import get_env
from .logging_utils import get_logger

log = get_logger("notify")


def send(message: str) -> None:
    token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.debug("Telegram ayarlı değil — bildirim atlandı.")
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram bildirimi gönderilemedi: %s", e)
