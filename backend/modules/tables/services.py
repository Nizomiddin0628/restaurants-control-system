"""Stol seansi: ochish, hisob so'rash, yopish, ko'chirish."""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.events import emit

from .models import Table, TableSession


def cfg(tenant) -> dict:
    try:
        return (tenant.settings or {}).get("modules", {}).get("tables", {}) or {}
    except AttributeError:
        return {}


@transaction.atomic
def open_session(table: Table, *, guests: int = 0, waiter=None, order=None, source: str = "hall",
                 tenant=None, note: str = "") -> TableSession:
    """Stolni band qiladi. Allaqachon ochiq bo'lsa - o'sha seans qaytadi (takror bosishdan himoya)."""
    s = table.session
    if s:
        if order and not s.order_id:
            s.order = order
            s.save(update_fields=["order"])
        return s
    s = TableSession.objects.create(
        table=table, order=order, waiter=waiter if getattr(waiter, "pk", None) else None,
        guests=guests or int(cfg(tenant).get("default_guests", 2)), source=source, note=note,
    )
    if table.needs_cleaning:
        table.needs_cleaning = False
        table.save(update_fields=["needs_cleaning"])
    emit("tables.session_opened", {"table_id": table.pk, "table_no": table.number, "session_id": s.pk,
                                   "guests": s.guests}, tenant=tenant)
    return s


@transaction.atomic
def close_session(session: TableSession, *, tenant=None) -> TableSession:
    if session.closed_at:
        return session
    session.closed_at = timezone.now()
    session.total = int(getattr(session.order, "total", 0) or 0)
    session.save(update_fields=["closed_at", "total"])
    if cfg(tenant).get("require_cleaning", True):
        Table.objects.filter(pk=session.table_id).update(needs_cleaning=True)
    emit("tables.session_closed", {"table_id": session.table_id, "session_id": session.pk,
                                   "minutes": session.minutes, "total": session.total}, tenant=tenant)
    return session


def ask_bill(session: TableSession, *, tenant=None) -> TableSession:
    session.bill_asked_at = session.bill_asked_at or timezone.now()
    session.save(update_fields=["bill_asked_at"])
    emit("tables.bill_asked", {"table_id": session.table_id, "session_id": session.pk}, tenant=tenant)
    return session


@transaction.atomic
def move_session(session: TableSession, target: Table, *, tenant=None) -> TableSession:
    """Mehmonlarni boshqa stolga ko'chirish - buyurtma ham u bilan ketadi."""
    if target.session:
        raise ValueError("Yangi stol band.")
    old = session.table
    session.table = target
    session.save(update_fields=["table"])
    if session.order_id:
        session.order.table_no = target.number
        session.order.save(update_fields=["table_no"])
    if cfg(tenant).get("require_cleaning", True):
        Table.objects.filter(pk=old.pk).update(needs_cleaning=True)
    emit("tables.session_moved", {"from": old.pk, "to": target.pk, "session_id": session.pk}, tenant=tenant)
    return session


def find_by_number(number: str) -> Table | None:
    return Table.objects.filter(number=str(number).strip(), is_active=True).first() if number else None


def reserved_table_ids(within_minutes: int = 120) -> set[int]:
    """Yaqin soatlarda broni bor stollar (reservations moduli yoqilgan bo'lsa)."""
    try:
        from modules.reservations.models import Reservation, ReservationStatus
    except Exception:  # pragma: no cover
        return set()
    now = timezone.now()
    qs = Reservation.objects.filter(
        status__in=[ReservationStatus.NEW, ReservationStatus.CONFIRMED],
        starts_at__gte=now - timedelta(minutes=30),
        starts_at__lte=now + timedelta(minutes=within_minutes),
        table__isnull=False,
    )
    return set(qs.values_list("table_id", flat=True))