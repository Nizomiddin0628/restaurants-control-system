"""Kassa hodisalari -> zal xaritasi o'zi yangilanadi."""
from __future__ import annotations

from core.events import on


@on("pos.order_created")
def on_order_created(payload: dict) -> None:
    from modules.pos.models import Order, OrderType

    from .services import cfg, find_by_number, open_session

    tenant = payload.get("_tenant")
    if not cfg(tenant).get("auto_open_on_order", True):
        return
    order = Order.objects.filter(pk=payload.get("order_id")).first()
    if not order or order.type != OrderType.DINE_IN or not order.table_no:
        return
    table = find_by_number(order.table_no)
    if table:
        open_session(table, order=order, waiter=order.cashier, source="pos", tenant=tenant)


@on("pos.order_paid")
def on_order_paid(payload: dict) -> None:
    from .models import TableSession
    from .services import close_session

    s = TableSession.objects.filter(order_id=payload.get("order_id"), closed_at__isnull=True).first()
    if s:
        close_session(s, tenant=payload.get("_tenant"))


@on("pos.order_cancelled")
def on_order_cancelled(payload: dict) -> None:
    from .models import TableSession
    from .services import close_session

    s = TableSession.objects.filter(order_id=payload.get("order_id"), closed_at__isnull=True).first()
    if s:
        close_session(s, tenant=payload.get("_tenant"))