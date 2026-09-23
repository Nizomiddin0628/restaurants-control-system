"""Oshxona ekrani API — /api/v1/kds/..."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_module, require_perm
from modules.catalog.models import Category

from . import services
from .models import Station, Ticket, TicketItem, TicketStatus, ensure_stations

router = Router(tags=["kds"])


def _guard(request, perm: str):
    require_module(request, "kds")
    require_perm(request, perm)


class I18n(Schema):
    uz: str = ""
    ru: str = ""
    en: str = ""


class StationIn(Schema):
    name: I18n
    color: str = "#0F6E63"
    category_ids: list[int] = []
    branch_id: Optional[int] = None
    is_active: bool = True


class StationOut(Schema):
    id: int
    code: str
    name: dict
    color: str
    is_active: bool
    category_ids: list[int] = []
    open_count: int = 0

    @staticmethod
    def resolve_category_ids(obj):
        return [c.id for c in obj.categories.all()]

    @staticmethod
    def resolve_open_count(obj):
        return obj.tickets.exclude(status__in=[TicketStatus.SERVED, TicketStatus.CANCELLED]).count()


class ItemOut(Schema):
    id: int
    name: str
    qty: int
    note: str
    modifiers: list = []
    is_done: bool


class TicketOut(Schema):
    id: int
    number: int
    status: str
    order_type: str = ""
    table_no: str = ""
    station_id: Optional[int] = None
    station_name: Optional[dict] = None
    waiting_minutes: int
    cook_minutes: Optional[int] = None
    created_at: datetime
    note: str
    cook: Optional[str] = None
    items: list[ItemOut] = []

    @staticmethod
    def resolve_order_type(obj):
        return obj.order.type

    @staticmethod
    def resolve_table_no(obj):
        return obj.order.table_no

    @staticmethod
    def resolve_station_name(obj):
        return obj.station.name if obj.station_id else None

    @staticmethod
    def resolve_cook(obj):
        return obj.cook.full_name if obj.cook_id else None


class StatusIn(Schema):
    status: str


@router.get("/meta", auth=auth)
def meta(request):
    """Stansiyalar, kategoriyalar va sozlamalar (rang chegaralari, yangilanish)."""
    _guard(request, "kds.view")
    ensure_stations()
    cfg = (request.tenant.settings or {}).get("modules", {}).get("kds", {}) or {}
    return {
        "stations": [StationOut.from_orm(s).dict() for s in Station.objects.prefetch_related("categories", "tickets")],
        "categories": [{"id": c.id, "name": c.name} for c in Category.objects.filter(deleted_at__isnull=True)],
        "settings": {
            "warn_minutes": int(cfg.get("warn_minutes", 8)),
            "late_minutes": int(cfg.get("late_minutes", 15)),
            "auto_refresh_seconds": int(cfg.get("auto_refresh_seconds", 5)),
            "create_on": cfg.get("create_on", "created"),
        },
        "can": {"cook": request.auth.has_perm_code("kds.cook"), "admin": request.auth.has_perm_code("kds.admin")},
    }


@router.get("/board", response=list[TicketOut], auth=auth)
def board(request, station_id: Optional[int] = None, include_served: bool = False):
    """Ekran: ochiq cheklar (yangi, tayyorlanmoqda, tayyor). Eng eski — birinchi."""
    _guard(request, "kds.view")
    qs = Ticket.objects.select_related("order", "station", "cook").prefetch_related("items")
    if not include_served:
        qs = qs.exclude(status__in=[TicketStatus.SERVED, TicketStatus.CANCELLED])
    else:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(hours=12))
    if station_id:
        qs = qs.filter(station_id=station_id)
    return qs


@router.post("/tickets/{tid}/status", response=TicketOut, auth=auth)
def set_status(request, tid: int, data: StatusIn):
    _guard(request, "kds.cook")
    if data.status not in TicketStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    t = get_object_or_404(Ticket.objects.select_related("order"), pk=tid)
    return services.set_status(request, t, data.status)


@router.post("/items/{iid}/toggle", response=TicketOut, auth=auth)
def toggle_item(request, iid: int):
    """Bitta taomni tayyor deb belgilash — hammasi tayyor bo'lsa chek o'zi «tayyor»ga o'tadi."""
    _guard(request, "kds.cook")
    item = get_object_or_404(TicketItem.objects.select_related("ticket"), pk=iid)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])
    t = item.ticket
    if t.status == TicketStatus.NEW and item.is_done:
        services.set_status(request, t, TicketStatus.COOKING)
    if all(i.is_done for i in t.items.all()) and t.status != TicketStatus.READY:
        services.set_status(request, t, TicketStatus.READY)
    t.refresh_from_db()
    return t


@router.get("/stats", auth=auth)
def stats(request):
    """Bugungi ko'rsatkichlar: nechta chek, o'rtacha tayyorlash vaqti, kechikkanlar."""
    _guard(request, "kds.view")
    today = timezone.localdate()
    qs = Ticket.objects.filter(created_at__date=today)
    done = [t for t in qs if t.ready_at]
    avg = round(sum((t.ready_at - t.created_at).total_seconds() / 60 for t in done) / len(done), 1) if done else None
    cfg = (request.tenant.settings or {}).get("modules", {}).get("kds", {}) or {}
    late_limit = int(cfg.get("late_minutes", 15))
    return {
        "tickets": qs.count(),
        "open": qs.exclude(status__in=[TicketStatus.SERVED, TicketStatus.CANCELLED]).count(),
        "avg_minutes": avg,
        "late": sum(1 for t in qs if t.waiting_minutes > late_limit and t.status != TicketStatus.SERVED),
    }


# ------------------------------------------------------------------ stansiyalar (egasi sozlaydi)
@router.post("/stations", response=StationOut, auth=auth)
def create_station(request, data: StationIn):
    _guard(request, "kds.admin")
    base = (data.name.uz or "station").lower().replace(" ", "_")[:30]
    code, i = base, 1
    while Station.objects.filter(code=code).exists():
        i += 1
        code = f"{base}_{i}"
    s = Station.objects.create(code=code, name=data.name.dict(), color=data.color, branch_id=data.branch_id,
                               is_active=data.is_active, sort_order=Station.objects.count())
    s.categories.set(data.category_ids)
    record(request, "create", s)
    return s


@router.put("/stations/{sid}", response=StationOut, auth=auth)
def update_station(request, sid: int, data: StationIn):
    _guard(request, "kds.admin")
    s = get_object_or_404(Station, pk=sid)
    s.name, s.color, s.branch_id, s.is_active = data.name.dict(), data.color, data.branch_id, data.is_active
    s.save()
    s.categories.set(data.category_ids)
    record(request, "update", s)
    return s


@router.delete("/stations/{sid}", auth=auth)
def delete_station(request, sid: int):
    _guard(request, "kds.admin")
    s = get_object_or_404(Station, pk=sid)
    if Station.objects.count() <= 1:
        raise HttpError(400, "Kamida bitta stansiya qolishi kerak.")
    s.delete()
    return {"ok": True}