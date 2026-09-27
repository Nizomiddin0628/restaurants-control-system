"""
Demo restoranlarni «bugungi» holatga keltirish (v28) — taqdimotda eskirgan raqamlar ko'rinmasin.

Faqat demo restoranlarda ishlaydi (namuna, lazzat yoki settings["demo"] = True). Haqiqiy restoranlarga tegmaydi.
  • Oshxona ekrani va kassa: 3 soatdan eski ochiq buyurtmalar «hozir»ga suriladi (3–25 daqiqa oldin) —
    «198 daq» o'rniga odatiy vaqt; holati (yangi / tayyorlanmoqda / tayyor) saqlanadi.
  • Zal: 3 soatdan beri ochiq turgan stollar — 10–70 daqiqa oldin ochilgandek.
  • Bron: o'tib ketgan, lekin yopilmagan bronlar bugun/ertaga shu soatga suriladi; o'tirgan — «tugadi».
  • Taomnoma: bo'sh (taomsiz) takroriy kategoriyalar yashiriladi — «Bu kategoriyada taom yo'q» ko'rinmaydi.
  • Ombor: to'langan demo cheklar uchun tex-karta bo'yicha «savdo» sarfi yoziladi (qoldiq o'zgarmaydi) —
    «Eng ko'p sarflangan xomashyo» vidjeti bo'sh turmaydi. Qayta ishga tushirilsa takrorlamaydi.
Ishga tushirish: python manage.py refresh_demo   (install.sh har yangilanishda chaqiradi)
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

DEMO_SLUGS = ("namuna", "lazzat")
STALE = timedelta(hours=3)


def demo_tenants(slugs: list[str] | None = None):
    from public.models import Tenant
    qs = Tenant.objects.exclude(schema_name="public")
    if slugs:
        return list(qs.filter(slug__in=slugs))
    return [t for t in qs if t.slug in DEMO_SLUGS or (t.settings or {}).get("demo")]


def refresh(tenant, *, now=None, seed: int = 7) -> dict:
    """Bitta restoran (sxema allaqachon tanlangan bo'lishi shart). Natija: nima o'zgargani."""
    now = now or timezone.now()
    rnd = random.Random(seed)
    out = {"orders": 0, "tables": 0, "reservations": 0, "usage": 0, "categories": 0}
    mods = set(tenant.enabled_modules or [])
    with transaction.atomic():
        if "pos" in mods:
            out["orders"] = _orders(now, rnd)
        if "tables" in mods:
            out["tables"] = _tables(now, rnd)
        if "reservations" in mods:
            out["reservations"] = _reservations(now)
        if "inventory" in mods and "pos" in mods:
            out["usage"] = _usage(now)
        if "catalog" in mods:
            out["categories"] = _empty_categories(now)
    return out


def _orders(now, rnd) -> int:
    from modules.pos.models import Order, OrderStatus
    try:
        from modules.kds.models import Ticket
    except Exception:   # pragma: no cover
        Ticket = None
    stale = list(Order.objects.filter(status=OrderStatus.OPEN, created_at__lt=now - STALE).order_by("created_at", "id"))
    n = len(stale)
    for k, o in enumerate(stale):
        created = now - timedelta(minutes=max(3, 25 - k * max(1, 22 // max(1, n))) + rnd.randint(0, 2))
        Order.objects.filter(pk=o.pk).update(created_at=created, updated_at=now)
        if Ticket is None:
            continue
        for tk in Ticket.objects.filter(order=o):
            upd = {"created_at": created}
            if tk.started_at:
                upd["started_at"] = min(now, created + timedelta(minutes=rnd.randint(1, 3)))
            if tk.ready_at:
                upd["ready_at"] = min(now, upd.get("started_at", created) + timedelta(minutes=rnd.randint(5, 9)))
            if tk.served_at:
                upd["served_at"] = min(now, upd.get("ready_at", created) + timedelta(minutes=1))
            Ticket.objects.filter(pk=tk.pk).update(**upd)
    return n


def _tables(now, rnd) -> int:
    from modules.tables.models import TableSession
    stale = list(TableSession.objects.filter(closed_at__isnull=True, opened_at__lt=now - STALE))
    for s in stale:
        opened = now - timedelta(minutes=rnd.randint(10, 70))
        upd = {"opened_at": opened}
        if s.bill_asked_at:
            upd["bill_asked_at"] = min(now, opened + timedelta(minutes=rnd.randint(30, 60)))
        TableSession.objects.filter(pk=s.pk).update(**upd)
    return len(stale)


def _reservations(now) -> int:
    from modules.reservations.models import Reservation
    from modules.reservations.models import ReservationStatus as RS
    n = 0
    for r in Reservation.objects.filter(status__in=[RS.NEW, RS.CONFIRMED], starts_at__lt=now - timedelta(hours=2)):
        days = (now - r.starts_at).days + 1
        new = r.starts_at + timedelta(days=days)
        while new < now - timedelta(hours=1):
            new += timedelta(days=1)
        Reservation.objects.filter(pk=r.pk).update(starts_at=new, reminded_at=None)
        n += 1
    n += Reservation.objects.filter(status=RS.SEATED, starts_at__lt=now - STALE).update(status=RS.DONE, closed_at=now)
    return n


def _empty_categories(now) -> int:
    """Taomi yo'q kategoriyalar (preset'dan qolgan «Asosiy taomlar», ikkinchi «Ichimliklar») — faqat to'la menyu bo'lsa yashiriladi."""
    from modules.catalog.models import Category
    cats = list(Category.objects.filter(deleted_at__isnull=True))
    full = [c for c in cats if c.products.filter(deleted_at__isnull=True).exists()]
    if len(full) < 3:
        return 0
    empty = [c.pk for c in cats if c not in full]
    return Category.objects.filter(pk__in=empty).update(deleted_at=now)


def _usage(now, days: int = 30) -> int:
    """To'langan cheklar bo'yicha tex-karta sarfi (faqat yozuv, qoldiq o'zgarmaydi). Bor bo'lsa — takrorlanmaydi."""
    from modules.inventory.models import MovementKind, Recipe, StockMovement
    from modules.pos.models import Order, OrderItem, OrderStatus
    since = now - timedelta(days=days)
    orders = dict(Order.objects.filter(status=OrderStatus.PAID, paid_at__gte=since).values_list("pk", "number"))
    if not orders:
        return 0
    done = set(StockMovement.objects.filter(kind=MovementKind.SALE, at__gte=since - timedelta(days=1)).values_list("ref", flat=True))
    todo = {pk: num for pk, num in orders.items() if f"Buyurtma #{num}" not in done}
    if not todo:
        return 0
    recipes = {r.product_id: r for r in Recipe.objects.prefetch_related("lines__ingredient")}
    if not recipes:
        return 0
    meta = {o["pk"]: o for o in Order.objects.filter(pk__in=todo.keys()).values("pk", "number", "paid_at", "branch_id")}
    rows: list[StockMovement] = []
    for it in OrderItem.objects.filter(order_id__in=todo.keys(), product_id__in=recipes.keys()).values("order_id", "product_id", "qty"):
        r, o = recipes[it["product_id"]], meta[it["order_id"]]
        portions = Decimal(str(it["qty"] or 1)) / (r.yield_qty or 1)
        for line in r.lines.all():
            qty = (line.base_qty * (1 + line.waste_percent / 100) * portions).quantize(Decimal("0.001"))
            if qty:
                rows.append(StockMovement(at=o["paid_at"], ingredient=line.ingredient, branch_id=o["branch_id"], kind=MovementKind.SALE,
                                          qty=-qty, unit_price=line.ingredient.price, ref=f"Buyurtma #{o['number']}", note="demo"))
    StockMovement.objects.bulk_create(rows, batch_size=2000)
    return len(rows)
