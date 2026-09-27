"""
Bo'lim panellari — /api/v1/dashboard/sections
Har bo'lim (Savdo, Menyu va mijozlar, Ombor va xarid, Xodimlar, O'qitish, Vazifa va loyihalar, Moliya, Sozlamalar) uchun
3–5 ta asosiy ko'rsatkich: qiymat, izoh, rang (ok / warn / bad) va qaysi sahifaga olib borishi.
Modul o'chiq yoki ruxsat bo'lmasa — o'sha ko'rsatkich chiqmaydi. Bir blokdagi xato boshqasini to'xtatmaydi.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

log = logging.getLogger(__name__)


def _m(v: int | float) -> str:
    v = int(v or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",") + " mln"
    return f"{v:,}".replace(",", " ")


def _k(label, value, hint="", tone="", route="", icon=""):
    return {"label": label, "value": value, "hint": hint, "tone": tone, "route": route, "icon": icon}


def sections(request, branch_id: int | None = None) -> dict:
    from .branchf import make
    t, u = request.tenant, request.auth
    S, L = make(branch_id)
    on = set(t.enabled_modules or [])
    can = u.has_perm_code
    today = timezone.localdate()
    ms = today.replace(day=1)
    out: dict[str, list] = {}

    def block(code, fn):
        try:
            rows = [r for r in fn() if r]
            if rows:
                out[code] = rows
        except Exception:
            log.exception("bo'lim paneli: %s", code)

    # ---------- Savdo va xizmat
    def sales():
        from modules.pos.models import Order
        rows = []
        if "pos" in on and (can("pos.sell") or can("finance.view")):
            q = S(Order.objects.filter(status="paid", paid_at__date=today))
            s = int(q.aggregate(s=Sum("total"))["s"] or 0)
            n = q.count()
            y = int(S(Order.objects.filter(status="paid", paid_at__date=today - timedelta(days=7),
                                           paid_at__time__lte=timezone.localtime().time())).aggregate(s=Sum("total"))["s"] or 0)
            d = round(100 * (s - y) / y) if y else None
            rows += [_k("Bugungi savdo", _m(s), f"{n} ta chek" + (f" · o'tgan haftaga {d:+d}%" if d is not None else ""), "ok" if (d or 0) >= 0 else "warn", "/pos", "💰"),
                     _k("O'rtacha chek", _m(s // n if n else 0), "so'm", "", "/reports", "🧾")]
        if "kds" in on:
            from modules.kds.models import Ticket
            act = S(Ticket.objects.exclude(status__in=["served", "cancelled"]), "order__branch")
            ready = act.filter(status="ready").count()
            rows.append(_k("Oshxonada hozir", act.count(), f"{ready} tasi tayyor — olib chiqish kerak" if ready else "hammasi jarayonda", "warn" if ready else "", "/kds", "👨‍🍳"))
        if "tables" in on:
            from modules.tables.models import Table, TableSession
            busy = L(TableSession.objects.filter(closed_at__isnull=True), "table__branch").count()
            tot = L(Table.objects.filter(is_active=True)).count()
            rows.append(_k("Band stollar", f"{busy} / {tot}", "zal xaritasi", "", "/tables", "🪑"))
        if "reservations" in on:
            from modules.reservations.models import Reservation
            r = L(Reservation.objects.filter(starts_at__date=today).exclude(status__in=["cancelled", "no_show"]))
            rows.append(_k("Bugungi bronlar", r.count(), f"{r.aggregate(g=Sum('guests'))['g'] or 0} mehmon", "", "/reservations", "📅"))
        return rows
    block("sales", sales)

    # ---------- Menyu va mijozlar
    def menu():
        rows = []
        if "catalog" in on:
            from modules.catalog.models import Product
            ps = Product.objects.filter(deleted_at__isnull=True, is_active=True)
            stop = ps.filter(in_stop_list=True).count()
            rows.append(_k("Taomlar", ps.count(), f"{stop} tasi stop-listda" if stop else "hammasi sotuvda", "warn" if stop else "", "/catalog", "🍽️"))
        if "pos" in on:
            from modules.pos.models import OrderItem
            top = (S(OrderItem.objects.filter(order__status="paid", order__paid_at__date__gte=today - timedelta(days=6)), "order__branch")
                   .values("name").annotate(q=Sum("qty")).order_by("-q").first())
            if top:
                rows.append(_k("Hafta xiti", top["name"], f"{top['q']} porsiya (7 kun)", "", "/reports", "🔥"))
        if "crm" in on and can("crm.view"):
            from modules.crm.models import Customer
            new = Customer.objects.filter(created_at__date__gte=today - timedelta(days=29)).count()
            rows.append(_k("Mijozlar", Customer.objects.count(), f"+{new} yangi (30 kun)", "ok" if new else "", "/crm", "❤️"))
        if "telegram" in on and can("telegram.view"):
            from modules.telegram.models import BotUser
            rows.append(_k("Telegram obunachilar", BotUser.objects.filter(is_blocked=False).count(), "botdagi mijozlar", "", "/telegram", "✈️"))
        return rows
    block("menu", menu)

    # ---------- Ombor va xarid
    def stock():
        rows = []
        if "inventory" in on and can("inventory.view"):
            from modules.inventory.models import Ingredient, Purchase
            ings = list(Ingredient.objects.filter(deleted_at__isnull=True, is_active=True))
            val = sum(float(i.stock) * float(i.price) for i in ings if i.stock > 0)
            low = [i for i in ings if i.is_low]
            rows.append(_k("Ombor qiymati", _m(val), f"{len(ings)} xil xomashyo", "", "/inventory", "📦"))
            rows.append(_k("Kam qolgan", len(low), ", ".join(str(i) for i in low[:3]) or "hammasi yetarli", "bad" if len(low) > 3 else "warn" if low else "ok",
                           "/inventory", "⚠️"))
            mp = int(L(Purchase.objects.filter(date__gte=ms)).aggregate(s=Sum("total"))["s"] or 0)
            rows.append(_k("Shu oy xarid", _m(mp), "kirimlar jami", "", "/procurement" if "procurement" in on else "/inventory", "🛒"))
        if "procurement" in on and can("procurement.view"):
            from modules.procurement.models import Order as PO
            from modules.procurement.models import Trip
            from modules.procurement.services import debts
            dd = debts().values()
            debt = sum(x["debt"] for x in dd)
            over = sum(1 for x in dd if x["overdue"])
            rows.append(_k("Ta'minotchilarga qarz", _m(debt), f"{over} tasi muddati o'tgan" if over else "muddati o'tgani yo'q", "bad" if over else "", "/procurement?tab=debts", "💳"))
            way = L(PO.objects.filter(status__in=["sent", "confirmed"])).count()
            trips = L(Trip.objects.filter(status__in=["planned", "active"])).count()
            rows.append(_k("Yo'ldagi zakup", way, f"{trips} ta ochiq bozorlik" if trips else "buyurtmalar", "", "/procurement?tab=orders", "🚚"))
        return rows
    block("stock", stock)

    # ---------- Xodimlar
    def team():
        rows = []
        if "hr" in on and can("hr.view"):
            from modules.hr.models import Attendance, Employee, ShiftPlan
            emps = L(Employee.objects.filter(is_active=True))
            att = L(Attendance.objects.filter(check_in__date=today))
            planned = L(ShiftPlan.objects.filter(date=today)).count()
            late = att.filter(late_minutes__gt=0).count()
            rows.append(_k("Xodimlar", emps.count(), f"{emps.values('position').distinct().count()} lavozimda", "", "/hr", "👥"))
            rows.append(_k("Bugun ishda", f"{att.values('employee').distinct().count()} / {planned}", "keldi / smenada", "", "/hr", "🕘"))
            rows.append(_k("Kechikishlar", late, "bugun" if late else "bugun hamma o'z vaqtida", "warn" if late else "ok", "/hr", "⏰"))
            if can("hr.recruit"):
                from modules.hr.models import Application, Vacancy
                vac = L(Vacancy.objects.filter(status="open")).count()
                apps = Application.objects.exclude(stage__in=["hired", "rejected"]).count()
                rows.append(_k("Ishga olish", f"{vac} vakansiya", f"{apps} nomzod jarayonda", "", "/recruiting", "📣"))
        return rows
    block("team", team)

    # ---------- O'qitish va standartlar
    def training():
        rows = []
        if "training" in on:
            from modules.training.models import Course, Enrollment, Standard, StandardAck, Submission
            en = Enrollment.objects.filter(course__is_archived=False)
            tot = en.count()
            done = en.filter(status="completed").count()
            late = sum(1 for e in en.exclude(status="completed").only("status", "due_at") if e.due_at and e.due_at < timezone.now())
            rows.append(_k("Kurslar", Course.objects.filter(is_published=True, is_archived=False).count(), f"{tot} ta biriktirish", "", "/training?tab=courses", "🎓"))
            rows.append(_k("Tugatganlar", f"{round(100 * done / tot) if tot else 0}%", f"{done} / {tot} kurs yakunlangan", "ok" if tot and done / tot > 0.6 else "warn", "/training?tab=report", "✅"))
            rows.append(_k("Kechikkan o'qish", late, "muddati o'tgan kurslar" if late else "kechikkan yo'q", "bad" if late else "ok", "/training?tab=report", "⏳"))
            chk = Submission.objects.filter(status="submitted").count()
            rows.append(_k("Tekshirish kerak", chk, "topshiriq dalillari", "warn" if chk else "", "/training?tab=assignments", "📸"))
            stds = Standard.objects.count()
            if stds:
                rows.append(_k("Standartlar", stds, f"{StandardAck.objects.count()} ta imzo", "", "/training?tab=standards", "🛡️"))
        if "ops" in on and can("ops.view"):
            from modules.ops.models import PositionProfile
            rows.append(_k("Lavozim yo'riqnomalari", PositionProfile.objects.count(), "tashkiliy tuzilmada", "", "/positions", "🗂️"))
        return rows
    block("training", training)

    # ---------- Vazifa va loyihalar
    def work():
        rows = []
        if "tasks" in on and can("tasks.view"):
            from modules.tasks.models import ColumnKind, Task
            op = L(Task.objects.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]))
            over = op.filter(due_at__lt=timezone.now()).count()
            rows.append(_k("Ochiq vazifalar", op.count(), f"{over} tasi kechikkan" if over else "kechikkan yo'q", "bad" if over else "ok", "/tasks", "📋"))
            done = L(Task.objects.filter(done_at__date=today)).count()
            rows.append(_k("Bugun bajarildi", done, "vazifa", "ok" if done else "", "/tasks", "✔️"))
        if "projects" in on and can("projects.view"):
            from modules.projects import services as ps
            live = [p for p in L(ps.visible_projects(u)).filter(status__in=["plan", "active"]).prefetch_related("tasks")]
            risk = 0
            for p in live:
                tasks = list(p.tasks.all())
                prog = ps.progress(tasks, p.status)
                over = sum(1 for x in tasks if x.due and x.due < today and x.status != "done")
                if ps.health(p, prog, over, 25, ps.planned_progress(p, tasks)) in ("risk", "late"):
                    risk += 1
            rows.append(_k("Faol loyihalar", len(live), f"{risk} tasi xavf ostida" if risk else "hammasi o'z vaqtida", "warn" if risk else "ok", "/projects", "🚩"))
        return rows
    block("work", work)

    # ---------- Moliya
    def finance():
        rows = []
        if "finance" in on and can("finance.view") and "pos" in on:
            from modules.pos.models import Order
            q = S(Order.objects.filter(status="paid", paid_at__date__gte=ms))
            agg = q.aggregate(s=Sum("total"), c=Sum("cost_total"))
            rev, cost = int(agg["s"] or 0), int(agg["c"] or 0)
            from modules.finance.models import Expense
            exp = int(L(Expense.objects.filter(date__gte=ms)).aggregate(s=Sum("amount"))["s"] or 0)
            fc = round(100 * cost / rev, 1) if rev else 0
            rows.append(_k("Shu oy savdo", _m(rev), f"{q.count()} ta chek", "", "/reports", "📈"))
            rows.append(_k("Food cost", f"{fc}%", "me'yor 28–35%", "ok" if 0 < fc <= 35 else "warn", "/reports", "🥘"))
            rows.append(_k("Xarajatlar (oy)", _m(exp), "ijara, kommunal, soliq…", "", "/reports", "💸"))
            rows.append(_k("Yalpi foyda", _m(rev - cost - exp), "savdo − tannarx − xarajat", "ok" if rev - cost - exp > 0 else "bad", "/reports", "💵"))
        return rows
    block("finance", finance)

    # ---------- Sozlamalar
    def settings_():
        from core.models import Branch, Membership
        rows = [_k("Filiallar", Branch.objects.filter(deleted_at__isnull=True, is_active=True).count(), "faol", "", "/branches", "🏪")]
        if can("core.users.manage"):
            rows.append(_k("Foydalanuvchilar", Membership.objects.filter(is_active=True).values("user").distinct().count(), "tizimga kira oladi", "", "/users", "👤"))
        rows.append(_k("Yoqilgan modullar", len(on), "tarifingiz bo'yicha", "", "/modules", "🧩"))
        if t.trial_ends_at and t.trial_ends_at > timezone.now():
            left = timezone.localtime(t.trial_ends_at).date() - today
            rows.append(_k("Sinov muddati", f"{max(0, left.days)} kun", "qoldi", "warn" if left.days < 7 else "", "/support", "⏳"))
        return rows
    block("settings", settings_)
    return out
