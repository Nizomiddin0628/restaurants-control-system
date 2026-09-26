"""
Bayram va ob-havo prognozi — hisob-kitob.

Qanday hisoblanadi (oddiy va tushunarli):
  1) Oxirgi N kun (standart 28) savdosidan har taomning kunlik o'rtacha sotuvi olinadi.
  2) Har kun uchun ko'paytuvchi: hafta kuni (juma-shanba odatda yuqori) × bayram (+uplift%) × ob-havo.
  3) Taom sotuvi × tex-karta = xomashyo ehtiyoji. Ehtiyoj + minimal qoldiq − hozirgi qoldiq = xarid qilish kerak.
Bayramdan `prep_days` kun oldin ombor va boshqaruv panelida ogohlantirish chiqadi, xohlasa — vazifa ochiladi.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.events import emit

from . import weather
from .models import Holiday, HolidayKind

# ------------------------------------------------------------------ O'zbekiston bayramlari
# (kod, {uz, ru, en}, (oy, kun) yoki None — ko'chib yuruvchi, necha kun, tur, savdo o'sishi %, necha kun oldin, izoh)
BUILTIN = [
    ("new_year", {"uz": "Yangi yil", "ru": "Новый год", "en": "New Year"}, (1, 1), 2, HolidayKind.OFFICIAL, 20, 7, ""),
    ("defenders", {"uz": "Vatan himoyachilari kuni", "ru": "День защитников Родины", "en": "Defenders' Day"}, (1, 14), 1, HolidayKind.COMMERCIAL, 10, 5, ""),
    ("valentine", {"uz": "Sevishganlar kuni", "ru": "День святого Валентина", "en": "Valentine's Day"}, (2, 14), 1, HolidayKind.COMMERCIAL, 15, 5, "Juftliklar uchun set va desertlar."),
    ("women", {"uz": "Xotin-qizlar kuni", "ru": "Международный женский день", "en": "Women's Day"}, (3, 8), 1, HolidayKind.OFFICIAL, 40, 7, "Stol bronlari ko'payadi, desert va gullar."),
    ("navruz", {"uz": "Navro'z", "ru": "Навруз", "en": "Navruz"}, (3, 21), 2, HolidayKind.OFFICIAL, 35, 10, "Sumalak, halim, ko'k somsa — mavsumiy menyu."),
    ("memory", {"uz": "Xotira va qadrlash kuni", "ru": "День памяти и почестей", "en": "Remembrance Day"}, (5, 9), 1, HolidayKind.OFFICIAL, 10, 5, ""),
    ("children", {"uz": "Bolalarni himoya qilish kuni", "ru": "День защиты детей", "en": "Children's Day"}, (6, 1), 1, HolidayKind.COMMERCIAL, 15, 5, "Oilaviy tashriflar — bolalar menyusi."),
    ("independence", {"uz": "Mustaqillik kuni", "ru": "День независимости", "en": "Independence Day"}, (9, 1), 1, HolidayKind.OFFICIAL, 30, 7, ""),
    ("teachers", {"uz": "O'qituvchi va murabbiylar kuni", "ru": "День учителя", "en": "Teachers' Day"}, (10, 1), 1, HolidayKind.OFFICIAL, 15, 5, ""),
    ("constitution", {"uz": "Konstitutsiya kuni", "ru": "День Конституции", "en": "Constitution Day"}, (12, 8), 1, HolidayKind.OFFICIAL, 10, 5, ""),
    ("new_year_eve", {"uz": "Yangi yil kechasi", "ru": "Новогодняя ночь", "en": "New Year's Eve"}, (12, 31), 1, HolidayKind.COMMERCIAL, 60, 10, "Korporativlar va oilaviy bronlar — oldindan zakaz qabul qiling."),
    ("ramadan", {"uz": "Ramazon oyi (iftorlik)", "ru": "Рамадан (ифтар)", "en": "Ramadan (iftar)"}, None, 30, HolidayKind.SEASON, 10, 10, "Kunduzi savdo kamayadi, kechki iftorlik ko'payadi — iftorlik setlarini tayyorlang."),
    ("ramadan_eid", {"uz": "Ramazon hayiti", "ru": "Рамазан хайит", "en": "Eid al-Fitr"}, None, 1, HolidayKind.RELIGIOUS, 20, 10, "Sana taxminiy — Diniy idora e'lonidan keyin aniqlang."),
    ("kurban_eid", {"uz": "Qurbon hayiti", "ru": "Курбан хайит", "en": "Eid al-Adha"}, None, 1, HolidayKind.RELIGIOUS, 15, 10, "Go'sht narxi oshadi — go'shtni oldindan xarid qiling. Sana taxminiy."),
]
# ko'chib yuruvchi sanalar (taxminiy, oy kalendari bo'yicha)
MOVABLE = {
    2026: {"ramadan": date(2026, 2, 18), "ramadan_eid": date(2026, 3, 20), "kurban_eid": date(2026, 5, 27)},
    2027: {"ramadan": date(2027, 2, 8), "ramadan_eid": date(2027, 3, 10), "kurban_eid": date(2027, 5, 16)},
    2028: {"ramadan": date(2028, 1, 28), "ramadan_eid": date(2028, 2, 27), "kurban_eid": date(2028, 5, 5)},
    2029: {"ramadan": date(2029, 1, 16), "ramadan_eid": date(2029, 2, 14), "kurban_eid": date(2029, 4, 24)},
    2030: {"ramadan": date(2030, 1, 5), "ramadan_eid": date(2030, 2, 4), "kurban_eid": date(2030, 4, 13)},
}
BUILTIN_CODES = [b[0] for b in BUILTIN]


def ensure_year(year: int) -> int:
    """Shu yil uchun tizim bayramlarini qo'shadi (bir marta — egasi o'chirgani qayta paydo bo'lmaydi)."""
    if Holiday.objects.filter(code__in=BUILTIN_CODES, date__year=year).exists():
        return 0
    n = 0
    for code, name, md, days, kind, uplift, prep, note in BUILTIN:
        if md:
            d, approx = date(year, *md), False
        else:
            d, approx = MOVABLE.get(year, {}).get(code), True
            if d is None:
                continue
        Holiday.objects.create(code=code, name=name, date=d, days=days, kind=kind, uplift_percent=uplift,
                               prep_days=prep, is_approx=approx, note=note)
        n += 1
    return n


def ensure_holidays() -> int:
    y = timezone.localdate().year
    return ensure_year(y) + ensure_year(y + 1)


# ------------------------------------------------------------------ savdo tarixi
def _paid_orders():
    from modules.pos.models import Order, OrderStatus
    return Order.objects.filter(status=OrderStatus.PAID)


def daily_revenue(start: date, end: date) -> dict[date, int]:
    rows = (_paid_orders().filter(paid_at__date__gte=start, paid_at__date__lte=end)
            .annotate(d=TruncDate("paid_at")).values("d").annotate(r=Sum("total"), n=Count("id")))
    return {r["d"]: int(r["r"] or 0) for r in rows}


def history_window(tenant) -> tuple[date, date, int]:
    """(boshi, oxiri, kunlar soni) — kechagacha, oxirgi N kun, lekin birinchi sotuvdan oldin emas."""
    n = max(7, int(weather.setting(tenant, "history_days", 28)))
    end = timezone.localdate() - timedelta(days=1)
    start = end - timedelta(days=n - 1)
    first = _paid_orders().order_by("paid_at").values_list("paid_at", flat=True).first()
    if first:
        fd = timezone.localtime(first).date()
        if fd > start:
            start = fd
    days = max(1, (end - start).days + 1)
    return start, end, days


def weekday_factors(rev: dict[date, int], start: date, end: date) -> list[float]:
    """Hafta kunlari ko'paytuvchisi (Du=0 … Ya=6). 14 kundan kam tarix bo'lsa — hammasi 1."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if len(days) < 14:
        return [1.0] * 7
    total = sum(rev.get(d, 0) for d in days) / len(days)
    if not total:
        return [1.0] * 7
    out = []
    for wd in range(7):
        ds = [d for d in days if d.weekday() == wd]
        avg = sum(rev.get(d, 0) for d in ds) / len(ds) if ds else total
        out.append(round(max(0.3, min(2.5, avg / total)), 3))
    return out


def history_uplift(h: Holiday) -> int | None:
    """Bayram kunlaridagi haqiqiy savdo ↔ undan oldingi 4 haftaning xuddi shu hafta kunlari. Ma'lumot yo'q → None."""
    yesterday = timezone.localdate() - timedelta(days=1)
    days = [h.date + timedelta(days=i) for i in range(max(1, h.days)) if h.date + timedelta(days=i) <= yesterday]
    if not days:
        return None
    rev = daily_revenue(days[0] - timedelta(days=28), days[-1])
    if not any(rev.get(d) for d in days):
        return None
    cur = sum(rev.get(d, 0) for d in days) / len(days)
    base_vals = [rev.get(d - timedelta(days=7 * k), 0) for d in days for k in range(1, 5)]
    base_vals = [v for v in base_vals if v]
    if not base_vals:
        return None
    base = sum(base_vals) / len(base_vals)
    return round(100 * (cur - base) / base)


def previous_of(h: Holiday) -> Holiday | None:
    if not h.code:
        return None
    return Holiday.objects.filter(code=h.code, date__lt=h.date).order_by("-date").first()


# ------------------------------------------------------------------ prognoz va xarid rejasi
def _holiday_factor(d: date, holidays: list[Holiday]) -> tuple[float, Holiday | None]:
    best, hh = 0, None
    for h in holidays:
        if h.is_active and h.covers(d) and (hh is None or abs(h.uplift_percent) > abs(best)):
            best, hh = h.uplift_percent, h
    return 1 + best / 100, hh


def _round_up(qty: float, unit: str) -> float:
    if qty <= 0:
        return 0.0
    if unit == "dona":
        return float(math.ceil(qty - 1e-9))
    return math.ceil(qty * 2 - 1e-9) / 2          # kg / l — 0,5 ga yaxlitlanadi


def plan(tenant, *, start: date | None = None, end: date | None = None, holiday: Holiday | None = None) -> dict:
    """[start, end] oralig'i uchun sotuv prognozi va xomashyo xarid rejasi."""
    from modules.catalog.models import Product
    from modules.inventory.models import SUB_UNIT, Ingredient, Recipe, Unit
    from modules.pos.models import OrderItem

    today = timezone.localdate()
    start = start or today
    if holiday is not None:   # uzun mavsum (Ramazon) — faqat birinchi haftasi uchun xarid
        end = min(holiday.end, max(start, holiday.date) + timedelta(days=6))
    end = end or start + timedelta(days=6)
    if end < start:
        end = start
    hs, he, hdays = history_window(tenant)
    rev = daily_revenue(hs, he)
    avg_rev = sum(rev.values()) / hdays if hdays else 0
    wf = weekday_factors(rev, hs, he)
    holidays = list(Holiday.objects.filter(is_active=True, date__lte=end, date__gte=start - timedelta(days=40)))
    wx = {w.date: w for w in weather.forecast_days(tenant, days=16)}

    # kunlar bo'yicha ko'paytuvchi
    days_out, total_factor, holiday_factor_sum = [], 0.0, 0.0
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        hf, hh = _holiday_factor(d, holidays)
        wfac = weather.factor(wx.get(d), tenant)
        f = wf[d.weekday()] * hf * wfac
        total_factor += f
        if hh is not None:
            holiday_factor_sum += f
        days_out.append({"date": d.isoformat(), "factor": round(f, 2), "holiday": str(hh) if hh else None,
                         "weather": weather.describe(wx[d].code)[0] if d in wx else None,
                         "revenue": int(avg_rev * f)})

    # taomlar kunlik sotuvi
    rates: dict[int, float] = {}
    for r in (OrderItem.objects.filter(order__in=_paid_orders().filter(paid_at__date__gte=hs, paid_at__date__lte=he),
                                       product_id__isnull=False)
              .values("product_id").annotate(q=Sum("qty"))):
        rates[r["product_id"]] = float(r["q"] or 0) / hdays

    # xomashyo ehtiyoji
    need: dict[int, float] = defaultdict(float)
    for rc in Recipe.objects.filter(product_id__in=rates.keys()).prefetch_related("lines__ingredient"):
        portions = rates[rc.product_id] * total_factor / float(rc.yield_qty or 1)
        for ln in rc.lines.all():
            per = float(ln.qty * SUB_UNIT[Unit(ln.ingredient.unit)][1] * (1 + ln.waste_percent / 100))
            need[ln.ingredient_id] += per * portions

    lines, total_cost = [], 0
    for ing in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True).select_related("supplier"):
        n = need.get(ing.pk, 0.0)
        if n <= 0 and not ing.is_low:
            continue
        stock, mn = float(ing.stock), float(ing.min_stock)
        buy = _round_up(n + mn - stock, ing.unit)
        cost = int(Decimal(str(buy)) * ing.price)
        total_cost += cost
        lines.append({"ingredient_id": ing.pk, "name": ing.name, "category": ing.category, "unit": ing.unit,
                      "stock": round(stock, 3), "min_stock": round(mn, 3), "need": round(n, 3), "buy": buy,
                      "price": float(ing.price), "cost": cost, "supplier_id": ing.supplier_id,
                      "supplier": ing.supplier.name if ing.supplier_id else None,
                      "days_left": round(stock / (n / len(days_out)), 1) if n > 0 else None})
    lines.sort(key=lambda x: (-(x["buy"] > 0), -x["cost"]))
    sup: dict[str, dict] = {}
    for ln in lines:
        if ln["buy"] > 0:
            k = ln["supplier"] or "Bozor / boshqa"
            s = sup.setdefault(k, {"name": k, "supplier_id": ln["supplier_id"], "count": 0, "total": 0})
            s["count"] += 1
            s["total"] += ln["cost"]

    # eng ko'p ketadigan taomlar (bayram kunlarida yoki butun davrda)
    pf = holiday_factor_sum if holiday is not None and holiday_factor_sum else total_factor
    names = {p.pk: p.name for p in Product.objects.filter(pk__in=rates.keys())}
    products = sorted(({"product_id": pid, "name": names.get(pid, {}), "qty": round(r * pf)} for pid, r in rates.items()),
                      key=lambda x: -x["qty"])[:8]

    lead = int(weather.setting(tenant, "purchase_lead_days", 2))
    return {
        "start": start.isoformat(), "end": end.isoformat(), "days": len(days_out),
        "holiday": holiday_out(holiday) if holiday else None,
        "history": {"start": hs.isoformat(), "end": he.isoformat(), "days": hdays, "avg_revenue": int(avg_rev),
                    "enough": bool(rates) and hdays >= 7},
        "weekday_factors": wf,
        "daily": days_out,
        "revenue_forecast": int(avg_rev * total_factor),
        "revenue_normal": int(avg_rev * len(days_out)),
        "lines": lines,
        "short_count": sum(1 for ln in lines if ln["buy"] > 0),
        "total_cost": total_cost,
        "suppliers": sorted(sup.values(), key=lambda s: -s["total"]),
        "products": products,
        "buy_by": (max(today, (holiday.date if holiday else start) - timedelta(days=lead))).isoformat(),
    }


# ------------------------------------------------------------------ yaqin bayramlar va ogohlantirishlar
def holiday_out(h: Holiday, *, with_history: bool = False) -> dict:
    today = timezone.localdate()
    d = {"id": h.pk, "code": h.code, "name": h.name, "date": h.date.isoformat(), "end": h.end.isoformat(), "days": h.days,
         "kind": h.kind, "kind_label": HolidayKind(h.kind).label, "uplift_percent": h.uplift_percent, "prep_days": h.prep_days,
         "is_approx": h.is_approx, "is_active": h.is_active, "note": h.note, "builtin": bool(h.code),
         "days_left": (h.date - today).days, "is_now": h.covers(today), "is_past": h.end < today}
    if with_history:
        d["actual_percent"] = history_uplift(h) if h.date < today else None
        prev = previous_of(h)
        d["last_year_percent"] = history_uplift(prev) if prev else None
    return d


def upcoming(limit: int = 6, horizon_days: int = 120) -> list[Holiday]:
    today = timezone.localdate()
    qs = Holiday.objects.filter(is_active=True, date__lte=today + timedelta(days=horizon_days),
                                date__gte=today - timedelta(days=40)).order_by("date")
    return [h for h in qs if h.end >= today][:limit]


def alerts(tenant, *, notify: bool = True) -> list[dict]:
    """Tayyorgarlik oynasidagi bayramlar (≤ prep_days kun qoldi yoki bugun bayram) + xarid rejasining qisqachasi."""
    ensure_holidays()
    today = timezone.localdate()
    out = []
    for h in upcoming(limit=10, horizon_days=45):
        left = (h.date - today).days
        if left > h.prep_days:
            continue
        p = plan(tenant, holiday=h)
        hol_rev = sum(x["revenue"] for x in p["daily"] if x["holiday"])
        a = {**holiday_out(h), "short_count": p["short_count"], "total_cost": p["total_cost"], "buy_by": p["buy_by"],
             "revenue_holiday": hol_rev, "top_short": [ln["name"].get("uz") for ln in p["lines"] if ln["buy"] > 0][:4],
             "message": _message(h, left, p)}
        out.append(a)
        if notify and h.notified_at is None and left >= 0:
            h.notified_at = timezone.now()
            h.save(update_fields=["notified_at", "updated_at"])
            if weather.setting(tenant, "create_task", True):
                emit("forecast.holiday_soon", {"holiday_id": h.pk, "name": str(h), "date": h.date.strftime("%d.%m.%Y"),
                                               "buy_by": date.fromisoformat(p["buy_by"]).strftime("%d.%m.%Y"),
                                               "short_count": p["short_count"], "total_cost": p["total_cost"],
                                               "items": a["top_short"]}, tenant=tenant)
    return out


def _message(h: Holiday, left: int, p: dict) -> str:
    when = "bugun" if left <= 0 else "ertaga" if left == 1 else f"{left} kundan keyin"
    s = f"{h} — {when}. Kutilayotgan savdo {'+' if h.uplift_percent >= 0 else ''}{h.uplift_percent}%."
    if p["short_count"]:
        s += f" {p['short_count']} ta xomashyo yetmaydi — xarid taxminan {p['total_cost']:,} so'm.".replace(",", " ")
    else:
        s += " Ombor yetarli."
    return s
