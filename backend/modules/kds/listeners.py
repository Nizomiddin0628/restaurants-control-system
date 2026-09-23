"""Kassa hodisalari → oshxona ekrani."""
from __future__ import annotations

from core.events import on


def _create(payload: dict, when: str) -> None:
    from modules.pos.models import Order

    from .models import TicketStatus
    from .services import create_tickets

    tenant = payload.get("_tenant")
    mode = "created"
    try:
        mode = (tenant.settings.get("modules", {}).get("kds", {}) or {}).get("create_on", "created")
    except Exception:
        pass
    if mode != when:
        return
    order = Order.objects.filter(pk=payload.get("order_id")).first()
    if order:
        create_tickets(order, tenant)
    _ = TicketStatus


@on("pos.order_created")
def on_created(payload: dict) -> None:
    _create(payload, "created")


@on("pos.order_paid")
def on_paid(payload: dict) -> None:
    _create(payload, "paid")


@on("pos.order_cancelled")
def on_cancelled(payload: dict) -> None:
    from .models import Ticket, TicketStatus

    Ticket.objects.filter(order_id=payload.get("order_id")).update(status=TicketStatus.CANCELLED)