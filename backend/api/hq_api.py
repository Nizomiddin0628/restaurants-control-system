"""
RESTROOS HQ API — platforma domenida /api/v1/hq/... (faqat platforma jamoasi).

Kirish: telefon + kod (faqat PlatformStaff ro'yxatidagi raqamlar). Token public sxemaga bog'langan —
restoran domenida ishlamaydi, restoran tokeni esa bu yerda ishlamaydi.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Optional

import jwt
from django.conf import settings
from django.db import connection
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_tenants.utils import schema_context
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import HttpBearer

from core.auth import issue_token
from core.models import OtpCode, User
from core.modules import all_modules
from integrations.sms import send_otp
from public import hq
from public.models import (
    DIRECT_ROLES,
    TOP_ROLES,
    FeatureFlag,
    HqAudit,
    Invoice,
    InvoiceStatus,
    Plan,
    PlatformStaff,
    Release,
    StaffRole,
    SupportSession,
    Tenant,
    TenantStat,
    Ticket,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from public.services import set_modules

router = Router(tags=["hq"])


class HqAuth(HttpBearer):
    def authenticate(self, request, token: str):
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError:
            return None
        if payload.get("sch") != "public" or connection.schema_name != "public":
            return None
        staff = PlatformStaff.objects.select_related("user").filter(user_id=payload.get("sub"), is_active=True, user__is_active=True).first()
        if staff is None:
            return None
        request.staff = staff
        return staff.user


hq_auth = HqAuth()


def _need(request, *roles: str):
    if request.staff.role not in TOP_ROLES and request.staff.role not in roles:
        raise HttpError(403, "Bu amal uchun huquqingiz yo'q.")


def _money_ok(t: Tenant) -> bool:
    return hq.consent(t)["share_finance"]


# ------------------------------------------------------------------ kirish
class OtpIn(Schema):
    phone: str


class VerifyIn(Schema):
    phone: str
    code: str


def _staff_out(s: PlatformStaff) -> dict:
    return {"id": s.pk, "name": s.user.full_name or s.user.phone, "phone": s.user.phone, "role": s.role, "role_label": StaffRole(s.role).label}


@router.post("/auth/otp")
def otp(request, data: OtpIn):
    phone = User.objects.normalize_phone(data.phone)
    if not PlatformStaff.objects.filter(user__phone=phone, is_active=True).exists():
        raise HttpError(404, "Bu raqam platforma jamoasida yo'q.")
    import os
    if not (settings.OTP_DEV_ECHO or os.environ.get("SMS_PROVIDER") == "eskiz"):
        raise HttpError(400, "Kod yuborish xizmati ulanmagan — parol bilan kiring.")
    code = OtpCode.issue(phone, purpose="hq")
    send_otp(phone, code.code)
    out = {"ok": True}
    if settings.OTP_DEV_ECHO:
        out["dev_code"] = code.code
    return out


class PwIn(Schema):
    phone: str
    password: str


@router.post("/auth/login")
def hq_login(request, data: PwIn):
    """Platforma jamoasi: telefon + parol (parolni serverda beriladi: restopos-manage seed_hq --phone … --password …)."""
    from django.core.cache import cache
    phone = User.objects.normalize_phone(data.phone)
    key = f"hqpw:{phone}"
    if (cache.get(key) or 0) >= 8:
        raise HttpError(429, "Juda ko'p noto'g'ri urinish — 15 daqiqadan keyin urinib ko'ring.")
    staff = PlatformStaff.objects.select_related("user").filter(user__phone=phone, is_active=True).first()
    if staff is None or not staff.user.has_usable_password() or not staff.user.check_password(data.password):
        cache.set(key, (cache.get(key) or 0) + 1, 900)
        raise HttpError(400, "Telefon yoki parol noto'g'ri.")
    cache.delete(key)
    hq.audit(staff, "login")
    return {"token": issue_token(staff.user, "public"), "staff": _staff_out(staff)}


@router.get("/auth/methods")
def hq_methods(request):
    """Kod bilan kirish faqat SMS ulangan yoki sinov rejimida (aks holda — parol)."""
    import os
    return {"code": bool(settings.OTP_DEV_ECHO or os.environ.get("SMS_PROVIDER") == "eskiz")}


@router.post("/auth/verify")
def verify(request, data: VerifyIn):
    phone = User.objects.normalize_phone(data.phone)
    otp_ = OtpCode.objects.filter(phone=phone, used_at__isnull=True, purpose="hq").order_by("-created_at").first()
    if not otp_ or not otp_.is_valid(settings.OTP_TTL_SECONDS):
        raise HttpError(400, "Kod muddati tugagan, qaytadan so'rang.")
    if otp_.code != data.code:
        otp_.attempts += 1
        otp_.save(update_fields=["attempts"])
        raise HttpError(400, "Kod noto'g'ri.")
    otp_.used_at = timezone.now()
    otp_.save(update_fields=["used_at"])
    staff = PlatformStaff.objects.select_related("user").get(user__phone=phone, is_active=True)
    hq.audit(staff, "login")
    return {"token": issue_token(staff.user, "public"), "staff": _staff_out(staff)}


@router.get("/me", auth=hq_auth)
def me(request):
    return {**_staff_out(request.staff), "platform": settings.PLATFORM_NAME}


# ------------------------------------------------------------------ bosh sahifa
@router.get("/overview", auth=hq_auth)
def overview(request):
    hq.ensure_stats()
    hq.ensure_invoices()
    today = timezone.localdate()
    tenants = list(hq.tenants_qs())
    st = hq.stats_by_tenant(30)
    tickets = hq.open_ticket_counts()
    inv = defaultdict(list)
    for i in Invoice.objects.filter(period__gte=today.replace(day=1) - timedelta(days=62)):
        inv[i.tenant_id].append(i)
    health = Counter()
    rows = []
    for t in tenants:
        s = st.get(t.pk, {})
        level, reasons = hq.health(t, s, tickets.get(t.pk, []), inv.get(t.pk, []))
        health[level] += 1
        rows.append((t, s, level, reasons))
    share = [t for t in tenants if _money_ok(t)]
    rev = sum(st.get(t.pk, {}).get("revenue", 0) for t in share)
    prev = sum(st.get(t.pk, {}).get("prev_revenue", 0) for t in share)
    orders = sum(st.get(t.pk, {}).get("orders", 0) for t in share)
    mrr = hq.mrr_series(12)
    new_month = sum(1 for t in tenants if t.created_at and t.created_at.date() >= today.replace(day=1))
    # platforma bo'yicha eng ko'p sotiladiganlar (rozilik berganlar)
    top = Counter()
    for s_ in TenantStat.objects.filter(date__gte=today - timedelta(days=29), tenant__in=share).only("top_products"):
        for p in s_.top_products or []:
            top[p["name"]] += p["qty"]
    daily = defaultdict(int)
    for s_ in TenantStat.objects.filter(date__gte=today - timedelta(days=29), tenant__in=share).only("date", "revenue"):
        daily[s_.date] += s_.revenue
    return {
        "kpis": {
            "clients": len(tenants), "clients_new": new_month,
            "branches": sum(st.get(t.pk, {}).get("branches", 0) for t in tenants),
            "employees": sum(st.get(t.pk, {}).get("employees", 0) for t in tenants),
            "users": sum(st.get(t.pk, {}).get("users", 0) for t in tenants),
            "mrr": mrr[-1]["amount"], "mrr_prev": mrr[-2]["amount"] if len(mrr) > 1 else 0,
            "revenue_30d": rev, "revenue_delta": round(100 * (rev - prev) / prev, 1) if prev else None,
            "orders_30d": orders, "avg_check": rev // orders if orders else 0,
            "customers": sum(st.get(t.pk, {}).get("customers", 0) for t in tenants),
            "share_count": len(share), "open_tickets": sum(len(v) for v in tickets.values()),
        },
        "mrr": mrr,
        "health": {"healthy": health["healthy"], "warning": health["warning"], "critical": health["critical"]},
        "attention": [{"id": t.pk, "name": t.name, "level": lv, "reasons": rs} for t, s, lv, rs in rows if lv != "healthy"][:8],
        "top_products": [{"name": n, "qty": q} for n, q in top.most_common(8)],
        "daily": [{"date": (today - timedelta(days=i)).isoformat(), "revenue": daily.get(today - timedelta(days=i), 0)} for i in range(30, 0, -1)],
        "top_clients": sorted([{"id": t.pk, "name": t.name, "revenue": s.get("revenue", 0), "branches": s.get("branches", 0)}
                               for t, s, _, _ in rows if _money_ok(t)], key=lambda x: -x["revenue"])[:5],
        "activity": [{"at": a.at.isoformat(), "who": a.staff_name, "action": a.action, "tenant": a.tenant.name if a.tenant_id else None}
                     for a in HqAudit.objects.select_related("tenant")[:8]],
        "upcoming": hq.upcoming(14)[:8],
        "regions": hq_ops.regions_summary(request)["items"][:8],
        "late_tickets": Ticket.objects.exclude(status=TicketStatus.CLOSED).filter(due_at__lt=timezone.now()).count(),
    }


# ------------------------------------------------------------------ mijozlar (restoranlar)
STATUS_UZ = {"active": "Faol", "trial": "Sinov", "stopped": "To'xtatilgan"}


def _tenant_row(t: Tenant, s: dict, level: str, reasons: list, tickets: list) -> dict:
    money = _money_ok(t)
    return {"id": t.pk, "name": t.name, "slug": t.slug, "domain": hq.primary_domain(t), "preset": t.preset,
            "plan": t.plan.name if t.plan else "—", "plan_code": t.plan.code if t.plan else None,
            "status": hq.status_of(t), "status_label": STATUS_UZ[hq.status_of(t)], "health": level, "reasons": reasons,
            "branches": s.get("branches", 0), "employees": s.get("employees", 0), "users": s.get("users", 0), "customers": s.get("customers", 0),
            "revenue_30d": s.get("revenue", 0) if money else None, "orders_30d": s.get("orders", 0) if money else None,
            "trend": round(100 * (s.get("last7", 0) - s.get("prev7", 0)) / s["prev7"], 1) if money and s.get("prev7") else None,
            "last_order": s["last_order"].isoformat() if s.get("last_order") else None, "shares_finance": money,
            "owner_phone": t.owner_phone, "created_at": t.created_at.isoformat() if t.created_at else None,
            "trial_ends_at": t.trial_ends_at.isoformat() if t.trial_ends_at else None,
            "open_tickets": len(tickets), "access_until": (a.until.isoformat() if (a := hq.active_access(t)) else None),
            "region": t.region, "district": t.district, **_terms_short(t, s.get("branches", 0))}


def _terms_short(t: Tenant, branches: int) -> dict:
    tr = hq.terms(t, branches)
    return {"tariff": tr["tariff"], "tariff_label": tr["tariff_label"], "price": tr["amount"], "currency": tr["currency"],
            "billing_day": tr["billing_day"], "contract_no": tr["number"], "paid_from": tr["paid_from"].isoformat() if tr["paid_from"] else None}


@router.get("/tenants", auth=hq_auth)
def tenants(request, q: Optional[str] = None, status: Optional[str] = None, health: Optional[str] = None, plan: Optional[str] = None,
            region: Optional[str] = None, tariff: Optional[str] = None):
    hq.ensure_stats()
    st = hq.stats_by_tenant(30)
    tickets = hq.open_ticket_counts()
    today = timezone.localdate()
    inv = defaultdict(list)
    for i in Invoice.objects.filter(period__gte=today.replace(day=1) - timedelta(days=62)):
        inv[i.tenant_id].append(i)
    qs = hq.tenants_qs()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q) | Q(owner_phone__icontains=q))
    if plan:
        qs = qs.filter(plan__code=plan)
    if region:
        qs = qs.filter(region="" if region == "-" else region)
    qs = qs.select_related("contract")
    out = []
    for t in qs:
        s = st.get(t.pk, {})
        level, reasons = hq.health(t, s, tickets.get(t.pk, []), inv.get(t.pk, []))
        r = _tenant_row(t, s, level, reasons, tickets.get(t.pk, []))
        if (status and r["status"] != status) or (health and r["health"] != health) or (tariff and r["tariff"] != tariff):
            continue
        out.append(r)
    regions = sorted({r for r in hq.tenants_qs().values_list("region", flat=True) if r})
    return {"items": out, "regions": regions,
            "plans": [{"code": p.code, "name": p.name, "price_per_branch": p.price_per_branch} for p in Plan.objects.filter(is_active=True)]}


def _branches_live(t: Tenant) -> list[dict]:
    """Bitta restoran kartasi uchun jonli: har filial savdosi (30 kun), xodimlar, oxirgi buyurtma."""
    from django.db.models import Max, Sum
    today = timezone.localdate()
    out = []
    with schema_context(t.schema_name):
        from core.models import Branch
        emp = Counter()
        try:
            from modules.hr.models import Employee
            emp = Counter(Employee.objects.filter(is_active=True).values_list("branch_id", flat=True))
        except Exception:
            pass
        agg = {}
        if t.module_enabled("pos"):
            from modules.pos.models import Order, OrderStatus
            for r in (Order.objects.filter(status=OrderStatus.PAID, paid_at__date__gte=today - timedelta(days=29))
                      .values("branch_id").annotate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"), last=Max("paid_at"))):
                agg[r["branch_id"]] = r
        for b in Branch.objects.filter(deleted_at__isnull=True):
            a = agg.get(b.pk, {})
            rev, n = int(a.get("r") or 0), a.get("n") or 0
            out.append({"id": b.pk, "name": b.name, "address": b.address, "phone": b.phone, "is_active": b.is_active,
                        "lat": float(b.lat) if b.lat is not None else None, "lng": float(b.lng) if b.lng is not None else None,
                        "employees": emp.get(b.pk, 0), "revenue_30d": rev, "orders_30d": n, "avg_check": rev // n if n else 0,
                        "food_cost": round(100 * int(a.get("c") or 0) / rev, 1) if rev else None,
                        "last_order": timezone.localtime(a["last"]).isoformat() if a.get("last") else None})
    return out


@router.get("/tenants/{int:tid}", auth=hq_auth)
def tenant_detail(request, tid: int):
    t = get_object_or_404(hq.tenants_qs(), pk=tid)
    hq.collect(t, start=timezone.localdate() - timedelta(days=1))
    st = hq.stats_by_tenant(30).get(t.pk, {})
    tickets = list(Ticket.objects.filter(tenant=t)[:20])
    invoices = list(Invoice.objects.filter(tenant=t)[:12])
    level, reasons = hq.health(t, st, [x for x in tickets if x.status != TicketStatus.CLOSED], invoices)
    money = _money_ok(t)
    branches = _branches_live(t)
    if not money:
        for b in branches:
            b.update(revenue_30d=None, avg_check=None, food_cost=None)
    series = [{"date": d, "revenue": v} for d, v in sorted(st.get("series", {}).items())] if money else []
    modules = [{"code": m.code, "name": m.name.get("uz"), "implemented": m.implemented, "enabled": t.module_enabled(m.code),
                "allowed": t.can_enable(m.code)} for m in all_modules() if m.implemented]
    acc = hq.active_access(t)
    return {
        **_tenant_row(t, st, level, reasons, [x for x in tickets if x.status != TicketStatus.CLOSED]),
        "consent": hq.consent(t), "series": series, "branches_list": branches, "modules": modules,
        "invoices": [_invoice_out(i) for i in invoices],
        "tickets": [_ticket_out(x) for x in tickets],
        "access": {"until": acc.until.isoformat(), "granted_by": acc.granted_by} if acc else None,
        "access_request": ((t.settings or {}).get("platform") or {}).get("access_request"),
        "sessions": [{"at": s.started_at.isoformat(), "staff": s.staff_name, "reason": s.reason} for s in SupportSession.objects.filter(tenant=t)[:10]],
        "activity": [{"at": a.at.isoformat(), "who": a.staff_name, "action": a.action, "detail": a.detail} for a in HqAudit.objects.filter(tenant=t)[:10]],
        "admin_url": f"{hq.tenant_base(t)}/admin/", "site_url": f"{hq.tenant_base(t)}/",
        "ai": _ai_out(t), "direct_entry": request.staff.role in DIRECT_ROLES,
        "contract": hq_ops.contract_out(_contract_any(t)),
        "profile": {"region": t.region, "district": t.district, "address": t.address, "max_branches": int((t.limits or {}).get("branches") or 0),
                    "max_users": int((t.limits or {}).get("users") or 0), "plan_branches": t.plan.max_branches if t.plan else 0},
        "flags": hq_ops.flags_for_tenant(t),
        "next_payment": next((x for x in hq.upcoming(62) if x["tenant_id"] == t.pk), None),
    }


def _contract_any(t: Tenant):
    """Shartnoma (faol bo'lmasa ham — kartada ko'rinadi)."""
    from public.models import Contract
    return Contract.objects.filter(tenant=t).select_related("manager__user").first()


def _ai_out(t: Tenant) -> dict:
    from modules.ai import limits
    out = {**limits.platform(t), "module_enabled": t.module_enabled("ai"), "used": 0, "today": 0}
    try:
        with schema_context(t.schema_name):
            from modules.ai.agent import used_today
            out["used"] = len(limits.holders()) if t.module_enabled("ai") else 0
            out["today"] = used_today() if t.module_enabled("ai") else 0
    except Exception:
        pass
    return out


class AiCapIn(Schema):
    enabled: bool = True
    daily_limit: int = 0
    seats: int = 0


@router.put("/tenants/{int:tid}/ai", auth=hq_auth)
def set_ai_cap(request, tid: int, data: AiCapIn):
    """AI Kotib tarifi: yoqilgan/o'chirilgan, kunlik so'rovlar va nechta xodim (0 — cheklovsiz)."""
    _need(request, StaffRole.SALES)
    t = get_object_or_404(Tenant, pk=tid)
    from modules.ai import limits
    c = limits.set_platform(t, enabled=data.enabled, daily_limit=data.daily_limit, seats=data.seats)
    if data.enabled and not t.module_enabled("ai"):
        try:
            set_modules(t, [*t.enabled_modules, "ai"])
        except PermissionError:
            pass
    hq.audit(request.staff, "ai_cap", t, **c)
    return _ai_out(t)


class StatusIn(Schema):
    is_active: bool
    reason: str = ""


@router.post("/tenants/{int:tid}/status", auth=hq_auth)
def set_status(request, tid: int, data: StatusIn):
    _need(request, StaffRole.FINANCE)
    t = get_object_or_404(Tenant, pk=tid)
    t.is_active = data.is_active
    t.save(update_fields=["is_active"])
    hq.audit(request.staff, "activate" if data.is_active else "suspend", t, reason=data.reason)
    return {"ok": True}


class PlanIn(Schema):
    plan_code: str


@router.post("/tenants/{int:tid}/plan", auth=hq_auth)
def set_plan(request, tid: int, data: PlanIn):
    _need(request, StaffRole.SALES, StaffRole.FINANCE)
    t = get_object_or_404(Tenant, pk=tid)
    t.plan = get_object_or_404(Plan, code=data.plan_code)
    t.save(update_fields=["plan"])
    hq.audit(request.staff, "plan", t, plan=data.plan_code)
    return {"ok": True}


class TrialIn(Schema):
    days: int


@router.post("/tenants/{int:tid}/trial", auth=hq_auth)
def extend_trial(request, tid: int, data: TrialIn):
    _need(request, StaffRole.SALES)
    if not 1 <= data.days <= 90:
        raise HttpError(400, "1–90 kun oralig'ida kiriting.")
    t = get_object_or_404(Tenant, pk=tid)
    base = max(t.trial_ends_at or timezone.now(), timezone.now())
    t.trial_ends_at = base + timedelta(days=data.days)
    t.save(update_fields=["trial_ends_at"])
    hq.audit(request.staff, "trial", t, days=data.days)
    return {"ok": True, "trial_ends_at": t.trial_ends_at.isoformat()}


class ModulesIn(Schema):
    codes: list[str]


@router.put("/tenants/{int:tid}/modules", auth=hq_auth)
def set_tenant_modules(request, tid: int, data: ModulesIn):
    _need(request, StaffRole.SUPPORT, StaffRole.SALES)
    t = get_object_or_404(Tenant, pk=tid)
    try:
        mods = set_modules(t, data.codes)
    except PermissionError as e:
        raise HttpError(400, str(e)) from None
    hq.audit(request.staff, "modules", t, codes=mods)
    return {"ok": True, "enabled": mods}


class ReasonIn(Schema):
    reason: str = ""


@router.post("/tenants/{int:tid}/access-request", auth=hq_auth)
def access_request(request, tid: int, data: ReasonIn):
    """Egasidan kirishga ruxsat so'rash: restoran panelida ogohlantirish chiqadi, Telegram ulangan bo'lsa — xabar."""
    t = get_object_or_404(Tenant, pk=tid)
    s = dict(t.settings or {})
    p = dict(s.get("platform") or {})
    who = request.staff.user.full_name or request.staff.user.phone
    p["access_request"] = {"by": who, "reason": data.reason.strip() or "Texnik yordam", "at": timezone.now().isoformat()}
    s["platform"] = p
    t.settings = s
    t.save(update_fields=["settings"])
    try:
        with schema_context(t.schema_name):
            from core.models import User as TUser
            from integrations.telegram import send_message
            owner = TUser.objects.filter(phone=t.owner_phone, telegram_id__isnull=False).first()
            if owner:
                send_message(owner.telegram_id, f"🛟 {settings.PLATFORM_NAME} yordami panelingizga kirish uchun ruxsat so'rayapti.\n"
                                                f"Sabab: {p['access_request']['reason']}\nPanel → Yordam bo'limida ruxsat bering yoki rad eting.")
    except Exception:
        pass
    hq.audit(request.staff, "access_request", t, reason=data.reason)
    return {"ok": True}


@router.post("/tenants/{int:tid}/impersonate", auth=hq_auth)
def impersonate(request, tid: int, data: ReasonIn):
    """Founder/developer/superadmin — to'g'ridan-to'g'ri (yoziladi); texnik yordam — egasi ruxsat berganda."""
    _need(request, StaffRole.SUPPORT)
    if not data.reason.strip() and request.staff.role in DIRECT_ROLES:
        data.reason = "Platforma rahbari: nazorat va sozlash"
    if not data.reason.strip():
        raise HttpError(400, "Kirish sababini yozing (masalan: murojaat #10482).")
    t = get_object_or_404(Tenant, pk=tid)
    try:
        return hq.impersonate(t, request.staff, data.reason.strip())
    except PermissionError as e:
        raise HttpError(403, str(e)) from None


# ------------------------------------------------------------------ billing
def _invoice_out(i: Invoice) -> dict:
    return {"id": i.pk, "tenant_id": i.tenant_id, "tenant": i.tenant.name, "period": i.period.isoformat(), "plan": i.plan_name,
            "branches": i.branches, "amount": i.amount, "currency": i.currency, "method": i.method, "note": i.note,
            "status": i.status, "status_label": InvoiceStatus(i.status).label,
            "due_date": i.due_date.isoformat() if i.due_date else None, "paid_at": i.paid_at.isoformat() if i.paid_at else None}


@router.get("/billing", auth=hq_auth)
def billing(request, period: Optional[str] = None, status: Optional[str] = None):
    hq.ensure_invoices()
    qs = Invoice.objects.select_related("tenant")
    if period:
        qs = qs.filter(period=period)
    if status:
        qs = qs.filter(status=status)
    items = [_invoice_out(i) for i in qs[:500]]
    cur = timezone.localdate().replace(day=1)
    month = list(Invoice.objects.filter(period=cur).exclude(status=InvoiceStatus.CANCELLED))
    overdue = list(Invoice.objects.filter(status=InvoiceStatus.OVERDUE))
    return {"items": items, "mrr": hq.mrr_series(12), "usd_rate": hq.usd_rate(),
            "summary": {"month_total": hq.money_totals((i.amount, i.currency) for i in month),
                        "paid": hq.money_totals((i.amount, i.currency) for i in month if i.status == InvoiceStatus.PAID),
                        "pending": hq.money_totals((i.amount, i.currency) for i in month if i.status == InvoiceStatus.PENDING),
                        "overdue": hq.money_totals((i.amount, i.currency) for i in overdue), "overdue_count": len(overdue)},
            "statuses": [{"code": s.value, "label": s.label} for s in InvoiceStatus]}


class InvoiceStatusIn(Schema):
    status: str
    note: str = ""
    method: str = ""


@router.post("/invoices/{int:iid}/status", auth=hq_auth)
def invoice_status(request, iid: int, data: InvoiceStatusIn):
    _need(request, StaffRole.FINANCE)
    if data.status not in InvoiceStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    i = get_object_or_404(Invoice, pk=iid)
    i.status = data.status
    i.paid_at = timezone.now() if data.status == InvoiceStatus.PAID else None
    i.note = data.note or i.note or ("to'landi" if data.status == InvoiceStatus.PAID else "")
    if data.method:
        i.method = data.method[:12]
    i.save()
    hq.audit(request.staff, f"invoice_{data.status}", i.tenant, invoice=i.pk, amount=i.amount)
    return _invoice_out(i)


# ------------------------------------------------------------------ yordam (murojaatlar)
def _ticket_out(x: Ticket, full: bool = False) -> dict:
    d = {"id": x.pk, "number": x.number, "tenant_id": x.tenant_id, "tenant": x.tenant.name if x.tenant_id else "Ichki vazifa", "branch": x.branch_name, "author": x.author_name,
         "phone": x.author_phone, "subject": x.subject, "priority": x.priority, "priority_label": TicketPriority(x.priority).label,
         "status": x.status, "status_label": TicketStatus(x.status).label, "assigned": x.assigned.user.full_name if x.assigned_id else None,
         "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat(), "kind": x.kind,
         "due_at": x.due_at.isoformat() if x.due_at else None}
    if full:
        d["body"] = x.body
        d["messages"] = [{"id": m.pk, "from_staff": m.from_staff, "author": m.author_name, "body": m.body, "at": m.created_at.isoformat()}
                         for m in x.messages.all()]
    return d


@router.get("/tickets", auth=hq_auth)
def tickets(request, status: Optional[str] = None, tenant_id: Optional[int] = None):
    qs = Ticket.objects.select_related("tenant", "assigned__user")
    if status:
        qs = qs.filter(status=status)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    counts = dict(Ticket.objects.values_list("status").annotate(n=Count("id")))
    return {"items": [_ticket_out(x) for x in qs[:300]], "counts": {s.value: counts.get(s.value, 0) for s in TicketStatus},
            "total": sum(counts.values()), "statuses": [{"code": s.value, "label": s.label} for s in TicketStatus],
            "priorities": [{"code": s.value, "label": s.label} for s in TicketPriority],
            "staff": [_staff_out(s) for s in PlatformStaff.objects.filter(is_active=True).select_related("user")]}


@router.get("/tickets/{int:kid}", auth=hq_auth)
def ticket(request, kid: int):
    return _ticket_out(get_object_or_404(Ticket.objects.select_related("tenant", "assigned__user"), pk=kid), full=True)


class TicketUpd(Schema):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_id: Optional[int] = None
    kind: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    due_at: Optional[str] = None          # ISO; "" — muddatni olib tashlash


@router.put("/tickets/{int:kid}", auth=hq_auth)
def ticket_update(request, kid: int, data: TicketUpd):
    x = get_object_or_404(Ticket, pk=kid)
    if data.status:
        if data.status not in TicketStatus.values:
            raise HttpError(400, "Noto'g'ri holat.")
        x.status = data.status
        x.closed_at = timezone.now() if data.status == TicketStatus.CLOSED else None
    if data.priority:
        if data.priority not in TicketPriority.values:
            raise HttpError(400, "Noto'g'ri muhimlik.")
        x.priority = data.priority
    if data.assigned_id is not None:
        x.assigned = PlatformStaff.objects.filter(pk=data.assigned_id).first()
    if data.kind:
        from public.models import TicketKind
        if data.kind not in TicketKind.values:
            raise HttpError(400, "Noto'g'ri tur.")
        x.kind = data.kind
    if data.subject is not None and data.subject.strip():
        x.subject = data.subject.strip()[:200]
    if data.body is not None:
        x.body = data.body
    if data.due_at is not None:
        from django.utils.dateparse import parse_datetime
        dd = parse_datetime(data.due_at) if data.due_at else None
        if data.due_at and dd is None:
            raise HttpError(400, "Muddat noto'g'ri.")
        x.due_at = timezone.make_aware(dd) if dd and timezone.is_naive(dd) else dd
    x.save()
    hq.audit(request.staff, "ticket_update", x.tenant, ticket=x.number, **{k: v for k, v in data.dict(exclude_none=True).items() if k != "body"})
    return _ticket_out(Ticket.objects.select_related("tenant", "assigned__user").get(pk=kid), full=True)


class MsgIn(Schema):
    body: str


@router.post("/tickets/{int:kid}/messages", auth=hq_auth)
def ticket_reply(request, kid: int, data: MsgIn):
    x = get_object_or_404(Ticket, pk=kid)
    if not data.body.strip():
        raise HttpError(400, "Javob matnini yozing.")
    TicketMessage.objects.create(ticket=x, from_staff=True, author_name=request.staff.user.full_name or "Yordam", body=data.body.strip())
    if x.status == TicketStatus.OPEN:
        x.status = TicketStatus.PROGRESS
    if x.assigned_id is None:
        x.assigned = request.staff
    x.save()
    hq.audit(request.staff, "ticket_reply", x.tenant, ticket=x.number)
    return _ticket_out(Ticket.objects.select_related("tenant", "assigned__user").get(pk=kid), full=True)


# ------------------------------------------------------------------ tizim holati
@router.get("/health", auth=hq_auth)
def system_health(request):
    import shutil
    import time as _t
    checks = []

    def check(name, fn):
        t0 = _t.perf_counter()
        try:
            detail = fn()
            ok = True
        except Exception as e:  # noqa: BLE001
            detail, ok = str(e)[:120], False
        checks.append({"name": name, "ok": ok, "ms": round((_t.perf_counter() - t0) * 1000, 1), "detail": detail or ""})

    def db():
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return f"{hq.tenants_qs().count()} ta restoran sxemasi"

    def cache_():
        from django.core.cache import cache
        cache.set("hq_ping", 1, 5)
        assert cache.get("hq_ping") == 1
        return "yozish/o'qish ishlaydi"

    def disk():
        total, used, free = shutil.disk_usage(settings.BASE_DIR)
        return f"bo'sh {free // 2**30} GB ({round(100 * free / total)}%)"

    def media():
        import os
        root = getattr(settings, "MEDIA_ROOT", settings.BASE_DIR)
        os.makedirs(root, exist_ok=True)
        assert os.access(root, os.W_OK)
        return "fayl saqlash yoziladi"

    def stats():
        last = TenantStat.objects.order_by("-collected_at").first()
        return f"oxirgi yig'ish: {timezone.localtime(last.collected_at):%d.%m %H:%M}" if last else "hali yig'ilmagan"

    def otp_():
        n = OtpCode.objects.filter(created_at__gte=timezone.now() - timedelta(hours=24)).count()
        return f"24 soatda {n} ta kod"

    check("Ma'lumotlar bazasi", db)
    check("Kesh (Redis)", cache_)
    check("Disk", disk)
    check("Fayl saqlash", media)
    check("Statistika yig'ish", stats)
    check("Autentifikatsiya (SMS/kod)", otp_)
    ok = sum(1 for c in checks if c["ok"])
    return {"checks": checks, "ok": ok, "total": len(checks), "percent": round(100 * ok / len(checks), 1),
            "version": getattr(settings, "APP_VERSION", "v14"), "time": timezone.now().isoformat()}


@router.post("/stats/refresh", auth=hq_auth)
def refresh_stats(request):
    n = hq.ensure_stats(force=True)
    hq.audit(request.staff, "stats_refresh", count=n)
    return {"ok": True, "tenants": n}


# ------------------------------------------------------------------ funksiya bayroqlari va relizlar
class FlagIn(Schema):
    code: str
    name: str
    description: str = ""
    enabled_all: bool = False
    tenants: list[int] = []


def _flag_out(f: FeatureFlag) -> dict:
    return {"id": f.pk, "code": f.code, "name": f.name, "description": f.description, "enabled_all": f.enabled_all, "tenants": f.tenants}


@router.get("/flags", auth=hq_auth)
def flags(request):
    return {"items": [_flag_out(f) for f in FeatureFlag.objects.all()],
            "tenants": [{"id": t.pk, "name": t.name} for t in hq.tenants_qs()],
            "releases": [{"id": r.pk, "version": r.version, "title": r.title, "notes": r.notes, "is_published": r.is_published,
                          "published_at": r.published_at.isoformat() if r.published_at else None} for r in Release.objects.all()[:20]]}


@router.post("/flags", auth=hq_auth)
def flag_save(request, data: FlagIn):
    _need(request)
    code = data.code.strip().lower().replace(" ", "_")
    if not code or not data.name.strip():
        raise HttpError(400, "Kod va nomni kiriting.")
    f, _ = FeatureFlag.objects.update_or_create(code=code, defaults={"name": data.name.strip(), "description": data.description,
                                                                     "enabled_all": data.enabled_all, "tenants": data.tenants})
    from core.features import reset_cache
    reset_cache()
    hq.audit(request.staff, "flag", code=code, enabled_all=data.enabled_all, tenants=data.tenants)
    return _flag_out(f)


class ReleaseIn(Schema):
    version: str
    title: str
    notes: str = ""
    publish: bool = False


@router.post("/releases", auth=hq_auth)
def release_save(request, data: ReleaseIn):
    _need(request)
    if not data.version.strip() or not data.title.strip():
        raise HttpError(400, "Versiya va sarlavhani kiriting.")
    r = Release.objects.create(version=data.version.strip(), title=data.title.strip(), notes=data.notes,
                               is_published=data.publish, published_at=timezone.now() if data.publish else None)
    hq.audit(request.staff, "release", version=r.version)
    return {"id": r.pk}


# ------------------------------------------------------------------ audit va jamoa
@router.get("/audit", auth=hq_auth)
def audit_log(request, tenant_id: Optional[int] = None):
    qs = HqAudit.objects.select_related("tenant")
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    return [{"at": a.at.isoformat(), "who": a.staff_name, "action": a.action, "tenant": a.tenant.name if a.tenant_id else None,
             "detail": a.detail} for a in qs[:300]]


@router.get("/staff", auth=hq_auth)
def staff_list(request):
    return {"items": [_staff_out(s) for s in PlatformStaff.objects.select_related("user")],
            "roles": [{"code": r.value, "label": r.label} for r in StaffRole]}


class StaffIn(Schema):
    phone: str
    full_name: str
    role: str = StaffRole.SUPPORT


@router.post("/staff", auth=hq_auth)
def staff_add(request, data: StaffIn):
    _need(request)
    if data.role not in StaffRole.values:
        raise HttpError(400, "Noto'g'ri rol.")
    phone = User.objects.normalize_phone(data.phone)
    u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": data.full_name})
    s, _ = PlatformStaff.objects.update_or_create(user=u, defaults={"role": data.role, "is_active": True})
    hq.audit(request.staff, "staff_add", phone=phone, role=data.role)
    return _staff_out(s)


# ------------------------------------------------------------------ platforma sayti: narxlar va taklif, mijozlar (lead)
class OfferIn(Schema):
    currency: str = "$"
    base_price: int = 100
    ai_price: int = 150
    price_note: str = ""
    trial_days: int = 30
    free_setup: bool = True
    setup_note: str = ""
    includes: list[str] = []
    phone: str = ""
    telegram: str = ""
    ai_chat: bool = True
    ai_key: str = ""          # yangi kalit (bo'sh — o'zgarmaydi)
    clear_ai_key: bool = False
    lead_chat: str = ""       # arizalar yuboriladigan Telegram chat ID
    price_note_ru: str = ""
    setup_note_ru: str = ""
    includes_ru: list[str] = []


def _mask(k: str) -> str:
    return (k[:4] + "…" + k[-4:]) if len(k) > 10 else ("••••" if k else "")


def _offer_out(o) -> dict:
    return {"currency": o.currency, "base_price": o.base_price, "ai_price": o.ai_price, "price_note": o.price_note, "trial_days": o.trial_days,
            "free_setup": o.free_setup, "setup_note": o.setup_note, "includes": o.includes or [], "phone": o.phone, "telegram": o.telegram,
            "ai_chat": o.ai_chat, "ai_key": _mask(o.ai_key or ""), "ai_key_source": _key_source(o),
            "lead_chat": o.lead_chat, "price_note_ru": o.price_note_ru, "setup_note_ru": o.setup_note_ru, "includes_ru": o.includes_ru or [],
            "notify_ready": bool((o.lead_chat or "").strip()) and bool(__import__("os").environ.get("TELEGRAM_BOT_TOKEN", "").strip()),
            "updated_at": o.updated_at.isoformat() if o.updated_at else None}


def _key_source(o) -> str:
    import os
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "server .env (GEMINI_API_KEY)"
    if (o.ai_key or "").strip():
        return "shu sahifadagi kalit"
    from website.sales_ai import key_holder
    return "restoranning AI Kotib kaliti" if key_holder().settings["modules"]["ai"]["api_key"] else "YO'Q — kalit kiriting"


@router.get("/offer", auth=hq_auth)
def offer_get(request):
    from public.models import SiteOffer
    return _offer_out(SiteOffer.get())


@router.put("/offer", auth=hq_auth)
def offer_put(request, data: OfferIn):
    _need(request, "sales", "finance")
    from public.models import SiteOffer
    if not (0 < data.base_price <= 100000 and 0 < data.ai_price <= 100000):
        raise HttpError(400, "Narx 1 dan 100 000 gacha bo'lsin.")
    if not 0 <= data.trial_days <= 365:
        raise HttpError(400, "Bepul davr 0–365 kun.")
    o = SiteOffer.get()
    before = _offer_out(o)
    d = data.dict()
    new_key, clear = (d.pop("ai_key") or "").strip(), d.pop("clear_ai_key")
    if clear:
        o.ai_key = ""
    elif new_key and "…" not in new_key and "•" not in new_key:
        o.ai_key = new_key[:200]
    for k, v in d.items():
        if isinstance(v, str):
            v = v.strip()
        if k in ("includes", "includes_ru"):
            v = [str(x).strip()[:120] for x in v if str(x).strip()][:12]
        if k == "lead_chat":
            v = re.sub(r"[^\d-]", "", v)[:20]
        if k == "telegram":
            v = v.lstrip("@").replace("https://t.me/", "")
        setattr(o, k, v)
    o.save()
    hq.audit(request.staff, "offer", before={k: before[k] for k in ("base_price", "ai_price", "trial_days", "free_setup")},
             after={"base_price": o.base_price, "ai_price": o.ai_price, "trial_days": o.trial_days, "free_setup": o.free_setup})
    return _offer_out(o)


@router.post("/offer/test-notify", auth=hq_auth)
def offer_test_notify(request):
    """Arizalar keladigan Telegram chatga sinov xabari."""
    _need(request, "sales", "finance")
    from website import sales_ai
    chat, tok = sales_ai.notify_chat()
    if not chat:
        raise HttpError(400, "Chat ID kiritilmagan — botga /id yozing va raqamni saqlang.")
    if not tok:
        raise HttpError(400, "Serverda bot tokeni yo'q (.env TELEGRAM_BOT_TOKEN).")
    if not sales_ai.notify("✅ <b>Sinov</b>: saytdan arizalar va ro'yxatdan o'tganlar shu chatga keladi."):
        raise HttpError(400, "Yuborib bo'lmadi — chat ID to'g'rimi, botga /start bosilganmi?")
    return {"ok": True}


def _lead_out(x) -> dict:
    return {"id": x.pk, "name": x.name, "phone": x.phone, "business": x.business, "note": x.note, "source": x.source,
            "status": x.status, "status_label": x.get_status_display(), "created_at": x.created_at.isoformat()}


@router.get("/leads", auth=hq_auth)
def leads(request, status: str = ""):
    _need(request, "sales", "support")
    from public.models import Lead
    qs = Lead.objects.all()
    if status:
        qs = qs.filter(status=status)
    return {"items": [_lead_out(x) for x in qs[:300]], "new": Lead.objects.filter(status=Lead.NEW).count()}


class LeadIn(Schema):
    status: str


@router.post("/leads/{int:lid}", auth=hq_auth)
def lead_status(request, lid: int, data: LeadIn):
    _need(request, "sales", "support")
    from public.models import Lead
    x = get_object_or_404(Lead, pk=lid)
    if data.status not in dict(Lead.STATUS):
        raise HttpError(400, "Noma'lum holat")
    x.status = data.status
    x.save(update_fields=["status"])
    hq.audit(request.staff, "lead", lead=lid, status=data.status)
    return _lead_out(x)



@router.get("/chats", auth=hq_auth)
def chats(request):
    """Saytdagi AI maslahatchi bilan suhbatlar (oxirgi 100)."""
    _need(request, "sales", "support")
    from public.models import ChatSession
    out = []
    for c in ChatSession.objects.select_related("lead")[:100]:
        out.append({"id": c.pk, "count": c.count, "ip": c.ip, "updated_at": c.updated_at.isoformat(), "created_at": c.created_at.isoformat(),
                    "lead": ({"name": c.lead.name, "phone": c.lead.phone} if c.lead else None),
                    "first": next((m["text"] for m in c.messages or [] if m.get("role") == "me"), "")[:160],
                    "messages": c.messages or []})
    return {"items": out}


from . import hq_ops  # noqa: E402  (shartnoma, yangi restoran, hududlar, to'lov kalendari, doska)
