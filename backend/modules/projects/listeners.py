"""Loyiha bildirishnomalari: vazifa berildi, muddat yaqin, tekshiruvga topshirildi → Telegram (xodim botga ulangan bo'lsa)."""
from __future__ import annotations

import logging

from django.db import connection

from core.events import on

log = logging.getLogger(__name__)


def _enabled() -> bool:
    t = getattr(connection, "tenant", None)
    try:
        return bool((t.settings.get("modules", {}).get("projects", {}) or {}).get("notify_telegram", True))
    except Exception:
        return True


def _tg(user_id, text: str) -> None:
    if not user_id or not _enabled():
        return
    try:
        from core.models import User
        from integrations.telegram import send_message
        u = User.objects.filter(pk=user_id, telegram_id__isnull=False).first()
        if u:
            send_message(u.telegram_id, text)
    except Exception:  # xabar ketmasa ham ish to'xtamasin
        log.exception("loyiha xabari yuborilmadi")


def _d(s):
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if s else ""


@on("projects.task_assigned")
def tg_assigned(p: dict) -> None:
    _tg(p.get("assignee_id"), f"📌 Sizga loyiha vazifasi: <b>{p.get('title')}</b>\nLoyiha: {p.get('project')}"
        + (f"\nMuddat: {_d(p.get('due'))}" if p.get("due") else ""))


@on("projects.task_due")
def tg_due(p: dict) -> None:
    when = "bugun" if p.get("today") else "ertaga"
    _tg(p.get("assignee_id"), f"⏰ Muddat {when} tugaydi: <b>{p.get('title')}</b>\nLoyiha: {p.get('project')}")


@on("projects.task_review")
def tg_review(p: dict) -> None:
    _tg(p.get("owner_id"), f"🔎 Tekshiruvga topshirildi: <b>{p.get('title')}</b>\nLoyiha: {p.get('project')}")
