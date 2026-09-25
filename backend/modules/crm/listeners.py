"""
Kassa hodisalari → bonus:
  pos.order_paid       → mijoz kartasi yangilanadi, bonus yechiladi / keshbek qo'shiladi, aksiya hisobi
  pos.order_cancelled  → to'langan chek bekor bo'lsa hammasi orqaga qaytadi
Har kuni birinchi to'lovda tug'ilgan kunlar tekshiriladi (alohida cron kerak emas).
"""
from __future__ import annotations

import logging

from django.db import connection

from core.events import on

log = logging.getLogger("crm")


def _tenant(payload):
    return payload.get("_tenant") or getattr(connection, "tenant", None)


@on("pos.order_paid")
def order_paid(payload: dict) -> None:
    from modules.pos.models import Order

    from . import services
    t = _tenant(payload)
    o = Order.objects.filter(pk=payload.get("order_id")).first()
    if o is None:
        return
    services.settle_paid(t, o)
    if t is not None:
        services.daily(t)


@on("pos.order_cancelled")
def order_cancelled(payload: dict) -> None:
    from . import services
    services.reverse(_tenant(payload), int(payload.get("order_id") or 0))
