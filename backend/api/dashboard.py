"""
Boshqaruv paneli (menejer ko'zi) — /api/v1/dashboard/overview?period=today|yesterday|week|month|year&branch_id=

Bir so'rovda hammasi: KPI (o'tgan davrga nisbatan), savdo dinamikasi, buyurtmalar holati, top taomlar,
filiallar, so'nggi buyurtmalar, ombor ogohlantirishlari, bugungi vazifalar, so'nggi faoliyat.
Modul o'chiq bo'lsa — o'sha blok bo'sh (None) qaytadi, sahifa uni ko'rsatmaydi.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate, TruncMonth
from django.utils import timezone

PERIODS = {"today": "Bugun", "yesterday": "Kecha", "week": "7 kun", "month": "Shu oy", "year": "Shu yil"}
TYPE_UZ = {"dine_in": "Zalda", "takeaway": "Olib ketish", "delivery": "Yetkazish"}
SOURCE_UZ = {"pos": "Kassa", "telegram": "Telegram", "site": "Sayt", "app": "Ilova"}


def _delta(cur, prev):
    return round(100 * (cur - prev) / prev, 1) if prev else None


def _range(period: str, today: date) -> tuple[date, date, date, date]:
    """(boshi, oxiri, oldingi boshi, oldingi oxiri) — adolatli taqqoslash uchun teng uzunlik."""
    if period == "yesterday":
        d = today - timedelta(days=1)
        return d, d, d - timedelta(days=1), d - timedelta(days=1)
    if period == "week":
        s = today - timedelta(days=6)
        return s, today, s - timedelta(days=7), s - timedelta(days=1)
    if period == "month":
        s = today.replace(day=1)
        ps = (s - timedelta(days=1)).replace(day=1)
        pe = min(ps + timedelta(days=(today - s).days), s - timedelta(days=1))
        return s, today, ps, pe
    if period == "year":
        s = today.replace(month=1, day=1)
        ps = s.replace(year=s.year - 1)
        return s, today, ps, today.replace(year=today.year - 1)
    return today, today, today - timedelta(days=1), today - timedelta(days=1)


def overview(request, period: str = "today", branch_id: Optional[int] = None) -> dict:
    t = request.tenant
    u = request.auth
    period = period if period in PERIODS else "today"
    today = timezone.localdate()
    now = timezone.now()
    start, end, pstart, pend = _range(period, today)
    out: dict = {
        "user": {"first_name": (u.full_name or "").split(" ")[0] or "", "full_name": u.full_name},
        "tenant": {"name": t.name},
        "period": {"code": period, "label": PERIODS[period], "start": start.isoformat(), "end": end.isoformat(),
                   "periods": [{"code": k, "label": v} for k, v in PERIODS.items()]},
        "branches_list": [], "kpis": [], "series": None, "status": None, "top": None, "branches": None,
        "recent": None, "stock": None, "tasks": None, "activity": [], "today": {"holiday": None, "weather": None, "alerts": []},
    }
    from core.models import Branch
    out["branches_list"] = [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True)]

    if t.module_enabled("pos"):
        _sales(out, period, start, end, pstart, pend, today, now, branch_id)
    if t.module_enabled("inventory"):
        _stock(out)
    if t.module_enabled("tasks"):
        _tasks(out, now)
    _activity(out, t, branch_id)
    if t.module_enabled("forecast"):
        _today(out, t)
    return out


def _holiday_todo(a: dict, t) -> list[dict]:
    """Bayramga tayyorgarlik ro'yxati: har band — nima qilish, qayerda, bajarilganmi."""
    from datetime import date as _date
    on = set(t.enabled_modules or [])
    buy_by = _date.fromisoformat(a["buy_by"]).strftime("%d.%m") if a.get("buy_by") else ""
    up = a.get("uplift_percent") or 0
    todo = [{"icon": "🛒", "text": (f"{a['short_count']} xil xomashyo xarid qiling — ~{a['total_cost']:,} so'm, {buy_by} gacha".replace(",", " ")
                                     if a.get("short_count") else "Ombor yetarli — xarid shart emas"),
             "short": "Xarid", "done": not a.get("short_count"), "route": f"/inventory?tab=plan&holiday={a['id']}" if "inventory" in on else "/forecast"}]
    if "hr" in on:
        todo.append({"icon": "👥", "text": f"Smena jadvalini kuchaytiring — savdo {'+' if up >= 0 else ''}{up}% kutilmoqda", "short": "Smenani kuchaytiring", "done": False, "route": "/hr"})
    if "catalog" in on:
        todo.append({"icon": "🍽️", "text": "Menyu va stop-listni tekshiring, bayram taomlarini qo'shing", "short": "Menyu va stop-list", "done": False, "route": "/catalog"})
    if "telegram" in on:
        todo.append({"icon": "📣", "text": "Mijozlarga Telegram orqali tabrik va aksiya yuboring", "short": "Telegram tabrik", "done": False, "route": "/telegram"})
    if "tasks" in on:
        todo.append({"icon": "📋", "text": "Bayram vazifalarini xodimlarga taqsimlang", "short": "Vazifalarni taqsimlang", "done": False, "route": "/tasks"})
    return todo


def _today(out, t):
    """Kichik blok: bugun bayram bo'lsa — bayram (faqat o'sha kunlari), va bugungi ob-havo (bir qator). Xato bo'lsa — chiqmaydi."""
    import logging
    try:
        from modules.forecast import services, weather
        # bayram yaqin (tayyorgarlik oynasida) — nima qilish kerakligi bilan
        out["today"]["alerts"] = [{**x, "todo": _holiday_todo(x, t)} for x in services.alerts(t)[:2]]
        h = next((x for x in services.upcoming(limit=6) if x.covers(timezone.localdate())), None)
        if h:
            ho = services.holiday_out(h)
            out["today"]["holiday"] = {"name": ho["name"], "uplift_percent": ho["uplift_percent"], "end": ho["end"], "days": ho["days"]}
        weather.refresh(t)
        days = weather.forecast_days(t, 1)
        if days:
            w = weather.day_out(days[0], t)
            out["today"]["weather"] = {"icon": w["icon"], "label": w["label"], "t_max": w["t_max"], "t_min": w["t_min"],
                                       "effect": w["effect"], "city": weather.location(t)["name"]}
    except Exception:
        logging.getLogger("dashboard").exception("bugungi bayram/ob-havo")


# ------------------------------------------------------------------ savdo
def _sales(out, period, start, end, pstart, pend, today, now, branch_id):
    from modules.finance.reports import pnl
    from modules.pos.models import Order, OrderItem, OrderStatus

    def paid(s, e):
        qs = Order.objects.filter(status=OrderStatus.PAID, paid_at__date__gte=s, paid_at__date__lte=e)
        return qs.filter(branch_id=branch_id) if branch_id else qs

    cur = paid(start, end)
    prev = paid(pstart, pend)
    if period == "today":                       # bugun hozirgacha ↔ kecha xuddi shu soatgacha
        prev = prev.filter(paid_at__lte=now - timedelta(days=1))
    a = cur.aggregate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"))
    b = prev.aggregate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"))
    rev, n, cogs = int(a["r"] or 0), a["n"] or 0, int(a["c"] or 0)
    prev_rev, prev_n, prev_cogs = int(b["r"] or 0), b["n"] or 0, int(b["c"] or 0)
    avg, prev_avg = (rev // n if n else 0), (prev_rev // prev_n if prev_n else 0)
    fc = round(100 * cogs / rev, 1) if rev else 0.0
    pfc = round(100 * prev_cogs / prev_rev, 1) if prev_rev else None
    # mehnat va sof foyda — kamida oylik kesimda ma'noli (bir kunlik oylik ulushi noto'g'ri tuyuladi)
    ms = start if period in ("month", "year") else today.replace(day=1)
    m = pnl(ms, end, branch_id)
    if period == "year":
        pm = pnl(pstart, pend, branch_id)
    else:
        _, _, mps, mpe = _range("month", end)
        pm = pnl(mps, mpe, branch_id)

    # 7 nuqtali sparkline (kunlik) — oxirgi nuqta = joriy kun
    spark_s = end - timedelta(days=6)
    daily = {r["d"]: r for r in paid(spark_s, end).annotate(d=TruncDate("paid_at")).values("d")
             .annotate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"))}
    days = [spark_s + timedelta(days=i) for i in range(7)]
    sp_rev = [int((daily.get(d) or {}).get("r") or 0) for d in days]
    sp_n = [int((daily.get(d) or {}).get("n") or 0) for d in days]
    sp_avg = [(r // k if k else 0) for r, k in zip(sp_rev, sp_n, strict=True)]
    sp_fc = [round(100 * int((daily.get(d) or {}).get("c") or 0) / r, 1) if r else 0 for d, r in zip(days, sp_rev, strict=True)]
    label_prev = {"today": "Kecha shu vaqtgacha", "yesterday": "Avvalgi kun", "week": "Oldingi 7 kun", "month": "O'tgan oy shu kungacha", "year": "O'tgan yil"}[period]
    out["kpis"] = [
        {"key": "revenue", "label": "Savdo", "value": rev, "money": True, "delta": _delta(rev, prev_rev), "prev": prev_rev, "prev_label": label_prev, "spark": sp_rev, "icon": "receipt", "route": "/reports"},
        {"key": "orders", "label": "Buyurtmalar", "value": n, "delta": _delta(n, prev_n), "prev": prev_n, "prev_label": label_prev, "spark": sp_n, "icon": "list", "route": "/pos"},
        {"key": "avg_check", "label": "O'rtacha chek", "value": avg, "money": True, "delta": _delta(avg, prev_avg), "prev": prev_avg, "prev_label": label_prev, "spark": sp_avg, "icon": "chart"},
        {"key": "food_cost", "label": "Food cost", "value": fc, "percent": True, "delta": round(fc - pfc, 1) if pfc is not None else None,
         "lower_is_better": True, "norm": "Me'yor: 28–35%", "ok": 0 < fc <= 35, "spark": sp_fc, "icon": "box", "route": "/inventory"},
        {"key": "labor", "label": "Mehnat xarajati", "value": m["labor_percent"], "percent": True, "delta": round(m["labor_percent"] - pm["labor_percent"], 1) if pm["revenue"] and pm["labor"] else None,
         "lower_is_better": True, "norm": "Me'yor: ≤ 25% · " + ("oy" if period not in ("year",) else "yil"), "ok": m["labor_percent"] <= 25, "icon": "users", "route": "/hr"},
        {"key": "net", "label": "Sof foyda", "value": m["net_profit"], "money": True, "delta": _delta(m["net_profit"], pm["net_profit"]) if pm["net_profit"] > 0 and pm["labor"] else None,
         "norm": f"Marja: {m['net_margin_percent']}% · " + ("oy" if period != "year" else "yil"), "ok": m["net_margin_percent"] >= 10, "icon": "chart", "route": "/reports"},
    ]

    # savdo dinamikasi: kun ichida — soatlar, hafta/oy — kunlar, yil — oylar
    if period in ("today", "yesterday"):
        rows = {r["h"]: r for r in cur.annotate(h=ExtractHour("paid_at")).values("h").annotate(r=Sum("total"), n=Count("id"))}
        hours = [h for h in range(8, 24)] + [h for h in range(0, 3) if rows.get(h)]
        pts = [{"label": f"{h:02d}:00", "revenue": int((rows.get(h) or {}).get("r") or 0), "orders": (rows.get(h) or {}).get("n") or 0} for h in hours]
    elif period == "year":
        rows = {r["m"].date() if isinstance(r["m"], datetime) else r["m"]: r for r in cur.annotate(m=TruncMonth("paid_at")).values("m").annotate(r=Sum("total"), n=Count("id"))}
        mon = ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"]
        pts = []
        for i in range(1, today.month + 1):
            k = date(today.year, i, 1)
            r = next((v for kk, v in rows.items() if (kk.year, kk.month) == (k.year, k.month)), None)
            pts.append({"label": mon[i - 1], "revenue": int((r or {}).get("r") or 0), "orders": (r or {}).get("n") or 0})
    else:
        rows = {r["d"]: r for r in cur.annotate(d=TruncDate("paid_at")).values("d").annotate(r=Sum("total"), n=Count("id"))}
        pts = [{"label": f"{d:%d.%m}", "revenue": int((rows.get(d) or {}).get("r") or 0), "orders": (rows.get(d) or {}).get("n") or 0}
               for d in (start + timedelta(days=i) for i in range((end - start).days + 1))]
    best = max(pts, key=lambda p: p["revenue"]) if pts else None
    out["series"] = {"points": pts, "unit": "soat" if period in ("today", "yesterday") else "kun" if period != "year" else "oy",
                     "best": best["label"] if best and best["revenue"] else None}

    # buyurtmalar holati (davr ichida yaratilganlar)
    made = Order.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    if branch_id:
        made = made.filter(branch_id=branch_id)
    st = {"new": 0, "cooking": 0, "ready": 0, "done": 0, "cancelled": 0}
    st["done"] = made.filter(status=OrderStatus.PAID).count()
    st["cancelled"] = made.filter(status=OrderStatus.CANCELLED).count()
    open_ids = list(made.filter(status=OrderStatus.OPEN).values_list("id", flat=True))
    kds = {}
    if open_ids and out is not None:
        try:
            from modules.kds.models import Ticket
            for oid, s in Ticket.objects.filter(order_id__in=open_ids).values_list("order_id", "status"):
                rank = {"new": 0, "cooking": 1, "ready": 2, "served": 3, "cancelled": -1}.get(s, 0)
                kds[oid] = min(kds.get(oid, 9), rank)
        except Exception:
            pass
    for oid in open_ids:
        r = kds.get(oid, 0)
        st["ready" if r >= 2 else "cooking" if r == 1 else "new"] += 1
    total = sum(st.values())
    labels = {"done": "Yakunlangan", "cooking": "Tayyorlanmoqda", "new": "Yangi", "ready": "Tayyor", "cancelled": "Bekor qilingan"}
    out["status"] = {"total": total, "items": [{"key": k, "label": labels[k], "value": st[k],
                                                "share": round(100 * st[k] / total, 1) if total else 0} for k in ("done", "cooking", "new", "ready", "cancelled")]}

    # eng ko'p sotilganlar
    items = (OrderItem.objects.filter(order__in=cur).values("product_id", "name").annotate(q=Sum("qty"), s=Sum(F("price") * F("qty")))
             .order_by("-q")[:5])
    qty_total = OrderItem.objects.filter(order__in=cur).aggregate(q=Sum("qty"))["q"] or 0
    from modules.catalog.models import Product
    imgs = {p.pk: p.image_src for p in Product.objects.filter(pk__in=[i["product_id"] for i in items if i["product_id"]])}
    out["top"] = [{"name": i["name"], "qty": int(i["q"] or 0), "revenue": int(i["s"] or 0), "image": imgs.get(i["product_id"]),
                   "share": round(100 * int(i["q"] or 0) / qty_total, 1) if qty_total else 0} for i in items]

    # filiallar
    from core.models import Branch
    brs = []
    for br in Branch.objects.filter(deleted_at__isnull=True, is_active=True):
        x = paid(start, end).filter(branch=br).aggregate(r=Sum("total"), n=Count("id"), c=Sum("cost_total")) if not branch_id or branch_id == br.pk else None
        if x is None:
            continue
        r, k, c = int(x["r"] or 0), x["n"] or 0, int(x["c"] or 0)
        f = round(100 * c / r, 1) if r else 0.0
        brs.append({"id": br.pk, "name": br.name, "revenue": r, "orders": k, "food_cost": f,
                    "state": "ok" if r and f <= 35 else "warn" if r and f <= 38 else ("bad" if r else "idle")})
    out["branches"] = sorted(brs, key=lambda b: -b["revenue"])

    # so'nggi buyurtmalar
    rec = Order.objects.exclude(status=OrderStatus.CANCELLED).order_by("-created_at")
    if branch_id:
        rec = rec.filter(branch_id=branch_id)
    rec = list(rec[:6])
    rkds = {}
    try:
        from modules.kds.models import Ticket
        for oid, s in Ticket.objects.filter(order_id__in=[o.pk for o in rec]).values_list("order_id", "status"):
            rank = {"new": 0, "cooking": 1, "ready": 2, "served": 3}.get(s, 0)
            rkds[oid] = min(rkds.get(oid, 9), rank)
    except Exception:
        pass
    out["recent"] = []
    for o in rec:
        if o.status == OrderStatus.PAID:
            s, lab = ("delivered", "Yetkazildi") if o.type == "delivery" else ("done", "To'langan")
        else:
            r = rkds.get(o.pk, 0)
            s, lab = ("ready", "Tayyor") if r >= 2 else ("cooking", "Oshxonada") if r == 1 else ("new", "Yangi")
        where = f"Stol {o.table_no}" if o.type == "dine_in" and o.table_no else TYPE_UZ.get(o.type, o.type)
        if o.source != "pos":
            where += f" · {SOURCE_UZ.get(o.source, o.source)}"
        out["recent"].append({"id": o.pk, "number": o.number, "time": timezone.localtime(o.created_at).strftime("%H:%M"),
                              "where": where, "total": o.total, "status": s, "status_label": lab})


# ------------------------------------------------------------------ ombor
def _stock(out):
    from modules.inventory.models import Ingredient
    rows = []
    for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True, min_stock__gt=0):
        ratio = float(i.stock) / float(i.min_stock) if i.min_stock else 9
        if ratio < 1.5:
            rows.append({"id": i.pk, "name": (i.name or {}).get("uz") or str(i), "stock": float(i.stock), "unit": i.unit,
                         "min": float(i.min_stock), "level": "critical" if ratio < 0.5 else "low" if ratio < 1 else "watch", "ratio": ratio})
    rows.sort(key=lambda r: r["ratio"])
    out["stock"] = {"count": sum(1 for r in rows if r["level"] != "watch"), "items": rows[:5]}



# ------------------------------------------------------------------ vazifalar
def _tasks(out, now):
    from modules.tasks.models import ColumnKind, Task
    end_day = timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 59)))
    qs = (Task.objects.live().filter(Q(due_at__lte=end_day) | Q(column__kind=ColumnKind.DONE, done_at__date=timezone.localdate()))
          .select_related("assignee", "column").order_by("due_at"))
    rows = []
    for tk in qs[:40]:
        done = tk.column.kind == ColumnKind.DONE
        if done and not (tk.done_at and tk.done_at.date() == timezone.localdate()):
            continue
        rows.append({"id": tk.pk, "title": tk.title, "done": done, "overdue": bool(not done and tk.due_at and tk.due_at < now),
                     "time": timezone.localtime(tk.due_at).strftime("%H:%M") if tk.due_at and tk.due_at.date() == timezone.localdate() else
                     (timezone.localtime(tk.due_at).strftime("%d.%m") if tk.due_at else ""),
                     "assignee": tk.assignee.full_name if tk.assignee_id else None})
    rows.sort(key=lambda r: (r["done"], not r["overdue"]))
    out["tasks"] = {"open": Task.objects.open().count(), "overdue": Task.objects.overdue().count(), "items": rows[:6]}


# ------------------------------------------------------------------ so'nggi faoliyat
def _activity(out, t, branch_id):
    ev = []
    if t.module_enabled("pos"):
        from modules.pos.models import Order, OrderStatus
        qs = Order.objects.filter(status=OrderStatus.PAID).select_related("cashier").order_by("-paid_at")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        for o in qs[:4]:
            ev.append({"at": o.paid_at, "icon": "receipt", "who": o.cashier.full_name if o.cashier_id else "Kassa",
                       "text": f"#{o.number} buyurtmani qabul qildi · {o.total:,} so'm".replace(",", " ")})
    if t.module_enabled("kds"):
        try:
            from modules.kds.models import Ticket
            for tk in Ticket.objects.filter(ready_at__isnull=False).select_related("cook", "order").order_by("-ready_at")[:3]:
                ev.append({"at": tk.ready_at, "icon": "play", "who": tk.cook.full_name if tk.cook_id else "Oshxona",
                           "text": f"#{tk.order.number} tayyorladi"})
        except Exception:
            pass
    if t.module_enabled("tasks"):
        from modules.tasks.models import TaskActivity
        for a in TaskActivity.objects.select_related("actor", "task").order_by("-at")[:4]:
            ev.append({"at": a.at, "icon": "check", "who": a.actor.full_name if a.actor_id else "Tizim", "text": f"{a.detail or a.action}: «{a.task.title}»"})
    if t.module_enabled("inventory"):
        from modules.inventory.models import Purchase
        for p in Purchase.objects.select_related("supplier", "created_by").order_by("-created_at")[:2]:
            ev.append({"at": p.created_at, "icon": "box", "who": p.created_by.full_name if p.created_by_id else "Ombor",
                       "text": f"kirim: {p.supplier.name if p.supplier_id else 'bozorlik'}"})
    if t.module_enabled("training"):
        from modules.training.models import Enrollment
        for e in Enrollment.objects.filter(completed_at__isnull=False).select_related("user", "course").order_by("-completed_at")[:2]:
            ev.append({"at": e.completed_at, "icon": "book", "who": e.user.full_name or e.user.phone, "text": f"«{e.course.title}» kursini tugatdi"})
    from core.models import AuditLog
    for a in AuditLog.objects.select_related("actor").order_by("-at")[:3]:
        ev.append({"at": a.at, "icon": "edit", "who": str(a.actor) if a.actor else "Tizim", "text": f"{a.action} · {a.model}"})
    ev.sort(key=lambda x: x["at"] or timezone.now(), reverse=True)
    out["activity"] = [{**e, "at": e["at"].isoformat() if e["at"] else None} for e in ev[:7]]
