"""Bron va navbat API - /api/v1/reservations/..."""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta
from typing import Optional

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_module, require_perm
from core.models import Branch
from modules.tables.models import Table, Zone

from . import services
from .models import ACTIVE_STATUSES, Reservation, ReservationStatus, WaitlistEntry, WaitStatus

router = Router(tags=["reservations"])


def _guard(request, perm: str):
    require_module(request, "reservations")
    require_perm(request, perm)


class ReservationIn(Schema):
    guest_name: str
    phone: str = ""
    guests: int = 2
    table_id: Optional[int] = None
    zone_id: Optional[int] = None
    branch_id: Optional[int] = None
    starts_at: datetime
    duration_minutes: int = 0
    source: str = "phone"
    note: str = ""
    occasion: str = ""
    deposit: int = 0
    auto_table: bool = True


class ReservationOut(Schema):
    id: int
    guest_name: str
    phone: str
    guests: int
    table_id: Optional[int] = None
    table_no: Optional[str] = None
    zone_id: Optional[int] = None
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    status: str
    source: str
    note: str
    occasion: str
    deposit: int
    minutes_left: int
    is_late: bool

    @staticmethod
    def resolve_table_no(obj):
        return obj.table.number if obj.table_id else None


class StatusIn(Schema):
    status: str
    table_id: Optional[int] = None


class WaitIn(Schema):
    guest_name: str
    phone: str = ""
    guests: int = 2
    quoted_minutes: int = 0
    note: str = ""


class WaitOut(Schema):
    id: int
    guest_name: str
    phone: str
    guests: int
    status: str
    quoted_minutes: int
    waiting_minutes: int
    note: str
    table_no: Optional[str] = None

    @staticmethod
    def resolve_table_no(obj):
        return obj.table.number if obj.table_id else None


# ------------------------------------------------------------------ meta / ro'yxat
@router.get("/meta", auth=auth)
def meta(request):
    _guard(request, "reservations.view")
    cfg = services.cfg(request.tenant)
    return {
        "settings": {
            "default_duration_minutes": int(cfg.get("default_duration_minutes", 90)),
            "buffer_minutes": int(cfg.get("buffer_minutes", 15)),
            "open_hour": int(cfg.get("open_hour", 10)),
            "close_hour": int(cfg.get("close_hour", 23)),
            "max_days_ahead": int(cfg.get("max_days_ahead", 30)),
            "no_show_minutes": int(cfg.get("no_show_minutes", 20)),
        },
        "zones": [{"id": z.id, "name": z.name} for z in Zone.objects.filter(is_active=True)],
        "tables": [{"id": t.id, "number": t.number, "seats": t.seats, "zone_id": t.zone_id}
                   for t in Table.objects.filter(is_active=True)],
        "branches": [{"id": b.id, "name": b.name} for b in Branch.objects.filter(is_active=True)],
        "quote_minutes": services.quote_minutes(),
        "can": {"manage": request.auth.has_perm_code("reservations.manage")},
    }


def _day_range(d: date_cls):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(d, time.min), tz)
    return start, start + timedelta(days=1)


@router.get("", response=list[ReservationOut], auth=auth)
def list_reservations(request, date: Optional[date_cls] = None, status: Optional[str] = None,
                      upcoming: bool = False, q: str = "", limit: int = 200):
    """Kun bo'yicha ro'yxat (sukut - bugun). `upcoming=true` - kelayotgan bronlar."""
    _guard(request, "reservations.view")
    qs = Reservation.objects.select_related("table")
    if upcoming:
        qs = qs.filter(starts_at__gte=timezone.now() - timedelta(hours=1), status__in=ACTIVE_STATUSES)
    else:
        d = date or timezone.localdate()
        a, b = _day_range(d)
        qs = qs.filter(starts_at__gte=a, starts_at__lt=b)
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(guest_name__icontains=q) | qs.filter(phone__icontains=q)
    return qs[:limit]


@router.get("/stats", auth=auth)
def stats(request, date: Optional[date_cls] = None):
    """Kun ko'rsatkichlari: nechta bron, nechta mehmon, kelmaganlar."""
    _guard(request, "reservations.view")
    a, b = _day_range(date or timezone.localdate())
    qs = Reservation.objects.filter(starts_at__gte=a, starts_at__lt=b)
    guests = sum(r.guests for r in qs.exclude(status__in=[ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW]))
    return {
        "total": qs.count(),
        "active": qs.filter(status__in=ACTIVE_STATUSES).count(),
        "seated": qs.filter(status=ReservationStatus.SEATED).count(),
        "no_show": qs.filter(status=ReservationStatus.NO_SHOW).count(),
        "cancelled": qs.filter(status=ReservationStatus.CANCELLED).count(),
        "guests": guests,
        "late": sum(1 for r in qs if r.is_late),
        "waitlist": WaitlistEntry.objects.filter(status__in=[WaitStatus.WAITING, WaitStatus.CALLED]).count(),
    }


@router.get("/availability", auth=auth)
def availability(request, at: datetime, guests: int = 2, minutes: int = 0, exclude_id: Optional[int] = None):
    """Shu vaqtga bo'sh stollar + yaqin bo'sh vaqtlar (band bo'lsa taklif qiladi)."""
    _guard(request, "reservations.view")
    cfg = services.cfg(request.tenant)
    minutes = minutes or int(cfg.get("default_duration_minutes", 90))
    free = services.free_tables(at, minutes, guests, tenant=request.tenant, exclude_id=exclude_id)
    slots = []
    if not free:
        for step in (30, 60, 90, 120):
            alt = at + timedelta(minutes=step)
            if services.free_tables(alt, minutes, guests, tenant=request.tenant, exclude_id=exclude_id):
                slots.append(timezone.localtime(alt).strftime("%H:%M"))
    return {
        "free": [{"id": t.id, "number": t.number, "seats": t.seats, "zone": t.zone.name if t.zone_id else ""} for t in free],
        "suggest_times": slots,
    }


# ------------------------------------------------------------------ CRUD
def _apply(res: Reservation, data: ReservationIn, tenant) -> Reservation:
    cfg = services.cfg(tenant)
    res.guest_name, res.phone, res.guests = data.guest_name.strip(), data.phone.strip(), max(1, data.guests)
    res.zone_id, res.branch_id = data.zone_id, data.branch_id
    res.starts_at = data.starts_at
    res.duration_minutes = data.duration_minutes or int(cfg.get("default_duration_minutes", 90))
    res.source, res.note, res.occasion, res.deposit = data.source, data.note, data.occasion, max(0, data.deposit)
    if data.table_id:
        res.table_id = data.table_id
    return res


@router.post("", response=ReservationOut, auth=auth)
def create_reservation(request, data: ReservationIn):
    _guard(request, "reservations.manage")
    if data.starts_at < timezone.now() - timedelta(hours=2):
        raise HttpError(400, "O'tgan vaqtga bron qilib bo'lmaydi.")
    res = _apply(Reservation(created_by=request.auth), data, request.tenant)
    if data.table_id:
        busy = [r for r in services.overlapping(res.starts_at, res.duration_minutes) if r.table_id == data.table_id]
        if busy:
            raise HttpError(400, f"Bu stol o'sha vaqtda band ({busy[0].guest_name}).")
    elif data.auto_table:
        res.table = services.auto_table(res, tenant=request.tenant)
    res.save()
    record(request, "create", res)
    return res


@router.put("/{int:rid}", response=ReservationOut, auth=auth)
def update_reservation(request, rid: int, data: ReservationIn):
    _guard(request, "reservations.manage")
    res = get_object_or_404(Reservation, pk=rid)
    _apply(res, data, request.tenant)
    if data.table_id:
        busy = [r for r in services.overlapping(res.starts_at, res.duration_minutes, exclude_id=rid)
                if r.table_id == data.table_id]
        if busy:
            raise HttpError(400, f"Bu stol o'sha vaqtda band ({busy[0].guest_name}).")
    res.save()
    record(request, "update", res)
    return res


@router.post("/{int:rid}/status", response=ReservationOut, auth=auth)
def change_status(request, rid: int, data: StatusIn):
    _guard(request, "reservations.manage")
    if data.status not in ReservationStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    res = get_object_or_404(Reservation.objects.select_related("table"), pk=rid)
    if data.table_id:
        res.table_id = data.table_id
        res.save(update_fields=["table"])
    try:
        services.set_status(res, data.status, request=request, tenant=request.tenant)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    record(request, "update", res, after={"status": data.status})
    return res


@router.delete("/{int:rid}", auth=auth)
def delete_reservation(request, rid: int):
    _guard(request, "reservations.manage")
    res = get_object_or_404(Reservation, pk=rid)
    res.delete()
    return {"ok": True}


@router.post("/mark-no-shows", auth=auth)
def mark_no_shows(request):
    _guard(request, "reservations.manage")
    return {"ok": True, "marked": services.mark_no_shows(tenant=request.tenant)}


# ------------------------------------------------------------------ navbat
@router.get("/waitlist", response=list[WaitOut], auth=auth)
def waitlist(request, all: bool = False):
    _guard(request, "reservations.view")
    qs = WaitlistEntry.objects.select_related("table")
    if not all:
        qs = qs.filter(status__in=[WaitStatus.WAITING, WaitStatus.CALLED])
    else:
        qs = qs.filter(created_at__date=timezone.localdate())
    return qs


@router.post("/waitlist", response=WaitOut, auth=auth)
def add_wait(request, data: WaitIn):
    _guard(request, "reservations.manage")
    e = WaitlistEntry.objects.create(guest_name=data.guest_name.strip(), phone=data.phone.strip(),
                                     guests=max(1, data.guests), note=data.note,
                                     quoted_minutes=data.quoted_minutes or services.quote_minutes())
    record(request, "create", e)
    return e


@router.post("/waitlist/{int:wid}/status", response=WaitOut, auth=auth)
def wait_status(request, wid: int, data: StatusIn):
    """waiting -> called -> seated (stol tanlanadi) / left."""
    _guard(request, "reservations.manage")
    if data.status not in WaitStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    e = get_object_or_404(WaitlistEntry, pk=wid)
    if data.status == WaitStatus.SEATED:
        if not data.table_id:
            raise HttpError(400, "Stolni tanlang.")
        table = get_object_or_404(Table, pk=data.table_id)
        if table.session:
            raise HttpError(400, "Stol band.")
        services.seat_from_waitlist(e, table, request=request, tenant=request.tenant)
        return e
    e.status = data.status
    if data.status == WaitStatus.CALLED:
        e.called_at = timezone.now()
    e.save(update_fields=["status", "called_at"])
    return e


@router.delete("/waitlist/{int:wid}", auth=auth)
def del_wait(request, wid: int):
    _guard(request, "reservations.manage")
    get_object_or_404(WaitlistEntry, pk=wid).delete()
    return {"ok": True}