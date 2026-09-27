"""Zakup xizmatlari: bozorlar ro'yxati, narx taqqoslash, buyurtma → omborga kirim, qarzdorlik, bozorlik hisobi, statistika."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from core.events import emit

from .models import (
    CATEGORIES,
    ExpenseKind,
    Market,
    MarketKind,
    Order,
    OrderStatus,
    Payment,
    PriceSource,
    SupplierInfo,
    SupplierPrice,
    Trip,
    TripStatus,
)

CAT = {c[0]: (c[1], c[2]) for c in CATEGORIES}


def setting(tenant, key, default):
    try:
        return (tenant.settings.get("modules", {}).get("procurement", {}) or {}).get(key, default)
    except Exception:
        return default


# ------------------------------------------------------------------ bozorlar (yuk olish joylari)
_CHECK = " Manzil va ish vaqtini o'zingiz tekshirib, kerak bo'lsa tahrirlang."
BUILTIN_MARKETS = [
    ("Chorsu bozori", MarketKind.BAZAAR, "Shayxontohur tumani", "05:00–18:00", "har kuni", ["meat", "spice", "fruit", "grain", "bread"],
     "Go'sht qatorida eng yangi mahsulot ertalab 6–8 da. Ziravor va quruq meva ulgurji qatorida arzonroq." + _CHECK, 41.3262, 69.2366),
    ("Qo'yliq dehqon bozori", MarketKind.WHOLESALE, "Bektemir tomoni", "04:00–16:00", "har kuni", ["veg", "fruit", "grain"],
     "Sabzavot va meva ulgurji: qop va yashik bilan arzon. Ertalab erta boring, yuk mashinasi/hammol oldindan kelishing." + _CHECK, None, None),
    ("Oloy bozori", MarketKind.BAZAAR, "Yunusobod tumani, Amir Temur ko'chasi", "06:00–19:00", "har kuni", ["meat", "dairy", "fruit", "spice"],
     "Sifatli, lekin narx o'rtachadan yuqori. Sut mahsulotlari va ko'katlar uchun qulay." + _CHECK, 41.3223, 69.2798),
    ("Parkent bozori", MarketKind.BAZAAR, "Mirzo Ulug'bek tumani", "05:00–18:00", "har kuni", ["veg", "fruit", "meat", "dairy"],
     "Sabzavot va ko'kat, suzma, qatiq. Avtoturargoh bor." + _CHECK, None, None),
    ("Farhod bozori", MarketKind.BAZAAR, "Chilonzor tumani", "05:00–18:00", "har kuni", ["veg", "meat", "grain", "oil"],
     "Chilonzor filiallari uchun yaqin. Guruch va yog' ulgurji do'konlari bor." + _CHECK, None, None),
    ("Mirobod bozori", MarketKind.BAZAAR, "Mirobod tumani", "06:00–18:00", "har kuni", ["meat", "veg", "fruit"],
     "Markazga yaqin, kichik xaridlar uchun qulay." + _CHECK, None, None),
    ("Sergeli dehqon bozori", MarketKind.BAZAAR, "Sergeli tumani", "05:00–18:00", "har kuni", ["veg", "meat", "poultry"],
     "Tovuq va sabzavot narxi ko'pincha arzonroq." + _CHECK, None, None),
    ("Supermarket / Cash&Carry", MarketKind.CASHCARRY, "Shahar bo'ylab", "08:00–23:00", "har kuni", ["drinks", "dairy", "pack", "clean", "oil"],
     "Ichimlik, qadoq va tozalash vositalari uchun: chek beriladi, hisob-faktura olish mumkin." + _CHECK, None, None),
]


def ensure_markets() -> int:
    if Market.objects.filter(is_builtin=True).exists():
        return 0
    for name, kind, district, hours, days, cats, tips, lat, lng in BUILTIN_MARKETS:
        Market.objects.create(name=name, kind=kind, district=district, hours=hours, days=days, categories=cats, tips=tips,
                              lat=lat, lng=lng, is_builtin=True)
    return len(BUILTIN_MARKETS)


def market_out(m: Market) -> dict:
    q = f"{m.name}, {m.district}, {m.city}".replace(" ", "+")
    return {"id": m.pk, "name": m.name, "kind": m.kind, "kind_label": MarketKind(m.kind).label, "city": m.city, "district": m.district,
            "address": m.address, "landmark": m.landmark, "hours": m.hours, "days": m.days, "tips": m.tips, "phone": m.phone,
            "lat": float(m.lat) if m.lat is not None else None, "lng": float(m.lng) if m.lng is not None else None,
            "categories": [{"code": c, "name": CAT[c][0], "emoji": CAT[c][1]} for c in (m.categories or []) if c in CAT],
            "map_url": (f"https://yandex.uz/maps/?pt={m.lng},{m.lat}&z=16" if m.lat is not None else f"https://yandex.uz/maps/?text={q}"),
            "is_builtin": m.is_builtin, "is_active": m.is_active, "suppliers": m.suppliers.count(), "trips": m.trips.count()}


# ------------------------------------------------------------------ toifa (ingredient → zakup toifasi)
def cat_of(ing) -> str:
    c = (ing.category or "").lower()
    n = str(ing).lower()
    if "tovuq" in n:
        return "poultry"
    for keys, code in ((("go'sht", "gosht", "kolbasa"), "meat"), (("sabzavot", "ko'kat"), "veg"), (("meva",), "fruit"),
                       (("sut", "qaymoq", "pishloq"), "dairy"), (("yog'", "moy"), "oil"), (("don", "quruq", "un", "guruch"), "grain"),
                       (("ziravor", "choy"), "spice"), (("ichimlik",), "drinks"), (("non", "shirinlik"), "bread"),
                       (("qadoq", "paket"), "pack"), (("tozalash",), "clean")):
        if any(k in c for k in keys):
            return code
    return "other"


# ------------------------------------------------------------------ narxlar
def record_price(*, ingredient, price: int, supplier=None, market=None, source=PriceSource.MANUAL, note="", day: date | None = None):
    if price <= 0:
        return None
    return SupplierPrice.objects.create(ingredient=ingredient, supplier=supplier, market=market, price=int(price), source=source,
                                        note=note, date=day or timezone.localdate())


def price_board(ingredient) -> list[dict]:
    """Bitta mahsulot: har ta'minotchi / bozor bo'yicha oxirgi narx, oldingisiga nisbatan o'zgarish, arzondan qimmatga."""
    rows: dict[tuple, list] = defaultdict(list)
    for p in SupplierPrice.objects.filter(ingredient=ingredient).select_related("supplier__info__market", "market").order_by("-date", "-id")[:400]:
        key = ("s", p.supplier_id) if p.supplier_id else ("m", p.market_id)
        if len(rows[key]) < 2:
            rows[key].append(p)
    out = []
    for (_kind, _), ps in rows.items():
        last, prev = ps[0], (ps[1] if len(ps) > 1 else None)
        mk = last.market or (last.supplier.info.market if last.supplier_id and hasattr(last.supplier, "info") else None)
        out.append({"supplier_id": last.supplier_id, "supplier": last.supplier.name if last.supplier_id else None,
                    "market_id": mk.pk if mk else None, "market": mk.name if mk else None,
                    "price": last.price, "date": last.date.isoformat(), "source": last.source,
                    "change": round(100 * (last.price - prev.price) / prev.price, 1) if prev and prev.price else None})
    out.sort(key=lambda r: r["price"])
    for i, r in enumerate(out):
        r["rank"] = i + 1
        r["vs_best"] = round(100 * (r["price"] - out[0]["price"]) / out[0]["price"], 1) if out[0]["price"] else 0
    return out


def last_price(ingredient, supplier) -> int | None:
    p = SupplierPrice.objects.filter(ingredient=ingredient, supplier=supplier).order_by("-date", "-id").first()
    return p.price if p else None


# ------------------------------------------------------------------ ta'minotchilar
def ensure_info(supplier) -> SupplierInfo:
    try:
        return supplier.info
    except SupplierInfo.DoesNotExist:
        return SupplierInfo.objects.create(supplier=supplier)


def debts() -> dict[int, dict]:
    """Qarzdorlik: qabul qilingan buyurtmalar − to'lovlar. Nasiya muddati o'tgani — muddati o'tgan."""
    today = timezone.localdate()
    out: dict[int, dict] = defaultdict(lambda: {"received": 0, "paid": 0, "debt": 0, "overdue": False, "oldest": None})
    for o in Order.objects.filter(status=OrderStatus.RECEIVED).select_related("supplier__info"):
        d = out[o.supplier_id]
        d["received"] += o.total
        if o.received_at and (d["oldest"] is None or o.received_at.date() < d["oldest"]):
            d["oldest"] = o.received_at.date()
    for sid, s in Payment.objects.values("supplier_id").annotate(s=Sum("amount")).values_list("supplier_id", "s"):
        out[sid]["paid"] += int(s or 0)
    infos = {i.supplier_id: i for i in SupplierInfo.objects.all()}
    for sid, d in out.items():
        d["debt"] = max(0, d["received"] - d["paid"])
        info = infos.get(sid)
        days = info.credit_days if info else 0
        d["overdue"] = bool(d["debt"] and d["oldest"] and (today - d["oldest"]).days > days)
        d["oldest"] = d["oldest"].isoformat() if d["oldest"] else None
    return out


def ratings() -> dict[int, dict]:
    return {r["supplier_id"]: {"avg": round(r["a"], 1), "count": r["n"]}
            for r in Order.objects.filter(rating__isnull=False).values("supplier_id").annotate(a=Avg("rating"), n=Count("id"))}


def supplier_out(s, *, debt: dict | None = None, rating: dict | None = None, month_total: int = 0) -> dict:
    i = ensure_info(s)
    main = list(s.ingredients.filter(deleted_at__isnull=True).values_list("name", flat=True)[:4])
    lp = SupplierPrice.objects.filter(supplier=s).select_related("ingredient").order_by("-date", "-id").first()
    tg = i.telegram.strip()
    tg_url = (f"https://t.me/{tg.lstrip('@')}" if tg and not tg.lstrip("+").isdigit() else
              f"https://t.me/+{tg.lstrip('+')}" if tg else "")
    return {"id": s.pk, "name": s.name, "phone": s.phone, "note": s.note, "is_active": s.is_active,
            "kind": i.kind, "kind_label": dict(i._meta.get_field("kind").choices)[i.kind],
            "categories": [{"code": c, "name": CAT[c][0], "emoji": CAT[c][1]} for c in (i.categories or []) if c in CAT],
            "market": {"id": i.market_id, "name": i.market.name} if i.market_id else None,
            "contact_name": i.contact_name, "telegram": tg, "telegram_url": tg_url, "address": i.address,
            "delivers": i.delivers, "min_order": i.min_order, "terms": i.terms, "credit_days": i.credit_days, "photo_url": i.photo_url,
            "products": [(n or {}).get("uz", "") for n in main],
            "last_price": {"ingredient": str(lp.ingredient), "unit": lp.ingredient.unit, "price": lp.price, "date": lp.date.isoformat()} if lp else None,
            "rating": (rating or {}).get("avg"), "reviews": (rating or {}).get("count", 0),
            "debt": (debt or {}).get("debt", 0), "overdue": (debt or {}).get("overdue", False), "month_total": month_total}


# ------------------------------------------------------------------ buyurtmalar
def recalc(order: Order) -> int:
    order.total = int(sum(Decimal(str(ln.qty if ln.received_qty is None else ln.received_qty)) * ln.price for ln in order.lines.all()))
    order.save(update_fields=["total", "updated_at"])
    return order.total


def order_text(order: Order) -> str:
    """Ta'minotchiga Telegram/SMS uchun tayyor matn."""
    lines = [f"Assalomu alaykum! Buyurtma #{order.number}"]
    if order.expected_date:
        lines.append(f"Kerak: {order.expected_date:%d.%m.%Y}")
    for ln in order.lines.select_related("ingredient"):
        q = f"{ln.qty:f}"
        q = q.rstrip("0").rstrip(".") if "." in q else q
        lines.append(f"• {ln.ingredient} — {q} {ln.ingredient.unit}")
    if order.branch_id:
        lines.append(f"Manzil: {order.branch.name}{', ' + order.branch.address if order.branch.address else ''}")
    if order.note:
        lines.append(order.note)
    return "\n".join(lines)


@transaction.atomic
def receive(order: Order, received: dict[int, Decimal] | None, *, tenant=None, actor=None) -> Order:
    """Qabul: haqiqiy miqdor bilan omborga kirim (qoldiq +, narx yangilanadi), narx tarixiga yoziladi."""
    from modules.inventory import services as inv
    if order.status in (OrderStatus.RECEIVED, OrderStatus.CANCELLED):
        raise ValueError("Bu buyurtma allaqachon yopilgan.")
    lines = []
    for ln in order.lines.select_related("ingredient"):
        q = Decimal(str((received or {}).get(ln.pk, ln.qty)))
        ln.received_qty = max(Decimal("0"), q)
        ln.save(update_fields=["received_qty"])
        if ln.received_qty > 0:
            lines.append({"ingredient_id": ln.ingredient_id, "qty": ln.received_qty, "unit_price": ln.price})
            record_price(ingredient=ln.ingredient, price=ln.price, supplier=order.supplier, source=PriceSource.ORDER, note=f"Buyurtma #{order.number}")
    if not lines:
        raise ValueError("Hech narsa qabul qilinmadi — miqdorlarni kiriting.")
    p = inv.create_purchase(lines=lines, branch=order.branch, supplier=order.supplier, note=f"Zakup #{order.number}", actor=actor, tenant=tenant)
    order.purchase_id = p.pk
    order.status = OrderStatus.RECEIVED
    order.received_at = timezone.now()
    order.save(update_fields=["purchase_id", "status", "received_at", "updated_at"])
    recalc(order)
    emit("procurement.order_received", {"order_id": order.pk, "number": order.number, "total": order.total}, tenant=tenant)
    return order


# ------------------------------------------------------------------ bozorlik
def trip_totals(t: Trip) -> dict:
    items = sum(i.total for i in t.items.all())
    exp = sum(e.amount for e in t.expenses.all())
    spent = items + exp
    balance = t.advance - spent
    return {"items": items, "expenses": exp, "spent": spent, "balance": balance,
            "to_return": max(0, balance), "owed_to_buyer": max(0, -balance),
            # yopilganda: qaytishi kerak bo'lgan pul bilan haqiqatda qaytgani farqi (manfiy — kamomad)
            "diff": (t.returned - max(0, balance)) if t.status == TripStatus.CLOSED else None,
            "overhead_percent": round(100 * exp / items, 1) if items else None,
            "bought": sum(1 for i in t.items.all() if i.qty > 0), "planned": sum(1 for i in t.items.all() if i.planned_qty > 0)}


@transaction.atomic
def close_trip(t: Trip, returned: int, *, tenant=None, actor=None) -> Trip:
    """Hisobni yopish: mahsulotlar omborga (xarajat tannarxga taqsimlanadi yoki Moliyaga alohida), narx tarixi, qaytgan pul."""
    from modules.inventory import services as inv
    if t.status == TripStatus.CLOSED:
        raise ValueError("Hisob allaqachon yopilgan.")
    items = [i for i in t.items.select_related("ingredient") if i.qty > 0]
    tot = trip_totals(t)
    lines = []
    for i in items:
        if i.ingredient_id is None:
            continue
        unit = Decimal(i.price)
        if t.overhead_to_cost and tot["items"]:
            share = Decimal(tot["expenses"]) * Decimal(i.total) / Decimal(tot["items"])
            unit += share / i.qty
        lines.append({"ingredient_id": i.ingredient_id, "qty": i.qty, "unit_price": unit.quantize(Decimal("0.01"))})
        record_price(ingredient=i.ingredient, price=i.price, market=t.market, source=PriceSource.TRIP, note=f"Bozorlik #{t.number} · {i.seller}".strip(" ·"), day=t.date)
    if lines:
        p = inv.create_purchase(lines=lines, branch=t.branch, date=t.date, note=f"Bozorlik #{t.number}", actor=actor, tenant=tenant)
        t.purchase_id = p.pk
    if tot["expenses"] and not t.overhead_to_cost and tenant is not None and tenant.module_enabled("finance"):
        from modules.finance.models import Expense, ExpenseCategory
        cat, _ = ExpenseCategory.objects.get_or_create(code="market", defaults={"name": "Bozor xarajatlari (transport, hammol)"})
        Expense.objects.create(date=t.date, branch=t.branch, category=cat, amount=tot["expenses"], note=f"Bozorlik #{t.number}",
                               created_by=actor, source="purchase", ref=f"Bozorlik #{t.number}")
    t.returned = max(0, int(returned))
    t.status = TripStatus.CLOSED
    t.closed_at = timezone.now()
    t.closed_by = actor
    t.save()
    emit("procurement.trip_closed", {"trip_id": t.pk, "number": t.number, "spent": tot["spent"], "diff": t.returned - max(0, tot["balance"])}, tenant=tenant)
    return t


def trip_stats(start: date, end: date) -> dict:
    from .models import TripExpense, TripItem
    trips = Trip.objects.filter(date__gte=start, date__lte=end).exclude(status=TripStatus.CANCELLED)
    items = int(TripItem.objects.filter(trip__in=trips).aggregate(s=Sum("total"))["s"] or 0)
    exp_qs = TripExpense.objects.filter(trip__in=trips)
    exp = int(exp_qs.aggregate(s=Sum("amount"))["s"] or 0)
    by_kind = [{"kind": k, "label": ExpenseKind(k).label, "amount": int(s or 0)}
               for k, s in exp_qs.values("kind").annotate(s=Sum("amount")).order_by("-s").values_list("kind", "s")]
    by_market = []
    for m in Market.objects.filter(trips__in=trips).distinct():
        ts = trips.filter(market=m)
        it = int(TripItem.objects.filter(trip__in=ts).aggregate(s=Sum("total"))["s"] or 0)
        ex = int(TripExpense.objects.filter(trip__in=ts).aggregate(s=Sum("amount"))["s"] or 0)
        by_market.append({"market": m.name, "trips": ts.count(), "items": it, "expenses": ex, "overhead_percent": round(100 * ex / it, 1) if it else None})
    by_buyer = []
    for r in trips.values("buyer_id", "buyer__full_name", "buyer__phone").annotate(n=Count("id")):
        ts = trips.filter(buyer_id=r["buyer_id"])
        diff = 0
        for t in ts.filter(status=TripStatus.CLOSED):
            tt = trip_totals(t)
            diff += tt["diff"] or 0
        by_buyer.append({"buyer": r["buyer__full_name"] or r["buyer__phone"], "trips": r["n"],
                         "spent": sum(trip_totals(t)["spent"] for t in ts), "diff": diff})
    n = trips.count()
    return {"trips": n, "items": items, "expenses": exp, "overhead_percent": round(100 * exp / items, 1) if items else None,
            "avg_expense": exp // n if n else 0, "by_kind": by_kind, "by_market": sorted(by_market, key=lambda x: -x["items"]),
            "by_buyer": by_buyer, "open": trips.filter(status__in=[TripStatus.ACTIVE, TripStatus.PLANNED]).count(),
            "unreturned": sum(max(0, trip_totals(t)["balance"]) for t in trips.filter(status=TripStatus.ACTIVE))}


# ------------------------------------------------------------------ bosh sahifa va qidiruv
def overview(tenant) -> dict:
    from modules.inventory.models import Purchase, PurchaseLine, Supplier
    today = timezone.localdate()
    ms = today.replace(day=1)
    pms = (ms - timedelta(days=1)).replace(day=1)
    month = int(Purchase.objects.filter(date__gte=ms).aggregate(s=Sum("total"))["s"] or 0)
    prev = int(Purchase.objects.filter(date__gte=pms, date__lt=ms).aggregate(s=Sum("total"))["s"] or 0)
    d = debts()
    active = Order.objects.filter(status__in=[OrderStatus.SENT, OrderStatus.CONFIRMED])
    top = []
    for r in (PurchaseLine.objects.filter(purchase__date__gte=ms).values("ingredient_id", "ingredient__name", "ingredient__unit")
              .annotate(q=Sum("qty")).order_by("-q")[:8]):
        top.append({"id": r["ingredient_id"], "name": (r["ingredient__name"] or {}).get("uz"), "unit": r["ingredient__unit"], "qty": float(r["q"] or 0)})
    rt = ratings()
    sup = list(Supplier.objects.filter(is_active=True))
    rank = sorted([{"id": s.pk, "name": s.name, "rating": rt.get(s.pk, {}).get("avg"), "reviews": rt.get(s.pk, {}).get("count", 0)} for s in sup],
                  key=lambda x: (x["rating"] is None, -(x["rating"] or 0), -x["reviews"]))[:5]
    return {
        "kpis": {"suppliers": len(sup), "suppliers_new": sum(1 for s in sup if s.created_at.date() >= ms),
                 "active_orders": active.count(), "on_way": active.filter(status=OrderStatus.CONFIRMED).count(),
                 "month_total": month, "month_delta": round(100 * (month - prev) / prev, 1) if prev else None,
                 "debt": sum(x["debt"] for x in d.values()), "debt_suppliers": sum(1 for x in d.values() if x["debt"]),
                 "overdue": sum(1 for x in d.values() if x["overdue"]),
                 "today": active.filter(expected_date=today).count(), "markets": Market.objects.filter(is_active=True).count()},
        "top": top, "ranking": rank,
        "recent": [order_out(o) for o in Order.objects.select_related("supplier", "branch")[:6]],
        "categories": [{"code": c, "name": n, "emoji": e} for c, n, e in CATEGORIES],
    }


def order_out(o: Order, full: bool = False) -> dict:
    out = {"id": o.pk, "number": o.number, "supplier_id": o.supplier_id, "supplier": o.supplier.name, "branch": o.branch.name if o.branch_id else None,
           "status": o.status, "status_label": OrderStatus(o.status).label, "expected_date": o.expected_date.isoformat() if o.expected_date else None,
           "total": o.total, "note": o.note, "created_at": o.created_at.isoformat(), "rating": o.rating,
           "received_at": o.received_at.isoformat() if o.received_at else None, "items": o.lines.count()}
    if full:
        out["lines"] = [{"id": ln.pk, "ingredient_id": ln.ingredient_id, "name": str(ln.ingredient), "unit": ln.ingredient.unit,
                         "qty": float(ln.qty), "price": ln.price, "received_qty": float(ln.received_qty) if ln.received_qty is not None else None}
                        for ln in o.lines.select_related("ingredient")]
        out["text"] = order_text(o)
        out["paid"] = int(o.payments.aggregate(s=Sum("amount"))["s"] or 0)
        out["phone"] = o.supplier.phone
        out["telegram_url"] = supplier_out(o.supplier)["telegram_url"]
    return out


def search(q: str = "", cat: str = "") -> dict:
    """«Nima kerak?» — mahsulot yoki toifa bo'yicha: kim sotadi, oxirgi narx, qaysi bozorda bor."""
    from modules.inventory.models import Ingredient, Supplier
    ings = Ingredient.objects.filter(deleted_at__isnull=True)
    if q:
        ings = ings.filter(Q(name__icontains=q) | Q(category__icontains=q))
    ings = [i for i in ings if not cat or cat_of(i) == cat][:12]
    offers = []
    for i in ings[:6]:
        for r in price_board(i)[:5]:
            offers.append({**r, "ingredient_id": i.pk, "ingredient": str(i), "unit": i.unit})
    offers.sort(key=lambda r: (r["ingredient"], r["price"]))
    cats = {cat} if cat else {cat_of(i) for i in ings}
    sup_ids = set(SupplierInfo.objects.filter(Q(*[Q(categories__contains=[c]) for c in cats], _connector=Q.OR) if cats else Q(pk__in=[]))
                  .values_list("supplier_id", flat=True))
    sup_ids |= {r["supplier_id"] for r in offers if r["supplier_id"]}
    d, rt = debts(), ratings()
    suppliers = [supplier_out(s, debt=d.get(s.pk), rating=rt.get(s.pk)) for s in Supplier.objects.filter(pk__in=sup_ids, is_active=True)]
    markets = [market_out(m) for m in Market.objects.filter(is_active=True) if cats & set(m.categories or [])]
    return {"ingredients": [{"id": i.pk, "name": str(i), "unit": i.unit, "category": cat_of(i), "stock": float(i.stock), "price": float(i.price)} for i in ings],
            "offers": offers, "suppliers": suppliers, "markets": markets}
