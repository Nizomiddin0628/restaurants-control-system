"""Demo: bozorlar, ta'minotchilar (toifa, bozor, Telegram), narx tarixi, buyurtmalar, to'lovlar va bozorliklar."""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from . import services
from .models import (
    ExpenseKind,
    Market,
    Order,
    OrderLine,
    OrderStatus,
    Payment,
    PayTerms,
    SupplierKind,
    SupplierPrice,
    Trip,
    TripExpense,
    TripItem,
)

NEW = [  # nomi, telefon, turi, toifalar, bozor, telegram, yetkazadi, min, shart, nasiya kun
    ("Aziz aka — mol go'shti", "+998901110011", SupplierKind.BAZAAR, ["meat"], "Chorsu bozori", "", False, "10 kg dan", PayTerms.CASH, 0),
    ("Bek Tovuq MChJ", "+998901110022", SupplierKind.COMPANY, ["poultry"], None, "@bektovuq_demo", True, "30 kg dan", PayTerms.CREDIT, 7),
    ("Anvar aka — sabzavot ulgurji", "+998901110033", SupplierKind.BAZAAR, ["veg", "fruit"], "Qo'yliq dehqon bozori", "", True, "50 kg dan", PayTerms.CASH, 0),
    ("Toza Sut fermasi", "+998901110044", SupplierKind.FARMER, ["dairy"], None, "@tozasut_demo", True, "", PayTerms.TRANSFER, 3),
    ("Ziravorchi Rustam", "+998901110055", SupplierKind.BAZAAR, ["spice", "grain"], "Chorsu bozori", "", False, "", PayTerms.CASH, 0),
    ("Qadoq Servis", "+998901110066", SupplierKind.COMPANY, ["pack", "clean"], None, "@qadoq_demo", True, "", PayTerms.CREDIT, 14),
]


def _guess(name: str) -> tuple[str, list[str], str | None, bool, str, int]:
    n = name.lower()
    if "go'sht" in n:
        return SupplierKind.BAZAAR, ["meat", "poultry"], "Chorsu bozori", False, PayTerms.CASH, 0
    if "sabzavot" in n or "ko'kat" in n:
        return SupplierKind.BAZAAR, ["veg", "fruit", "dairy"], "Parkent bozori", True, PayTerms.CASH, 0
    if "ichimlik" in n:
        return SupplierKind.COMPANY, ["drinks"], None, True, PayTerms.CREDIT, 14
    return SupplierKind.COMPANY, ["grain", "oil", "spice"], None, True, PayTerms.TRANSFER, 7


def seed_demo_procurement(tenant=None) -> dict:
    from core.models import User
    from modules.inventory.models import Ingredient, Supplier
    if Order.objects.exists() or Trip.objects.exists():
        return {"skipped": True}
    rnd = random.Random(15)
    services.ensure_markets()
    mk = {m.name: m for m in Market.objects.all()}
    today = timezone.localdate()
    for s in Supplier.objects.all():
        i = services.ensure_info(s)
        kind, cats, market, delivers, terms, days = _guess(s.name)
        i.kind, i.categories, i.market, i.delivers, i.terms, i.credit_days = kind, cats, mk.get(market) if market else None, delivers, terms, days
        i.contact_name = "Menejer"
        i.save()
    for name, phone, kind, cats, market, tg, delivers, mn, terms, days in NEW:
        s, _ = Supplier.objects.get_or_create(name=name, defaults={"phone": phone})
        i = services.ensure_info(s)
        i.kind, i.categories, i.market, i.telegram, i.delivers, i.min_order, i.terms, i.credit_days = (
            kind, cats, mk.get(market) if market else None, tg, delivers, mn, terms, days)
        i.save()
    # narx tarixi: har mahsulotga 2–4 ta taklif (±8%), har biriga 2 ta sana
    sups = list(Supplier.objects.select_related("info"))
    ings = list(Ingredient.objects.filter(deleted_at__isnull=True))
    for ing in ings:
        cat = services.cat_of(ing)
        who = [s for s in sups if cat in (s.info.categories or [])] or ([s for s in sups if s.pk == ing.supplier_id])
        for s in who[:4]:
            base = float(ing.price) * rnd.uniform(0.92, 1.08)
            for k, dd in ((0, rnd.randint(18, 28)), (1, rnd.randint(0, 6))):
                price = int(round(base * (1 + (rnd.uniform(-0.05, 0.06) if k else 0)) / 100) * 100) or 100
                SupplierPrice.objects.create(supplier=s, ingredient=ing, price=price, date=today - timedelta(days=dd), source="manual")
    # buyurtmalar
    plan = [(OrderStatus.RECEIVED, 12, 5), (OrderStatus.RECEIVED, 6, 4), (OrderStatus.CONFIRMED, 0, None), (OrderStatus.SENT, -1, None),
            (OrderStatus.DRAFT, -3, None), (OrderStatus.CANCELLED, 9, None)]
    made = 0
    for n, (st, ago, rating) in enumerate(plan):
        s = sups[n % len(sups)]
        mine = [i for i in ings if services.cat_of(i) in (s.info.categories or [])][:4] or ings[:3]
        o = Order.objects.create(supplier=s, status=OrderStatus.DRAFT, expected_date=today - timedelta(days=ago) if ago >= 0 else today + timedelta(days=-ago),
                                 note="Ertalab 9 gacha olib keling")
        for ing in mine:
            qty = Decimal(rnd.choice([5, 10, 15, 20, 30])) if ing.unit != "dona" else Decimal(rnd.choice([50, 100, 200]))
            OrderLine.objects.create(order=o, ingredient=ing, qty=qty, price=services.last_price(ing, s) or int(ing.price))
        services.recalc(o)
        if st == OrderStatus.RECEIVED:
            o.status = OrderStatus.CONFIRMED
            o.save()
            services.receive(o, None, tenant=tenant)
            Order.objects.filter(pk=o.pk).update(received_at=timezone.now() - timedelta(days=ago), rating=rating)
            o.refresh_from_db()
            Payment.objects.create(supplier=s, order=o, amount=int(o.total * (0.6 if n == 0 else 1)) // 1000 * 1000, date=today - timedelta(days=max(0, ago - 1)))
        else:
            o.status = st
            o.sent_at = timezone.now() if st != OrderStatus.DRAFT else None
            o.save()
        made += 1
    # bozorliklar
    buyer = User.objects.filter(is_active=True, memberships__role__code__in=["cook", "cashier", "manager"]).exclude(full_name="").first() or User.objects.first()
    markets = [m for m in Market.objects.filter(kind__in=["bazaar", "wholesale"])][:4]
    veg = [i for i in ings if services.cat_of(i) in ("veg", "fruit", "meat", "spice")]
    trips = 0
    for k, ago in enumerate([18, 13, 9, 5, 2, 0]):
        m = markets[k % len(markets)] if markets else None
        t = Trip.objects.create(buyer=buyer, date=today - timedelta(days=ago), market=m, advance=rnd.choice([1_500_000, 2_000_000, 2_500_000]),
                                overhead_to_cost=True, note="Haftalik sabzavot va go'sht")
        picks = rnd.sample(veg, min(len(veg), rnd.randint(4, 7)))
        for j, ing in enumerate(picks):
            planned = Decimal(rnd.choice([5, 10, 20]))
            it = TripItem(trip=t, ingredient=ing, name=str(ing), unit=ing.unit, planned_qty=planned)
            if ago or j < 3:                     # bugungisi — hali yarim
                it.qty = planned
                it.price = int(float(ing.price) * rnd.uniform(0.9, 1.05) / 100) * 100 or 100
                it.total = int(it.qty * it.price)
                it.seller = rnd.choice(["Ahmad aka", "Dilshod", "Sobir opa", "Qator 12", ""])
            it.save()
        TripExpense.objects.create(trip=t, kind=ExpenseKind.TAXI, amount=rnd.choice([40_000, 50_000, 60_000]), note="Bozorga borish-qaytish")
        TripExpense.objects.create(trip=t, kind=ExpenseKind.PORTER, amount=rnd.choice([20_000, 30_000]), note="Qoplarni mashinaga ortish")
        if k % 2:
            TripExpense.objects.create(trip=t, kind=ExpenseKind.PACK, amount=10_000, note="Qop va paket")
        spent = services.trip_totals(t)["spent"]
        t.advance = max(500_000, int(spent * rnd.uniform(1.02, 1.25) / 100_000 + 1) * 100_000)
        t.save(update_fields=["advance"])
        if ago:
            tot = services.trip_totals(t)
            services.close_trip(t, max(0, tot["balance"]) - (10_000 if k == 1 else 0), tenant=tenant)
        trips += 1
    return {"suppliers": len(sups), "orders": made, "trips": trips}
