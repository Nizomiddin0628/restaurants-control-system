"""
«Jonli demo» — namuna restoranlarda vaqt o'tgani sari hayot o'zi davom etadi (xuddi haqiqiy restoran ishlayotgandek).

Har gal panel ochilganda (ko'pi bilan 4 daqiqada bir marta) oxirgi holatdan hozirgacha bo'lgan bo'shliq to'ldiriladi:
  • kassa: kun/soat bo'yicha real taqsimotda cheklar (filial, zal/olib ketish/yetkazish, to'lov usuli — tarixdagi ulushlarda),
           mijozlar kartasi va bonus, ~1% bekor qilingan, kassa smenalari;
  • ombor: sotilgan taomlar tex-karta bo'yicha xomashyoni kamaytiradi → kam qolsa vazifa ochiladi;
  • zakup: kam qolgan xomashyo — kompaniyadan buyurtma (qabul, to'lov, nasiya) yoki bozorlik (avans, taksi/hammol, qaytgan pul);
  • hozir: oshxona ekranida 3–6 ta faol buyurtma, zalda band stollar;
  • xodimlar: smena jadvali va davomat (kechikishlar bilan);
  • bron: bugun va keyingi kunlarga bronlar; moliya: oy boshida ijara/kommunal/soliq; oylik varaqlari;
  • loyihalar: muddati o'tgan vazifalarning ko'pi bajariladi.
Faqat `tenant.settings["demo_live"] = True` bo'lgan restoranlarda ishlaydi (haqiqiy mijozlarga hech qachon tegmaydi).
Yoqish: python manage.py demo_live --slug namuna --on
"""
from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

log = logging.getLogger("live")

KEY = "demo_live"
HOURS = list(range(10, 23))                                  # 10:00–22:59
HOUR_W = [2, 3, 6, 8, 6, 4, 4, 5, 7, 9, 8, 5, 2]             # tushlik va kechki cho'qqi
MAX_GAP_DAYS = 45


def is_live(tenant) -> bool:
    try:
        return bool((tenant.settings or {}).get(KEY))
    except Exception:
        return False


def tick(tenant, *, force: bool = False, now: datetime | None = None) -> dict:
    """Bo'shliqni to'ldiradi. Tez: hech narsa qilish kerak bo'lmasa — bir necha mikrosoniya (kesh)."""
    if tenant is None or getattr(tenant, "schema_name", "public") == "public" or not is_live(tenant):
        return {}
    k = f"live:tick:{tenant.schema_name}"
    if force:
        cache.set(k, 1, 240)
    elif not cache.add(k, 1, 240):
        return {}
    lock = f"live:lock:{tenant.schema_name}"
    if not cache.add(lock, 1, 900):
        return {}
    try:
        return _run(tenant, timezone.localtime(now or timezone.now()))
    except Exception:                                    # demo xatosi hech qachon panelni yiqitmasin
        log.exception("live tick xatosi")
        return {"error": True}
    finally:
        cache.delete(lock)


# ------------------------------------------------------------------ asosiy
def _run(t, now: datetime) -> dict:
    from modules.pos.models import Order
    last = Order.objects.exclude(paid_at__isnull=True).aggregate(m=Max("paid_at"))["m"]
    if last is None:
        return {}
    last = timezone.localtime(last)
    start = max(last + timedelta(minutes=1), now - timedelta(days=MAX_GAP_DAYS))
    out = Counter()
    rnd = random.Random(f"{t.schema_name}:{now:%Y%m%d%H%M}")
    prof = _profile(start)
    day = start.date()
    while day <= now.date():
        a = max(start, _at(day, 10, 0))
        b = min(now, _at(day, 23, 0))
        done_day = b >= _at(day, 23, 0)
        with transaction.atomic():
            if a < b:
                out["orders"] += _sales(t, prof, day, a, b, rnd)
            if done_day or day < now.date():
                _close_shifts(day)
            out["restock"] += _restock(t, day, rnd, final=day < now.date())
            _people(day, now, rnd)
            _monthly(t, day, rnd)
        day += timedelta(days=1)
    with transaction.atomic():
        _now_kitchen(t, now, prof, rnd)
        _bookings(now, rnd)
        _projects(now, rnd)
        _payables(now)
        _daily_work(t, now, rnd)
        _learning(t, now, rnd)
    return dict(out)


def _at(d: date, h: int, m: int) -> datetime:
    return timezone.make_aware(datetime.combine(d, time(h, m)))


# ------------------------------------------------------------------ savdo profili (tarixdan)
def _profile(before: datetime) -> dict:
    from modules.catalog.models import Product
    from modules.crm.models import Customer
    from modules.pos.models import Order, OrderItem
    from modules.tables.models import Table
    since = before - timedelta(days=28)
    qs = Order.objects.filter(paid_at__gte=since, paid_at__lt=before, status="paid")
    per_wd = defaultdict(list)
    for r in qs.values("paid_at__date").annotate(n=Count("id")):
        per_wd[r["paid_at__date"].weekday()].append(r["n"])
    avg = {wd: (sum(v) / len(v)) for wd, v in per_wd.items() if v}
    base = (sum(avg.values()) / len(avg)) if avg else 60
    for wd in range(7):
        avg.setdefault(wd, base * (1.2 if wd >= 5 else 1))
    items = Counter(dict(OrderItem.objects.filter(order__in=qs).values_list("product_id").annotate(n=Sum("qty")).values_list("product_id", "n")))
    prods = {p.pk: p for p in Product.objects.filter(deleted_at__isnull=True, is_active=True, in_stop_list=False)}
    if not items:
        items = Counter({pid: 1 for pid in prods})
    pw = [(prods[pid], n) for pid, n in items.items() if pid in prods]
    def share(field):
        c = Counter(qs.values_list(field, flat=True))
        return list(c.keys()) or [None], list(c.values()) or [1]
    total = qs.count() or 1
    custs = list(Customer.objects.all().only("id", "phone", "name", "spent_total", "balance"))
    return {
        "avg": avg, "products": [p for p, _ in pw], "pw": [n for _, n in pw],
        "branch": share("branch_id"), "type": share("type"), "pay": share("payment_method"), "source": share("source"),
        "cust_ratio": qs.exclude(customer_phone="").count() / total,
        "customers": custs, "cw": [max(1.0, (c.spent_total or 0) / 100_000) for c in custs],
        "tables": list(Table.objects.filter(is_active=True).values_list("number", flat=True)) or [str(i) for i in range(1, 11)],
    }


def _pick_items(prof, rnd) -> list:
    if not prof["products"]:
        return []
    k = rnd.choices([1, 2, 3, 4], weights=[30, 38, 22, 10])[0]
    picks = {}
    for p in rnd.choices(prof["products"], weights=prof["pw"], k=k):
        picks[p.pk] = (p, picks.get(p.pk, (p, 0))[1] + rnd.choice([1, 1, 1, 2]))
    return list(picks.values())


def _shift(branch_id, d: date):
    from modules.pos.models import CashShift
    s = CashShift.objects.filter(branch_id=branch_id, opened_at__date=d).first()
    if s is None:
        from core.models import User
        cashier = User.objects.filter(memberships__role__code="cashier", is_active=True).first()
        s = CashShift.objects.create(branch_id=branch_id, opened_by=cashier, opened_at=_at(d, 9, 0), cash_start=200_000)
    return s


def _sales(t, prof, d: date, a: datetime, b: datetime, rnd) -> int:
    """[a, b) oralig'ida cheklar: kunlik o'rtacha × shu oraliqqa to'g'ri keladigan soatlar ulushi."""
    from modules.pos.models import Order, OrderItem, OrderStatus
    total_w = sum(HOUR_W)
    frac = 0.0
    slots = []
    for h, w in zip(HOURS, HOUR_W, strict=True):
        s, e = max(a, _at(d, h, 0)), min(b, _at(d, h, 0) + timedelta(hours=1))
        if e > s:
            part = (e - s).total_seconds() / 3600
            frac += w * part / total_w
            slots.append((s, e, w * part))
    if not slots:
        return 0
    n_day = prof["avg"][d.weekday()] * rnd.uniform(0.9, 1.1)
    n = int(n_day * frac + rnd.random())
    made = []
    usage = Counter()
    for _ in range(n):
        s, e, _w = rnd.choices(slots, weights=[x[2] for x in slots])[0]
        at = s + timedelta(seconds=rnd.uniform(0, (e - s).total_seconds()))
        branch_id = rnd.choices(*prof["branch"])[0]
        typ = rnd.choices(*prof["type"])[0] or "takeaway"
        o = Order(branch_id=branch_id, shift=_shift(branch_id, d), type=typ, status=OrderStatus.PAID,
                  payment_method=rnd.choices(*prof["pay"])[0] or "cash", paid_at=at,
                  source=rnd.choices(*prof["source"])[0] or "pos",
                  table_no=rnd.choice(prof["tables"]) if typ == "dine_in" else "")
        o.cashier = o.shift.opened_by
        if prof["customers"] and rnd.random() < prof["cust_ratio"]:
            c = rnd.choices(prof["customers"], weights=prof["cw"])[0]
            o.customer_phone, o.customer_name = c.phone, c.name
        o.save()
        for p, q in _pick_items(prof, rnd):
            OrderItem.objects.create(order=o, product=p, name=p.name.get("uz") or str(p), qty=q, price=p.price, cost=p.cost)
            usage[p.pk] += q
        o.recalc()
        if rnd.random() < 0.011:
            o.status, o.cancelled_at, o.cancel_reason, o.paid_at = OrderStatus.CANCELLED, at, "Mijoz bekor qildi", None
        o.save()
        Order.objects.filter(pk=o.pk).update(created_at=at - timedelta(minutes=rnd.randint(8, 25)))
        made.append(o)
    _crm(t, [o for o in made if o.status == "paid"], rnd)
    if usage:
        _consume(t, usage, d, b)
    return len(made)


def _consume(t, usage: Counter, d: date, at: datetime):
    from modules.inventory.models import StockMovement
    from modules.inventory.services import consume_for_sale
    ref = f"Savdo {d:%d.%m} (kassa)"
    before = StockMovement.objects.aggregate(m=Max("id"))["m"] or 0
    consume_for_sale([{"product_id": pid, "qty": q} for pid, q in usage.items()], ref=ref, tenant=t)
    StockMovement.objects.filter(id__gt=before, ref=ref).update(at=at)


def _crm(t, orders, rnd):
    """Mijoz kartasi: xarid soni, summa, bonus (daraja foizi bo'yicha) — kassa to'lovidagi kabi."""
    if not orders:
        return
    from modules.crm import services
    from modules.crm.models import BonusTxn, Customer, OrderLink, TxnKind
    cfg = services.conf(t)
    by = {c.phone: c for c in Customer.objects.filter(phone__in={o.customer_phone for o in orders if o.customer_phone})}
    for o in orders:
        c = by.get(o.customer_phone)
        if c is None:
            continue
        pct = services.level_of(c, cfg)["percent"]
        earned = o.total * pct // 100
        c.orders_count += 1
        c.spent_total += o.total
        c.balance += earned
        c.last_order_at = o.paid_at
        c.first_order_at = c.first_order_at or o.paid_at
        OrderLink.objects.create(order_id=o.pk, customer=c, earned=earned, settled=True)
        if earned:
            BonusTxn.objects.create(customer=c, kind=TxnKind.EARN, amount=earned, order_id=o.pk, note=f"Chek #{o.number} · {pct}%",
                                    created_at=o.paid_at)
    for c in by.values():
        c.save(update_fields=["orders_count", "spent_total", "balance", "last_order_at", "first_order_at", "updated_at"])
    # har kuni 1–3 ta yangi mijoz (birinchi xaridi bilan)
    from modules.crm.demo import MEN, SURN, WOMEN
    for o in [x for x in orders if not x.customer_phone][: rnd.randint(0, 2)]:
        f = rnd.random() < 0.5
        phone = f"+99893{rnd.randint(1000000, 9999999)}"
        if Customer.objects.filter(phone=phone).exists():
            continue
        name = f"{rnd.choice(WOMEN if f else MEN)} {rnd.choice(SURN)}{'a' if f else ''}"
        c = Customer.objects.create(phone=phone, name=name, gender="f" if f else "m", source=o.source if o.source in ("telegram", "site") else "pos",
                                    orders_count=1, spent_total=o.total, first_order_at=o.paid_at, last_order_at=o.paid_at)
        Customer.objects.filter(pk=c.pk).update(created_at=o.paid_at)
        from modules.pos.models import Order
        Order.objects.filter(pk=o.pk).update(customer_phone=phone, customer_name=name)
        OrderLink.objects.create(order_id=o.pk, customer=c, earned=0, settled=True)


def _close_shifts(d: date):
    from modules.pos.models import CashShift
    for s in CashShift.objects.filter(opened_at__date__lte=d, closed_at__isnull=True):
        if s.opened_at.date() < timezone.localdate() or d < timezone.localdate():
            tot = s.totals()
            s.closed_at = _at(s.opened_at.date(), 23, 0)
            s.cash_end = tot["expected_cash"] - random.choice([0, 0, 0, 5000, 10000])
            s.save(update_fields=["closed_at", "cash_end"])


# ------------------------------------------------------------------ ombor → zakup
def _restock(t, d: date, rnd, final: bool) -> int:
    """Kam qolgan xomashyo: bozor sotuvchisi/fermer — bozorlik; kompaniya — buyurtma. Bugun uchun — yo'lda (yuborilgan)."""
    from modules.inventory.models import Ingredient, StockMovement
    low = [i for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True).select_related("supplier") if i.min_stock and i.stock < i.min_stock * Decimal("1.1")]
    if not low:
        return 0
    week = defaultdict(Decimal)
    for r in (StockMovement.objects.filter(kind="sale", at__date__gt=d - timedelta(days=7), at__date__lte=d, ingredient__in=low)
              .values("ingredient_id").annotate(q=Sum("qty"))):
        week[r["ingredient_id"]] = -r["q"]
    need = {}
    for i in low:
        daily = (week[i.pk] / 7) if week[i.pk] else i.min_stock / 3
        q = max(i.min_stock * Decimal("2.2"), daily * 4) - i.stock
        if q > 0:
            need[i] = _round_qty(q, i.unit)
    if not need:
        return 0
    if not t.module_enabled("procurement"):
        from modules.inventory.services import create_purchase
        create_purchase(lines=[{"ingredient_id": i.pk, "qty": q, "unit_price": i.price or 1000} for i, q in need.items()], date=d,
                        note="Ta'minot (avtomatik)", tenant=t)
        return len(need)
    from modules.procurement import services as ps
    from modules.procurement.models import Order, OrderStatus
    groups = defaultdict(dict)
    for i, q in need.items():
        groups[i.supplier_id][i] = q
    n = 0
    for sid, lines in groups.items():
        sup = next(iter(lines)).supplier
        info = ps.ensure_info(sup) if sup else None
        if Order.objects.filter(supplier_id=sid, status__in=[OrderStatus.SENT, OrderStatus.CONFIRMED]).exists():
            continue                                         # allaqachon yo'lda
        if sup is None or (info and info.kind in ("bazaar", "farmer")):
            n += _trip(t, d, lines, info, rnd, final)
        else:
            n += _order(t, d, sup, lines, rnd, final)
    return n


def _round_qty(q: Decimal, unit: str) -> Decimal:
    if unit == "dona":
        return Decimal(max(12, int((q + 11) // 12 * 12)))
    return Decimal(max(1, int(q + Decimal("0.99"))))


def _price(i, sup=None, market=None, rnd=None):
    from modules.procurement.models import SupplierPrice
    p = SupplierPrice.objects.filter(ingredient=i, **({"supplier": sup} if sup else {})).order_by("-date", "-id").values_list("price", flat=True).first()
    base = p or int(i.price) or 1000
    return max(100, int(base * (1 + (rnd.uniform(-0.04, 0.05) if rnd else 0)) / 100) * 100)


def _order(t, d: date, sup, lines: dict, rnd, final: bool) -> int:
    from modules.procurement import services as ps
    from modules.procurement.models import Order, OrderLine, OrderStatus, Payment
    o = Order.objects.create(supplier=sup, status=OrderStatus.DRAFT, expected_date=d + timedelta(days=0 if final else 1), note="Kam qolgan xomashyo (avtomatik)")
    for i, q in lines.items():
        OrderLine.objects.create(order=o, ingredient=i, qty=q, price=_price(i, sup, rnd=rnd))
    ps.recalc(o)
    Order.objects.filter(pk=o.pk).update(created_at=_at(d, 8, rnd.randint(0, 50)))
    if not final:                                        # bugun: yuborildi / tasdiqlandi — ertaga keladi
        Order.objects.filter(pk=o.pk).update(status=rnd.choice([OrderStatus.SENT, OrderStatus.CONFIRMED]), sent_at=timezone.now())
        return 1
    o.status = OrderStatus.CONFIRMED
    o.save(update_fields=["status"])
    ps.receive(o, None, tenant=t)
    _backdate_purchase(o.purchase_id, _at(d, 11, 5))
    Order.objects.filter(pk=o.pk).update(received_at=_at(d, 11, rnd.randint(0, 59)), sent_at=_at(d, 8, 10),
                                         rating=rnd.choices([5, 4, 4, 3], weights=[45, 35, 15, 5])[0])
    info = ps.ensure_info(sup)
    if info.terms != "credit":
        o.refresh_from_db()
        Payment.objects.create(supplier=sup, order=o, amount=o.total, method="cash" if info.terms == "cash" else "transfer", date=d,
                               note="Qabulda to'landi")
    return 1


def _trip(t, d: date, lines: dict, info, rnd, final: bool) -> int:
    from core.models import User
    from modules.procurement import services as ps
    from modules.procurement.models import Trip, TripExpense, TripItem
    if not final:
        return 0                                         # bozorlik ertalab — bugungi kam qolganlar ertangi bozorlikka
    buyer = (User.objects.filter(memberships__role__code="buyer", is_active=True).first()
             or User.objects.filter(memberships__role__code__in=["cook", "manager"], is_active=True).first())
    if buyer is None:
        return 0
    market = info.market if info and info.market_id else None
    t_obj = Trip.objects.create(buyer=buyer, date=d, market=market, advance=0, overhead_to_cost=ps.setting(t, "overhead_to_cost", True),
                                note="Kunlik bozorlik (kam qolganlar)")
    items = 0
    for i, q in lines.items():
        price = _price(i, market=market, rnd=rnd)
        TripItem.objects.create(trip=t_obj, ingredient=i, name=str(i), unit=i.unit, planned_qty=q, qty=q, price=price, total=int(q * price),
                                seller=rnd.choice(["Ahmad aka", "Dilshod", "Sobir opa", "Qator 12", "Ravshan aka", ""]))
        items += int(q * price)
    TripExpense.objects.create(trip=t_obj, kind="taxi", amount=rnd.choice([40_000, 50_000, 60_000]), note="Bozorga borish-qaytish")
    if items > 800_000:
        TripExpense.objects.create(trip=t_obj, kind="porter", amount=rnd.choice([20_000, 30_000]), note="Qoplarni ortish")
    spent = ps.trip_totals(t_obj)["spent"]
    t_obj.advance = int(spent * rnd.uniform(1.03, 1.2) / 50_000 + 1) * 50_000
    t_obj.save(update_fields=["advance"])
    bal = ps.trip_totals(t_obj)["balance"]
    ps.close_trip(t_obj, max(0, bal) - (rnd.choice([10_000, 20_000]) if rnd.random() < 0.12 else 0), tenant=t)
    _backdate_purchase(t_obj.purchase_id, _at(d, 12, 0))
    Trip.objects.filter(pk=t_obj.pk).update(closed_at=_at(d, 12, rnd.randint(0, 59)), created_at=_at(d, 6, 30))
    return 1


def _backdate_purchase(pid, at: datetime):
    if not pid:
        return
    from modules.inventory.models import Purchase, StockMovement
    p = Purchase.objects.filter(pk=pid).first()
    if p:
        Purchase.objects.filter(pk=pid).update(date=at.date())
        StockMovement.objects.filter(ref=f"Kirim #{p.number}").update(at=at)


def _payables(now: datetime):
    """Nasiya muddati kelgan qarzlarni to'lash (qarzdorlik o'sib ketmasin, lekin bir qismi qolsin)."""
    from modules.procurement.models import Order, Payment
    from modules.procurement.services import debts
    for sid, dd in debts().items():
        if Payment.objects.filter(supplier_id=sid, date=now.date()).exists():
            continue
        if dd["debt"] and dd["oldest"] and (now.date() - date.fromisoformat(dd["oldest"])).days > 10:
            o = Order.objects.filter(supplier_id=sid, status="received").order_by("received_at").first()
            if o:
                Payment.objects.create(supplier_id=sid, amount=int(dd["debt"] * 0.7) // 1000 * 1000, method="transfer", date=now.date(),
                                       note="Nasiya bo'yicha to'lov")


# ------------------------------------------------------------------ hozirgi lahza: oshxona va zal
def _now_kitchen(t, now: datetime, prof, rnd):
    from modules.kds.models import Ticket
    from modules.kds.services import create_tickets
    from modules.pos.models import Order, OrderItem, OrderStatus
    opened = list(Order.objects.filter(status=OrderStatus.OPEN).order_by("created_at"))
    # 25 daqiqadan eski ochiq buyurtmalar — to'landi (oshxona ekrani «muzlab» qolmasin)
    for o in opened:
        if now - timezone.localtime(o.created_at) > timedelta(minutes=25) or not (10 <= now.hour < 23):
            o.status, o.paid_at = OrderStatus.PAID, min(now, o.created_at + timedelta(minutes=rnd.randint(20, 35)))
            o.payment_method = o.payment_method or rnd.choices(*prof["pay"])[0] or "cash"
            o.save()
            Ticket.objects.filter(order=o).exclude(status="served").update(status="served", ready_at=o.paid_at)
            _table_close(t, o)
    if not (10 <= now.hour < 23):
        return
    live = Order.objects.filter(status=OrderStatus.OPEN).count()
    for _ in range(max(0, rnd.randint(3, 6) - live)):
        branch_id = rnd.choices(*prof["branch"])[0]
        typ = rnd.choices(["dine_in", "dine_in", "takeaway", "delivery"])[0]
        o = Order.objects.create(branch_id=branch_id, shift=_shift(branch_id, now.date()), type=typ, status=OrderStatus.OPEN,
                                 table_no=rnd.choice(prof["tables"]) if typ == "dine_in" else "",
                                 source="telegram" if typ == "delivery" else "pos")
        o.cashier = o.shift.opened_by
        for p, q in _pick_items(prof, rnd):
            OrderItem.objects.create(order=o, product=p, name=p.name.get("uz") or str(p), qty=q, price=p.price, cost=p.cost)
        o.recalc()
        o.save()
        ago = rnd.randint(1, 18)
        Order.objects.filter(pk=o.pk).update(created_at=now - timedelta(minutes=ago))
        create_tickets(o, t)
        st = "new" if ago < 5 else rnd.choice(["cooking", "cooking", "ready"])
        upd = {"status": st}
        if st != "new":
            upd["started_at"] = now - timedelta(minutes=ago - 2)
        if st == "ready":
            upd["ready_at"] = now - timedelta(minutes=1)
        Ticket.objects.filter(order=o).update(**upd)
        if typ == "dine_in" and t.module_enabled("tables"):
            from modules.tables.services import find_by_number, open_session
            table = find_by_number(o.table_no)
            if table and not table.session:
                open_session(table, order=o, waiter=o.cashier, source="pos", tenant=t, guests=rnd.randint(2, 5))


def _table_close(t, o):
    if not t.module_enabled("tables"):
        return
    from modules.tables.models import Table, TableSession
    from modules.tables.services import close_session
    s = TableSession.objects.filter(order_id=o.pk, closed_at__isnull=True).first()
    if s:
        close_session(s, tenant=t)
        Table.objects.filter(pk=s.table_id).update(needs_cleaning=False)


# ------------------------------------------------------------------ xodimlar: smena va davomat
def _people(d: date, now: datetime, rnd):
    from modules.hr.models import Attendance, Employee, ShiftPlan
    today = now.date()
    emps = list(Employee.objects.filter(is_active=True).select_related("position", "branch")) if hasattr(Employee, "is_active") else \
        list(Employee.objects.select_related("position", "branch"))
    for e in emps:
        for k in range(0, 7):                            # 1 hafta oldinga smena jadvali
            day = d + timedelta(days=k)
            if (e.pk + day.toordinal()) % 7 == 0:        # haftada 1 kun dam
                continue
            if not ShiftPlan.objects.filter(employee=e, date=day).exists():
                cashier = e.position and e.position.name == "Kassir"
                ShiftPlan.objects.create(employee=e, branch=e.branch, date=day, start=time(9, 0), end=time(23, 0) if cashier else time(18, 0))
        sp = ShiftPlan.objects.filter(employee=e, date=d).first()
        if sp is None or Attendance.objects.filter(employee=e, check_in__date=d).exists():
            continue
        start = _at(d, sp.start.hour, sp.start.minute)
        if d == today and now < start:
            continue
        r = random.Random(f"{e.pk}:{d}")
        if r.random() < 0.04:                            # kelmadi
            continue
        late = r.choice([0] * 8 + [5, 12, 25])
        cin = start + timedelta(minutes=late - r.randint(0, 6) if not late else late)
        end = _at(d, sp.end.hour, sp.end.minute)
        cout = None if (d == today and now < end) else end + timedelta(minutes=r.randint(-5, 20))
        Attendance.objects.create(employee=e, branch=sp.branch, check_in=cin, check_out=cout, late_minutes=late, source=r.choice(["panel", "telegram", "pos"]))


# ------------------------------------------------------------------ oylik: xarajat va oylik varaqlari
def _monthly(t, d: date, rnd):
    if d.day != 1 and not (d == timezone.localdate()):
        return
    first = d.replace(day=1)
    try:
        from modules.finance.models import Expense, ExpenseCategory, ensure_categories
    except Exception:
        return
    ensure_categories()
    cats = {c.code: c for c in ExpenseCategory.objects.all()}
    rows = [("rent", 30_000_000, 3, "Ijara (oylik)"), ("utilities", rnd.randint(6_500_000, 8_000_000), 10, "Svet, gaz, suv"),
            ("software", 490_000, 2, "RestoPOS obuna"), ("marketing", 2_500_000, 5, "Instagram va Telegram reklama"),
            ("packaging", 1_400_000, 8, "Olib ketish idishlari"), ("repair", rnd.choice([450_000, 900_000]), 18, "Jihoz ta'miri"),
            ("delivery", rnd.randint(1_800_000, 2_600_000), 25, "Kuryer yoqilg'isi"), ("other", 700_000, 20, "Xo'jalik mollari")]
    today = timezone.localdate()
    for code, amount, day, note in rows:
        dd = first + timedelta(days=day - 1)
        if dd <= today and code in cats and not Expense.objects.filter(category=cats[code], date__gte=first, date__lt=first + timedelta(days=32), note=note).exists():
            Expense.objects.create(date=dd, category=cats[code], amount=amount, note=note)
    # o'tgan oy uchun aylanmadan soliq (4%) — oy tugagach
    prev = (first - timedelta(days=1)).replace(day=1)
    if "tax" in cats and not Expense.objects.filter(category=cats["tax"], date__gte=first, date__lt=first + timedelta(days=32)).exists() and today.day >= 15:
        from modules.pos.models import Order
        rev = Order.objects.filter(status="paid", paid_at__date__gte=prev, paid_at__date__lt=first).aggregate(s=Sum("total"))["s"] or 0
        if rev:
            Expense.objects.create(date=first + timedelta(days=14), category=cats["tax"], amount=int(rev * 0.04), note="Aylanmadan soliq 4%")
    try:
        from modules.hr.models import Employee, Payslip
    except Exception:
        return
    for e in Employee.objects.all():
        if not Payslip.objects.filter(employee=e, period=first).exists():
            s = Payslip(employee=e, period=first, salary_type=e.salary_type, rate=e.rate, hours=160, shifts=22, sales_base=0)
            s.compute()
            s.save()


# ------------------------------------------------------------------ bron
def _bookings(now: datetime, rnd):
    try:
        from modules.reservations.models import Reservation, ReservationStatus
        from modules.tables.models import Table
    except Exception:
        return
    tables = list(Table.objects.filter(is_active=True))
    if not tables:
        return
    from modules.reservations.demo import NAMES, OCCASIONS
    # o'tgan bronlar — yakunlangan / kelmagan
    Reservation.objects.filter(starts_at__lt=now - timedelta(hours=3), status__in=[ReservationStatus.NEW, ReservationStatus.CONFIRMED]).update(status=ReservationStatus.DONE)
    for k, want in ((0, 5), (1, 4), (2, 3)):
        d = now.date() + timedelta(days=k)
        have = Reservation.objects.filter(starts_at__date=d).count()
        for j in range(max(0, want - have)):
            h = rnd.choice([12, 13, 13, 18, 19, 19, 20])
            at = _at(d, h, rnd.choice([0, 30]))
            if k == 0 and at < now:
                at = now + timedelta(hours=rnd.randint(1, 4))
                at = at.replace(minute=0 if at.minute < 30 else 30, second=0, microsecond=0)
            Reservation.objects.create(guest_name=rnd.choice(NAMES), phone=f"+99890{rnd.randint(1000000, 9999999)}", guests=rnd.choice([2, 2, 4, 4, 6, 8]),
                                       table=rnd.choice(tables), starts_at=at, duration_minutes=90,
                                       status=rnd.choice([ReservationStatus.CONFIRMED, ReservationStatus.CONFIRMED, ReservationStatus.NEW]),
                                       source=rnd.choice(["phone", "telegram", "hall"]), occasion=rnd.choice(OCCASIONS))


# ------------------------------------------------------------------ loyihalar
def _projects(now: datetime, rnd):
    try:
        from modules.projects import services as S
        from modules.projects.models import PTask, Status, TaskStatus
    except Exception:
        return
    if not cache.add(f"live:proj:{now:%Y%m%d}", 1, 86400):
        return
    for t in PTask.objects.filter(project__status=Status.ACTIVE, due__lt=now.date() - timedelta(days=1)).exclude(status=TaskStatus.DONE).select_related("project"):
        if rnd.random() < 0.6:
            S.set_task_status(t, TaskStatus.DONE, actor=t.assignee)


# ------------------------------------------------------------------ kundalik vazifalar
ISSUES = [
    ("Muzlatkich harorati +7°C — tekshirish", "equipment"), ("Kassa printerida qog'oz tugayapti", "supply"),
    ("Zalda 5-stol oyog'i qimirlayapti", "furniture"), ("Hojatxonada qog'oz sochiq yo'q", "sanitary"),
    ("Mijoz shikoyati: osh sovuq keldi", "safety"), ("Tandir o't olishi sekin", "equipment"),
    ("Yetkazib berish sumkasi yirtilgan", "supply"), ("Kechki smenaga ofitsiant yetmayapti", "staff"),
    ("Oshxona vytyajkasini tozalash", "sanitary"), ("Wi-Fi zalda uzilib qolyapti", "it"),
]


def _daily_work(t, now: datetime, rnd):
    """Har kuni: muddati o'tgan vazifalarning bir qismi bajariladi, 1–2 ta yangi muammo tushadi."""
    if "tasks" not in (t.enabled_modules or []) or not cache.add(f"live:tasks:{t.schema_name}:{now:%Y%m%d}", 1, 86400):
        return
    from core.models import User
    from modules.tasks.models import ColumnKind, Task, TaskCategory, TaskColumn
    from modules.tasks.services import create_task
    done = TaskColumn.objects.filter(kind=ColumnKind.DONE).first()
    active = TaskColumn.objects.filter(kind=ColumnKind.ACTIVE).first()
    if done is None:
        return
    op = list(Task.objects.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).order_by("due_at"))
    for tk in op:
        r = rnd.random()
        if (tk.due_at and tk.due_at < now and r < 0.6) or (tk.column.kind == ColumnKind.ACTIVE and r < 0.25):
            Task.objects.filter(pk=tk.pk).update(column=done, done_at=now.replace(hour=rnd.randint(9, max(9, min(now.hour, 20))), minute=rnd.randint(0, 59)))
        elif active and tk.column.kind == ColumnKind.BACKLOG and r < 0.3:
            Task.objects.filter(pk=tk.pk).update(column=active)
    staff = list(User.objects.filter(is_active=True, memberships__role__code__in=["manager", "cook", "waiter", "cashier"]).distinct())
    if Task.objects.filter(created_at__date=now.date(), title__in=[x[0] for x in ISSUES]).exists() or not staff:
        return

    class _Req:
        auth = None
        tenant = t
    for title, cat in rnd.sample(ISSUES, rnd.randint(1, 2)):
        create_task(_Req(), title=title, description="Xodim tomonidan qayd etilgan (jonli demo).",
                    category=TaskCategory.objects.filter(code=cat).first(), assignee=rnd.choice(staff),
                    due_at=now + timedelta(hours=rnd.choice([4, 8, 24])))


# ------------------------------------------------------------------ o'qitish: xodimlar kursni asta-sekin o'tadi
def _learning(t, now: datetime, rnd):
    if "training" not in (t.enabled_modules or []) or not cache.add(f"live:learn:{t.schema_name}:{now:%Y%m%d}", 1, 86400):
        return
    from modules.training import services as tr
    from modules.training.models import Enrollment, LessonProgress, QuizAttempt
    for e in Enrollment.objects.exclude(status="completed").select_related("course", "user"):
        if rnd.random() > 0.35:
            continue
        c, u = e.course, e.user
        done = tr.lesson_done_ids(u, c)
        nxt = next((les for les in c.lessons.order_by("sort_order", "id") if les.pk not in done), None) if hasattr(c, "lessons") else None
        if nxt is not None:
            p, _ = LessonProgress.objects.get_or_create(user=u, lesson=nxt)
            p.percent, p.completed_at, p.views = 100, now - timedelta(minutes=rnd.randint(10, 600)), p.views + 1
            p.max_position = p.last_position = p.duration = p.duration or 300
            p.watched_seconds = p.duration
            p.save()
        else:
            for q in c.quizzes.all():
                if not QuizAttempt.objects.filter(quiz=q, user=u, passed=True).exists():
                    n = max(1, q.questions.count()) if hasattr(q, "questions") else 10
                    ok = max(1, round(n * rnd.uniform(0.75, 1)))
                    QuizAttempt.objects.create(quiz=q, user=u, finished_at=now, total=n, correct_count=ok, score=round(100 * ok / n), passed=True)
        tr.recompute(c, u)
