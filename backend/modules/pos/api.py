"""Kassa API — /api/v1/pos/... (planshet/telefon kassa ekrani, Mini App ham shu yo'llardan buyurtma beradi)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_module, require_perm
from core.events import emit
from core.models import Branch
from modules.catalog.models import Category, Product

from .models import CashShift, Order, OrderItem, OrderStatus, OrderType, PayMethod

router = Router(tags=["pos"])


def _guard(request, perm: str):
    require_module(request, "pos")
    require_perm(request, perm)


class ItemIn(Schema):
    product_id: int
    qty: int = 1
    modifiers: list[dict] = []
    note: str = ""


class OrderIn(Schema):
    items: list[ItemIn]
    type: str = OrderType.TAKEAWAY
    branch_id: Optional[int] = None
    table_no: str = ""
    customer_phone: str = ""
    customer_name: str = ""
    note: str = ""
    discount: int = 0
    source: str = "pos"


class PayIn(Schema):
    payment_method: str
    discount: Optional[int] = None


class CancelIn(Schema):
    reason: str = ""


class ShiftOpenIn(Schema):
    branch_id: Optional[int] = None
    cash_start: int = 0


class ShiftCloseIn(Schema):
    cash_end: int
    note: str = ""


class ItemOut(Schema):
    id: int
    product_id: Optional[int] = None
    name: str
    qty: int
    price: int
    cost: int
    modifiers: list = []
    note: str
    line_total: int


class OrderOut(Schema):
    id: int
    number: int
    type: str
    status: str
    table_no: str
    customer_phone: str
    customer_name: str
    note: str
    subtotal: int
    discount: int
    total: int
    cost_total: int
    payment_method: str
    paid_at: Optional[datetime] = None
    created_at: datetime
    cashier: Optional[str] = None
    branch_id: Optional[int] = None
    source: str
    items: list[ItemOut] = []

    @staticmethod
    def resolve_cashier(obj):
        return obj.cashier.full_name if obj.cashier_id else None


class ShiftOut(Schema):
    id: int
    branch_id: Optional[int] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    cash_start: int
    cash_end: Optional[int] = None
    note: str
    opened_by: Optional[str] = None
    totals: dict = {}

    @staticmethod
    def resolve_opened_by(obj):
        return obj.opened_by.full_name if obj.opened_by_id else None

    @staticmethod
    def resolve_totals(obj):
        return obj.totals()


# ------------------------------------------------------------------ menyu (kassa uchun)
@router.get("/menu", auth=auth)
def menu(request):
    """Kassa uchun faol taomlar (stop-listdagilar belgilanadi), kategoriya bo'yicha."""
    _guard(request, "pos.sell")
    cats = []
    for c in Category.objects.filter(deleted_at__isnull=True, is_active=True):
        prods = [{"id": p.id, "name": p.name, "price": p.price, "cost": p.cost, "image": p.image.url if p.image else None,
                  "in_stop_list": p.in_stop_list, "tags": p.tags}
                 for p in c.products.filter(deleted_at__isnull=True, is_active=True)]
        if prods:
            cats.append({"id": c.id, "name": c.name, "products": prods})
    return {"categories": cats, "payment_methods": [{"code": m.value, "label": m.label} for m in PayMethod],
            "order_types": [{"code": t.value, "label": t.label} for t in OrderType]}


# ------------------------------------------------------------------ smena
@router.get("/shift", response=Optional[ShiftOut], auth=auth)
def current_shift(request, branch_id: Optional[int] = None):
    _guard(request, "pos.sell")
    qs = CashShift.objects.filter(closed_at__isnull=True)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    return qs.first()


@router.post("/shift/open", response=ShiftOut, auth=auth)
def open_shift(request, data: ShiftOpenIn):
    _guard(request, "pos.shift")
    if CashShift.objects.filter(closed_at__isnull=True, branch_id=data.branch_id).exists():
        raise HttpError(400, "Bu filialda ochiq smena bor — avval uni yoping.")
    s = CashShift.objects.create(branch_id=data.branch_id, opened_by=request.auth, cash_start=data.cash_start)
    record(request, "shift_open", s)
    emit("pos.shift_opened", {"shift_id": s.pk}, tenant=request.tenant)
    return s


@router.post("/shift/{sid}/close", response=ShiftOut, auth=auth)
def close_shift(request, sid: int, data: ShiftCloseIn):
    _guard(request, "pos.shift")
    s = get_object_or_404(CashShift, pk=sid, closed_at__isnull=True)
    if s.orders.filter(status=OrderStatus.OPEN).exists():
        raise HttpError(400, "Ochiq buyurtmalar bor — avval ularni yoping yoki bekor qiling.")
    s.closed_at, s.closed_by, s.cash_end, s.note = timezone.now(), request.auth, data.cash_end, data.note
    s.save()
    record(request, "shift_close", s, after=s.totals())
    emit("pos.shift_closed", {"shift_id": s.pk, **s.totals()}, tenant=request.tenant)
    return s


@router.get("/shifts", response=list[ShiftOut], auth=auth)
def list_shifts(request, limit: int = 30):
    _guard(request, "pos.shift")
    return CashShift.objects.select_related("opened_by")[:limit]


# ------------------------------------------------------------------ buyurtmalar
def _build_items(order: Order, items: list[ItemIn]) -> None:
    order.items.all().delete()
    for it in items:
        p = get_object_or_404(Product, pk=it.product_id, deleted_at__isnull=True)
        if p.in_stop_list:
            raise HttpError(400, f"«{p.name.get('uz')}» stop-listda.")
        OrderItem.objects.create(order=order, product=p, name=p.name.get("uz") or str(p), qty=max(1, it.qty),
                                 price=p.price, cost=p.cost, modifiers=it.modifiers, note=it.note)
    order.recalc()
    order.save()


@router.post("/orders", response=OrderOut, auth=auth)
def create_order(request, data: OrderIn):
    with transaction.atomic():
        _guard(request, "pos.sell")
        if not data.items:
            raise HttpError(400, "Buyurtma bo'sh.")
        shift = CashShift.objects.filter(closed_at__isnull=True, branch_id=data.branch_id).first() \
            or CashShift.objects.filter(closed_at__isnull=True).first()
        branch_id = data.branch_id or (shift.branch_id if shift else None) \
            or Branch.objects.filter(deleted_at__isnull=True, is_active=True).values_list("id", flat=True).first()
        o = Order.objects.create(branch_id=branch_id, shift=shift, type=data.type, table_no=data.table_no,
                                 customer_phone=data.customer_phone, customer_name=data.customer_name, note=data.note,
                                 discount=max(0, data.discount), cashier=request.auth, source=data.source)
        _build_items(o, data.items)
        emit("pos.order_created", {"order_id": o.pk, "number": o.number, "total": o.total,
                                   "_tenant": request.tenant}, tenant=request.tenant)
        return o


@router.get("/orders", response=list[OrderOut], auth=auth)
def list_orders(request, status: Optional[str] = None, branch_id: Optional[int] = None, today: bool = False, limit: int = 100):
    _guard(request, "pos.sell")
    qs = Order.objects.prefetch_related("items").select_related("cashier")
    if status:
        qs = qs.filter(status=status)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if today:
        qs = qs.filter(created_at__date=timezone.localdate())
    return qs[:limit]


@router.get("/orders/{oid}", response=OrderOut, auth=auth)
def get_order(request, oid: int):
    _guard(request, "pos.sell")
    return get_object_or_404(Order.objects.prefetch_related("items"), pk=oid)


@router.put("/orders/{oid}", response=OrderOut, auth=auth)
def update_order(request, oid: int, data: OrderIn):
    with transaction.atomic():
        _guard(request, "pos.sell")
        o = get_object_or_404(Order, pk=oid, status=OrderStatus.OPEN)
        o.type, o.table_no, o.note, o.discount = data.type, data.table_no, data.note, max(0, data.discount)
        o.customer_phone, o.customer_name = data.customer_phone, data.customer_name
        _build_items(o, data.items)
        return o


@router.post("/orders/{oid}/pay", response=OrderOut, auth=auth)
def pay_order(request, oid: int, data: PayIn):
    with transaction.atomic():
        """To'lov: naqd/karta/Click/Payme. Hodisa → ombor yechiladi, moliya savdoni oladi."""
        _guard(request, "pos.sell")
        o = get_object_or_404(Order.objects.prefetch_related("items"), pk=oid, status=OrderStatus.OPEN)
        if data.payment_method not in PayMethod.values:
            raise HttpError(400, "Noto'g'ri to'lov usuli.")
        if data.discount is not None:
            o.discount = max(0, data.discount)
            o.recalc()
        o.status, o.payment_method, o.paid_at = OrderStatus.PAID, data.payment_method, timezone.now()
        o.save()
        record(request, "pay", o, after={"total": o.total, "method": o.payment_method})
        emit("pos.order_paid", {
            "order_id": o.pk, "number": o.number, "total": o.total, "cost_total": o.cost_total,
            "payment_method": o.payment_method, "branch_id": o.branch_id, "customer_phone": o.customer_phone,
            "items": [{"product_id": i.product_id, "name": i.name, "qty": i.qty, "price": i.price} for i in o.items.all()],
            "_tenant": request.tenant,
        }, tenant=request.tenant)
        return o


@router.post("/orders/{oid}/cancel", response=OrderOut, auth=auth)
def cancel_order(request, oid: int, data: CancelIn):
    _guard(request, "pos.sell")
    o = get_object_or_404(Order, pk=oid)
    if o.status == OrderStatus.PAID and not request.auth.has_perm_code("pos.refund"):
        raise HttpError(403, "To'langan buyurtmani bekor qilish uchun `pos.refund` ruxsati kerak.")
    o.status, o.cancelled_at, o.cancel_reason = OrderStatus.CANCELLED, timezone.now(), data.reason
    o.save()
    record(request, "cancel", o, after={"reason": data.reason})
    emit("pos.order_cancelled", {"order_id": o.pk, "number": o.number}, tenant=request.tenant)
    return o


@router.get("/summary", auth=auth)
def summary(request, branch_id: Optional[int] = None):
    """Bugungi savdo — kassa ekranining yuqori qatori va dashboard uchun."""
    _guard(request, "pos.sell")
    qs = Order.objects.filter(status=OrderStatus.PAID, paid_at__date=timezone.localdate())
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    agg = qs.aggregate(total=Sum("total"), cost=Sum("cost_total"))
    n = qs.count()
    total = int(agg["total"] or 0)
    return {"orders": n, "total": total, "avg_check": int(total / n) if n else 0, "cost": int(agg["cost"] or 0),
            "gross_profit": total - int(agg["cost"] or 0), "open_orders": Order.objects.filter(status=OrderStatus.OPEN).count(),
            "by_method": {r["payment_method"]: int(r["s"]) for r in qs.values("payment_method").annotate(s=Sum("total"))}}
