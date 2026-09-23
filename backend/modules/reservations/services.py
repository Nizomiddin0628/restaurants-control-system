"""Bron xizmatlari: bo'sh stol izlash, o'tirg'izish, eslatma."""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.events import emit
from modules.tables.models import Table
from modules.tables.services import close_session, open_session

from .models import ACTIVE_STATUSES, Reservation, ReservationStatus, WaitlistEntry, WaitStatus


def cfg(tenant) -> dict:
    try:
        return (tenant.settings or {}).get("modules", {}).get("reservations", {}) or {}
    except AttributeError:
        return {}


def overlapping(starts_at, minutes: int, *, buffer_minutes: int = 15, exclude_id: int | None = None):
    """Shu vaqt oralig'ini band qiladigan bronlar."""
    start = starts_at - timedelta(minutes=buffer_minutes)
    end = starts_at + timedelta(minutes=minutes + buffer_minutes)
    qs = Reservation.objects.filter(status__in=ACTIVE_STATUSES + [ReservationStatus.SEATED],
                                    table__isnull=False, starts_at__lt=end)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return [r for r in qs if r.ends_at > start]


def free_tables(starts_at, minutes: int, guests: int = 1, *, tenant=None, exclude_id: int | None = None) -> list[Table]:
    """Shu vaqtga bo'sh va mehmon soniga yetadigan stollar - eng kichigi birinchi."""
    buf = int(cfg(tenant).get("buffer_minutes", 15))
    busy = {r.table_id for r in overlapping(starts_at, minutes, buffer_minutes=buf, exclude_id=exclude_id)}
    # hozir zalda o'tirganlar ham band (agar bron yaqin vaqtga bo'lsa)
    if starts_at <= timezone.now() + timedelta(minutes=30):
        from modules.tables.models import TableSession
        busy |= set(TableSession.objects.filter(closed_at__isnull=True).values_list("table_id", flat=True))
    return list(Table.objects.filter(is_active=True, seats__gte=guests).exclude(id__in=busy).order_by("seats", "number"))


def auto_table(res: Reservation, *, tenant=None) -> Table | None:
    free = free_tables(res.starts_at, res.duration_minutes, res.guests, tenant=tenant, exclude_id=res.pk)
    return free[0] if free else None


@transaction.atomic
def seat(res: Reservation, *, table: Table | None = None, request=None, tenant=None) -> Reservation:
    """Mehmon keldi - stol band bo'ladi, zal xaritasida darhol ko'rinadi."""
    table = table or res.table or auto_table(res, tenant=tenant)
    if table is None:
        raise ValueError("Bo'sh stol yo'q - avval stol tanlang.")
    res.table, res.status, res.seated_at = table, ReservationStatus.SEATED, timezone.now()
    res.save(update_fields=["table", "status", "seated_at"])
    open_session(table, guests=res.guests, waiter=getattr(request, "auth", None),
                 source="reservation", tenant=tenant, note=res.guest_name)
    emit("reservations.seated", {"reservation_id": res.pk, "table_id": table.pk, "guests": res.guests}, tenant=tenant)
    return res


@transaction.atomic
def finish(res: Reservation, *, tenant=None) -> Reservation:
    res.status, res.closed_at = ReservationStatus.DONE, timezone.now()
    res.save(update_fields=["status", "closed_at"])
    if res.table_id and res.table.session:
        close_session(res.table.session, tenant=tenant)
    emit("reservations.done", {"reservation_id": res.pk}, tenant=tenant)
    return res


def set_status(res: Reservation, status: str, *, request=None, tenant=None) -> Reservation:
    if status == ReservationStatus.SEATED:
        return seat(res, request=request, tenant=tenant)
    if status == ReservationStatus.DONE:
        return finish(res, tenant=tenant)
    res.status = status
    if status in (ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW):
        res.closed_at = timezone.now()
    res.save(update_fields=["status", "closed_at"])
    emit(f"reservations.{status}", {"reservation_id": res.pk, "phone": res.phone,
                                    "guest": res.guest_name}, tenant=tenant)
    return res


@transaction.atomic
def seat_from_waitlist(entry: WaitlistEntry, table: Table, *, request=None, tenant=None) -> WaitlistEntry:
    entry.status, entry.seated_at, entry.table = WaitStatus.SEATED, timezone.now(), table
    entry.save(update_fields=["status", "seated_at", "table"])
    open_session(table, guests=entry.guests, waiter=getattr(request, "auth", None),
                 source="reservation", tenant=tenant, note=entry.guest_name)
    emit("reservations.waitlist_seated", {"entry_id": entry.pk, "table_id": table.pk}, tenant=tenant)
    return entry


def quote_minutes() -> int:
    """Navbatdagilarga aytiladigan taxminiy kutish vaqti - oldindagilar soniga qarab."""
    from modules.tables.models import Table as T
    from modules.tables.models import TableSession

    waiting = WaitlistEntry.objects.filter(status=WaitStatus.WAITING).count()
    free = T.objects.filter(is_active=True).count() - TableSession.objects.filter(closed_at__isnull=True).count()
    if free > waiting:
        return 5
    return min(120, 15 + max(0, waiting - max(0, free)) * 10)


def mark_no_shows(*, tenant=None) -> int:
    """Kechikkanlarni avtomatik «kelmadi» qilish (Celery yoki ekran ochilganda)."""
    limit = int(cfg(tenant).get("no_show_minutes", 20))
    edge = timezone.now() - timedelta(minutes=limit)
    qs = Reservation.objects.filter(status__in=ACTIVE_STATUSES, starts_at__lt=edge)
    n = qs.count()
    for r in qs:
        set_status(r, ReservationStatus.NO_SHOW, tenant=tenant)
    return n