"""Zakup (xarid) API — /api/v1/procurement/..."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.audit import record
from core.auth import auth, require_module, require_perm

from . import services
from .models import (
    CAT_CODES,
    CATEGORIES,
    ExpenseKind,
    Market,
    MarketKind,
    Order,
    OrderLine,
    OrderStatus,
    Payment,
    PayMethod,
    PayTerms,
    SupplierKind,
    SupplierPrice,
    Trip,
    TripExpense,
    TripItem,
    TripStatus,
)

router = Router(tags=["procurement"])


def _guard(request, perm: str):
    require_module(request, "procurement")
    require_perm(request, perm)


def _can(request, perm: str) -> bool:
    return request.auth.has_perm_code(perm)


def _cats(v: list[str]) -> list[str]:
    return [c for c in v if c in CAT_CODES]


# ------------------------------------------------------------------ umumiy
@router.get("/meta", auth=auth)
def meta(request):
    _guard(request, "procurement.buy")
    from core.models import Branch, User
    from modules.inventory.models import Ingredient, Supplier
    services.ensure_markets()
    return {
        "categories": [{"code": c, "name": n, "emoji": e} for c, n, e in CATEGORIES],
        "market_kinds": [{"code": k.value, "label": k.label} for k in MarketKind],
        "supplier_kinds": [{"code": k.value, "label": k.label} for k in SupplierKind],
        "terms": [{"code": k.value, "label": k.label} for k in PayTerms],
        "pay_methods": [{"code": k.value, "label": k.label} for k in PayMethod],
        "expense_kinds": [{"code": k.value, "label": k.label} for k in ExpenseKind],
        "order_statuses": [{"code": k.value, "label": k.label} for k in OrderStatus],
        "suppliers": [{"id": s.pk, "name": s.name} for s in Supplier.objects.filter(is_active=True)],
        "markets": [{"id": m.pk, "name": m.name} for m in Market.objects.filter(is_active=True)],
        "ingredients": [{"id": i.pk, "name": str(i), "unit": i.unit, "price": float(i.price), "stock": float(i.stock), "supplier_id": i.supplier_id,
                         "category": services.cat_of(i)} for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True)],
        "branches": [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True)],
        "buyers": [{"id": str(u.pk), "name": u.full_name or u.phone} for u in User.objects.filter(is_active=True, memberships__is_active=True).distinct()]
        if _can(request, "procurement.edit") else [{"id": str(request.auth.pk), "name": request.auth.full_name or request.auth.phone}],
        "me": str(request.auth.pk), "can_edit": _can(request, "procurement.edit"), "can_pay": _can(request, "procurement.pay"),
        "overhead_to_cost": services.setting(request.tenant, "overhead_to_cost", True),
    }


@router.get("/overview", auth=auth)
def overview(request):
    _guard(request, "procurement.view")
    services.ensure_markets()
    return services.overview(request.tenant)


@router.get("/search", auth=auth)
def search(request, q: str = "", cat: str = ""):
    _guard(request, "procurement.view")
    return services.search(q.strip(), cat if cat in CAT_CODES else "")


# ------------------------------------------------------------------ bozorlar
class MarketIn(Schema):
    name: str
    kind: str = MarketKind.BAZAAR
    city: str = "Toshkent"
    district: str = ""
    address: str = ""
    landmark: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    hours: str = ""
    days: str = ""
    categories: list[str] = []
    tips: str = ""
    phone: str = ""
    is_active: bool = True


@router.get("/markets", auth=auth)
def markets(request, cat: str = ""):
    _guard(request, "procurement.buy")
    services.ensure_markets()
    out = [services.market_out(m) for m in Market.objects.all()]
    return [m for m in out if not cat or any(c["code"] == cat for c in m["categories"])]


def _market_save(m: Market, data: MarketIn):
    if not data.name.strip():
        raise HttpError(400, "Bozor nomini kiriting.")
    if data.kind not in MarketKind.values:
        raise HttpError(400, "Noto'g'ri tur.")
    for k, v in data.dict().items():
        setattr(m, k, _cats(v) if k == "categories" else v)
    m.save()


@router.post("/markets", auth=auth)
def create_market(request, data: MarketIn):
    _guard(request, "procurement.edit")
    m = Market()
    _market_save(m, data)
    record(request, "create", m)
    return services.market_out(m)


@router.put("/markets/{int:mid}", auth=auth)
def update_market(request, mid: int, data: MarketIn):
    _guard(request, "procurement.edit")
    m = get_object_or_404(Market, pk=mid)
    _market_save(m, data)
    record(request, "update", m)
    return services.market_out(m)


@router.delete("/markets/{int:mid}", auth=auth)
def delete_market(request, mid: int):
    _guard(request, "procurement.edit")
    m = get_object_or_404(Market, pk=mid)
    record(request, "delete", m)
    if m.is_builtin or m.trips.exists() or m.suppliers.exists():
        m.is_active = False
        m.save(update_fields=["is_active", "updated_at"])
        return {"ok": True, "disabled": True}
    m.delete()
    return {"ok": True, "disabled": False}


# ------------------------------------------------------------------ ta'minotchilar
class SupplierIn(Schema):
    name: str
    phone: str = ""
    note: str = ""
    is_active: bool = True
    kind: str = SupplierKind.COMPANY
    categories: list[str] = []
    market_id: Optional[int] = None
    contact_name: str = ""
    telegram: str = ""
    address: str = ""
    delivers: bool = False
    min_order: str = ""
    terms: str = PayTerms.CASH
    credit_days: int = 0
    photo_url: str = ""


def _month_totals() -> dict[int, int]:
    from modules.inventory.models import Purchase
    ms = timezone.localdate().replace(day=1)
    return {r["supplier_id"]: int(r["s"] or 0) for r in Purchase.objects.filter(date__gte=ms, supplier__isnull=False).values("supplier_id").annotate(s=Sum("total"))}


@router.get("/suppliers", auth=auth)
def suppliers(request, q: str = "", cat: str = "", kind: str = "", debt: bool = False):
    _guard(request, "procurement.view")
    from modules.inventory.models import Supplier
    qs = Supplier.objects.all().select_related("info__market")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(info__contact_name__icontains=q))
    d, rt, mt = services.debts(), services.ratings(), _month_totals()
    out = [services.supplier_out(s, debt=d.get(s.pk), rating=rt.get(s.pk), month_total=mt.get(s.pk, 0)) for s in qs]
    if cat:
        out = [s for s in out if any(c["code"] == cat for c in s["categories"])]
    if kind:
        out = [s for s in out if s["kind"] == kind]
    if debt:
        out = [s for s in out if s["debt"] > 0]
    counts = {k.value: sum(1 for s in out if s["kind"] == k.value) for k in SupplierKind}
    return {"items": sorted(out, key=lambda s: (not s["is_active"], -(s["rating"] or 0), s["name"])), "counts": counts}


@router.get("/suppliers/{int:sid}", auth=auth)
def supplier_detail(request, sid: int):
    _guard(request, "procurement.view")
    from modules.inventory.models import Supplier
    s = get_object_or_404(Supplier, pk=sid)
    d, rt = services.debts(), services.ratings()
    out = services.supplier_out(s, debt=d.get(s.pk), rating=rt.get(s.pk))
    seen, prices = set(), []
    for p in SupplierPrice.objects.filter(supplier=s).select_related("ingredient")[:200]:
        if p.ingredient_id in seen:
            continue
        seen.add(p.ingredient_id)
        prices.append({"ingredient_id": p.ingredient_id, "ingredient": str(p.ingredient), "unit": p.ingredient.unit, "price": p.price, "date": p.date.isoformat()})
    out["prices"] = prices
    out["orders"] = [services.order_out(o) for o in s.orders.select_related("branch")[:20]]
    out["payments"] = [{"id": p.pk, "amount": p.amount, "date": p.date.isoformat(), "method": PayMethod(p.method).label, "note": p.note} for p in s.payments.all()[:20]]
    out["debt_info"] = d.get(s.pk)
    return out


def _supplier_save(s, data: SupplierIn):
    if not data.name.strip():
        raise HttpError(400, "Ta'minotchi nomini kiriting.")
    if data.kind not in SupplierKind.values or data.terms not in PayTerms.values:
        raise HttpError(400, "Tur yoki to'lov sharti noto'g'ri.")
    s.name, s.phone, s.note, s.is_active = data.name.strip(), data.phone.strip(), data.note, data.is_active
    s.save()
    i = services.ensure_info(s)
    i.kind, i.categories = data.kind, _cats(data.categories)
    i.market = Market.objects.filter(pk=data.market_id).first() if data.market_id else None
    for k in ("contact_name", "telegram", "address", "delivers", "min_order", "terms", "credit_days", "photo_url"):
        setattr(i, k, getattr(data, k))
    i.save()


@router.post("/suppliers", auth=auth)
def create_supplier(request, data: SupplierIn):
    _guard(request, "procurement.edit")
    from modules.inventory.models import Supplier
    s = Supplier(name=data.name.strip() or "—")
    _supplier_save(s, data)
    record(request, "create", s)
    return services.supplier_out(s)


@router.put("/suppliers/{int:sid}", auth=auth)
def update_supplier(request, sid: int, data: SupplierIn):
    _guard(request, "procurement.edit")
    from modules.inventory.models import Supplier
    s = get_object_or_404(Supplier, pk=sid)
    _supplier_save(s, data)
    record(request, "update", s)
    return services.supplier_out(s)


# ------------------------------------------------------------------ narxlar
class PriceIn(Schema):
    ingredient_id: int
    price: int
    supplier_id: Optional[int] = None
    market_id: Optional[int] = None
    note: str = ""


@router.get("/prices", auth=auth)
def prices(request, ingredient_id: int):
    _guard(request, "procurement.view")
    from modules.inventory.models import Ingredient
    i = get_object_or_404(Ingredient, pk=ingredient_id)
    hist = [{"date": p.date.isoformat(), "price": p.price, "who": p.supplier.name if p.supplier_id else (p.market.name if p.market_id else "—"),
             "source": p.source} for p in SupplierPrice.objects.filter(ingredient=i).select_related("supplier", "market")[:30]]
    return {"ingredient": {"id": i.pk, "name": str(i), "unit": i.unit, "price": float(i.price), "stock": float(i.stock)},
            "board": services.price_board(i), "history": hist}


@router.post("/prices", auth=auth)
def add_price(request, data: PriceIn):
    _guard(request, "procurement.buy")
    from modules.inventory.models import Ingredient, Supplier
    if data.price <= 0:
        raise HttpError(400, "Narxni kiriting.")
    if not data.supplier_id and not data.market_id:
        raise HttpError(400, "Ta'minotchi yoki bozorni tanlang.")
    i = get_object_or_404(Ingredient, pk=data.ingredient_id)
    services.record_price(ingredient=i, price=data.price, supplier=Supplier.objects.filter(pk=data.supplier_id).first() if data.supplier_id else None,
                          market=Market.objects.filter(pk=data.market_id).first() if data.market_id else None, note=data.note)
    return {"board": services.price_board(i)}


# ------------------------------------------------------------------ buyurtmalar
class LineIn(Schema):
    ingredient_id: int
    qty: float
    price: int = 0


class OrderIn(Schema):
    supplier_id: int
    branch_id: Optional[int] = None
    expected_date: Optional[date] = None
    note: str = ""
    lines: list[LineIn]


@router.get("/orders", auth=auth)
def orders(request, status: str = "", supplier_id: Optional[int] = None):
    _guard(request, "procurement.view")
    qs = Order.objects.select_related("supplier", "branch")
    if status:
        qs = qs.filter(status=status)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    counts = {k.value: Order.objects.filter(status=k.value).count() for k in OrderStatus}
    return {"items": [services.order_out(o) for o in qs[:300]], "counts": counts}


@router.get("/orders/{int:oid}", auth=auth)
def order(request, oid: int):
    _guard(request, "procurement.view")
    return services.order_out(get_object_or_404(Order.objects.select_related("supplier", "branch"), pk=oid), full=True)


def _lines(o: Order, lines: list[LineIn]):
    from modules.inventory.models import Ingredient
    o.lines.all().delete()
    for ln in lines:
        if ln.qty <= 0:
            continue
        ing = get_object_or_404(Ingredient, pk=ln.ingredient_id)
        price = ln.price or services.last_price(ing, o.supplier) or int(ing.price)
        OrderLine.objects.create(order=o, ingredient=ing, qty=Decimal(str(ln.qty)), price=price)
    if not o.lines.exists():
        raise HttpError(400, "Kamida bitta mahsulot va miqdor kiriting.")
    services.recalc(o)


@router.post("/orders", auth=auth)
def create_order(request, data: OrderIn):
    _guard(request, "procurement.edit")
    from django.db import transaction

    from modules.inventory.models import Supplier
    with transaction.atomic():
        o = Order.objects.create(supplier=get_object_or_404(Supplier, pk=data.supplier_id), branch_id=data.branch_id,
                                 expected_date=data.expected_date, note=data.note, created_by=request.auth)
        _lines(o, data.lines)
    record(request, "create", o)
    return services.order_out(o, full=True)


@router.put("/orders/{int:oid}", auth=auth)
def update_order(request, oid: int, data: OrderIn):
    _guard(request, "procurement.edit")
    from django.db import transaction
    o = get_object_or_404(Order, pk=oid)
    if o.status in (OrderStatus.RECEIVED, OrderStatus.CANCELLED):
        raise HttpError(400, "Yopilgan buyurtmani o'zgartirib bo'lmaydi.")
    with transaction.atomic():
        o.expected_date, o.note, o.branch_id = data.expected_date, data.note, data.branch_id
        o.save()
        _lines(o, data.lines)
    return services.order_out(o, full=True)


class StatusIn(Schema):
    status: str


@router.post("/orders/{int:oid}/status", auth=auth)
def order_status(request, oid: int, data: StatusIn):
    _guard(request, "procurement.edit")
    o = get_object_or_404(Order, pk=oid)
    allowed = {OrderStatus.DRAFT: {"sent", "cancelled"}, OrderStatus.SENT: {"confirmed", "cancelled", "draft"}, OrderStatus.CONFIRMED: {"cancelled", "sent"}}
    if data.status not in allowed.get(o.status, set()):
        raise HttpError(400, f"«{OrderStatus(o.status).label}» holatidan bunga o'tib bo'lmaydi.")
    o.status = data.status
    if data.status == "sent":
        o.sent_at = timezone.now()
    o.save()
    record(request, "update", o, after={"status": data.status})
    return services.order_out(o, full=True)


class ReceiveIn(Schema):
    lines: dict[str, float] = {}


@router.post("/orders/{int:oid}/receive", auth=auth)
def receive(request, oid: int, data: ReceiveIn):
    """Qabul qilish: haqiqiy miqdor → omborga kirim, narx tarixi, qarzdorlik."""
    _guard(request, "procurement.edit")
    o = get_object_or_404(Order, pk=oid)
    try:
        services.receive(o, {int(k): Decimal(str(v)) for k, v in data.lines.items()}, tenant=request.tenant, actor=request.auth)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    record(request, "receive", o, after={"total": o.total})
    return services.order_out(Order.objects.get(pk=oid), full=True)


class RateIn(Schema):
    rating: int
    note: str = ""


@router.post("/orders/{int:oid}/rate", auth=auth)
def rate(request, oid: int, data: RateIn):
    _guard(request, "procurement.edit")
    if not 1 <= data.rating <= 5:
        raise HttpError(400, "Baho 1 dan 5 gacha.")
    o = get_object_or_404(Order, pk=oid)
    o.rating, o.rating_note = data.rating, data.note
    o.save(update_fields=["rating", "rating_note", "updated_at"])
    return {"ok": True}


# ------------------------------------------------------------------ qarzdorlik va to'lov
@router.get("/debts", auth=auth)
def debts(request):
    _guard(request, "procurement.view")
    from modules.inventory.models import Supplier
    d = services.debts()
    sup = {s.pk: s for s in Supplier.objects.filter(pk__in=d.keys()).select_related("info")}
    rows = [{"supplier_id": sid, "supplier": sup[sid].name, "phone": sup[sid].phone, **v,
             "terms": getattr(getattr(sup[sid], "info", None), "terms", "cash"), "credit_days": getattr(getattr(sup[sid], "info", None), "credit_days", 0)}
            for sid, v in d.items() if sid in sup]
    rows.sort(key=lambda r: (-r["overdue"], -r["debt"]))
    return {"items": rows, "total": sum(r["debt"] for r in rows), "overdue": sum(r["debt"] for r in rows if r["overdue"]),
            "recent_payments": [{"id": p.pk, "supplier": p.supplier.name, "amount": p.amount, "date": p.date.isoformat(), "method": PayMethod(p.method).label}
                                for p in Payment.objects.select_related("supplier")[:15]]}


class PaymentIn(Schema):
    supplier_id: int
    amount: int
    method: str = PayMethod.CASH
    note: str = ""
    order_id: Optional[int] = None
    date: Optional[date] = None


@router.post("/payments", auth=auth)
def pay(request, data: PaymentIn):
    _guard(request, "procurement.pay")
    from modules.inventory.models import Supplier
    if data.amount <= 0:
        raise HttpError(400, "Summani kiriting.")
    s = get_object_or_404(Supplier, pk=data.supplier_id)
    p = Payment.objects.create(supplier=s, amount=data.amount, method=data.method if data.method in PayMethod.values else PayMethod.CASH,
                               note=data.note, order_id=data.order_id, date=data.date or timezone.localdate(), created_by=request.auth)
    record(request, "create", p)
    return {"ok": True, "debt": services.debts().get(s.pk, {}).get("debt", 0)}


# ------------------------------------------------------------------ bozorlik
def _trip(request, tid: int) -> Trip:
    t = get_object_or_404(Trip.objects.select_related("buyer", "market", "branch"), pk=tid)
    if t.buyer_id != request.auth.pk and not _can(request, "procurement.edit"):
        raise HttpError(403, "Bu bozorlik sizniki emas.")
    return t


def _trip_out(t: Trip, full: bool = False) -> dict:
    tot = services.trip_totals(t)
    out = {"id": t.pk, "number": t.number, "date": t.date.isoformat(), "buyer_id": str(t.buyer_id), "buyer": t.buyer.full_name or t.buyer.phone,
           "market": {"id": t.market_id, "name": t.market.name} if t.market_id else None, "branch": t.branch.name if t.branch_id else None,
           "status": t.status, "status_label": TripStatus(t.status).label, "advance": t.advance, "returned": t.returned, "note": t.note,
           "overhead_to_cost": t.overhead_to_cost, "closed_at": t.closed_at.isoformat() if t.closed_at else None, **tot,
           "items_sum": tot["items"], "expenses_sum": tot["expenses"]}   # to'liq ko'rinishda items/expenses — ro'yxatlar
    if full:
        out["items"] = [{"id": i.pk, "ingredient_id": i.ingredient_id, "name": i.name, "unit": i.unit, "planned_qty": float(i.planned_qty),
                         "qty": float(i.qty), "price": i.price, "total": i.total, "seller": i.seller, "photo": i.photo.url if i.photo else None}
                        for i in t.items.all()]
        out["expenses"] = [{"id": e.pk, "kind": e.kind, "label": ExpenseKind(e.kind).label, "amount": e.amount, "note": e.note,
                            "photo": e.photo.url if e.photo else None} for e in t.expenses.all()]
    return out


@router.get("/trips", auth=auth)
def trips(request, status: str = "", mine: bool = False):
    _guard(request, "procurement.buy")
    qs = Trip.objects.select_related("buyer", "market", "branch").prefetch_related("items", "expenses")
    if mine or not _can(request, "procurement.edit"):
        qs = qs.filter(buyer=request.auth)
    if status:
        qs = qs.filter(status=status)
    return [_trip_out(t) for t in qs[:200]]


class PlanItem(Schema):
    ingredient_id: Optional[int] = None
    name: str = ""
    qty: float = 0
    unit: str = "kg"


class TripIn(Schema):
    buyer_id: Optional[str] = None
    advance: int = 0
    market_id: Optional[int] = None
    branch_id: Optional[int] = None
    date: Optional[date] = None
    note: str = ""
    plan: list[PlanItem] = []


@router.post("/trips", auth=auth)
def create_trip(request, data: TripIn):
    """Yangi bozorlik: bozorchi, avans, bozor, xarid ro'yxati (Xarid rejasidan yoki qo'lda)."""
    _guard(request, "procurement.buy")
    from core.models import User
    from modules.inventory.models import Ingredient
    buyer = request.auth
    if data.buyer_id and data.buyer_id != str(request.auth.pk):
        if not _can(request, "procurement.edit"):
            raise HttpError(403, "Boshqa xodimga bozorlik ocha olmaysiz.")
        buyer = get_object_or_404(User, pk=data.buyer_id)
    limit = int(services.setting(request.tenant, "trip_limit", 0) or 0)
    if data.advance < 0 or (limit and data.advance > limit):
        raise HttpError(400, f"Avans 0 dan {limit:,} so'mgacha bo'lishi mumkin.".replace(",", " ") if limit else "Avans manfiy bo'lmaydi.")
    t = Trip.objects.create(buyer=buyer, advance=data.advance, market_id=data.market_id, branch_id=data.branch_id, date=data.date or timezone.localdate(),
                            note=data.note, created_by=request.auth, overhead_to_cost=services.setting(request.tenant, "overhead_to_cost", True))
    for p in data.plan:
        ing = Ingredient.objects.filter(pk=p.ingredient_id).first() if p.ingredient_id else None
        name = str(ing) if ing else p.name.strip()
        if name:
            TripItem.objects.create(trip=t, ingredient=ing, name=name, unit=ing.unit if ing else (p.unit or "kg"), planned_qty=Decimal(str(max(0, p.qty))))
    record(request, "create", t, after={"advance": t.advance, "buyer": str(buyer)})
    return _trip_out(t, full=True)


@router.get("/trips/{int:tid}", auth=auth)
def trip(request, tid: int):
    _guard(request, "procurement.buy")
    return _trip_out(_trip(request, tid), full=True)


class ItemIn(Schema):
    ingredient_id: Optional[int] = None
    name: str = ""
    unit: str = "kg"
    qty: float
    price: int = 0
    total: int = 0
    seller: str = ""


def _open(t: Trip):
    if t.status in (TripStatus.CLOSED, TripStatus.CANCELLED):
        raise HttpError(400, "Bozorlik yopilgan — o'zgartirib bo'lmaydi.")


def _apply_item(i: TripItem, data: ItemIn):
    from modules.inventory.models import Ingredient
    if data.qty <= 0:
        raise HttpError(400, "Miqdorni kiriting.")
    ing = Ingredient.objects.filter(pk=data.ingredient_id).first() if data.ingredient_id else i.ingredient
    name = str(ing) if ing else (data.name.strip() or i.name)
    if not name:
        raise HttpError(400, "Mahsulot nomini kiriting yoki ro'yxatdan tanlang.")
    q = Decimal(str(data.qty))
    if data.total and not data.price:
        price, total = int(Decimal(data.total) / q), int(data.total)
    else:
        price = data.price
        total = data.total or int(q * price)
    if total <= 0:
        raise HttpError(400, "Narx yoki umumiy summani kiriting.")
    i.ingredient, i.name, i.unit = ing, name, ing.unit if ing else data.unit
    i.qty, i.price, i.total, i.seller = q, price, total, data.seller.strip()
    i.save()


@router.post("/trips/{int:tid}/items", auth=auth)
def add_item(request, tid: int, data: ItemIn):
    _guard(request, "procurement.buy")
    t = _trip(request, tid)
    _open(t)
    i = None
    if data.ingredient_id:   # rejadagi band bo'lsa — o'shani to'ldiramiz
        i = t.items.filter(ingredient_id=data.ingredient_id, qty=0).first()
    _apply_item(i or TripItem(trip=t), data)
    if t.status == TripStatus.PLANNED:
        t.status = TripStatus.ACTIVE
        t.save(update_fields=["status", "updated_at"])
    return _trip_out(t, full=True)


@router.put("/trips/{int:tid}/items/{int:iid}", auth=auth)
def edit_item(request, tid: int, iid: int, data: ItemIn):
    _guard(request, "procurement.buy")
    t = _trip(request, tid)
    _open(t)
    _apply_item(get_object_or_404(TripItem, pk=iid, trip=t), data)
    return _trip_out(t, full=True)


@router.delete("/trips/{int:tid}/items/{int:iid}", auth=auth)
def del_item(request, tid: int, iid: int):
    _guard(request, "procurement.buy")
    t = _trip(request, tid)
    _open(t)
    get_object_or_404(TripItem, pk=iid, trip=t).delete()
    return _trip_out(t, full=True)


@router.post("/trips/{int:tid}/items/{int:iid}/photo", auth=auth)
def item_photo(request, tid: int, iid: int, file: UploadedFile = File(...)):
    _guard(request, "procurement.buy")
    t = _trip(request, tid)
    i = get_object_or_404(TripItem, pk=iid, trip=t)
    if file.size > 8 * 1024 * 1024:
        raise HttpError(400, "Rasm 8 MB dan oshmasin.")
    i.photo.save(file.name, file, save=True)
    return _trip_out(t, full=True)


class ExpIn(Schema):
    kind: str = ExpenseKind.TAXI
    amount: int
    note: str = ""


@router.post("/trips/{int:tid}/expenses", auth=auth)
def add_expense(request, tid: int, data: ExpIn):
    _guard(request, "procurement.buy")
    t = _trip(request, tid)
    _open(t)
    if data.amount <= 0 or data.kind not in ExpenseKind.values:
        raise HttpError(400, "Xarajat turi va summasini kiriting.")
    TripExpense.objects.create(trip=t, kind=data.kind, amount=data.amount, note=data.note.strip())
    return _trip_out(t, full=True)


@router.delete("/trips/{int:tid}/expenses/{int:eid}", auth=auth)
def del_expense(request, tid: int, eid: int):
    _guard(request, "procurement.buy")
    t = _trip(request, tid)
    _open(t)
    get_object_or_404(TripExpense, pk=eid, trip=t).delete()
    return _trip_out(t, full=True)


class CloseIn(Schema):
    returned: int = 0


@router.post("/trips/{int:tid}/close", auth=auth)
def close(request, tid: int, data: CloseIn):
    """Hisobni qabul qilish (menejer/kassir): qaytgan pul, mahsulotlar omborga."""
    _guard(request, "procurement.buy")
    if not (_can(request, "procurement.edit") or _can(request, "procurement.pay")):
        raise HttpError(403, "Hisobni menejer yoki kassir qabul qiladi.")
    t = _trip(request, tid)
    if not t.items.filter(qty__gt=0).exists() and not t.expenses.exists():
        raise HttpError(400, "Hali hech narsa kiritilmagan.")
    try:
        services.close_trip(t, data.returned, tenant=request.tenant, actor=request.auth)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    record(request, "close", t, after={"returned": data.returned})
    return _trip_out(Trip.objects.get(pk=tid), full=True)


@router.post("/trips/{int:tid}/cancel", auth=auth)
def cancel(request, tid: int):
    _guard(request, "procurement.edit")
    t = _trip(request, tid)
    _open(t)
    t.status = TripStatus.CANCELLED
    t.save(update_fields=["status", "updated_at"])
    return _trip_out(t, full=True)


@router.get("/trip-stats", auth=auth)
def trip_stats(request, days: int = 30):
    _guard(request, "procurement.view")
    end = timezone.localdate()
    return services.trip_stats(end - timedelta(days=max(1, min(365, days)) - 1), end)
