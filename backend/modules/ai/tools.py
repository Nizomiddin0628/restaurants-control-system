"""
AI Kotib asboblari — AI raqamlarni o'zi to'qimaydi, faqat shu funksiyalar orqali tizimdan oladi.
Hammasi faqat o'qiydi. Yagona o'zgartiruvchi amal — `create_task` (foydalanuvchi buyruqni tasdiqlagandan keyin).
Har asbob foydalanuvchining filial doirasida ishlaydi (menejer — o'z filiali, egasi — hammasi).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from . import report

log = logging.getLogger("ai")


def _d(s, default: date) -> date:
    try:
        return date.fromisoformat(str(s)[:10]) if s else default
    except ValueError:
        return default


def _rng(args: dict) -> tuple[date, date]:
    today = timezone.localdate()
    a = _d(args.get("date_from"), today - timedelta(days=1))
    b = _d(args.get("date_to"), a)
    if b < a:
        a, b = b, a
    return a, min(b, a + timedelta(days=366))


def _bf(qs, ctx, field="branch"):
    return report._bf(qs, ctx.branch_ids, field)


# ------------------------------------------------------------------ asboblar
def daily_report(ctx, args):
    """Tayyor kunlik hisobot ma'lumoti (kecha + bugun + muammolar + prognoz)."""
    d = _d(args.get("date"), timezone.localdate())
    return report.build(ctx.tenant, ctx.branch_ids, d)


def sales(ctx, args):
    from modules.pos.models import Order
    a, b = _rng(args)
    paid = _bf(Order.objects.filter(status="paid", paid_at__date__gte=a, paid_at__date__lte=b), ctx)
    agg = paid.aggregate(s=Sum("total"), c=Sum("cost_total"), n=Count("id"))
    rev, n = int(agg["s"] or 0), int(agg["n"] or 0)
    days = [{"date": r["paid_at__date"].isoformat(), "revenue": int(r["s"] or 0), "orders": r["n"]}
            for r in paid.values("paid_at__date").annotate(s=Sum("total"), n=Count("id")).order_by("paid_at__date")]
    return {"from": a.isoformat(), "to": b.isoformat(), "revenue": rev, "orders": n, "avg_check": rev // n if n else 0,
            "food_cost_percent": round(100 * int(agg["c"] or 0) / rev, 1) if rev else None,
            "by_day": days[-31:],
            "by_branch": [{"branch": r["branch__name"] or "—", "revenue": int(r["s"] or 0), "orders": r["n"]}
                          for r in paid.values("branch__name").annotate(s=Sum("total"), n=Count("id")).order_by("-s")],
            "by_type": {report.TYPE_UZ.get(r["type"], r["type"]): {"orders": r["n"], "revenue": int(r["s"] or 0)}
                        for r in paid.values("type").annotate(n=Count("id"), s=Sum("total"))},
            "by_payment": {r["payment_method"] or "—": int(r["s"] or 0) for r in paid.values("payment_method").annotate(s=Sum("total"))},
            "cancelled": _bf(Order.objects.filter(status="cancelled", created_at__date__gte=a, created_at__date__lte=b), ctx).count()}


def top_products(ctx, args):
    from modules.pos.models import OrderItem
    a, b = _rng(args)
    limit = max(1, min(int(args.get("limit") or 10), 30))
    qs = _bf(OrderItem.objects.filter(order__status="paid", order__paid_at__date__gte=a, order__paid_at__date__lte=b), ctx, "order__branch")
    rows = qs.values("name").annotate(q=Sum("qty"), s=Sum(F("qty") * F("price")))
    rows = rows.order_by("q" if args.get("order") == "least" else "-q")[:limit]
    return {"from": a.isoformat(), "to": b.isoformat(),
            "items": [{"name": r["name"], "qty": int(r["q"] or 0), "revenue": int(r["s"] or 0)} for r in rows]}


def stock(ctx, args):
    from modules.inventory.models import Ingredient
    q = (args.get("search") or "").strip().lower()
    ings = list(Ingredient.objects.filter(deleted_at__isnull=True, is_active=True))
    if q:
        ings = [i for i in ings if q in str(i).lower()]
    only_low = bool(args.get("only_low")) or not q
    rows = [{"name": str(i), "stock": float(i.stock), "min": float(i.min_stock), "unit": i.unit, "price": float(i.price), "low": i.is_low}
            for i in ings if (i.is_low or not only_low)]
    return {"items": rows[:40], "low_count": sum(1 for i in ings if i.is_low),
            "stock_value": int(sum(float(i.stock) * float(i.price) for i in ings if i.stock > 0))}


def tasks(ctx, args):
    from modules.tasks.models import ColumnKind, Task
    now = timezone.now()
    qs = _bf(Task.objects.live().filter(is_archived=False), ctx).select_related("assignee", "column")
    st = args.get("status") or "open"
    if st == "overdue":
        qs = qs.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).filter(due_at__lt=now)
    elif st == "done":
        a, b = _rng(args)
        qs = qs.filter(done_at__date__gte=a, done_at__date__lte=b)
    elif st == "today":
        qs = qs.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).filter(due_at__date=timezone.localdate())
    else:
        qs = qs.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED])
    who = (args.get("assignee") or "").strip()
    if who:
        qs = qs.filter(Q(assignee__full_name__icontains=who) | Q(assignee__phone__icontains=who))
    rows = [{"n": t.number, "title": t.title, "status": (t.column.name or {}).get("uz", t.column.kind), "priority": t.priority,
             "assignee": (t.assignee.full_name or t.assignee.phone) if t.assignee_id else None,
             "due": timezone.localtime(t.due_at).strftime("%d.%m.%Y %H:%M") if t.due_at else None,
             "overdue": bool(t.due_at and t.due_at < now and t.column.kind not in (ColumnKind.DONE, ColumnKind.CANCELLED))}
            for t in qs.order_by("due_at")[:30]]
    return {"count": qs.count(), "items": rows}


def staff(ctx, args):
    from modules.hr.models import Attendance, Employee, ShiftPlan
    a, b = _rng({**args, "date_from": args.get("date_from") or timezone.localdate().isoformat()})
    plans = _bf(ShiftPlan.objects.filter(date__gte=a, date__lte=b), ctx).select_related("employee__user", "branch")
    att = _bf(Attendance.objects.filter(check_in__date__gte=a, check_in__date__lte=b), ctx).select_related("employee__user")
    who = (args.get("name") or "").strip().lower()
    nm = lambda e: e.user.full_name or e.user.phone  # noqa: E731
    return {"from": a.isoformat(), "to": b.isoformat(),
            "employees": Employee.objects.filter(is_active=True).count(),
            "shifts": [{"date": s.date.isoformat(), "name": nm(s.employee), "start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"),
                        "branch": s.branch.name if s.branch_id else ""} for s in plans if not who or who in nm(s.employee).lower()][:40],
            "attendance": [{"name": nm(x.employee), "in": timezone.localtime(x.check_in).strftime("%d.%m %H:%M"),
                            "out": timezone.localtime(x.check_out).strftime("%H:%M") if x.check_out else None, "late_min": x.late_minutes}
                           for x in att if not who or who in nm(x.employee).lower()][:40]}


def bookings(ctx, args):
    from modules.reservations.models import Reservation
    a, b = _rng({**args, "date_from": args.get("date_from") or timezone.localdate().isoformat()})
    qs = _bf(Reservation.objects.filter(starts_at__date__gte=a, starts_at__date__lte=b), ctx).select_related("table").order_by("starts_at")
    return {"items": [{"at": timezone.localtime(r.starts_at).strftime("%d.%m %H:%M"), "name": r.guest_name, "phone": r.phone, "guests": r.guests,
                       "table": r.table.number if r.table_id else None, "status": r.status, "occasion": r.occasion} for r in qs[:40]]}


def supply(ctx, args):
    from modules.inventory.models import Supplier
    from modules.procurement.models import Order as PO
    from modules.procurement.services import debts
    qs = _bf(PO.objects.exclude(status__in=["received", "cancelled"]), ctx).select_related("supplier").order_by("expected_date")
    d = debts()
    names = dict(Supplier.objects.filter(pk__in=d.keys()).values_list("id", "name"))
    return {"open_orders": [{"n": o.number, "supplier": o.supplier.name, "status": o.status, "expected": o.expected_date.isoformat() if o.expected_date else None,
                             "total": o.total} for o in qs[:20]],
            "debts": [{"supplier": names.get(k, "—"), "debt": v["debt"], "overdue": v["overdue"], "oldest": v["oldest"]} for k, v in d.items() if v["debt"]]}


def forecast(ctx, args):
    from modules.forecast import services, weather
    days = max(1, min(int(args.get("days") or 1), 14))
    today = timezone.localdate()
    p = services.plan(ctx.tenant, start=today, end=today + timedelta(days=days - 1))
    wx = []
    try:
        wx = [weather.day_out(w, ctx.tenant) for w in weather.forecast_days(ctx.tenant, days)]
    except Exception:
        pass
    return {"days": p.get("daily"), "revenue_forecast": p.get("revenue_forecast"), "revenue_normal": p.get("revenue_normal"),
            "buy": [{"name": (ln["name"] or {}).get("uz") if isinstance(ln["name"], dict) else ln["name"], "buy": ln["buy"], "unit": ln["unit"], "cost": ln["cost"]}
                    for ln in p.get("lines", []) if ln.get("buy")][:20],
            "buy_total": p.get("total_cost"), "holiday": (p.get("holiday") or {}).get("name"),
            "weather": [{"date": w.get("date"), "label": w.get("label"), "t_max": w.get("t_max"), "t_min": w.get("t_min")} for w in wx]}


def finance(ctx, args):
    from modules.finance.models import Expense
    from modules.pos.models import Order
    today = timezone.localdate()
    a = _d(args.get("date_from"), today.replace(day=1))
    b = _d(args.get("date_to"), today)
    agg = _bf(Order.objects.filter(status="paid", paid_at__date__gte=a, paid_at__date__lte=b), ctx).aggregate(s=Sum("total"), c=Sum("cost_total"))
    rev, cost = int(agg["s"] or 0), int(agg["c"] or 0)
    ex = _bf(Expense.objects.filter(date__gte=a, date__lte=b), ctx)
    exp = int(ex.aggregate(s=Sum("amount"))["s"] or 0)
    return {"from": a.isoformat(), "to": b.isoformat(), "revenue": rev, "food_cost": cost, "expenses": exp, "gross_profit": rev - cost - exp,
            "expenses_by_category": {r["category__name"]: int(r["s"] or 0) for r in ex.values("category__name").annotate(s=Sum("amount")).order_by("-s")}}


def find_employee(name: str):
    """Ism bo'yicha xodim (User): to'liq, qisman yoki ism/familiya bo'yicha."""
    from core.models import User
    name = (name or "").strip()
    if not name:
        return None
    qs = User.objects.filter(is_active=True, memberships__is_active=True).distinct()
    hit = list(qs.filter(full_name__iexact=name)) or list(qs.filter(full_name__icontains=name))
    if not hit:
        # o'zbekcha qo'shimchalar: «Rustamga», «Nodiraning», «Jasurdan» → Rustam, Nodira, Jasur (faqat birinchi so'z, so'z boshidan)
        w = name.split()[0]
        stems = [w] + [w[: -len(sf)] for sf in ("ning", "dan", "ga", "ka", "qa", "ni", "da") if w.lower().endswith(sf) and len(w) - len(sf) >= 3]
        for st in stems:
            hit = [u for u in qs.filter(full_name__icontains=st) if any(p.lower().startswith(st.lower()) for p in (u.full_name or "").split())]
            if hit:
                break
    return hit[0] if len(hit) == 1 else (hit if hit else None)


def create_task(ctx, args):
    from modules.tasks import services as ts
    from modules.tasks.models import Priority
    title = (args.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "vazifa nomi yo'q"}
    who = find_employee(args.get("assignee") or "")
    if isinstance(who, list):
        return {"ok": False, "error": "bir nechta xodim topildi, aniqlashtiring", "candidates": [u.full_name for u in who[:5]]}
    if args.get("assignee") and who is None:
        return {"ok": False, "error": f"«{args['assignee']}» ismli xodim topilmadi"}
    due = None
    if args.get("due"):
        try:
            due = datetime.fromisoformat(str(args["due"]).replace("Z", ""))
            if timezone.is_naive(due):
                due = timezone.make_aware(due)
        except ValueError:
            due = None
    pr = args.get("priority") if args.get("priority") in Priority.values else None
    branch = None
    if ctx.branch_ids and len(ctx.branch_ids) == 1:
        from core.models import Branch
        branch = Branch.objects.filter(pk=ctx.branch_ids[0]).first()
    t = ts.create_task(SimpleNamespace(tenant=ctx.tenant, auth=ctx.user), title=title[:180], description=(args.get("description") or "")[:2000],
                       assignee=who, reporter=ctx.user, due_at=due, priority=pr, branch=branch, requires_proof=False)
    return {"ok": True, "number": t.number, "title": t.title, "assignee": (who.full_name if who else None),
            "due": timezone.localtime(due).strftime("%d.%m.%Y %H:%M") if due else None}


def make_chart(ctx, args):
    """Diagramma: AI raqamlarni beradi, server PNG chizadi (javob bilan birga yuboriladi). Bitta javobda ko'pi bilan 2 ta."""
    from . import charts
    lst = getattr(ctx, "charts", None)
    if lst is None:
        return {"ok": False, "error": "bu kanalda diagramma yuborib bo'lmaydi"}
    if len(lst) >= 2:
        return {"ok": False, "error": "bitta javobda 2 tadan ortiq diagramma kerak emas"}
    try:
        spec = charts.validate(args or {})
        png = charts.render(spec)
    except Exception as e:
        return {"ok": False, "error": f"diagramma chizilmadi: {e}"}
    lst.append({"title": spec["title"], "png": png})
    return {"ok": True, "note": "Diagramma foydalanuvchiga rasm sifatida yuboriladi. Matnda uni qisqa izohla, raqamlarni takrorlama."}


# ------------------------------------------------------------------ Gemini uchun e'lonlar
_D = {"type": "string", "description": "sana YYYY-MM-DD"}
DECLS = [
    {"name": "daily_report", "description": "Kunlik to'liq hisobot: kechagi savdo, muammolar (tugayotgan xomashyo, kechikkan vazifalar, kechikkan xodimlar, qarz), bugungi smena, bron, ta'minot, prognoz. Umumiy «qanday ketyapti», «bugun nima qilish kerak» savollari uchun.",
     "parameters": {"type": "object", "properties": {"date": _D}}},
    {"name": "sales", "description": "Savdo: tushum, cheklar, o'rtacha chek, food cost, kunlar/filiallar/turlar/to'lov usullari bo'yicha, bekor qilinganlar. Istalgan davr uchun.",
     "parameters": {"type": "object", "properties": {"date_from": _D, "date_to": _D}}},
    {"name": "top_products", "description": "Eng ko'p (yoki eng kam) sotilgan taomlar davr bo'yicha.",
     "parameters": {"type": "object", "properties": {"date_from": _D, "date_to": _D, "limit": {"type": "integer"}, "order": {"type": "string", "enum": ["most", "least"]}}}},
    {"name": "stock", "description": "Ombor: tugayotgan xomashyo, qoldiq, ombor qiymati. search — nom bo'yicha qidirish.",
     "parameters": {"type": "object", "properties": {"search": {"type": "string"}, "only_low": {"type": "boolean"}}}},
    {"name": "tasks", "description": "Vazifalar: ochiq, kechikkan, bugungi yoki bajarilgan (davr bilan), bajaruvchi ismi bo'yicha filtr.",
     "parameters": {"type": "object", "properties": {"status": {"type": "string", "enum": ["open", "overdue", "today", "done"]}, "assignee": {"type": "string"}, "date_from": _D, "date_to": _D}}},
    {"name": "staff", "description": "Xodimlar: smena jadvali va davomat (keldi/ketdi, kechikish daqiqasi) davr bo'yicha; name — xodim ismi.",
     "parameters": {"type": "object", "properties": {"date_from": _D, "date_to": _D, "name": {"type": "string"}}}},
    {"name": "bookings", "description": "Stol bronlari davr bo'yicha (standart — bugun).",
     "parameters": {"type": "object", "properties": {"date_from": _D, "date_to": _D}}},
    {"name": "supply", "description": "Zakup: ta'minotchilarga ochiq buyurtmalar (qachon keladi) va qarzlar.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "forecast", "description": "Prognoz: kelgusi kunlar savdosi, bayram, ob-havo va nima xarid qilish kerak.",
     "parameters": {"type": "object", "properties": {"days": {"type": "integer", "description": "1–14"}}}},
    {"name": "finance", "description": "Moliya: davr bo'yicha tushum, tannarx, xarajatlar (turlari bilan), yalpi foyda. Standart — shu oy.",
     "parameters": {"type": "object", "properties": {"date_from": _D, "date_to": _D}}},
    {"name": "make_chart", "description": "Diagramma (rasm) chizish. FAQAT foydali bo'lganda: dinamika (kunlar bo'yicha savdo — line/bar), taqqoslash (filiallar, "
     "bu hafta va o'tgan hafta — bar), reyting (top taomlar — hbar), ulush (to'lov turlari — pie) yoki foydalanuvchi grafik so'rasa. "
     "Oddiy bitta raqamli savolga chizma. Raqamlarni avval boshqa asbobdan ol, o'zingdan to'qima. labels va har series.values uzunligi bir xil.",
     "parameters": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["bar", "hbar", "line", "pie"]}, "title": {"type": "string"},
         "unit": {"type": "string", "description": "masalan so'm, ta, %"},
         "labels": {"type": "array", "items": {"type": "string"}},
         "series": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}}}}}},
         "required": ["kind", "title", "labels", "series"]}},
    {"name": "create_task", "description": "Xodimga vazifa berish (faqat foydalanuvchi aniq buyursa). assignee — xodim ismi, due — muddat ISO formatda (YYYY-MM-DDTHH:MM), priority: urgent|high|normal|low.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "assignee": {"type": "string"}, "due": {"type": "string"},
                                                     "priority": {"type": "string", "enum": ["urgent", "high", "normal", "low"]}, "description": {"type": "string"}},
                    "required": ["title"]}},
]
FUNCS = {"daily_report": daily_report, "sales": sales, "top_products": top_products, "stock": stock, "tasks": tasks, "staff": staff,
         "bookings": bookings, "supply": supply, "forecast": forecast, "finance": finance, "create_task": create_task, "make_chart": make_chart}
NEEDS = {"sales": "pos", "top_products": "pos", "stock": "inventory", "tasks": "tasks", "staff": "hr", "bookings": "reservations",
         "supply": "procurement", "forecast": "forecast", "finance": "finance", "create_task": "tasks"}


def available(tenant) -> list[dict]:
    on = set(tenant.enabled_modules or [])
    return [d for d in DECLS if NEEDS.get(d["name"]) is None or NEEDS[d["name"]] in on]


def run(ctx, name: str, args: dict) -> dict:
    fn = FUNCS.get(name)
    if not fn:
        return {"error": f"noma'lum asbob: {name}"}
    if name == "create_task" and not ctx.user.has_perm_code("tasks.create"):
        return {"ok": False, "error": "sizda vazifa yaratish ruxsati yo'q"}
    try:
        return fn(ctx, args or {})
    except Exception as e:
        log.exception("ai asbob %s", name)
        return {"error": f"ma'lumot olinmadi: {type(e).__name__}"}
