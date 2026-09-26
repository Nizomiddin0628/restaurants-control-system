"""
Hodisa tinglovchilari. Modul o'chirilgan bo'lsa bu funksiyalar umuman chaqirilmaydi (core/events.py).

Bu yerda modullar bir-biriga "yopishmaydi": ombor moduli keyin `inventory.low_stock` chiqaradi —
biz avtomatik vazifa ochamiz; POS `pos.shift_closed` chiqaradi — tozalash checklisti tug'iladi va h.k.
"""
from __future__ import annotations

import logging

from core.events import on

log = logging.getLogger("tasks")


@on("tenant.created")
def setup_board(payload: dict) -> None:
    """Yangi restoran: Kanban ustunlari, bo'limlar va muammo turlari darhol tayyor bo'lsin."""
    from .services import ensure_setup

    ensure_setup()


@on("inventory.low_stock")
def task_from_low_stock(payload: dict) -> None:
    """Ombor moduli (2-bosqich) kam qoldiq haqida xabar bersa — ta'minot vazifasi ochiladi."""
    from .models import Source, TaskCategory
    from .services import create_task

    class _Req:
        auth = None
        tenant = None

    name = payload.get("product_name") or "Mahsulot"
    create_task(_Req(), title=f"Ta'minot: {name} tugayapti",
                description=f"Qoldiq: {payload.get('qty', '—')}. Zakaz berish kerak.",
                category=TaskCategory.objects.filter(code="supply").first(),
                source=Source.SYSTEM)


@on("forecast.holiday_soon")
def task_from_holiday(payload: dict) -> None:
    """Bayram yaqinlashdi — ta'minot vazifasi: nima va qachongacha xarid qilish kerak."""
    from datetime import datetime, time

    from django.utils import timezone

    from .models import Source, TaskCategory
    from .services import create_task

    class _Req:
        auth = None
        tenant = None

    due = None
    try:
        due = timezone.make_aware(datetime.combine(datetime.strptime(payload.get("buy_by", ""), "%d.%m.%Y").date(), time(18, 0)))
    except ValueError:
        pass
    cost = f"{int(payload.get('total_cost') or 0):,}".replace(",", " ")
    items = ", ".join(payload.get("items") or [])
    desc = (f"{payload.get('name')} — {payload.get('date')}. " +
            (f"{payload.get('short_count')} ta xomashyo yetmaydi ({items}…), taxminan {cost} so'm. "
             if payload.get("short_count") else "Ombor yetarli, qoldiqlarni tekshiring. ") +
            "To'liq ro'yxat: Ombor → Xarid rejasi.")
    create_task(_Req(), title=f"Bayramga tayyorgarlik: {payload.get('name')}", description=desc, due_at=due,
                category=TaskCategory.objects.filter(code="supply").first(), source=Source.SYSTEM)


@on("tasks.overdue")
def notify_overdue(payload: dict) -> None:
    """Kechikkan vazifa — hozircha log, Telegram moduli ulangach o'sha yerga ketadi."""
    log.warning("Vazifa kechikdi: #%s %s", payload.get("number"), payload.get("title"))


# ------------------------------------------------------------------ Telegram bildirishnomalari (real Bot API)
def _tg(user_id, text: str) -> None:
    if not user_id:
        return
    from core.models import User
    from integrations.telegram import send_message

    u = User.objects.filter(pk=user_id, telegram_id__isnull=False).first()
    if u:
        send_message(u.telegram_id, text)


@on("tasks.created")
def tg_created(payload: dict) -> None:
    _tg(payload.get("assignee_id"), f"🆕 Yangi vazifa #{payload.get('number')}: <b>{payload.get('title')}</b>"
        + (f"\nMuddat: {payload['due_at'][:16].replace('T', ' ')}" if payload.get("due_at") else ""))


@on("tasks.submitted")
def tg_submitted(payload: dict) -> None:
    _tg(payload.get("supervisor_id"), f"🔎 Tekshiruvga topshirildi #{payload.get('number')}: <b>{payload.get('title')}</b>\nDalilni ko'rib tasdiqlang yoki qaytaring.")


@on("tasks.rejected")
def tg_rejected(payload: dict) -> None:
    _tg(payload.get("assignee_id"), f"↩️ Qaytarildi #{payload.get('number')}: <b>{payload.get('title')}</b>\nSabab: {payload.get('reason', '')}")


@on("tasks.approved")
def tg_approved(payload: dict) -> None:
    _tg(payload.get("assignee_id"), f"✅ Tasdiqlandi #{payload.get('number')}: <b>{payload.get('title')}</b>. Rahmat!")


@on("tasks.overdue")
def tg_overdue(payload: dict) -> None:
    _tg(payload.get("supervisor_id"), f"⚠️ Muddati o'tdi #{payload.get('number')}: <b>{payload.get('title')}</b>")
