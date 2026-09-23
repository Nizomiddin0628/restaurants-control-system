"""KDS xizmatlari: buyurtmadan cheklar yaratish, holatni o'zgartirish."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from core.events import emit

from .models import Station, Ticket, TicketItem, TicketStatus, ensure_stations


def _station_for(product) -> Station | None:
    """Taom kategoriyasi qaysi stansiyaga biriktirilgan bo'lsa — o'sha. Biriktirilmagan bo'lsa — birinchi stansiya."""
    if product is None:
        return Station.objects.filter(is_active=True).first()
    st = Station.objects.filter(is_active=True, categories=product.category_id).first()
    return st or Station.objects.filter(is_active=True).first()


@transaction.atomic
def create_tickets(order, tenant=None) -> list[Ticket]:
    """Buyurtma → stansiyalar bo'yicha cheklar. Takroriy chaqirilsa yangi chek yaratmaydi."""
    ensure_stations()
    if order.kds_tickets.exists():
        return list(order.kds_tickets.all())
    by_station: dict[int | None, list] = {}
    for item in order.items.select_related("product"):
        st = _station_for(item.product)
        by_station.setdefault(st.pk if st else None, []).append(item)
    tickets = []
    for station_id, items in by_station.items():
        t = Ticket.objects.create(order=order, station_id=station_id, note=order.note)
        for i in items:
            TicketItem.objects.create(ticket=t, order_item=i, name=i.name, qty=i.qty, note=i.note, modifiers=i.modifiers)
        tickets.append(t)
        emit("kds.ticket_created", {"ticket_id": t.pk, "order_number": order.number, "station_id": station_id}, tenant=tenant)
    return tickets


@transaction.atomic
def set_status(request, ticket: Ticket, status: str) -> Ticket:
    now = timezone.now()
    ticket.status = status
    if status == TicketStatus.COOKING and not ticket.started_at:
        ticket.started_at = now
        ticket.cook = request.auth if getattr(request.auth, "pk", None) else None
    if status == TicketStatus.READY:
        ticket.ready_at = ticket.ready_at or now
        ticket.items.update(is_done=True)
    if status == TicketStatus.SERVED:
        ticket.ready_at = ticket.ready_at or now
        ticket.served_at = now
    if status == TicketStatus.NEW:
        ticket.started_at = ticket.ready_at = ticket.served_at = None
    ticket.save()
    emit(f"kds.ticket_{status}", {"ticket_id": ticket.pk, "order_number": ticket.order.number,
                                  "minutes": ticket.waiting_minutes}, tenant=getattr(request, "tenant", None))
    return ticket