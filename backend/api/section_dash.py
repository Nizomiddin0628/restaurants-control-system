"""
Bo'lim dashboardi — /api/v1/dashboard/section/{code}?days=1|7|30
Har bo'lim uchun o'z grafiklari va ro'yxatlari (vidjetlar). Frontend ularni bitta umumiy ko'rinishda chizadi.

Vidjet turlari:
  chart  — {kind: bars|line, points: [{label, value}], money}      — dinamika
  rank   — {rows: [{label, value, display, sub}]}                   — reyting (gorizontal chiziqlar)
  list   — {rows: [{title, sub, right, tone, route}], empty}        — ro'yxat
  donut  — {items: [{key, label, value, color}]}                   — ulushlar
  table  — {cols: [...], rows: [[...]]}                            — jadval
Har biri: title, sub, route (bosilganda ochiladigan sahifa), wide (ikki ustunni egallaydi).
Modul o'chiq yoki ruxsat yo'q bo'lsa — o'sha vidjet chiqmaydi. Bir vidjetdagi xato qolganlarini to'xtatmaydi.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from django.db.models import Count, F, Sum
from django.utils import timezone

log = logging.getLogger(__name__)
WD = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
COLORS = ["#2563EB", "#EA580C", "#059669", "#DB2777", "#7C3AED", "#0891B2", "#CA8A04", "#64748B"]


def _m(v) -> str:
    v = int(v or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",") + " mln"
    return f"{v:,}".replace(",", " ")


def _d(x) -> str:
    return f"{x:%d.%m}"


def _days(today, n):
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def section_dashboard(request, code: str, days: int = 7, branch_id: int | None = None) -> dict:
    from .branchf import make
    t, u = request.tenant, request.auth
    S, L = make(branch_id)
    on = set(t.enabled_modules or [])
    can = u.has_perm_code
    today = timezone.localdate()
    now = timezone.localtime()
    days = days if days in (1, 7, 30) else 7
    since = today - timedelta(days=days - 1)
    period = {1: "bugun", 7: "7 kun", 30: "30 kun"}[days]
    W: list[dict] = []

    def add(fn):
        try:
            w = fn()
            if w:
                W.extend(w if isinstance(w, list) else [w])
        except Exception:
            log.exception("bo'lim dashboardi: %s", getattr(fn, "__name__", "?"))

    def paid():
        from modules.pos.models import Order
        return S(Order.objects.filter(status="paid"))

    def daily_revenue(n=14):
        qs = paid().filter(paid_at__date__gte=today - timedelta(days=n - 1)).values("paid_at__date").annotate(s=Sum("total"))
        by = {r["paid_at__date"]: int(r["s"] or 0) for r in qs}
        return [{"label": f"{WD[d.weekday()]} {d:%d}", "value": by.get(d, 0)} for d in _days(today, n)]

    # ================================================================== SAVDO VA XIZMAT
    if code == "sales":
        if "pos" in on:
            def hourly():
                qs = paid().filter(paid_at__date=today).values("paid_at__hour").annotate(s=Sum("total"))
                by = {r["paid_at__hour"]: int(r["s"] or 0) for r in qs}
                last = paid().filter(paid_at__date=today - timedelta(days=7)).aggregate(s=Sum("total"))["s"] or 0
                return {"type": "chart", "kind": "bars", "money": True, "title": "Bugun soatlar bo'yicha savdo",
                        "sub": f"o'tgan hafta shu kuni jami: {_m(last)} so'm", "points": [{"label": f"{h}:00", "value": by.get(h, 0)} for h in range(9, 24)],
                        "route": "/reports", "wide": True}
            add(hourly)
            add(lambda: {"type": "chart", "kind": "line", "money": True, "title": "So'nggi 14 kun savdosi", "sub": "kunlik tushum",
                         "points": daily_revenue(14), "route": "/reports", "wide": True})

            def types():
                q = paid().filter(paid_at__date__gte=since).values("type").annotate(n=Count("id"))
                lab = {"dine_in": "Zalda", "takeaway": "Olib ketish", "delivery": "Yetkazish"}
                return {"type": "donut", "title": "Buyurtma turlari", "sub": period, "route": "/reports",
                        "items": [{"key": r["type"], "label": lab.get(r["type"], r["type"]), "value": r["n"], "color": COLORS[i]} for i, r in enumerate(q.order_by("-n"))]}
            add(types)

            def pay():
                q = paid().filter(paid_at__date__gte=since).values("payment_method").annotate(s=Sum("total")).order_by("-s")
                lab = {"cash": "Naqd", "card": "Karta", "click": "Click", "payme": "Payme", "uzum": "Uzum", "transfer": "O'tkazma"}
                rows = [{"label": lab.get(r["payment_method"], r["payment_method"] or "—"), "value": int(r["s"] or 0), "display": _m(r["s"])} for r in q]
                return {"type": "rank", "title": "To'lov usullari", "sub": period, "rows": rows, "route": "/reports"}
            add(pay)

            def branches():
                from core.models import Branch
                q = {r["branch_id"]: r for r in paid().filter(paid_at__date__gte=since).values("branch_id").annotate(s=Sum("total"), n=Count("id"), c=Sum("cost_total"))}
                rows = []
                for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True, **({"pk": branch_id} if branch_id else {})):
                    r = q.get(b.pk, {"s": 0, "n": 0, "c": 0})
                    s, n = int(r["s"] or 0), r["n"] or 0
                    rows.append([b.name, _m(s), n, _m(s // n if n else 0), f"{round(100 * (r['c'] or 0) / s, 1) if s else 0}%"])
                return {"type": "table", "title": "Filiallar", "sub": period, "cols": ["Filial", "Savdo", "Chek", "O'rtacha", "Food cost"], "rows": rows, "route": "/branches"}
            add(branches)
        if "kds" in on:
            def kitchen():
                from modules.kds.models import Ticket
                lab = {"new": ("Yangi", "warn"), "cooking": ("Tayyorlanmoqda", ""), "ready": ("Tayyor — olib chiqing", "ok")}
                rows = []
                for tk in S(Ticket.objects.exclude(status__in=["served", "cancelled"]), "order__branch").select_related("order").order_by("created_at")[:8]:
                    mins = int((now - tk.created_at).total_seconds() // 60)
                    o = tk.order
                    where = f"Stol {o.table_no}" if o.table_no else {"takeaway": "Olib ketish", "delivery": "Yetkazish"}.get(o.type, "")
                    rows.append({"title": f"#{o.number} · {where}", "sub": ", ".join(f"{i.name} ×{i.qty}" for i in o.items.all()[:3]),
                                 "right": f"{mins} daq", "tone": "bad" if mins > 20 else lab.get(tk.status, ("", ""))[1], "badge": lab.get(tk.status, (tk.status,))[0]})
                return {"type": "list", "title": "Oshxonada hozir", "sub": "faol buyurtmalar", "rows": rows, "empty": "Oshxona bo'sh", "route": "/kds"}
            add(kitchen)
        if "reservations" in on:
            def bookings():
                from modules.reservations.models import Reservation
                rows = [{"title": f"{timezone.localtime(r.starts_at):%H:%M} · {r.guest_name}", "sub": f"{r.guests} kishi" + (f" · {r.occasion}" if r.occasion else ""),
                         "right": f"Stol {r.table.number}" if r.table_id else "—", "tone": {"confirmed": "ok", "new": "warn", "seated": "ok"}.get(r.status, ""),
                         "badge": {"new": "Yangi", "confirmed": "Tasdiqlangan", "seated": "O'tirdi", "done": "Tugadi"}.get(r.status, r.status)}
                        for r in L(Reservation.objects.filter(starts_at__date=today).exclude(status__in=["cancelled", "no_show"])).select_related("table").order_by("starts_at")[:8]]
                return {"type": "list", "title": "Bugungi bronlar", "sub": "vaqt bo'yicha", "rows": rows, "empty": "Bugun bron yo'q", "route": "/reservations"}
            add(bookings)

    # ================================================================== MENYU VA MIJOZLAR
    elif code == "menu":
        if "pos" in on:
            def top():
                from modules.pos.models import OrderItem
                q = (S(OrderItem.objects.filter(order__status="paid", order__paid_at__date__gte=since), "order__branch").values("name")
                     .annotate(q=Sum("qty"), s=Sum(F("qty") * F("price")), c=Sum(F("qty") * F("cost"))).order_by("-s")[:10])
                rows = [{"label": r["name"], "value": int(r["s"] or 0), "display": _m(r["s"]),
                         "sub": f"{r['q']} porsiya · marja {round(100 * (1 - (r['c'] or 0) / r['s'])) if r['s'] else 0}%"} for r in q]
                return {"type": "rank", "title": "Eng ko'p daromad keltirgan taomlar", "sub": period, "rows": rows, "route": "/reports", "wide": True}
            add(top)

            def low():
                from modules.catalog.models import Product
                from modules.pos.models import OrderItem
                sold = dict(S(OrderItem.objects.filter(order__status="paid", order__paid_at__date__gte=today - timedelta(days=29)), "order__branch")
                            .values_list("product_id").annotate(q=Sum("qty")).values_list("product_id", "q"))
                ps = sorted(Product.objects.filter(deleted_at__isnull=True, is_active=True, in_stop_list=False), key=lambda p: sold.get(p.pk, 0))[:6]
                rows = [{"title": p.name.get("uz") or str(p), "sub": f"{_m(p.price)} so'm", "right": f"{sold.get(p.pk, 0)} ta / 30 kun",
                         "tone": "warn" if sold.get(p.pk, 0) < 10 else ""} for p in ps]
                return {"type": "list", "title": "Kam sotilayotgan taomlar", "sub": "menyudan olib tashlash yoki aksiya qilishni o'ylang", "rows": rows, "route": "/catalog"}
            add(low)

        if "catalog" in on:
            def stop():
                from modules.catalog.models import Product
                rows = [{"title": p.name.get("uz") or str(p), "sub": "stop-listda — sotilmayapti", "right": f"{_m(p.price)}", "tone": "bad"}
                        for p in Product.objects.filter(deleted_at__isnull=True, in_stop_list=True)[:6]]
                return {"type": "list", "title": "Stop-list", "sub": "hozir sotuvda yo'q", "rows": rows, "empty": "Hamma taom sotuvda", "route": "/catalog"}
            add(stop)


    # ================================================================== MIJOZLAR VA MARKETING
    elif code == "clients":
        if "pos" in on:
            def sources():
                lab = {"pos": "Kassa", "telegram": "Telegram", "site": "Sayt", "app": "Ilova"}
                q = paid().filter(paid_at__date__gte=since).values("source").annotate(n=Count("id")).order_by("-n")
                return {"type": "donut", "title": "Buyurtma manbalari", "sub": period, "route": "/telegram",
                        "items": [{"key": r["source"], "label": lab.get(r["source"], r["source"]), "value": r["n"], "color": COLORS[i]} for i, r in enumerate(q)]}
            add(sources)
        if "crm" in on and can("crm.view"):
            def newc():
                from modules.crm.models import Customer
                by = dict(Customer.objects.filter(created_at__date__gte=today - timedelta(days=29)).values_list("created_at__date").annotate(n=Count("id")).values_list("created_at__date", "n"))
                return {"type": "chart", "kind": "bars", "money": False, "title": "Yangi mijozlar", "sub": "30 kun, kunlik",
                        "points": [{"label": _d(d), "value": by.get(d, 0)} for d in _days(today, 30)], "route": "/crm"}
            add(newc)

            def vip():
                from modules.crm.models import Customer
                rows = [{"title": c.name or c.phone, "sub": f"{c.orders_count} ta xarid · bonus {_m(c.balance)}", "right": f"{_m(c.spent_total)} so'm",
                         "tone": "ok"} for c in Customer.objects.order_by("-spent_total")[:7]]
                return {"type": "list", "title": "Eng yaxshi mijozlar", "sub": "jami xarid bo'yicha", "rows": rows, "route": "/crm"}
            add(vip)

    # ================================================================== OMBOR VA XARID
    elif code == "stock":
        if "inventory" in on and can("inventory.view"):
            def low():
                from modules.inventory.models import Ingredient
                rows = []
                for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True, min_stock__gt=0):
                    r = float(i.stock) / float(i.min_stock)
                    if r < 1.6:
                        rows.append((r, {"title": str(i), "sub": f"qoldiq {float(i.stock):g} {i.unit} · min {float(i.min_stock):g}",
                                         "right": f"{round(r * 100)}%", "tone": "bad" if r < 0.5 else "warn" if r < 1 else ""}))
                rows.sort(key=lambda x: x[0])
                return {"type": "list", "title": "Tugab borayotgan xomashyo", "sub": "minimal qoldiqqa nisbatan", "rows": [r for _, r in rows[:8]],
                        "empty": "Hamma xomashyo yetarli ✓", "route": "/inventory"}
            add(low)

            def purchases():
                from modules.inventory.models import Purchase
                by = {r["date"]: int(r["s"] or 0) for r in L(Purchase.objects.filter(date__gte=today - timedelta(days=13))).values("date").annotate(s=Sum("total"))}
                return {"type": "chart", "kind": "bars", "money": True, "title": "Kirim (xarid) — 14 kun", "sub": "kunlik summa",
                        "points": [{"label": f"{WD[d.weekday()]} {d:%d}", "value": by.get(d, 0)} for d in _days(today, 14)], "route": "/inventory", "wide": True}
            add(purchases)

            def usage():
                from modules.inventory.models import StockMovement
                q = (L(StockMovement.objects.filter(kind="sale", at__date__gte=since)).values("ingredient__name", "ingredient__unit")
                     .annotate(q=Sum("qty"), v=Sum(F("qty") * F("unit_price"))).order_by("v")[:8])
                rows = [{"label": (r["ingredient__name"] or {}).get("uz", "—"), "value": -int(r["v"] or 0), "display": _m(-(r["v"] or 0)),
                         "sub": f"{-float(r['q'] or 0):.1f} {r['ingredient__unit']}"} for r in q]
                return {"type": "rank", "title": "Eng ko'p sarflangan xomashyo", "sub": f"{period}, tannarx bo'yicha", "rows": rows, "route": "/inventory"}
            add(usage)
        if "procurement" in on and can("procurement.view"):
            def orders():
                from modules.procurement.models import Order as PO
                lab = {"draft": "Qoralama", "sent": "Yuborildi", "confirmed": "Tasdiqlandi"}
                rows = [{"title": f"#{o.number} · {o.supplier.name}", "sub": f"kerak: {o.expected_date:%d.%m}" if o.expected_date else "",
                         "right": f"{_m(o.total)}", "badge": lab.get(o.status, o.status), "tone": "ok" if o.status == "confirmed" else ""}
                        for o in L(PO.objects.filter(status__in=["draft", "sent", "confirmed"])).select_related("supplier").order_by("expected_date")[:6]]
                return {"type": "list", "title": "Yo'ldagi buyurtmalar", "sub": "ta'minotchilardan", "rows": rows, "empty": "Ochiq buyurtma yo'q", "route": "/procurement?tab=orders"}
            add(orders)

            def debt():
                from modules.inventory.models import Supplier
                from modules.procurement.services import debts
                d = {k: v for k, v in debts().items() if v["debt"]}
                names = dict(Supplier.objects.filter(pk__in=d.keys()).values_list("id", "name"))
                rows = [{"title": names.get(k, "—"), "sub": f"eng eski: {v['oldest'] or '—'}", "right": _m(v["debt"]), "tone": "bad" if v["overdue"] else ""}
                        for k, v in sorted(d.items(), key=lambda x: -x[1]["debt"])[:6]]
                return {"type": "list", "title": "Ta'minotchilarga qarz", "sub": "muddati o'tgani qizil", "rows": rows, "empty": "Qarz yo'q", "route": "/procurement?tab=debts"}
            add(debt)

            def market():
                from modules.procurement.services import trip_stats
                s = trip_stats(since, today)
                rows = [{"label": k["label"], "value": k["amount"], "display": _m(k["amount"])} for k in s["by_kind"]]
                return {"type": "rank", "title": "Bozor xarajatlari", "sub": f"{period} · ulushi {s['overhead_percent'] or 0}%", "rows": rows, "route": "/market"}
            add(market)

    # ================================================================== XODIMLAR
    elif code == "team":
        if "hr" in on and can("hr.view"):
            def onshift():
                from modules.hr.models import Attendance
                rows = [{"title": a.employee.user.full_name or a.employee.user.phone, "sub": a.employee.position.name if a.employee.position_id else "",
                         "right": f"{timezone.localtime(a.check_in):%H:%M}" + (f" → {timezone.localtime(a.check_out):%H:%M}" if a.check_out else ""),
                         "badge": f"{a.late_minutes} daq kechikdi" if a.late_minutes else ("ishda" if not a.check_out else "ketdi"),
                         "tone": "warn" if a.late_minutes else ("ok" if not a.check_out else "")}
                        for a in L(Attendance.objects.filter(check_in__date=today)).select_related("employee__user", "employee__position").order_by("check_in")[:12]]
                return {"type": "list", "title": "Bugun ishda", "sub": "davomat", "rows": rows, "empty": "Hali hech kim kelmagan", "route": "/hr"}
            add(onshift)

            def att():
                from modules.hr.models import Attendance
                by = Counter(L(Attendance.objects.filter(check_in__date__gte=today - timedelta(days=13))).values_list("check_in__date", flat=True))
                return {"type": "chart", "kind": "bars", "money": False, "title": "Davomat — 14 kun", "sub": "kunlik kelgan xodimlar",
                        "points": [{"label": f"{WD[d.weekday()]} {d:%d}", "value": by.get(d, 0)} for d in _days(today, 14)], "route": "/hr", "wide": True}
            add(att)

            def lates():
                from modules.hr.models import Attendance
                q = (L(Attendance.objects.filter(check_in__date__gte=today - timedelta(days=29), late_minutes__gt=0))
                     .values("employee__user__full_name").annotate(n=Count("id"), m=Sum("late_minutes")).order_by("-m")[:7])
                rows = [{"label": r["employee__user__full_name"] or "—", "value": r["m"], "display": f"{r['m']} daq", "sub": f"{r['n']} marta"} for r in q]
                return {"type": "rank", "title": "Ko'p kechikkanlar", "sub": "30 kun", "rows": rows, "route": "/hr"}
            add(lates)

            def payroll():
                from modules.hr.models import Payslip
                q = (L(Payslip.objects.filter(period=today.replace(day=1)), "employee__branch").values("employee__position__name").annotate(s=Sum("total"), n=Count("id")).order_by("-s"))
                rows = [{"label": r["employee__position__name"] or "—", "value": int(r["s"] or 0), "display": _m(r["s"]), "sub": f"{r['n']} kishi"} for r in q]
                return {"type": "rank", "title": "Oylik fondi (shu oy)", "sub": "lavozimlar bo'yicha", "rows": rows, "route": "/hr"} if can("hr.payroll") or can("hr.*") else None
            add(payroll)
            if can("hr.recruit"):
                def funnel():
                    from modules.hr.models import Application, Stage
                    c = Counter(Application.objects.values_list("stage", flat=True))
                    rows = [{"label": s.label, "value": c.get(s.value, 0), "display": str(c.get(s.value, 0))} for s in Stage if s.value != "rejected"]
                    return {"type": "rank", "title": "Ishga olish voronkasi", "sub": "nomzodlar bosqichlar bo'yicha", "rows": rows, "route": "/recruiting"}
                add(funnel)

        if can("core.users.manage"):
            def roles():
                from core.models import Membership
                q = Membership.objects.filter(is_active=True).values("role__name").annotate(n=Count("id")).order_by("-n")
                return {"type": "rank", "title": "Foydalanuvchilar rollar bo'yicha", "sub": "kim tizimga kira oladi",
                        "rows": [{"label": r["role__name"], "value": r["n"], "display": str(r["n"])} for r in q], "route": "/users"}
            add(roles)

    # ================================================================== O'QITISH VA STANDARTLAR
    elif code == "training":
        if "training" in on:
            def courses():
                from modules.training.models import Course, Enrollment
                rows = []
                for c in Course.objects.filter(is_published=True, is_archived=False):
                    en = Enrollment.objects.filter(course=c)
                    n = en.count()
                    d = en.filter(status="completed").count()
                    rows.append({"label": c.title, "value": round(100 * d / n) if n else 0, "display": f"{round(100 * d / n) if n else 0}%", "sub": f"{d} / {n} tugatgan"})
                return {"type": "rank", "title": "Kurslar bo'yicha tugatish", "sub": "foizda", "rows": rows, "route": "/training?tab=courses", "wide": True}
            add(courses)

            def lagging():
                from modules.training.models import Enrollment
                rows = [{"title": e.user.full_name or e.user.phone, "sub": e.course.title, "right": f"{e.progress}%",
                         "tone": "bad" if e.is_overdue else "warn" if e.progress < 30 else ""}
                        for e in Enrollment.objects.exclude(status="completed").select_related("user", "course").order_by("progress")[:8]]
                return {"type": "list", "title": "Orqada qolayotganlar", "sub": "eng kam progress", "rows": rows, "empty": "Hamma tugatgan 🎉", "route": "/training?tab=report"}
            add(lagging)

            def recent():
                from modules.training.models import Enrollment
                rows = [{"title": e.user.full_name or e.user.phone, "sub": e.course.title, "right": f"{timezone.localtime(e.completed_at):%d.%m}", "tone": "ok", "badge": "tugatdi"}
                        for e in Enrollment.objects.filter(status="completed", completed_at__isnull=False).select_related("user", "course").order_by("-completed_at")[:6]]
                return {"type": "list", "title": "Yaqinda tugatganlar", "sub": "sertifikat oldi", "rows": rows, "empty": "Hali yo'q", "route": "/training?tab=report"}
            add(recent)

            def review():
                from modules.training.models import Submission
                rows = [{"title": s.user.full_name or s.user.phone, "sub": s.assignment.title, "right": f"{timezone.localtime(s.submitted_at or s.updated_at):%d.%m %H:%M}", "tone": "warn", "badge": "tekshiring"}
                        for s in Submission.objects.filter(status="submitted").select_related("user", "assignment")[:6]]
                return {"type": "list", "title": "Tekshirish kerak", "sub": "topshiriq dalillari (foto)", "rows": rows, "empty": "Tekshiradigan narsa yo'q", "route": "/training?tab=assignments"}
            add(review)

            def stds():
                from modules.training import services as tr
                from modules.training.models import Standard, StandardAck
                rows = []
                for s in Standard.objects.all():
                    aud = len(tr.audience_users(s)) or 1
                    a = StandardAck.objects.filter(standard=s).count()
                    rows.append({"label": s.title, "value": round(100 * a / aud), "display": f"{round(100 * a / aud)}%", "sub": f"{a} / {aud} imzo"})
                return {"type": "rank", "title": "Standartlar bilan tanishish", "sub": "imzo qo'yganlar ulushi", "rows": rows, "route": "/training?tab=standards"}
            add(stds)

    # ================================================================== VAZIFA VA LOYIHALAR
    elif code == "work":
        if "tasks" in on and can("tasks.view"):
            def cols():
                from modules.tasks.models import Task, TaskColumn
                c = Counter(L(Task.objects.all()).values_list("column_id", flat=True))
                items = [{"key": str(col.pk), "label": (col.name or {}).get("uz", col.code), "value": c.get(col.pk, 0), "color": COLORS[i % 8]}
                         for i, col in enumerate(TaskColumn.objects.order_by("sort_order")) if col.kind != "cancelled"]
                return {"type": "donut", "title": "Vazifalar holati", "sub": "hammasi", "items": items, "route": "/tasks"}
            add(cols)

            def overdue():
                from modules.tasks.models import ColumnKind, Task
                rows = [{"title": tk.title, "sub": (tk.assignee.full_name if tk.assignee_id else "tayinlanmagan"),
                         "right": f"{timezone.localtime(tk.due_at):%d.%m %H:%M}", "tone": "bad", "badge": "kechikdi"}
                        for tk in L(Task.objects.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).filter(due_at__lt=timezone.now())).select_related("assignee").order_by("due_at")[:8]]
                return {"type": "list", "title": "Kechikkan vazifalar", "sub": "birinchi navbatda", "rows": rows, "empty": "Kechikkan vazifa yo'q ✓", "route": "/tasks"}
            add(overdue)

            def flow():
                from modules.tasks.models import Task
                made = Counter(L(Task.objects.filter(created_at__date__gte=today - timedelta(days=13))).values_list("created_at__date", flat=True))
                return {"type": "chart", "kind": "bars", "money": False, "title": "Yangi vazifalar — 14 kun", "sub": "kunlik tushgan muammo va vazifalar",
                        "points": [{"label": f"{WD[d.weekday()]} {d:%d}", "value": made.get(d, 0)} for d in _days(today, 14)], "route": "/tasks", "wide": True}
            add(flow)
        if "projects" in on and can("projects.view"):
            def projects():
                from modules.projects import services as ps
                rows = []
                for p in L(ps.visible_projects(u)).filter(status__in=["plan", "active", "paused"]).prefetch_related("tasks"):
                    tasks = list(p.tasks.all())
                    pr = ps.progress(tasks, p.status)
                    rows.append({"label": p.title, "value": pr, "display": f"{pr}%", "sub": f"{p.code} · muddat {p.due:%d.%m}" if p.due else p.code})
                return {"type": "rank", "title": "Loyihalar progressi", "sub": "faol loyihalar", "rows": rows, "route": "/projects"}
            add(projects)

    # ================================================================== MOLIYA
    elif code == "finance":
        if "finance" in on and can("finance.view") and "pos" in on:
            ms = today.replace(day=1)
            add(lambda: {"type": "chart", "kind": "line", "money": True, "title": "Kunlik savdo — 30 kun", "sub": "tushum", "points": daily_revenue(30), "route": "/reports", "wide": True})

            def pnl():
                from modules.finance.models import Expense
                from modules.hr.models import Payslip
                agg = paid().filter(paid_at__date__gte=ms).aggregate(s=Sum("total"), c=Sum("cost_total"))
                rev, cost = int(agg["s"] or 0), int(agg["c"] or 0)
                exp = int(L(Expense.objects.filter(date__gte=ms)).aggregate(s=Sum("amount"))["s"] or 0)
                pay = int(L(Payslip.objects.filter(period=ms), "employee__branch").aggregate(s=Sum("total"))["s"] or 0)
                net = rev - cost - exp - pay
                pct = lambda v: f"{round(100 * v / rev, 1) if rev else 0}%"  # noqa: E731
                return {"type": "table", "title": "Foyda va zarar (shu oy)", "sub": f"{ms:%d.%m} — {today:%d.%m}", "route": "/reports",
                        "cols": ["Modda", "Summa", "Savdoga nisbatan"],
                        "rows": [["Savdo", _m(rev), "100%"], ["Tannarx (xomashyo)", _m(-cost), pct(cost)], ["Xarajatlar", _m(-exp), pct(exp)],
                                 ["Mehnat (oylik)", _m(-pay), pct(pay)], ["Sof foyda", _m(net), pct(net)]]}
            add(pnl)

            def exp_cats():
                from modules.finance.models import Expense
                q = L(Expense.objects.filter(date__gte=ms)).values("category__name").annotate(s=Sum("amount")).order_by("-s")
                return {"type": "rank", "title": "Xarajatlar turlari", "sub": "shu oy", "route": "/reports",
                        "rows": [{"label": r["category__name"], "value": int(r["s"] or 0), "display": _m(r["s"])} for r in q]}
            add(exp_cats)

            def fc_weeks():
                pts = []
                for k in range(7, -1, -1):
                    a = today - timedelta(days=today.weekday()) - timedelta(weeks=k)
                    agg = paid().filter(paid_at__date__gte=a, paid_at__date__lt=a + timedelta(days=7)).aggregate(s=Sum("total"), c=Sum("cost_total"))
                    s, c = int(agg["s"] or 0), int(agg["c"] or 0)
                    pts.append({"label": f"{a:%d.%m}", "value": round(100 * c / s, 1) if s else 0})
                return {"type": "chart", "kind": "line", "money": False, "title": "Food cost % — haftalar", "sub": "me'yor 28–35%", "points": pts, "route": "/reports"}
            add(fc_weeks)

    # ================================================================== SOZLAMALAR
    elif code == "settings":
        def branches():
            from core.models import Branch
            q = {r["branch_id"]: r for r in paid().filter(paid_at__date=today).values("branch_id").annotate(s=Sum("total"), n=Count("id"))} if "pos" in on else {}
            rows = [{"title": b.name, "sub": b.address or "", "right": f"{_m((q.get(b.pk) or {}).get('s', 0))} bugun", "tone": "ok" if b.pk in q else ""}
                    for b in Branch.objects.filter(deleted_at__isnull=True)]
            return {"type": "list", "title": "Filiallar", "sub": "bugungi savdo bilan", "rows": rows, "route": "/branches"}
        add(branches)

        def audit():
            from core.models import AuditLog
            act = {"create": "qo'shdi", "update": "o'zgartirdi", "delete": "o'chirdi", "pay": "to'ladi", "cancel": "bekor qildi", "receive": "qabul qildi", "close": "yopdi"}
            rows = [{"title": f"{(a.actor.full_name or a.actor.phone) if a.actor_id else 'Tizim'} {act.get(a.action, a.action)}", "sub": f"{a.model} #{a.object_id}"[:80],
                     "right": f"{timezone.localtime(a.at):%d.%m %H:%M}"}
                    for a in AuditLog.objects.select_related("actor").order_by("-at")[:8]]
            return {"type": "list", "title": "So'nggi o'zgarishlar", "sub": "kim, nima qildi", "rows": rows, "empty": "Hali o'zgarish yo'q", "route": "/audit"}
        if can("core.settings.view"):
            add(audit)

        def mods():
            from core import modules as modreg
            rows = []
            for m in sorted(modreg.all_modules(), key=lambda x: x.code not in on):
                d = m.to_dict()
                rows.append({"title": (d.get("name") or {}).get("uz", m.code), "right": "yoqilgan" if m.code in on else "o'chiq", "tone": "ok" if m.code in on else ""})
            return {"type": "list", "title": "Modullar", "sub": f"{len(on)} ta yoqilgan", "rows": rows[:12], "route": "/modules"} if rows else None
        add(mods)

    return {"code": code, "days": days, "widgets": W}
