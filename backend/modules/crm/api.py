"""CRM API — /api/v1/crm/... : mijozlar, bonus, aksiyalar, segmentlar, kassa uchun hisob (quote/attach)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_module, require_perm

from . import services
from .models import BonusTxn, Customer, OrderLink, Promo, PromoAudience, PromoKind, TxnKind

router = Router(tags=["crm"])


def _guard(request, perm: str):
    require_module(request, "crm")
    require_perm(request, perm)


def _cfg(request) -> dict:
    return services.conf(request.tenant)


# ------------------------------------------------------------------ statistika
@router.get("/stats", auth=auth)
def stats(request):
    _guard(request, "crm.view")
    services.daily(request.tenant)
    cfg = _cfg(request)
    now = timezone.now()
    m30 = now - timedelta(days=30)
    qs = Customer.objects.all()
    total = qs.count()
    buyers = qs.filter(orders_count__gte=1).count()
    returning = qs.filter(orders_count__gte=2).count()
    agg = qs.aggregate(bal=Sum("balance"), spent=Sum("spent_total"), orders=Sum("orders_count"))
    tx = BonusTxn.objects.filter(created_at__gte=m30)
    earned = int(tx.filter(amount__gt=0).exclude(kind=TxnKind.REFUND).aggregate(s=Sum("amount"))["s"] or 0)
    spent = -int(tx.filter(kind=TxnKind.SPEND).aggregate(s=Sum("amount"))["s"] or 0)
    from modules.pos.models import Order, OrderStatus
    paid30 = Order.objects.filter(status=OrderStatus.PAID, paid_at__gte=m30)
    with_c = paid30.exclude(customer_phone="")
    a_all, a_c = paid30.aggregate(s=Sum("total"), n=Count("id")), with_c.aggregate(s=Sum("total"), n=Count("id"))
    return {
        "customers": total, "new_30d": qs.filter(created_at__gte=m30).count(), "buyers": buyers,
        "returning_rate": round(returning * 100 / buyers, 1) if buyers else 0.0,
        "bonus_liability": int(agg["bal"] or 0), "bonus_earned_30d": earned, "bonus_spent_30d": spent,
        "identified_share": round((a_c["n"] or 0) * 100 / a_all["n"], 1) if a_all["n"] else 0.0,
        "avg_check_customer": int((a_c["s"] or 0) / a_c["n"]) if a_c["n"] else 0,
        "avg_check_all": int((a_all["s"] or 0) / a_all["n"]) if a_all["n"] else 0,
        "segments": {k: services.segment_qs(k, cfg).count() for k in services.SEGMENTS},
        "levels": {"silver": qs.filter(spent_total__gte=cfg["silver_from"], spent_total__lt=cfg["gold_from"]).count(),
                   "gold": qs.filter(spent_total__gte=cfg["gold_from"]).count()},
        "promos_active": Promo.objects.filter(is_active=True).count(),
    }


# ------------------------------------------------------------------ mijozlar
class CustomerIn(Schema):
    phone: str
    name: str = ""
    birthday: Optional[date] = None
    gender: str = ""
    note: str = ""
    tags: list[str] = []
    marketing_ok: bool = True


@router.get("/customers", auth=auth)
def list_customers(request, q: str = "", segment: str = "all", sort: str = "recent", limit: int = 300):
    _guard(request, "crm.view")
    cfg = _cfg(request)
    qs = services.segment_qs(segment, cfg)
    if q.strip():
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = Q(name__icontains=q.strip())
        if digits:
            cond |= Q(phone__contains=digits)
        qs = qs.filter(cond)
    last = F("last_order_at").desc(nulls_last=True)
    order = {"recent": [last, "-created_at"], "spent": ["-spent_total"], "balance": ["-balance"],
             "orders": ["-orders_count"], "new": ["-created_at"]}.get(sort, [last])
    rows = list(qs.order_by(*order)[: min(limit, 1000)])
    return {"total": qs.count(), "items": [services.customer_card(c, cfg) for c in rows]}


@router.post("/customers", auth=auth)
def create_customer(request, data: CustomerIn):
    _guard(request, "crm.manage")
    p = services.normalize(data.phone)
    if not p:
        raise HttpError(400, "Telefon raqam noto'g'ri. Masalan: +998 90 123 45 67")
    if Customer.objects.filter(phone=p).exists():
        raise HttpError(400, "Bu raqamli mijoz allaqachon bor.")
    c, _ = services.get_or_create(request.tenant, p, data.name, source="manual")
    for k in ("birthday", "gender", "note", "tags", "marketing_ok"):
        setattr(c, k, getattr(data, k))
    c.save()
    record(request, "create", c)
    return services.customer_card(c, _cfg(request))


@router.get("/customers/{int:cid}", auth=auth)
def get_customer(request, cid: int):
    _guard(request, "crm.view")
    c = get_object_or_404(Customer, pk=cid)
    from modules.pos.models import Order
    orders = Order.objects.filter(customer_phone=c.phone).order_by("-created_at")[:20]
    fav = (Order.objects.filter(customer_phone=c.phone, status="paid").values("items__name")
           .annotate(n=Sum("items__qty")).order_by("-n")[:5])
    return {**services.customer_card(c, _cfg(request)),
            "txns": [{"id": t.id, "kind": t.kind, "kind_label": TxnKind(t.kind).label, "amount": t.amount, "note": t.note,
                      "order_id": t.order_id, "created_at": t.created_at.isoformat(),
                      "by": t.created_by.full_name if t.created_by_id else None} for t in c.txns.select_related("created_by")[:50]],
            "orders": [{"id": o.id, "number": o.number, "total": o.total, "status": o.status, "type": o.type, "source": o.source,
                        "created_at": o.created_at.isoformat()} for o in orders],
            "favorites": [{"name": f["items__name"], "qty": int(f["n"] or 0)} for f in fav if f["items__name"]]}


@router.put("/customers/{int:cid}", auth=auth)
def update_customer(request, cid: int, data: CustomerIn):
    _guard(request, "crm.manage")
    c = get_object_or_404(Customer, pk=cid)
    p = services.normalize(data.phone)
    if not p:
        raise HttpError(400, "Telefon raqam noto'g'ri.")
    if p != c.phone and Customer.objects.filter(phone=p).exists():
        raise HttpError(400, "Bu raqam boshqa mijozda bor.")
    c.phone = p
    for k in ("name", "birthday", "gender", "note", "tags", "marketing_ok"):
        setattr(c, k, getattr(data, k))
    c.save()
    record(request, "update", c)
    return services.customer_card(c, _cfg(request))


class BonusIn(Schema):
    amount: int
    note: str = ""


@router.post("/customers/{int:cid}/bonus", auth=auth)
def adjust_bonus(request, cid: int, data: BonusIn):
    _guard(request, "crm.bonus")
    c = get_object_or_404(Customer, pk=cid)
    if data.amount == 0:
        raise HttpError(400, "Summa kiriting.")
    if c.balance + data.amount < 0:
        raise HttpError(400, f"Balansda faqat {services.money(c.balance)} so'm bor.")
    if not data.note.strip():
        raise HttpError(400, "Sababini yozing (masalan: shikoyat uchun uzr).")
    services.add_txn(request.tenant, c, TxnKind.ADJUST, data.amount, note=data.note, user=request.auth)
    record(request, "bonus_adjust", c, after={"amount": data.amount, "note": data.note})
    return services.customer_card(c, _cfg(request))


@router.post("/sync", auth=auth)
def sync_from_orders(request):
    """Eski kassa buyurtmalari va Telegram mijozlaridan kartalar yig'iladi (bonus berilmaydi)."""
    _guard(request, "crm.manage")
    from modules.pos.models import Order
    made = 0
    rows = (Order.objects.filter(status="paid").exclude(customer_phone="")
            .values("customer_phone").annotate(n=Count("id"), s=Sum("total")))
    for r in rows:
        p = services.normalize(r["customer_phone"])
        if not p:
            continue
        first = Order.objects.filter(customer_phone=r["customer_phone"], status="paid").order_by("paid_at").values_list("paid_at", flat=True).first()
        last = Order.objects.filter(customer_phone=r["customer_phone"], status="paid").order_by("-paid_at").values_list("paid_at", flat=True).first()
        name = Order.objects.filter(customer_phone=r["customer_phone"]).exclude(customer_name="").values_list("customer_name", flat=True).first() or ""
        c, created = Customer.objects.get_or_create(phone=p, defaults={"name": name, "source": "import"})
        if created or not OrderLink.objects.filter(customer=c).exists():
            c.orders_count, c.spent_total, c.first_order_at, c.last_order_at = r["n"], int(r["s"] or 0), first, last
            c.save()
        made += int(created)
    if request.tenant.module_enabled("telegram"):
        from modules.telegram.models import BotUser
        for bu in BotUser.objects.exclude(phone=""):
            _, created = Customer.objects.get_or_create(phone=bu.phone, defaults={"name": bu.full_name, "source": "telegram"})
            made += int(created)
    return {"created": made, "total": Customer.objects.count()}


# ------------------------------------------------------------------ tug'ilgan kun
@router.get("/birthdays", auth=auth)
def birthdays(request, days: int = 14):
    _guard(request, "crm.view")
    cfg = _cfg(request)
    today = timezone.localdate()
    out = []
    for c in Customer.objects.exclude(birthday=None):
        for y in (today.year, today.year + 1):
            try:
                b = c.birthday.replace(year=y)
            except ValueError:
                b = date(y, 3, 1)
            d = (b - today).days
            if 0 <= d <= days:
                out.append({**services.customer_card(c, cfg), "in_days": d, "age": y - c.birthday.year,
                            "greeted": BonusTxn.objects.filter(customer=c, kind=TxnKind.BIRTHDAY, created_at__year=today.year).exists()})
                break
    return sorted(out, key=lambda x: x["in_days"])


@router.post("/birthdays/run", auth=auth)
def run_birthdays(request):
    _guard(request, "crm.manage")
    return {"greeted": services.daily(request.tenant, force=True)}


# ------------------------------------------------------------------ segmentga xabar
class MessageIn(Schema):
    text: str


@router.post("/segments/{seg}/message", auth=auth)
def message_segment(request, seg: str, data: MessageIn):
    _guard(request, "crm.message")
    if seg not in services.SEGMENTS:
        raise HttpError(404, "Segment topilmadi")
    if not data.text.strip():
        raise HttpError(400, "Xabar matnini yozing.")
    if not request.tenant.module_enabled("telegram"):
        raise HttpError(400, "Xabar Telegram bot orqali ketadi — avval «Telegram bot» modulini yoqing.")
    from modules.telegram.models import BotUser
    from modules.telegram.services import say
    phones = set(services.segment_qs(seg, _cfg(request)).filter(marketing_ok=True).values_list("phone", flat=True))
    sent = failed = 0
    for bu in BotUser.objects.filter(phone__in=phones, is_blocked=False):
        ok = say(request.tenant, bu.chat_id, data.text)
        sent, failed = sent + int(ok), failed + int(not ok)
    record(request, "crm_message", model="Segment", after={"segment": seg, "sent": sent, "failed": failed})
    return {"segment": seg, "customers": len(phones), "sent": sent, "failed": failed, "no_bot": len(phones) - sent - failed}


# ------------------------------------------------------------------ aksiyalar
class PromoIn(Schema):
    name: str
    description: str = ""
    kind: str = PromoKind.PERCENT
    value: int
    max_discount: int = 0
    code: str = ""
    audience: str = PromoAudience.ALL
    min_order: int = 0
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    weekdays: list[int] = []
    hour_from: Optional[int] = None
    hour_to: Optional[int] = None
    category_ids: list[int] = []
    product_ids: list[int] = []
    max_uses: int = 0
    is_active: bool = True


def _promo_out(p: Promo) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "kind": p.kind, "value": p.value,
            "max_discount": p.max_discount, "code": p.code, "audience": p.audience, "audience_label": PromoAudience(p.audience).label,
            "min_order": p.min_order, "starts_on": p.starts_on.isoformat() if p.starts_on else None,
            "ends_on": p.ends_on.isoformat() if p.ends_on else None, "weekdays": p.weekdays,
            "hour_from": p.hour_from, "hour_to": p.hour_to, "category_ids": p.category_ids, "product_ids": p.product_ids,
            "max_uses": p.max_uses, "used_count": p.used_count, "discount_total": p.discount_total,
            "revenue_total": p.revenue_total, "is_active": p.is_active,
            "expired": bool(p.ends_on and p.ends_on < timezone.localdate())}


def _validate(data: PromoIn) -> dict:
    d = data.dict()
    d["name"] = d["name"].strip()
    if not d["name"]:
        raise HttpError(400, "Aksiya nomini yozing.")
    if d["kind"] not in PromoKind.values or d["audience"] not in PromoAudience.values:
        raise HttpError(400, "Noto'g'ri tur.")
    if d["value"] <= 0 or (d["kind"] == PromoKind.PERCENT and d["value"] > 100):
        raise HttpError(400, "Chegirma: foiz 1–100 oralig'ida yoki summa 0 dan katta bo'lsin.")
    if d["starts_on"] and d["ends_on"] and d["ends_on"] < d["starts_on"]:
        raise HttpError(400, "Tugash sanasi boshlanishdan oldin bo'lmasin.")
    if (d["hour_from"] is None) != (d["hour_to"] is None):
        raise HttpError(400, "Soat oralig'ini to'liq kiriting (dan va gacha) yoki ikkalasini bo'sh qoldiring.")
    d["code"] = d["code"].strip().upper().replace(" ", "")
    d["weekdays"] = sorted({w for w in d["weekdays"] if 0 <= w <= 6})
    return d


@router.get("/promos", auth=auth)
def list_promos(request):
    _guard(request, "crm.view")
    return [_promo_out(p) for p in Promo.objects.all()]


@router.post("/promos", auth=auth)
def create_promo(request, data: PromoIn):
    _guard(request, "crm.manage")
    d = _validate(data)
    if d["code"] and Promo.objects.filter(code__iexact=d["code"]).exists():
        raise HttpError(400, "Bunday promokod bor.")
    p = Promo.objects.create(**d)
    record(request, "create", p)
    return _promo_out(p)


@router.put("/promos/{int:pid}", auth=auth)
def update_promo(request, pid: int, data: PromoIn):
    _guard(request, "crm.manage")
    p = get_object_or_404(Promo, pk=pid)
    d = _validate(data)
    if d["code"] and Promo.objects.filter(code__iexact=d["code"]).exclude(pk=pid).exists():
        raise HttpError(400, "Bunday promokod bor.")
    for k, v in d.items():
        setattr(p, k, v)
    p.save()
    record(request, "update", p)
    return _promo_out(p)


@router.delete("/promos/{int:pid}", auth=auth)
def delete_promo(request, pid: int):
    _guard(request, "crm.manage")
    p = get_object_or_404(Promo, pk=pid)
    if p.used_count:
        p.is_active = False                    # ishlatilgan aksiya tarix uchun saqlanadi
        p.save(update_fields=["is_active", "updated_at"])
        return {"ok": True, "archived": True}
    p.delete()
    return {"ok": True}


# ------------------------------------------------------------------ kassa uchun
class QuoteIn(Schema):
    phone: str = ""
    items: list[dict] = []
    promo_code: str = ""
    manual_discount: int = 0
    use_bonus: Optional[int] = None


@router.post("/quote", auth=auth)
def quote(request, data: QuoteIn):
    """Kassa: telefon kiritilganda — mijoz kartasi, aksiya, bonus. Hech narsa saqlanmaydi."""
    require_module(request, "crm")
    require_perm(request, "pos.sell")
    return services.quote(request.tenant, phone=data.phone, lines=services._lines_from_items(data.items),
                          promo_code=data.promo_code, manual_discount=data.manual_discount, use_bonus=data.use_bonus)


class AttachIn(Schema):
    phone: str = ""
    promo_code: str = ""
    manual_discount: int = 0
    use_bonus: int = 0


@router.post("/orders/{int:oid}/attach", auth=auth)
def attach(request, oid: int, data: AttachIn):
    """Ochiq buyurtmaga mijoz, aksiya va bonus biriktiriladi; chegirma serverda qayta hisoblanadi."""
    require_module(request, "crm")
    require_perm(request, "pos.sell")
    from modules.pos.models import Order, OrderStatus
    o = get_object_or_404(Order, pk=oid, status=OrderStatus.OPEN)
    q = services.attach(request.tenant, o, phone=data.phone, promo_code=data.promo_code,
                        manual_discount=data.manual_discount, use_bonus=data.use_bonus)
    return {**q, "order_total": o.total, "order_discount": o.discount}


# ------------------------------------------------------------------ sozlamalar
class SettingsIn(Schema):
    cashback_percent: int = 3
    silver_from: int = 1_000_000
    silver_percent: int = 5
    gold_from: int = 3_000_000
    gold_percent: int = 8
    max_pay_percent: int = 50
    welcome_bonus: int = 0
    birthday_bonus: int = 0
    birthday_text: str = ""
    birthday_window: int = 3
    sleeping_days: int = 30
    notify_bonus: bool = True


@router.get("/settings", auth=auth)
def get_settings(request):
    _guard(request, "crm.view")
    return _cfg(request)


@router.put("/settings", auth=auth)
def put_settings(request, data: SettingsIn):
    _guard(request, "crm.manage")
    d = data.dict()
    for k in ("cashback_percent", "silver_percent", "gold_percent", "max_pay_percent"):
        if not 0 <= d[k] <= 100:
            raise HttpError(400, "Foizlar 0–100 oralig'ida bo'lsin.")
    if d["gold_from"] <= d["silver_from"]:
        raise HttpError(400, "Oltin daraja chegarasi Kumushdan katta bo'lsin.")
    if min(d["silver_from"], d["welcome_bonus"], d["birthday_bonus"], d["birthday_window"], d["sleeping_days"]) < 0:
        raise HttpError(400, "Manfiy qiymat bo'lmaydi.")
    t = request.tenant
    mods = dict((t.settings or {}).get("modules") or {})
    mods["crm"] = {**(mods.get("crm") or {}), **d}
    t.settings = {**(t.settings or {}), "modules": mods}
    t.save(update_fields=["settings"])
    record(request, "update", model="CrmSettings", after=d)
    return _cfg(request)
