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
    cash_end: Optional[int] = None          # berilmasa — kupyuralar yig'indisi
    counted: dict = {}                      # {"200000": 3, ...}
    card_terminal: Optional[int] = None
    left_amount: Optional[int] = None       # kassada keyingi smenaga qoldiriladi
    handed_to: Optional[str] = None         # kimga topshirildi (user id)
    diff_reason: str = ""
    note: str = ""


class MoveIn(Schema):
    kind: str          # in | out
    amount: int
    reason: str


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
    closed_by: Optional[str] = None
    branch: Optional[str] = None
    counted: dict = {}
    card_terminal: Optional[int] = None
    left_amount: Optional[int] = None
    handed_amount: Optional[int] = None
    handed_to: Optional[str] = None
    diff_reason: str = ""
    accepted_at: Optional[datetime] = None
    totals: dict = {}

    @staticmethod
    def resolve_opened_by(obj):
        return obj.opened_by.full_name if obj.opened_by_id else None

    @staticmethod
    def resolve_closed_by(obj):
        return obj.closed_by.full_name if obj.closed_by_id else None

    @staticmethod
    def resolve_branch(obj):
        return obj.branch.name if obj.branch_id else None

    @staticmethod
    def resolve_handed_to(obj):
        return (obj.handed_to.full_name or obj.handed_to.phone) if obj.handed_to_id else None

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
        prods = [{"id": p.id, "name": p.name, "price": p.price, "cost": p.cost, "image": p.image_src,
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
    """Kassa topshirish: naqd sanaladi (kupyuralar), terminal solishtiriladi, qoldiq va topshiriladigan summa, qabul qiluvchi."""
    from . import handover
    _guard(request, "pos.shift")
    s = get_object_or_404(CashShift, pk=sid, closed_at__isnull=True)
    open_n = s.orders.filter(status=OrderStatus.OPEN).count()
    if open_n:
        raise HttpError(400, f"{open_n} ta ochiq buyurtma bor — avval ularni to'lang yoki bekor qiling.")
    counted = {str(k): max(0, int(v or 0)) for k, v in (data.counted or {}).items() if str(k).isdigit() and int(v or 0) > 0}
    cash_end = data.cash_end if data.cash_end is not None else handover.counted_sum(counted)
    if cash_end is None or cash_end < 0:
        raise HttpError(400, "Kassadagi naqd pulni sanab yozing")
    expected = s.totals()["expected_cash"]
    if cash_end != expected and len(data.diff_reason.strip()) < 3:
        raise HttpError(400, f"Naqd farqi bor ({cash_end - expected:+,} so'm) — sababini yozing".replace(",", " "))
    left = max(0, min(int(data.left_amount or 0), cash_end))
    receiver = None
    if data.handed_to:
        from core.models import User
        receiver = User.objects.filter(pk=data.handed_to, is_active=True).first()
        if receiver is None:
            raise HttpError(400, "Qabul qiluvchi topilmadi")
    s.closed_at, s.closed_by, s.cash_end, s.note = timezone.now(), request.auth, cash_end, data.note[:200]
    s.counted, s.card_terminal, s.left_amount, s.handed_amount = counted, data.card_terminal, left, cash_end - left
    s.handed_to, s.diff_reason = receiver, data.diff_reason.strip()[:200]
    s.save()
    record(request, "shift_close", s, after=s.totals())
    emit("pos.shift_closed", {"shift_id": s.pk, **s.totals()}, tenant=request.tenant)
    handover.notify(request.tenant, s)
    return s


@router.post("/shift/{sid}/move", response=ShiftOut, auth=auth)
def cash_move(request, sid: int, data: MoveIn):
    """Smena davomida kassaga kirim yoki chiqim (xarajat, inkassatsiya, maydalash)."""
    from .models import CashMove
    _guard(request, "pos.shift")
    s = get_object_or_404(CashShift, pk=sid, closed_at__isnull=True)
    if data.kind not in ("in", "out") or data.amount <= 0:
        raise HttpError(400, "Summani to'g'ri kiriting")
    if len(data.reason.strip()) < 3:
        raise HttpError(400, "Sababini yozing (masalan: non uchun, inkassatsiya)")
    if data.kind == "out" and data.amount > s.totals()["expected_cash"]:
        raise HttpError(400, "Kassada buncha naqd yo'q")
    CashMove.objects.create(shift=s, kind=data.kind, amount=data.amount, reason=data.reason.strip()[:160], user=request.auth)
    record(request, "cash_move", s, after={"kind": data.kind, "amount": data.amount, "reason": data.reason})
    return s


@router.get("/shift/{sid}/report", auth=auth)
def shift_report(request, sid: int):
    """Z-hisobot: jami, to'lov turlari, kassirlar, soatlar, kirim/chiqim, farq."""
    from django.db.models import Count
    from django.db.models.functions import ExtractHour

    from . import handover
    _guard(request, "pos.sell")
    s = get_object_or_404(CashShift, pk=sid)
    paid = s.orders.filter(status=OrderStatus.PAID)
    return {
        "shift": ShiftOut.from_orm(s).dict(), "denoms": handover.DENOMS,
        "cashiers": [{"name": r["cashier__full_name"] or "—", "orders": r["n"], "total": int(r["t"] or 0)}
                     for r in paid.values("cashier__full_name").annotate(n=Count("id"), t=Sum("total")).order_by("-t")],
        "by_type": [{"type": dict(OrderType.choices).get(r["type"], r["type"]), "orders": r["n"], "total": int(r["t"] or 0)}
                    for r in paid.values("type").annotate(n=Count("id"), t=Sum("total")).order_by("-t")],
        "hours": [{"hour": r["h"], "total": int(r["t"] or 0)} for r in paid.annotate(h=ExtractHour("paid_at")).values("h").annotate(t=Sum("total")).order_by("h")],
        "moves": [{"kind": x.kind, "amount": x.amount, "reason": x.reason, "at": x.created_at.isoformat(), "user": x.user.full_name if x.user_id else ""}
                  for x in s.moves.select_related("user")],
        "open_orders": s.orders.filter(status=OrderStatus.OPEN).count(),
        "text": handover.z_text(s, request.tenant.name) if s.closed_at else "",
    }


@router.post("/shift/{sid}/accept", response=ShiftOut, auth=auth)
def accept_shift(request, sid: int):
    from . import handover
    s = get_object_or_404(CashShift, pk=sid)
    if not handover.accept(s, request.auth):
        raise HttpError(400, "Bu topshiriq sizga emas yoki allaqachon qabul qilingan")
    return s


@router.get("/shift-helpers", auth=auth)
def shift_helpers(request, branch_id: Optional[int] = None):
    """Smena ochish/yopish uchun: oldingi smenadan qoldiq, kimga topshirish mumkin (rahbar/kassirlar), oxirgi smenalar."""
    from core.models import User

    from .handover import DENOMS
    _guard(request, "pos.shift")
    last = CashShift.objects.filter(closed_at__isnull=False, branch_id=branch_id).first() if branch_id else CashShift.objects.filter(closed_at__isnull=False).first()
    people = [u for u in User.objects.filter(is_active=True, memberships__is_active=True).distinct().order_by("full_name")
              if u.pk != request.auth.pk and (u.has_perm_code("pos.shift") or u.access_level() >= 60)]
    pending = CashShift.objects.filter(handed_to=request.auth, accepted_at__isnull=True, closed_at__isnull=False)[:5]
    return {"left_from_last": (last.left_amount if last and last.left_amount is not None else None),
            "last_closed_by": (last.closed_by.full_name if last and last.closed_by_id else None),
            "receivers": [{"id": str(u.pk), "name": u.full_name or u.phone, "role": ", ".join(mm.role.name for mm in u.memberships.filter(is_active=True).select_related("role"))[:60]}
                          for u in people[:40]],
            "to_accept": [ShiftOut.from_orm(x).dict() for x in pending],
            "recent": [ShiftOut.from_orm(x).dict() for x in CashShift.objects.filter(closed_at__isnull=False).select_related("opened_by", "closed_by", "handed_to", "branch")[:8]],
            "denoms": DENOMS}


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
