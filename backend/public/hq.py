"""
RESTROOS HQ xizmatlari — platforma jamoasi uchun.

Statistika: har restoran sxemasidan kunlik yig'ma TenantStat ga yoziladi (bitta guruhlangan so'rov / restoran).
100+ restoranda ham HQ sahifasi tez ochiladi — jonli so'rov faqat bitta restoran kartasini ochganda.
Maxfiylik: daromad va chek faqat restoran «ma'lumot ulashish»ga rozi bo'lsa ko'rsatiladi (settings.platform.share_finance).
Kirish: egasi bergan vaqtinchalik ruxsat (SupportAccess) bo'lsagina, har kirish SupportSession + restoran audit jurnaliga yoziladi.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz

from django.core.cache import cache
from django.utils import timezone
from django_tenants.utils import schema_context

from .models import (
    HqAudit,
    Invoice,
    InvoiceStatus,
    SupportAccess,
    SupportSession,
    Tenant,
    TenantStat,
    Ticket,
    TicketPriority,
    TicketStatus,
)

STATS_DAYS = 35


def tenants_qs():
    return Tenant.objects.exclude(schema_name="public").select_related("plan")


def consent(t: Tenant) -> dict:
    p = (t.settings or {}).get("platform") or {}
    return {"share_finance": p.get("share_finance", True), "showcase": p.get("showcase", False)}


def primary_domain(t: Tenant) -> str:
    d = t.domains.filter(is_primary=True).first() or t.domains.first()
    return d.domain if d else ""


def audit(staff, action: str, tenant=None, **detail) -> None:
    HqAudit.objects.create(staff=staff, staff_name=(staff.user.full_name or staff.user.phone) if staff else "Tizim",
                           action=action, tenant=tenant, detail=detail)


# ------------------------------------------------------------------ statistika
def collect(t: Tenant, start: date | None = None, end: date | None = None) -> int:
    """[start, end] kunlari uchun TenantStat. Holat ko'rsatkichlari (xodim, filial…) — oxirgi kunga yoziladi."""
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncDate
    end = end or timezone.localdate()
    start = start or end - timedelta(days=STATS_DAYS - 1)
    rows: dict[date, dict] = {start + timedelta(days=i): {"revenue": 0, "orders": 0, "cost": 0, "top": []} for i in range((end - start).days + 1)}
    snap = {"employees": 0, "branches": 0, "customers": 0, "users": 0}
    with schema_context(t.schema_name):
        from core.models import Branch, Membership
        snap["branches"] = Branch.objects.filter(deleted_at__isnull=True, is_active=True).count()
        snap["users"] = Membership.objects.filter(is_active=True).values("user").distinct().count()
        try:
            from modules.hr.models import Employee
            snap["employees"] = Employee.objects.filter(is_active=True).count()
        except Exception:
            pass
        try:
            from modules.crm.models import Customer
            snap["customers"] = Customer.objects.count()
        except Exception:
            pass
        if t.module_enabled("pos"):
            from modules.pos.models import Order, OrderItem, OrderStatus
            paid = Order.objects.filter(status=OrderStatus.PAID, paid_at__date__gte=start, paid_at__date__lte=end)
            for r in paid.annotate(d=TruncDate("paid_at")).values("d").annotate(r=Sum("total"), n=Count("id"), c=Sum("cost_total")):
                if r["d"] in rows:
                    rows[r["d"]].update(revenue=int(r["r"] or 0), orders=r["n"] or 0, cost=int(r["c"] or 0))
            tops: dict[date, list] = defaultdict(list)
            for r in (OrderItem.objects.filter(order__in=paid).annotate(d=TruncDate("order__paid_at")).values("d", "name")
                      .annotate(q=Sum("qty")).order_by("d", "-q")):
                if len(tops[r["d"]]) < 8:
                    tops[r["d"]].append({"name": r["name"], "qty": int(r["q"] or 0)})
            for d, lst in tops.items():
                if d in rows:
                    rows[d]["top"] = lst
    for d, v in rows.items():
        extra = snap if d == end else {}
        TenantStat.objects.update_or_create(tenant=t, date=d, defaults={
            "revenue": v["revenue"], "orders": v["orders"], "cost": v["cost"], "top_products": v["top"], **extra})
    # oldingi kunlar uchun holat bo'sh qolmasin (grafik uchun) — oxirgi ma'lum qiymat
    TenantStat.objects.filter(tenant=t, date__gte=start, date__lt=end, employees=0).update(**snap)
    return len(rows)


def ensure_stats(force: bool = False) -> int:
    """Har restoran statistikasi 15 daqiqada bir yangilanadi (so'nggi 2 kun); bo'sh bo'lsa — 35 kunlik tarix."""
    n = 0
    today = timezone.localdate()
    for t in tenants_qs():
        key = f"hq_stats:{t.pk}"
        if not force and cache.get(key):
            continue
        has = TenantStat.objects.filter(tenant=t, date__gte=today - timedelta(days=STATS_DAYS - 1)).count()
        start = today - timedelta(days=1) if has >= STATS_DAYS - 1 else None
        try:
            collect(t, start=start, end=today)
            n += 1
        except Exception:
            pass
        cache.set(key, 1, 15 * 60)
    return n


def stats_by_tenant(days: int = 30) -> dict[int, dict]:
    today = timezone.localdate()
    out: dict[int, dict] = defaultdict(lambda: {"revenue": 0, "orders": 0, "cost": 0, "prev_revenue": 0, "last7": 0, "prev7": 0,
                                                "employees": 0, "branches": 0, "customers": 0, "users": 0, "last_order": None, "series": {}})
    for s in TenantStat.objects.filter(date__gte=today - timedelta(days=2 * days - 1)).order_by("date"):
        o = out[s.tenant_id]
        age = (today - s.date).days
        if age == 0:
            o["today"] = s.revenue
        if age < days:
            o["revenue"] += s.revenue
            o["orders"] += s.orders
            o["cost"] += s.cost
            if age > 0:                       # grafikda faqat to'liq kunlar (bugun hali tugamagan)
                o["series"][s.date.isoformat()] = s.revenue
        else:
            o["prev_revenue"] += s.revenue
        if age < 7:
            o["last7"] += s.revenue
        elif age < 14:
            o["prev7"] += s.revenue
        if s.orders:
            o["last_order"] = s.date
        if s.employees or s.branches:
            o.update(employees=s.employees, branches=s.branches, customers=s.customers, users=s.users)
    return out


# ------------------------------------------------------------------ billing
# Narx manbai: shartnoma (Contract) → bo'lmasa sayt narxi (SiteOffer: Dastur / Dastur+AI, restoran uchun).
# Valyutalar aralash bo'lishi mumkin (USD va so'm) — umumiy ko'rsatkichlar $ ekvivalentida (USD_UZS_RATE).
TARIFF_UZ = {"base": "Dastur", "ai": "Dastur + AI Kotib"}


def usd_rate() -> int:
    import os
    try:
        return max(1000, int(os.environ.get("USD_UZS_RATE", "12800")))
    except ValueError:
        return 12800


def to_usd(amount: int, currency: str) -> float:
    return amount if currency == "USD" else amount / usd_rate()


def contract_of(t: Tenant):
    from .models import Contract
    try:
        c = t.contract
    except Contract.DoesNotExist:
        return None
    return c if c.is_active else None


def _month_day(period: date, day: int) -> date:
    import calendar
    return period.replace(day=min(max(1, day), calendar.monthrange(period.year, period.month)[1]))


def terms(t: Tenant, branches: int | None = None) -> dict:
    """Restoranning oylik to'lov sharti: narx, valyuta, tarif, to'lov kuni, qachondan pullik."""
    from .models import SiteOffer
    branches = max(1, branches or 1)
    c = contract_of(t)
    if c:
        start = c.paid_from or (t.trial_ends_at.date() if t.trial_ends_at else None)
        return {"source": "contract", "tariff": c.tariff, "tariff_label": TARIFF_UZ[c.tariff], "amount": c.monthly(branches), "currency": c.currency,
                "billing_day": c.billing_day, "paid_from": start, "number": c.number}
    o = SiteOffer.get()
    ai = t.module_enabled("ai")
    return {"source": "site", "tariff": "ai" if ai else "base", "tariff_label": TARIFF_UZ["ai" if ai else "base"],
            "amount": o.ai_price if ai else o.base_price, "currency": "USD" if o.currency.strip() in ("$", "USD") else "UZS",
            "billing_day": 10, "paid_from": t.trial_ends_at.date() if t.trial_ends_at else None, "number": None}


def due_date_of(t: Tenant, period: date, tr: dict | None = None) -> date:
    tr = tr or terms(t)
    return _month_day(period, tr["billing_day"])


def ensure_invoices(period: date | None = None) -> int:
    """Oy uchun hisob: har faol restoran, pullik davri boshlangan bo'lsa. To'lanmagan joriy hisob shart o'zgarsa yangilanadi.
    Muddati o'tganlar «overdue» bo'ladi."""
    today = timezone.localdate()
    period = (period or today).replace(day=1)
    st = stats_by_tenant(7)
    n = 0
    for t in tenants_qs().filter(is_active=True).select_related("contract"):
        branches = max(1, st.get(t.pk, {}).get("branches") or 1)
        tr = terms(t, branches)
        due = due_date_of(t, period, tr)
        if tr["paid_from"] and tr["paid_from"] > due:  # hali bepul davr — avval avtomatik chiqqan to'lanmagan hisob bekor bo'ladi
            Invoice.objects.filter(tenant=t, period=period, status__in=[InvoiceStatus.PENDING, InvoiceStatus.OVERDUE], note="").update(
                status=InvoiceStatus.CANCELLED, note="bepul davr")
            continue
        inv, created = Invoice.objects.get_or_create(tenant=t, period=period, defaults={
            "plan_name": tr["tariff_label"], "branches": branches, "amount": tr["amount"], "currency": tr["currency"], "due_date": due})
        n += created
        if not created and inv.status in (InvoiceStatus.PENDING, InvoiceStatus.OVERDUE) and not inv.note and \
                (inv.amount, inv.currency, inv.plan_name) != (tr["amount"], tr["currency"], tr["tariff_label"]):
            # shart o'zgardi (tarif, narx, filiallar) — to'lanmagan hisob yangi shartga moslanadi (qo'lda o'zgartirilgan muddat saqlanadi)
            inv.amount, inv.currency, inv.plan_name, inv.branches = tr["amount"], tr["currency"], tr["tariff_label"], branches
            inv.save(update_fields=["amount", "currency", "plan_name", "branches"])
    Invoice.objects.filter(status=InvoiceStatus.PENDING, due_date__lt=today).update(status=InvoiceStatus.OVERDUE)
    return n


def mrr_series(months: int = 12) -> list[dict]:
    """Oylar bo'yicha hisoblangan summa ($ ekvivalenti)."""
    today = timezone.localdate().replace(day=1)
    out = []
    for i in range(months - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        p = date(y, m, 1)
        amt = sum(to_usd(a, c) for a, c in Invoice.objects.filter(period=p).exclude(status=InvoiceStatus.CANCELLED).values_list("amount", "currency"))
        out.append({"period": p.isoformat(), "label": ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"][m - 1], "amount": round(amt)})
    return out


def upcoming(days: int = 45) -> list[dict]:
    """To'lov kalendari: muddati o'tgan va yaqin hisoblar + sinovi tugab, pullik davri boshlanadiganlar."""
    today = timezone.localdate()
    out = []
    for i in Invoice.objects.filter(status__in=[InvoiceStatus.PENDING, InvoiceStatus.OVERDUE], due_date__lte=today + timedelta(days=days)).select_related("tenant"):
        late = (today - i.due_date).days if i.due_date else 0
        out.append({"kind": "invoice", "invoice_id": i.pk, "tenant_id": i.tenant_id, "tenant": i.tenant.name, "region": i.tenant.region,
                    "date": i.due_date.isoformat() if i.due_date else None, "amount": i.amount, "currency": i.currency, "tariff": i.plan_name,
                    "state": "overdue" if late > 0 else ("today" if late == 0 else "soon"), "days": -late})
    have = {(x["tenant_id"]) for x in out}
    st = stats_by_tenant(7)
    for t in tenants_qs().filter(is_active=True).select_related("contract"):
        if t.pk in have:
            continue
        tr = terms(t, st.get(t.pk, {}).get("branches") or 1)
        start = tr["paid_from"]
        if start is None or start < today or start > today + timedelta(days=days):
            continue
        first = due_date_of(t, start.replace(day=1), tr)
        if first < start:                               # birinchi to'lov — keyingi oyning to'lov kunida
            nm = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
            first = due_date_of(t, nm, tr)
        out.append({"kind": "trial_end", "tenant_id": t.pk, "tenant": t.name, "region": t.region, "date": first.isoformat(), "trial_end": start.isoformat(),
                    "amount": tr["amount"], "currency": tr["currency"], "tariff": tr["tariff_label"], "state": "trial", "days": (first - today).days})
    return sorted(out, key=lambda x: (x["date"] or "9999", x["tenant"]))


def money_totals(rows) -> dict:
    """{"USD": 450, "UZS": 980000, "usd_eq": 526.6}"""
    out: dict = defaultdict(int)
    for amount, cur in rows:
        out[cur] += amount
    out["usd_eq"] = round(sum(to_usd(v, k) for k, v in list(out.items()) if k in ("USD", "UZS")), 1)
    return dict(out)


def daily_tick(force: bool = False) -> dict | None:
    """Kuniga bir marta (09:00 dan keyin): hisoblarni yangilash va HQ Telegram chatiga qisqa xulosa — kim bugun/kechikib to'lashi kerak,
    muddati o'tgan murojaatlar."""
    now = timezone.localtime()
    key = f"hq_daily:{now.date().isoformat()}"
    if not force and (now.hour < 9 or cache.get(key)):
        return None
    cache.set(key, 1, 26 * 3600)
    ensure_invoices()
    up = upcoming(3)
    late_t = Ticket.objects.exclude(status=TicketStatus.CLOSED).filter(due_at__lt=timezone.now()).count()
    lines = []
    for x in up:
        cur = "$" if x["currency"] == "USD" else " so'm"
        amt = f"{x['amount']:,}".replace(",", " ")
        if x["state"] == "overdue":
            lines.append(f"🔴 {x['tenant']} — {amt}{cur}, {-x['days']} kun kechikdi")
        elif x["state"] == "today":
            lines.append(f"🟠 {x['tenant']} — {amt}{cur}, bugun")
        elif x["state"] == "trial":
            lines.append(f"🔵 {x['tenant']} — sinov tugaydi, birinchi to'lov {x['date'][8:10]}.{x['date'][5:7]}")
        else:
            lines.append(f"🟡 {x['tenant']} — {amt}{cur}, {x['date'][8:10]}.{x['date'][5:7]}")
    if late_t:
        lines.append(f"🛠 Muddati o'tgan murojaatlar: {late_t} ta")
    if lines:
        try:
            from website.sales_ai import notify
            notify("📅 <b>Bugungi to'lovlar va vazifalar</b>\n" + "\n".join(lines[:25]))
        except Exception:
            pass
    return {"lines": lines}


# ------------------------------------------------------------------ holat (sog'lom / e'tibor / kritik)
def health(t: Tenant, s: dict, open_tickets: list, invoices: list) -> tuple[str, list[str]]:
    today = timezone.localdate()
    crit, warn = [], []
    if not t.is_active:
        crit.append("To'xtatilgan")
    if any(i.status == InvoiceStatus.OVERDUE and i.due_date and (today - i.due_date).days > 15 for i in invoices):
        crit.append("To'lov 15 kundan ortiq kechikkan")
    elif any(i.status == InvoiceStatus.OVERDUE for i in invoices):
        warn.append("To'lov muddati o'tgan")
    if any(tk.priority == TicketPriority.CRITICAL for tk in open_tickets):
        crit.append("Kritik murojaat ochiq")
    age_days = (timezone.now() - t.created_at).days if t.created_at else 99
    last = s.get("last_order")
    if age_days > 7 and last is None:
        crit.append("7 kundan beri savdo yo'q") if s.get("prev_revenue") else warn.append("Hali savdo boshlanmagan")
    elif last and (today - last).days >= 3:
        warn.append(f"{(today - last).days} kundan beri savdo yo'q")
    if s.get("prev7") and s.get("last7", 0) < 0.7 * s["prev7"]:
        warn.append(f"Savdo haftalik {round(100 * (s['last7'] - s['prev7']) / s['prev7'])}%")
    if t.trial_ends_at and 0 <= (t.trial_ends_at - timezone.now()).days <= 3:
        warn.append("Sinov muddati tugayapti")
    if crit:
        return "critical", crit + warn
    if warn:
        return "warning", warn
    return "healthy", []


def status_of(t: Tenant) -> str:
    if not t.is_active:
        return "stopped"
    if t.trial_ends_at and t.trial_ends_at > timezone.now():
        return "trial"
    return "active"


# ------------------------------------------------------------------ kirish ruxsati
def active_access(t: Tenant) -> SupportAccess | None:
    return SupportAccess.objects.filter(tenant=t, revoked_at__isnull=True, until__gt=timezone.now()).first()


def impersonate(t: Tenant, staff, reason: str) -> dict:
    """Egasi ruxsat bergan bo'lsa — restoran paneliga «Platforma yordami» nomidan vaqtinchalik token."""
    import jwt
    from django.conf import settings

    from .models import DIRECT_ROLES
    acc = active_access(t)
    direct = staff.role in DIRECT_ROLES
    if acc is None and not direct:
        raise PermissionError("Restoran egasi hozir kirishga ruxsat bermagan. «Ruxsat so'rash» tugmasini bosing.")
    until = acc.until if acc else timezone.now() + timedelta(hours=8)
    with schema_context(t.schema_name):
        from core.models import AuditLog, Membership, Role, User
        role, _ = Role.objects.get_or_create(code="platform_support", defaults={"name": "Platforma yordami", "permissions": ["*"], "is_system": True, "level": 1000})
        u, _ = User.objects.get_or_create(phone="+998000000001", defaults={"full_name": "Platforma yordami"})
        Membership.objects.get_or_create(user=u, defaults={"role": role})
        AuditLog.objects.create(actor=u, action="support_login", model="Platforma",
                                after={"staff": staff.user.full_name or staff.user.phone, "role": staff.role, "reason": reason, "until": until.isoformat(), "direct": direct})
        now = datetime.now(dt_tz.utc)
        exp = min(until, timezone.now() + timedelta(hours=8 if direct else 2))
        token = jwt.encode({"sub": str(u.pk), "sch": t.schema_name, "iat": int(now.timestamp()), "exp": int(exp.timestamp()), "support": True},
                           settings.JWT_SECRET, algorithm="HS256")
    SupportSession.objects.create(tenant=t, staff=staff, staff_name=staff.user.full_name or staff.user.phone, reason=reason)
    audit(staff, "impersonate", t, reason=reason)
    return {"token": token, "url": f"{tenant_base(t)}/admin/?support_token={token}", "until": exp.isoformat()}


def tenant_base(t: Tenant) -> str:
    from django.conf import settings
    d = primary_domain(t)
    return f"http://{d}:8000" if settings.DEBUG and d.endswith("localhost") else f"https://{d}"


def open_ticket_counts() -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    for tk in Ticket.objects.exclude(status=TicketStatus.CLOSED).filter(tenant__isnull=False):
        out[tk.tenant_id].append(tk)
    return out
