"""
Telegram Bot API (real): xabar yuborish, webhook o'rnatish, kontakt orqali xodimni bog'lash.

Ishga tushirish:
  1) @BotFather → token → .env TELEGRAM_BOT_TOKEN
  2) python manage.py telegram_webhook https://lazzat.restopos.uz   (yoki API: POST /api/v1/telegram/set-webhook)
  3) xodim botga /start → "Telefonni ulashish" tugmasi → tizim telefon bo'yicha xodimni topadi va telegram_id yozadi.
Token yo'q bo'lsa — xabarlar logga yoziladi (dev), xato bermaydi.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"


def _token(token: str | None = None) -> str | None:
    """Token tartibi: aniq berilgan → restoranning o'z boti (sozlamada) → .env TELEGRAM_BOT_TOKEN."""
    if token:
        return token
    try:
        from django.db import connection
        tenant = getattr(connection, "tenant", None)
        saved = (((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("telegram") or {}).get("bot_token")
        if saved:
            return saved
    except Exception:
        pass
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def call(method: str, payload: dict, token: str | None = None) -> dict:
    tok = _token(token)
    if not tok:
        log.info("[TG %s] %s", method, payload)
        return {"ok": True, "dev": True}
    try:
        r = requests.post(API.format(token=tok, method=method), json=payload, timeout=10)
        return r.json()
    except Exception as e:  # tarmoq xatosi ish oqimini to'xtatmasin
        log.warning("Telegram %s xato: %s", method, e)
        return {"ok": False, "error": str(e)}


def send_message(chat_id: int | str, text: str, token: str | None = None, reply_markup: dict | None = None, parse_mode: str = "HTML") -> bool:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return bool(call("sendMessage", payload, token).get("ok"))


def set_webhook(base_url: str, secret: str, token: str | None = None) -> dict:
    return call("setWebhook", {"url": f"{base_url.rstrip('/')}/api/v1/telegram/webhook", "secret_token": secret,
                               "allowed_updates": ["message", "callback_query"]}, token)


CONTACT_KEYBOARD = {"keyboard": [[{"text": "📱 Telefonni ulashish", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True}
