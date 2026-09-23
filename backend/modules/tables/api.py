"""Zal va stollar API - /api/v1/tables/..."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_module, require_perm
from core.models import Branch

from . import services
from .models import Table, TableSession, TableStatus, Zone, ensure_zones

router = Router(tags=["tables"])


def _guard(request, perm: str):
    require_module(request, "tables")
    require_perm(request, perm)


# ------------------------------------------------------------------ sxemalar
class ZoneIn(Schema):
    name: str
    color: str = "#0F6E63"
    branch_id: Optional[int] = None
    is_active: bool = True


class ZoneOut(ZoneIn):
    id: int
    sort_order: int = 0
    tables_count: int = 0


class TableIn(Schema):
    number: str
    zone_id: Optional[int] = None
    branch_id: Optional[int] = None
    seats: int = 4
    shape: str = "square"
    x: float = 10
    y: float = 10
    size: int = 1
    is_active: bool = True
    note: str = ""


class SessionOut(Schema):
    id: int
    guests: int
    minutes: int
    waiter: Optional[str] = None
    order_id: Optional[int] = None
    order_number: Optional[int] = None
    order_total: int = 0
    bill_asked: bool = False
    note: str = ""

    @staticmethod
    def resolve_waiter(obj):
        return obj.waiter.full_name if obj.waiter_id else None

    @staticmethod
    def resolve_order_number(obj):
        return obj.order.number if obj.order_id else None

    @staticmethod
    def resolve_order_total(obj):
        return int(obj.order.total) if obj.order_id else 0

    @staticmethod
    def resolve_bill_asked(obj):
        return bool(obj.bill_asked_at)


class TableOut(Schema):
    id: int
    number: str
    zone_id: Optional[int] = None
    branch_id: Optional[int] = None
    seats: int
    shape: str
    x: float
    y: float
    size: int
    is_active: bool
    note: str = ""
    status: str = "free"
    session: Optional[SessionOut] = None
    reservation: Optional[dict] = None


class PosIn(Schema):
    id: int
    x: float
    y: float


class LayoutIn(Schema):
    tables: list[PosIn]


class OpenIn(Schema):
    guests: int = 0
    waiter_id: Optional[int] = None
    note: str = ""


class MoveIn(Schema):
    target_id: int


# ------------------------------------------------------------------ o'qish
@router.get("/meta", auth=auth)
def meta(request):
    """Zallar, filiallar, sozlamalar, ruxsatlar - ekran shu bilan quriladi."""
    _guard(request, "tables.view")
    ensure_zones()
    zones = Zone.objects.annotate(n=Count("tables")).order_by("sort_order", "id")
    cfg = services.cfg(request.tenant)
    return {
        "zones": [{"id": z.id, "name": z.name, "color": z.color, "branch_id": z.branch_id,
                   "is_active": z.is_active, "sort_order": z.sort_order, "tables_count": z.n} for z in zones],
        "branches": [{"id": b.id, "name": b.name} for b in Branch.objects.filter(is_active=True)],
        "waiters": [{"id": u.id, "name": u.full_name or u.phone} for u in _staff()],
        "settings": {
            "long_sit_minutes": int(cfg.get("long_sit_minutes", 90)),
            "require_cleaning": bool(cfg.get("require_cleaning", True)),
            "default_guests": int(cfg.get("default_guests", 2)),
        },
        "reservations_on": "reservations" in (request.tenant.enabled_modules or []),
        "can": {"serve": request.auth.has_perm_code("tables.serve"),
                "admin": request.auth.has_perm_code("tables.admin")},
    }


def _staff():
    from core.models import User

    return User.objects.filter(is_active=True).order_by("full_name")[:200]


def _table_dict(t: Table, reserved: set[int], res_map: dict) -> dict:
    s = t.session
    return {
        "id": t.id, "number": t.number, "zone_id": t.zone_id, "branch_id": t.branch_id,
        "seats": t.seats, "shape": t.shape, "x": t.x, "y": t.y, "size": t.size,
        "is_active": t.is_active, "note": t.note,
        "status": t.status(reserved),
        "session": SessionOut.from_orm(s).dict() if s else None,
        "reservation": res_map.get(t.id),
    }


@router.get("/board", auth=auth)
def board(request, branch_id: Optional[int] = None, zone_id: Optional[int] = None):
    """Zal xaritasi: har stol holati, kim o'tirgan, qancha vaqt, keyingi bron."""
    _guard(request, "tables.view")
    qs = Table.objects.select_related("zone").prefetch_related("sessions__order", "sessions__waiter")
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if zone_id:
        qs = qs.filter(zone_id=zone_id)
    reserved = services.reserved_table_ids()
    res_map = _next_reservations(set(qs.values_list("id", flat=True)))
    tables = [_table_dict(t, reserved, res_map) for t in qs]
    counts = {s: 0 for s in TableStatus.values}
    for t in tables:
        counts[t["status"]] += 1
    return {"tables": tables, "counts": counts, "guests": sum((t["session"] or {}).get("guests", 0) for t in tables)}


def _next_reservations(table_ids: set[int]) -> dict:
    try:
        from modules.reservations.models import Reservation, ReservationStatus
    except Exception:  # pragma: no cover
        return {}
    now = timezone.now()
    out: dict[int, dict] = {}
    qs = Reservation.objects.filter(table_id__in=table_ids, starts_at__gte=now - timedelta(minutes=30),
                                    starts_at__lte=now + timedelta(hours=6),
                                    status__in=[ReservationStatus.NEW, ReservationStatus.CONFIRMED]).order_by("starts_at")
    for r in qs:
        out.setdefault(r.table_id, {"id": r.id, "name": r.guest_name, "guests": r.guests,
                                    "at": r.starts_at.isoformat(), "phone": r.phone})
    return out


@router.get("/stats", auth=auth)
def stats(request):
    """Bugun: nechta stol aylandi, o'rtacha o'tirish vaqti, o'rtacha chek."""
    _guard(request, "tables.view")
    today = timezone.localdate()
    qs = TableSession.objects.filter(opened_at__date=today)
    closed = [s for s in qs if s.closed_at]
    avg_min = round(sum(s.minutes for s in closed) / len(closed)) if closed else None
    total = qs.filter(closed_at__isnull=False).aggregate(s=Sum("total"))["s"] or 0
    tables_n = Table.objects.filter(is_active=True).count()
    return {
        "sessions": qs.count(), "open": qs.filter(closed_at__isnull=True).count(),
        "avg_minutes": avg_min, "guests": qs.aggregate(g=Sum("guests"))["g"] or 0,
        "turnover": round(qs.count() / tables_n, 1) if tables_n else 0,
        "avg_check": int(total / len(closed)) if closed else 0,
    }


@router.get("/sessions", auth=auth)
def sessions(request, limit: int = 50):
    """Bugungi o'tirishlar tarixi (ofitsiant hisoboti uchun)."""
    _guard(request, "tables.view")
    qs = (TableSession.objects.select_related("table", "waiter", "order")
          .filter(opened_at__date=timezone.localdate())[:limit])
    return [{"id": s.id, "table": s.table.number, "guests": s.guests, "minutes": s.minutes,
             "waiter": s.waiter.full_name if s.waiter_id else None, "total": s.total,
             "opened_at": s.opened_at.isoformat(), "closed": bool(s.closed_at),
             "order_number": s.order.number if s.order_id else None} for s in qs]


# ------------------------------------------------------------------ ofitsiant amallari
@router.post("/{int:tid}/open", auth=auth)
def open_table(request, tid: int, data: OpenIn):
    _guard(request, "tables.serve")
    t = get_object_or_404(Table, pk=tid)
    if not t.is_active:
        raise HttpError(400, "Bu stol ishlatilmaydi.")
    s = services.open_session(t, guests=data.guests, waiter=request.auth, note=data.note, tenant=request.tenant)
    if data.waiter_id:
        s.waiter_id = data.waiter_id
        s.save(update_fields=["waiter"])
    record(request, "open", s)
    return SessionOut.from_orm(s).dict()


@router.post("/{int:tid}/bill", auth=auth)
def bill(request, tid: int):
    _guard(request, "tables.serve")
    t = get_object_or_404(Table, pk=tid)
    s = t.session
    if not s:
        raise HttpError(400, "Stol bo'sh.")
    services.ask_bill(s, tenant=request.tenant)
    return {"ok": True}


@router.post("/{int:tid}/close", auth=auth)
def close_table(request, tid: int):
    """Mehmonlar ketdi. Ochiq buyurtma bo'lsa - avval kassada to'lansin."""
    _guard(request, "tables.serve")
    t = get_object_or_404(Table, pk=tid)
    s = t.session
    if not s:
        raise HttpError(400, "Stol allaqachon bo'sh.")
    if s.order_id and s.order.status == "open":
        raise HttpError(400, f"Buyurtma #{s.order.number} hali to'lanmagan - avval kassada yoping.")
    services.close_session(s, tenant=request.tenant)
    record(request, "close", s)
    return {"ok": True}


@router.post("/{int:tid}/clean", auth=auth)
def clean(request, tid: int):
    _guard(request, "tables.serve")
    Table.objects.filter(pk=tid).update(needs_cleaning=False)
    return {"ok": True}


@router.post("/{int:tid}/move", auth=auth)
def move(request, tid: int, data: MoveIn):
    _guard(request, "tables.serve")
    t = get_object_or_404(Table, pk=tid)
    target = get_object_or_404(Table, pk=data.target_id)
    s = t.session
    if not s:
        raise HttpError(400, "Stol bo'sh.")
    try:
        services.move_session(s, target, tenant=request.tenant)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    record(request, "move", s, after={"to": target.number})
    return {"ok": True}


# ------------------------------------------------------------------ egasi sozlaydi
@router.post("/zones", response=ZoneOut, auth=auth)
def create_zone(request, data: ZoneIn):
    _guard(request, "tables.admin")
    z = Zone.objects.create(**data.dict(), sort_order=Zone.objects.count())
    record(request, "create", z)
    return z


@router.put("/zones/{int:zid}", response=ZoneOut, auth=auth)
def update_zone(request, zid: int, data: ZoneIn):
    _guard(request, "tables.admin")
    z = get_object_or_404(Zone, pk=zid)
    for k, v in data.dict().items():
        setattr(z, k, v)
    z.save()
    record(request, "update", z)
    return z


@router.delete("/zones/{int:zid}", auth=auth)
def delete_zone(request, zid: int):
    _guard(request, "tables.admin")
    z = get_object_or_404(Zone, pk=zid)
    if z.tables.exists():
        raise HttpError(400, "Avval shu zaldagi stollarni ko'chiring yoki o'chiring.")
    z.delete()
    return {"ok": True}


@router.post("", auth=auth)
def create_table(request, data: TableIn):
    _guard(request, "tables.admin")
    if Table.objects.filter(number=data.number, branch_id=data.branch_id).exists():
        raise HttpError(400, f"«{data.number}» raqamli stol allaqachon bor.")
    t = Table.objects.create(**data.dict())
    record(request, "create", t)
    return _table_dict(t, set(), {})


@router.put("/{int:tid}", auth=auth)
def update_table(request, tid: int, data: TableIn):
    _guard(request, "tables.admin")
    t = get_object_or_404(Table, pk=tid)
    if Table.objects.filter(number=data.number, branch_id=data.branch_id).exclude(pk=tid).exists():
        raise HttpError(400, f"«{data.number}» raqamli stol allaqachon bor.")
    for k, v in data.dict().items():
        setattr(t, k, v)
    t.save()
    record(request, "update", t)
    return _table_dict(t, set(), {})


@router.delete("/{int:tid}", auth=auth)
def delete_table(request, tid: int):
    _guard(request, "tables.admin")
    t = get_object_or_404(Table, pk=tid)
    if t.session:
        raise HttpError(400, "Stol band - avval yoping.")
    t.delete()
    return {"ok": True}


@router.post("/layout", auth=auth)
def save_layout(request, data: LayoutIn):
    """Zal xaritasini sichqoncha bilan tartiblab, bir marta saqlash."""
    _guard(request, "tables.admin")
    by_id = {t.id: t for t in Table.objects.filter(id__in=[p.id for p in data.tables])}
    upd = []
    for p in data.tables:
        t = by_id.get(p.id)
        if t:
            t.x, t.y = max(0.0, min(96.0, p.x)), max(0.0, min(94.0, p.y))
            upd.append(t)
    Table.objects.bulk_update(upd, ["x", "y"])
    record(request, "update", model="TableLayout", after={"tables": len(upd)})
    return {"ok": True, "saved": len(upd)}


@router.post("/bulk", auth=auth)
def bulk_create(request, count: int = 10, zone_id: Optional[int] = None, seats: int = 4, start: int = 1):
    """«10 ta stol qo'shish» tugmasi - qo'lda bittalab kiritmaslik uchun."""
    _guard(request, "tables.admin")
    if count < 1 or count > 100:
        raise HttpError(400, "1 dan 100 gacha.")
    made, n = [], start
    exists = set(Table.objects.values_list("number", flat=True))
    for i in range(count):
        while str(n) in exists:
            n += 1
        made.append(Table(number=str(n), zone_id=zone_id, seats=seats,
                          x=8 + (i % 6) * 15, y=10 + (i // 6) * 22))
        exists.add(str(n))
    Table.objects.bulk_create(made)
    return {"ok": True, "created": len(made)}


@router.get("/free", auth=auth)
def free_tables(request, guests: int = 1):
    """Bo'sh stollar (bron va ko'chirish oynasi uchun)."""
    _guard(request, "tables.view")
    busy = set(TableSession.objects.filter(closed_at__isnull=True).values_list("table_id", flat=True))
    qs = Table.objects.filter(is_active=True, seats__gte=guests).exclude(id__in=busy).filter(~Q(needs_cleaning=True))
    return [{"id": t.id, "number": t.number, "seats": t.seats, "zone": t.zone.name if t.zone_id else ""} for t in qs]