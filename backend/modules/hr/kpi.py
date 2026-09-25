"""
Xodim KPI (oylik) — tizimdagi haqiqiy ma'lumotdan avtomatik + menejer bahosi.

Ball (0–100) = og'irlikli o'rtacha (mavjud ko'rsatkichlar bo'yicha, yo'g'i hisobga olinmaydi):
  Davomat (reja bo'yicha kelgan smenalar)          15
  O'z vaqtida kelish (kechikishsiz smenalar)        15
  O'qitish (tugatilgan kurslar + test bali)         15
  Vazifalar (muddatida bajarilgan)                  15
  Rol ko'rsatkichi                                  20   kassir/ofitsiant: o'rtacha chek restoran o'rtachasiga nisbatan, bekor cheklar
                                                          oshpaz: o'rtacha tayyorlash vaqti (maqsad ≤ 12 daq)
  Menejer bahosi (1–5 → 0–100)                      20
Daraja: A ≥ 85 · B ≥ 70 · C ≥ 50 · D < 50.  Tavsiya bonus: A — bazaning 10%, B — 5%.
Kayfiyat (smenadan keyingi baho) ballga kirmaydi — «xavf» belgisi uchun (o'rtacha < 2.5 → suhbatlashing).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Avg, Count, F, Sum
from django.utils import timezone

from .models import Attendance, Employee, Review, ShiftFeedback, ShiftPlan

WEIGHTS = {"attendance": 15, "punctuality": 15, "training": 15, "tasks": 15, "role": 20, "review": 20}
LABELS = {"attendance": "Davomat", "punctuality": "O'z vaqtida kelish", "training": "O'qitish", "tasks": "Vazifalar",
          "role": "Ish natijasi", "review": "Menejer bahosi"}


def month_bounds(m: date) -> tuple[date, date]:
    start = m.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, min(nxt - timedelta(days=1), timezone.localdate())


def grade(score: float | None) -> str:
    if score is None:
        return "—"
    return "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"


def _tolerance(tenant) -> int:
    try:
        return int((((tenant.settings or {}).get("modules") or {}).get("hr") or {}).get("late_tolerance_minutes", 10))
    except Exception:
        return 10


def compute(e: Employee, month: date, tenant=None, ctx: dict | None = None) -> dict:
    start, end = month_bounds(month)
    ctx = ctx or {}
    parts: dict[str, dict] = {}
    tol = _tolerance(tenant)

    # --- davomat / kechikish
    planned = ShiftPlan.objects.filter(employee=e, date__gte=start, date__lte=end).values_list("date", flat=True).distinct()
    planned = set(planned)
    att = list(Attendance.objects.filter(employee=e, check_in__date__gte=start, check_in__date__lte=end))
    came = {timezone.localtime(a.check_in).date() for a in att}
    if planned:
        hit = len(planned & came)
        parts["attendance"] = {"value": round(100 * hit / len(planned)), "text": f"{hit}/{len(planned)} smena"}
    if att:
        late = [a for a in att if a.late_minutes > tol]
        parts["punctuality"] = {"value": round(100 * (len(att) - len(late)) / len(att)),
                                "text": f"{len(late)} marta kechikdi" + (f" · o'rtacha {round(sum(a.late_minutes for a in late) / len(late))} daq" if late else "")}

    # --- o'qitish
    try:
        from modules.training.models import Enrollment, QuizAttempt
        ens = Enrollment.objects.filter(user=e.user, course__is_archived=False)
        n = ens.count()
        if n:
            done = ens.filter(status="completed").count()
            prog = ens.aggregate(p=Avg("progress"))["p"] or 0
            best = QuizAttempt.objects.filter(user=e.user, finished_at__isnull=False).aggregate(s=Avg("score"))["s"]
            val = round(0.6 * prog + 0.4 * (best if best is not None else prog))
            parts["training"] = {"value": val, "text": f"{done}/{n} kurs" + (f" · test {round(best)}%" if best is not None else "")}
    except Exception:
        pass

    # --- vazifalar
    try:
        from modules.tasks.models import ColumnKind, Task
        qs = Task.objects.live().filter(assignee=e.user, due_at__date__gte=start, due_at__date__lte=end)
        total = qs.count()
        if total:
            on_time = qs.filter(column__kind=ColumnKind.DONE).exclude(done_at__isnull=True).filter(done_at__lte=F("due_at")).count()
            done_late = qs.filter(column__kind=ColumnKind.DONE).count() - on_time
            parts["tasks"] = {"value": round(100 * (on_time + 0.5 * done_late) / total), "text": f"{on_time}/{total} muddatida"}
    except Exception:
        pass

    # --- rol ko'rsatkichi
    role = _role_part(e, start, end, ctx)
    if role:
        parts["role"] = role

    # --- menejer bahosi
    rv = Review.objects.filter(employee=e, period=start).order_by("-created_at").first()
    if rv and rv.average:
        parts["review"] = {"value": round((rv.average - 1) / 4 * 100), "text": f"{rv.average} / 5", "review_id": rv.pk}

    wsum = sum(WEIGHTS[k] for k in parts)
    score = round(sum(parts[k]["value"] * WEIGHTS[k] for k in parts) / wsum, 1) if wsum else None
    mood = ShiftFeedback.objects.filter(employee=e, date__gte=start, date__lte=end).aggregate(m=Avg("mood"), n=Count("id"))
    g = grade(score)
    base = int(e.rate if e.salary_type == "monthly" else 0)
    return {
        "score": score, "grade": g, "parts": {k: {**v, "label": LABELS[k], "weight": WEIGHTS[k]} for k, v in parts.items()},
        "mood": round(mood["m"], 2) if mood["m"] else None, "mood_count": mood["n"],
        "risk": bool(mood["m"] and mood["m"] < 2.5) or (parts.get("attendance", {}).get("value", 100) < 70),
        "bonus_suggest": int(base * (0.10 if g == "A" else 0.05 if g == "B" else 0)) if base else 0,
        "reviewed": rv is not None,
    }


def _role_part(e: Employee, start: date, end: date, ctx: dict) -> dict | None:
    from core.models import Membership
    roles = set(Membership.objects.filter(user=e.user).values_list("role__code", flat=True))
    if roles & {"cashier", "waiter"}:
        try:
            from modules.pos.models import Order
            qs = Order.objects.filter(cashier=e.user, created_at__date__gte=start, created_at__date__lte=end)
            paid = qs.filter(status="paid").aggregate(r=Sum("total"), n=Count("id"))
            n = paid["n"] or 0
            if not n:
                return None
            avg = (paid["r"] or 0) / n
            if "avg_all" not in ctx:
                al = Order.objects.filter(status="paid", paid_at__date__gte=start, paid_at__date__lte=end).aggregate(r=Sum("total"), n=Count("id"))
                ctx["avg_all"] = (al["r"] or 0) / al["n"] if al["n"] else avg
            idx = avg / ctx["avg_all"] if ctx["avg_all"] else 1
            cancelled = qs.filter(status="cancelled").count()
            cancel_rate = cancelled / (n + cancelled)
            val = max(0, min(100, 70 + (idx - 1) * 150 - cancel_rate * 400))
            return {"value": round(val), "text": f"{n} chek · o'rtacha {round(avg):,} ({round(idx * 100)}%)".replace(",", " ")
                    + (f" · {cancelled} bekor" if cancelled else "")}
        except Exception:
            return None
    if "cook" in roles:
        try:
            from modules.kds.models import Ticket
            ts = Ticket.objects.filter(cook=e.user, ready_at__isnull=False, started_at__isnull=False,
                                       ready_at__date__gte=start, ready_at__date__lte=end)
            n = ts.count()
            if not n:
                return None
            mins = sum((t.ready_at - t.started_at).total_seconds() for t in ts) / n / 60
            val = max(0, min(100, 100 - max(0, mins - 12) * 6))
            return {"value": round(val), "text": f"{n} buyurtma · o'rtacha {mins:.1f} daq"}
        except Exception:
            return None
    return None


def leaderboard(month: date, tenant=None, branch_id=None) -> list[dict]:
    ctx: dict = {}
    rows = []
    qs = Employee.objects.filter(is_active=True).select_related("user", "position", "branch")
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    for e in qs:
        k = compute(e, month, tenant, ctx)
        rows.append({"employee_id": e.pk, "user_id": str(e.user_id), "full_name": e.user.full_name or e.user.phone,
                     "avatar": e.user.avatar.url if e.user.avatar else None, "position": e.position.name if e.position_id else "",
                     "branch": e.branch.name if e.branch_id else "", **k})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    for i, r in enumerate(rows):
        r["rank"] = i + 1 if r["score"] is not None else None
    return rows
