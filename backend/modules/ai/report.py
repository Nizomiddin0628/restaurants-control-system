"""
Ertalabki hisobot — «kecha qanday o'tdi, bugun nima bor, nimadan boshlash kerak».

Hamma raqamlarni tizim o'zi hisoblaydi (build). AI faqat shu raqamlarni o'qib «Birinchi navbatda» ro'yxati va
qisqa xulosa yozadi (ai_note). AI ishlamasa ham hisobot keladi — «Birinchi navbatda» qoidalar bo'yicha tuziladi.
Har blok alohida try/except: bitta modul xatosi butun hisobotni to'xtatmaydi.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import date, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

log = logging.getLogger("ai")
WD = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
TYPE_UZ = {"dine_in": "zalda", "takeaway": "olib ketish", "delivery": "yetkazish"}


def money(v) -> str:
    v = int(v or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",").replace(",0", "") + " mln"
    return f"{v:,}".replace(",", " ")


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _bf(qs, branch_ids, field: str = "branch"):
    """Filial filtri: None — hammasi; ro'yxat — shu filiallar (+ filialsiz yozuvlar emas)."""
    return qs if not branch_ids else qs.filter(**{f"{field}__in": branch_ids})


def _safe(out: dict, key: str, fn):
    try:
        out[key] = fn()
    except Exception:
        log.exception("hisobot bloki: %s", key)
        out[key] = None


def scope_of(user) -> list[int] | None:
    """Foydalanuvchi ko'radigan filiallar: rolda filial ko'rsatilmagan bo'lsa (yoki egasi) — hammasi (None)."""
    if user is None or user.is_superuser:
        return None
    ids: set[int] = set()
    for m in user.memberships.filter(is_active=True).prefetch_related("branches"):
        b = [x.pk for x in m.branches.all()]
        if not b:
            return None
        ids.update(b)
    return sorted(ids) or None


# ====================================================================== ma'lumot
def build(tenant, branch_ids: list[int] | None = None, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    y = today - timedelta(days=1)
    on = set(tenant.enabled_modules or [])
    out: dict = {"date": today.isoformat(), "weekday": WD[today.weekday()], "yesterday": y.isoformat(),
                 "restaurant": tenant.name, "scope": _scope_name(branch_ids)}
    if "pos" in on:
        _safe(out, "sales", lambda: _sales(y, branch_ids))
        _safe(out, "month", lambda: _month(today, branch_ids))
    if "inventory" in on:
        _safe(out, "stock", lambda: _stock())
    if "tasks" in on:
        _safe(out, "tasks", lambda: _tasks(today, branch_ids))
    if "hr" in on:
        _safe(out, "staff", lambda: _staff(today, y, branch_ids))
    if "reservations" in on:
        _safe(out, "bookings", lambda: _bookings(today, branch_ids))
    if "procurement" in on:
        _safe(out, "supply", lambda: _supply(today, branch_ids))
    if "forecast" in on:
        _safe(out, "forecast", lambda: _forecast(tenant, today))
    return out


def _scope_name(branch_ids) -> str:
    from core.models import Branch
    if not branch_ids:
        n = Branch.objects.filter(deleted_at__isnull=True, is_active=True).count()
        return "Barcha filiallar" if n > 1 else ""
    return ", ".join(Branch.objects.filter(pk__in=branch_ids).values_list("name", flat=True))


def _sales(y: date, branch_ids) -> dict:
    from modules.pos.models import Order, OrderItem
    paid = _bf(Order.objects.filter(status="paid", paid_at__date=y), branch_ids)
    agg = paid.aggregate(s=Sum("total"), c=Sum("cost_total"), n=Count("id"))
    rev, n, cost = int(agg["s"] or 0), int(agg["n"] or 0), int(agg["c"] or 0)
    wk = _bf(Order.objects.filter(status="paid", paid_at__date=y - timedelta(days=7)), branch_ids).aggregate(s=Sum("total"), n=Count("id"))
    prev = int(wk["s"] or 0)
    canc = _bf(Order.objects.filter(status="cancelled", created_at__date=y), branch_ids).aggregate(s=Sum("total"), n=Count("id"))
    top = list(_bf(OrderItem.objects.filter(order__status="paid", order__paid_at__date=y), branch_ids, "order__branch")
               .values("name").annotate(q=Sum("qty")).order_by("-q")[:5])
    by_branch = []
    if not branch_ids or len(branch_ids) > 1:
        by_branch = [{"name": r["branch__name"] or "—", "revenue": int(r["s"] or 0), "orders": r["n"]}
                     for r in paid.values("branch__name").annotate(s=Sum("total"), n=Count("id")).order_by("-s")]
    by_type = {TYPE_UZ.get(r["type"], r["type"]): r["n"] for r in paid.values("type").annotate(n=Count("id"))}
    return {"revenue": rev, "orders": n, "avg_check": rev // n if n else 0, "food_cost": round(100 * cost / rev, 1) if rev else None,
            "prev_week": prev, "prev_week_orders": int(wk["n"] or 0), "delta": round(100 * (rev - prev) / prev) if prev else None,
            "cancelled": int(canc["n"] or 0), "cancelled_sum": int(canc["s"] or 0),
            "top": [{"name": r["name"], "qty": int(r["q"] or 0)} for r in top], "by_branch": by_branch if len(by_branch) > 1 else [],
            "by_type": by_type}


def _month(today: date, branch_ids) -> dict:
    from modules.pos.models import Order
    ms = today.replace(day=1)
    agg = _bf(Order.objects.filter(status="paid", paid_at__date__gte=ms, paid_at__date__lt=today), branch_ids).aggregate(s=Sum("total"), n=Count("id"))
    return {"revenue": int(agg["s"] or 0), "orders": int(agg["n"] or 0), "days": (today - ms).days}


def _stock() -> dict:
    from modules.inventory.models import Ingredient
    ings = list(Ingredient.objects.filter(deleted_at__isnull=True, is_active=True))
    low = sorted((i for i in ings if i.is_low), key=lambda i: float(i.stock) / float(i.min_stock or 1))
    return {"low": [{"name": str(i), "stock": float(i.stock), "min": float(i.min_stock), "unit": i.unit} for i in low[:8]],
            "low_count": len(low), "value": int(sum(float(i.stock) * float(i.price) for i in ings if i.stock > 0))}


def _tasks(today: date, branch_ids) -> dict:
    from modules.tasks.models import ColumnKind, Task
    now = timezone.now()
    live = _bf(Task.objects.live().filter(is_archived=False), branch_ids)
    op = live.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED])
    over = op.filter(due_at__lt=now).select_related("assignee").order_by("due_at")
    due_today = op.filter(due_at__date=today, due_at__gte=now).select_related("assignee").order_by("due_at")
    done_y = live.filter(done_at__date=today - timedelta(days=1)).count()
    who = lambda t: (t.assignee.full_name or t.assignee.phone) if t.assignee_id else "tayinlanmagan"  # noqa: E731
    return {"open": op.count(), "overdue_count": over.count(), "done_yesterday": done_y,
            "overdue": [{"n": t.number, "title": t.title, "who": who(t), "due": timezone.localtime(t.due_at).strftime("%d.%m %H:%M")} for t in over[:6]],
            "today": [{"n": t.number, "title": t.title, "who": who(t), "due": timezone.localtime(t.due_at).strftime("%H:%M")} for t in due_today[:6]]}


def _staff(today: date, y: date, branch_ids) -> dict:
    from modules.hr.models import Attendance, ShiftPlan
    plan = _bf(ShiftPlan.objects.filter(date=today), branch_ids).select_related("employee__user", "branch").order_by("start")
    shifts = [{"name": s.employee.user.full_name or s.employee.user.phone, "start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"),
               "branch": s.branch.name if s.branch_id else ""} for s in plan]
    late = _bf(Attendance.objects.filter(check_in__date=y, late_minutes__gt=0), branch_ids).select_related("employee__user").order_by("-late_minutes")
    planned_y = set(_bf(ShiftPlan.objects.filter(date=y), branch_ids).values_list("employee_id", flat=True))
    came_y = set(_bf(Attendance.objects.filter(check_in__date=y), branch_ids).values_list("employee_id", flat=True))
    from modules.hr.models import Employee
    absent = [e.user.full_name or e.user.phone for e in Employee.objects.filter(pk__in=planned_y - came_y).select_related("user")]
    return {"today_count": len(shifts), "today": shifts[:12], "first_start": shifts[0]["start"] if shifts else None,
            "late_yesterday": [{"name": a.employee.user.full_name or a.employee.user.phone, "min": a.late_minutes} for a in late[:5]],
            "absent_yesterday": absent[:5]}


def _bookings(today: date, branch_ids) -> dict:
    from modules.reservations.models import Reservation
    qs = _bf(Reservation.objects.filter(starts_at__date=today, status__in=["new", "confirmed"]), branch_ids).select_related("table").order_by("starts_at")
    rows = [{"time": timezone.localtime(r.starts_at).strftime("%H:%M"), "name": r.guest_name, "guests": r.guests,
             "table": r.table.number if r.table_id else "", "occasion": r.occasion, "status": r.status} for r in qs]
    return {"count": len(rows), "guests": sum(r["guests"] for r in rows), "list": rows[:8], "unconfirmed": sum(1 for r in rows if r["status"] == "new")}


def _supply(today: date, branch_ids) -> dict:
    from modules.inventory.models import Supplier
    from modules.procurement.models import Order as PO
    from modules.procurement.services import debts
    arr = _bf(PO.objects.filter(status__in=["sent", "confirmed"], expected_date__lte=today), branch_ids).select_related("supplier").order_by("expected_date")
    arriving = [{"n": o.number, "supplier": o.supplier.name, "total": o.total, "late": bool(o.expected_date and o.expected_date < today)} for o in arr[:6]]
    d = {k: v for k, v in debts().items() if v["overdue"]}
    names = dict(Supplier.objects.filter(pk__in=d.keys()).values_list("id", "name"))
    return {"arriving": arriving, "debts_overdue": [{"supplier": names.get(k, "—"), "debt": v["debt"]} for k, v in sorted(d.items(), key=lambda x: -x[1]["debt"])[:4]],
            "debt_total": sum(v["debt"] for v in d.values())}


def _forecast(tenant, today: date) -> dict:
    from modules.forecast import services, weather
    out: dict = {}
    try:
        p = services.plan(tenant, start=today, end=today)
        out["revenue"] = p.get("revenue_forecast")
        out["normal"] = p.get("revenue_normal")
        out["enough_history"] = (p.get("history") or {}).get("enough")
        out["buy"] = [{"name": (ln["name"] or {}).get("uz", "") if isinstance(ln["name"], dict) else str(ln["name"]), "qty": ln["buy"], "unit": ln["unit"], "cost": ln["cost"]}
                      for ln in p.get("lines", []) if ln.get("buy")][:6]
        out["buy_total"] = p.get("total_cost")
    except Exception:
        log.exception("prognoz")
    try:
        days = weather.forecast_days(tenant, 1)
        if days:
            w = weather.day_out(days[0], tenant)
            out["weather"] = {"icon": w["icon"], "label": w["label"], "t_max": w["t_max"], "t_min": w["t_min"], "effect": w["effect"]}
    except Exception:
        log.exception("ob-havo")
    try:
        al = services.alerts(tenant, notify=False)[:1]
        if al:
            a = al[0]
            out["holiday"] = {"name": (a["name"] or {}).get("uz", "") if isinstance(a["name"], dict) else a["name"], "days_left": a.get("days_left"),
                              "is_now": a.get("is_now"), "uplift": a.get("uplift_percent"), "short_count": a.get("short_count"), "buy_by": a.get("buy_by")}
    except Exception:
        log.exception("bayram")
    return out


# ====================================================================== «birinchi navbatda» (qoidalar bo'yicha)
def priorities(r: dict) -> list[str]:
    out: list[str] = []
    st, tk, bk, sp, fc, sf, sa = (r.get(k) or {} for k in ("stock", "tasks", "bookings", "supply", "forecast", "staff", "sales"))
    if fc.get("holiday") and fc["holiday"].get("short_count"):
        h = fc["holiday"]
        out.append(f"🎉 {esc(h['name'])} yaqin ({h['days_left']} kun) — xarid rejasini tasdiqlang ({h['short_count']} xil xomashyo)")
    if st.get("low"):
        names = ", ".join(f"{esc(x['name'])} ({x['stock']:g} {x['unit']})" for x in st["low"][:3])
        out.append(f"🛒 Xarid: {names}" + (f" va yana {st['low_count'] - 3} ta" if st.get("low_count", 0) > 3 else ""))
    if tk.get("overdue_count"):
        t = tk["overdue"][0]
        out.append(f"⚠️ {tk['overdue_count']} ta kechikkan vazifa — avval #{t['n']} «{esc(t['title'])}» ({esc(t['who'])})")
    if bk.get("count"):
        first = bk["list"][0]
        extra = f", {bk['unconfirmed']} tasini tasdiqlang" if bk.get("unconfirmed") else ""
        out.append(f"📅 Bugun {bk['count']} ta bron ({bk['guests']} mehmon), birinchisi {first['time']}{extra}")
    if sp.get("arriving"):
        late = [a for a in sp["arriving"] if a["late"]]
        out.append(f"🚚 Ta'minotchidan {len(sp['arriving'])} ta buyurtma kutilmoqda" + (f" ({len(late)} tasi kechikkan — qo'ng'iroq qiling)" if late else " — qabul qilishga tayyorlaning"))
    if sa.get("delta") is not None and sa["delta"] <= -15:
        out.append(f"📉 Kecha savdo o'tgan haftadan {abs(sa['delta'])}% kam — sababini ko'ring (menyu, xodim, ob-havo)")
    if sf.get("absent_yesterday"):
        out.append(f"👥 Kecha smenaga kelmadi: {esc(', '.join(sf['absent_yesterday'][:3]))} — sababini so'rang")
    if sp.get("debts_overdue"):
        out.append(f"💳 Muddati o'tgan qarz: {money(sp['debt_total'])} so'm — to'lov rejasini tuzing")
    return out[:5] or ["✅ Jiddiy muammo yo'q — odatdagi ish tartibi"]


# ====================================================================== Telegram / panel uchun matn
def render(r: dict, ai_note: str | None = None, first: list[str] | None = None) -> str:
    d = date.fromisoformat(r["date"])
    L: list[str] = [f"☀️ <b>{esc(r['restaurant'])}</b> — {d:%d.%m.%Y}, {r['weekday']}" + (f"\n📍 {esc(r['scope'])}" if r.get("scope") else "")]
    sa = r.get("sales")
    if sa is not None:
        L.append("\n<b>📊 Kecha qanday o'tdi</b>")
        if sa["orders"]:
            dl = f" ({'+' if sa['delta'] >= 0 else ''}{sa['delta']}% o'tgan haftaga)" if sa.get("delta") is not None else ""
            L.append(f"• Savdo: <b>{money(sa['revenue'])} so'm</b>{dl}")
            L.append(f"• Cheklar: {sa['orders']} ta · o'rtacha chek {money(sa['avg_check'])} so'm")
            if sa.get("food_cost") is not None:
                L.append(f"• Food cost: {sa['food_cost']}%" + (" ⚠️" if sa["food_cost"] > 35 else ""))
            if sa.get("by_type"):
                L.append("• " + " · ".join(f"{k}: {v}" for k, v in sa["by_type"].items()))
            if sa.get("top"):
                L.append("• Eng ko'p sotilgan: " + ", ".join(f"{esc(t['name'])} ({t['qty']})" for t in sa["top"][:3]))
            for b in sa.get("by_branch") or []:
                L.append(f"   🏪 {esc(b['name'])}: {money(b['revenue'])} so'm · {b['orders']} chek")
            if sa.get("cancelled"):
                L.append(f"• Bekor qilingan: {sa['cancelled']} ta ({money(sa['cancelled_sum'])} so'm)")
        else:
            L.append("• Kecha savdo bo'lmagan")
        m = r.get("month")
        if m and m.get("revenue"):
            L.append(f"• Oy boshidan: {money(m['revenue'])} so'm · {m['orders']} chek")
    problems: list[str] = []
    st, tk, sf, sp = (r.get(k) or {} for k in ("stock", "tasks", "staff", "supply"))
    if st.get("low"):
        problems.append(f"• Tugayapti ({st['low_count']}): " + ", ".join(f"{esc(x['name'])} {x['stock']:g}/{x['min']:g} {x['unit']}" for x in st["low"][:5]))
    if tk.get("overdue_count"):
        problems.append(f"• Kechikkan vazifalar: {tk['overdue_count']} ta")
        problems += [f"   #{t['n']} {esc(t['title'])} — {esc(t['who'])}" for t in tk["overdue"][:3]]
    if sf.get("late_yesterday"):
        problems.append("• Kecha kechikkanlar: " + ", ".join(f"{esc(x['name'])} ({x['min']} daq)" for x in sf["late_yesterday"][:4]))
    if sf.get("absent_yesterday"):
        problems.append("• Kecha kelmaganlar: " + esc(", ".join(sf["absent_yesterday"][:4])))
    if sp.get("debts_overdue"):
        problems.append(f"• Muddati o'tgan qarz: {money(sp['debt_total'])} so'm (" + ", ".join(esc(x["supplier"]) for x in sp["debts_overdue"][:3]) + ")")
    if problems:
        L.append("\n<b>⚠️ E'tibor bering</b>")
        L += problems
    today_l: list[str] = []
    if sf.get("today_count"):
        today_l.append(f"• Smenada: {sf['today_count']} kishi, birinchisi {sf['first_start']} da")
    bk = r.get("bookings") or {}
    if bk.get("count"):
        today_l.append(f"• Bronlar: {bk['count']} ta, {bk['guests']} mehmon")
        today_l += [f"   {b['time']} — {esc(b['name'])}, {b['guests']} kishi" + (f", stol {esc(b['table'])}" if b["table"] else "") + (f" ({esc(b['occasion'])})" if b["occasion"] else "")
                    for b in bk["list"][:4]]
    if sp.get("arriving"):
        today_l.append("• Keladi: " + ", ".join(f"{esc(a['supplier'])} {money(a['total'])}" + (" (kechikkan)" if a["late"] else "") for a in sp["arriving"][:3]))
    if tk.get("today"):
        today_l.append(f"• Muddati bugun: {len(tk['today'])} ta vazifa")
        today_l += [f"   {t['due']} — {esc(t['title'])} ({esc(t['who'])})" for t in tk["today"][:3]]
    fc = r.get("forecast") or {}
    if fc.get("weather"):
        w = fc["weather"]
        today_l.append(f"• Ob-havo: {w['icon']} {w['t_max']}°/{w['t_min']}° {esc(w['label'])}" + (f" — savdoga ta'siri {'+' if w['effect'] > 0 else ''}{w['effect']}%" if w.get("effect") else ""))
    if fc.get("holiday"):
        h = fc["holiday"]
        today_l.append(f"• 🎉 {esc(h['name'])}: " + ("bugun!" if h.get("is_now") else f"{h['days_left']} kun qoldi") + (f", savdo +{h['uplift']}% kutilmoqda" if h.get("uplift") else ""))
    if today_l:
        L.append("\n<b>📋 Bugun</b>")
        L += today_l
    if fc.get("revenue") and fc.get("enough_history"):
        L.append("\n<b>🔮 Prognoz</b>")
        L.append(f"• Kutilayotgan savdo: ~{money(fc['revenue'])} so'm")
        if fc.get("buy"):
            L.append("• Xarid kerak: " + ", ".join(f"{esc(b['name'])} {b['qty']:g} {b['unit']}" for b in fc["buy"][:4]) + (f" (~{money(fc['buy_total'])} so'm)" if fc.get("buy_total") else ""))
    L.append("\n<b>🎯 Birinchi navbatda</b>")
    L += [f"{i}. {p}" for i, p in enumerate(first or priorities(r), 1)]
    if ai_note:
        L.append(f"\n🤖 <i>{ai_note}</i>")
    return "\n".join(L)


NOTE_PROMPT = """Sen restoranning tajribali operatsion direktori va rahbarning kotibisan.
Quyida tizim hisoblagan bugungi hisobot ma'lumotlari (JSON). Faqat shu raqamlarga tayan, hech narsa to'qima.
O'zbek tilida (lotin) javob ber. Qat'iy formatda:
BIRINCHI: 3–5 qator — menejer bugun ishga kelib birinchi navbatda qiladigan aniq ishlar, muhimlik tartibida. Har qator bitta ish, 15 so'zdan oshmasin, boshida mos emoji.
XULOSA: 1–2 gap — kecha va bugun haqida eng muhim fikr (masalan savdo pasaygan bo'lsa sababi haqida taxmin va nima qilish kerak).
Boshqa hech narsa yozma."""


def ai_note(tenant, r: dict) -> tuple[list[str] | None, str | None, dict]:
    """Gemini'dan «Birinchi navbatda» va qisqa xulosa. Xato bo'lsa — (None, None, info)."""
    from . import gemini
    info: dict = {"calls": 0, "tokens": 0, "model": "", "error": ""}
    if not gemini.api_key(tenant):
        info["error"] = "kalit yo'q"
        return None, None, info
    try:
        res = gemini.generate(tenant, [{"role": "user", "parts": [{"text": NOTE_PROMPT + "\n\nMA'LUMOT:\n" + json.dumps(r, ensure_ascii=False, default=str)}]}],
                              temperature=0.4, max_tokens=2048)
    except gemini.AiError as e:
        info["error"] = str(e)
        return None, None, info
    info.update(calls=1, tokens=gemini.tokens_of(res["data"]), model=res["model"])
    txt = gemini.text_of(res["data"])
    first, note, mode = [], [], ""
    for line in txt.splitlines():
        s = line.strip().strip("*").strip()
        if not s:
            continue
        up = s.upper()
        if up.startswith("BIRINCHI"):
            mode = "f"
            s = s.split(":", 1)[1].strip() if ":" in s else ""
            if not s:
                continue
        elif up.startswith("XULOSA"):
            mode = "n"
            s = s.split(":", 1)[1].strip() if ":" in s else ""
            if not s:
                continue
        s = s.lstrip("-•*0123456789.) ").strip()
        if mode == "f" and s:
            first.append(esc(s))
        elif mode == "n" and s:
            note.append(esc(s))
    return (first[:5] or None), (" ".join(note)[:500] or None), info


def full_text(tenant, user=None, branch_ids: list[int] | None = None, *, use_ai: bool = True, today: date | None = None) -> tuple[str, dict]:
    """Tayyor hisobot matni (Telegram HTML) + ma'lumot. branch_ids berilmasa — foydalanuvchi ko'radigan filiallar."""
    if branch_ids is None and user is not None:
        branch_ids = scope_of(user)
    r = build(tenant, branch_ids, today)
    first, note, info = (ai_note(tenant, r) if use_ai else (None, None, {"calls": 0, "tokens": 0, "model": "", "error": "o'chirilgan"}))
    return render(r, note, first), {"data": r, "ai": info}


def split(text: str, limit: int = 3900) -> list[str]:
    """Telegram 4096 belgidan uzun xabarni qabul qilmaydi — bo'limlar bo'yicha bo'linadi."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return [p[:limit] for p in out]

