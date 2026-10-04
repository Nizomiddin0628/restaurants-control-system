"""
HQ — operatsion bo'limlar: shartnoma bilan yangi restoran ochish, shartnoma va chegaralar, restoranga xos funksiyalar,
hududlar, to'lov kalendari va vazifalar doskasi (kanban).

Muhim qaror: har restoran uchun alohida «application» yoki kod nusxasi ochilmaydi. Hamma restoran bitta kodda,
farqlar — sozlama, modul, chegara va funksiya bayroqlari orqali (core/features.py). Shunda bitta xato bir marta tuzatiladi
va bir yangilanish 100 ta restoranga birdan boradi.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_tenants.utils import schema_context
from ninja import Schema
from ninja.errors import HttpError

from core.features import reset_cache
from core.presets import PRESETS
from public import hq
from public.models import (
    SLA_HOURS,
    Contract,
    FeatureFlag,
    PlatformStaff,
    StaffRole,
    Tenant,
    Ticket,
    TicketKind,
    TicketPriority,
    TicketStatus,
)
from public.regions import region_list

from .hq_api import _need, _staff_out, _ticket_out, hq_auth, router

PRIO_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}


# ------------------------------------------------------------------ ma'lumotnomalar
@router.get("/refs", auth=hq_auth)
def refs(request):
    """Formalar uchun: hududlar, restoran turlari, tariflar, valyutalar, jamoa, murojaat turlari."""
    from public.models import SiteOffer
    o = SiteOffer.get()
    return {"regions": region_list(), "presets": [{"code": k, "name": v["name"]} for k, v in PRESETS.items()],
            "tariffs": [{"code": c, "name": n, "price": o.ai_price if c == "ai" else o.base_price} for c, n in Contract.TARIFFS],
            "currencies": [{"code": c, "name": n} for c, n in Contract.CURRENCIES], "trial_days": o.trial_days,
            "staff": [_staff_out(s) for s in PlatformStaff.objects.filter(is_active=True).select_related("user")],
            "kinds": [{"code": k.value, "label": k.label} for k in TicketKind], "priorities": [{"code": p.value, "label": p.label} for p in TicketPriority],
            "sla": SLA_HOURS, "domain": settings.PLATFORM_DOMAIN, "usd_rate": hq.usd_rate()}


# ------------------------------------------------------------------ shartnoma
def contract_out(c: Contract | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.pk, "number": c.number, "signed_at": c.signed_at.isoformat() if c.signed_at else None, "tariff": c.tariff,
            "tariff_label": hq.TARIFF_UZ[c.tariff], "price": c.price, "currency": c.currency, "included_branches": c.included_branches,
            "extra_branch_price": c.extra_branch_price, "billing_day": c.billing_day, "paid_from": c.paid_from.isoformat() if c.paid_from else None,
            "company": c.company, "inn": c.inn, "contact_name": c.contact_name, "contact_phone": c.contact_phone, "terms": c.terms,
            "manager_id": c.manager_id, "manager": (c.manager.user.full_name or c.manager.user.phone) if c.manager_id else None,
            "is_active": c.is_active, "updated_at": c.updated_at.isoformat() if c.updated_at else None}


class ContractIn(Schema):
    tariff: str = "base"
    price: Optional[int] = None
    currency: str = "USD"
    included_branches: int = 1
    extra_branch_price: int = 0
    billing_day: int = 5
    paid_from: Optional[date] = None
    signed_at: Optional[date] = None
    company: str = ""
    inn: str = ""
    contact_name: str = ""
    contact_phone: str = ""
    terms: str = ""
    manager_id: Optional[int] = None
    is_active: bool = True


def _check_contract(d: ContractIn) -> None:
    if d.tariff not in dict(Contract.TARIFFS):
        raise HttpError(400, "Tarif: Dastur yoki Dastur + AI.")
    if d.currency not in dict(Contract.CURRENCIES):
        raise HttpError(400, "Valyuta: USD yoki UZS.")
    if not 1 <= d.billing_day <= 28:
        raise HttpError(400, "To'lov kuni 1 dan 28 gacha bo'lsin.")
    if d.price is not None and not 0 <= d.price <= 100_000_000:
        raise HttpError(400, "Narx noto'g'ri.")
    if d.inn and not re.fullmatch(r"\d{9}", d.inn.strip()):
        raise HttpError(400, "STIR 9 ta raqamdan iborat bo'ladi.")


def _apply_contract(c: Contract, d: ContractIn) -> Contract:
    from public.models import SiteOffer
    o = SiteOffer.get()
    c.tariff, c.currency = d.tariff, d.currency
    c.price = d.price if d.price is not None else (o.ai_price if d.tariff == Contract.AI else o.base_price)
    c.included_branches, c.extra_branch_price, c.billing_day = max(1, d.included_branches), max(0, d.extra_branch_price), d.billing_day
    c.paid_from, c.signed_at = d.paid_from, d.signed_at
    c.company, c.inn, c.contact_name, c.contact_phone, c.terms = d.company.strip()[:160], d.inn.strip(), d.contact_name.strip()[:120], d.contact_phone.strip()[:20], d.terms.strip()
    c.manager = PlatformStaff.objects.filter(pk=d.manager_id).first() if d.manager_id else None
    c.is_active = d.is_active
    c.save()
    return c


def _sync_ai(t: Tenant, tariff: str) -> None:
    """Dastur + AI tarifi — AI Kotib moduli yoqiladi; oddiy Dastur — o'chiriladi."""
    from public.services import set_modules
    mods = [m for m in (t.enabled_modules or []) if m != "ai"] + (["ai"] if tariff == Contract.AI else [])
    try:
        set_modules(t, mods)
    except PermissionError:
        pass
    try:
        from modules.ai import limits
        limits.set_platform(t, enabled=tariff == Contract.AI)
    except Exception:
        pass


@router.put("/tenants/{int:tid}/contract", auth=hq_auth)
def contract_save(request, tid: int, data: ContractIn):
    _need(request, StaffRole.SALES, StaffRole.FINANCE)
    _check_contract(data)
    t = get_object_or_404(Tenant, pk=tid)
    c = Contract.objects.filter(tenant=t).first() or Contract(tenant=t, number=Contract.next_number())
    before = c.tariff if c.pk else None
    c = _apply_contract(c, data)
    if before != c.tariff:
        _sync_ai(t, c.tariff)
    if c.paid_from:
        t.trial_ends_at = timezone.make_aware(datetime.combine(c.paid_from, datetime.min.time()))
        t.save(update_fields=["trial_ends_at"])
    hq.ensure_invoices()
    hq.audit(request.staff, "contract", t, number=c.number, tariff=c.tariff, price=c.price, currency=c.currency)
    return contract_out(c)


# ------------------------------------------------------------------ restoran kartasi: hudud, chegaralar, maxsus funksiyalar
class ProfileIn(Schema):
    region: str = ""
    district: str = ""
    address: str = ""
    max_branches: int = 0
    max_users: int = 0


@router.put("/tenants/{int:tid}/profile", auth=hq_auth)
def profile_save(request, tid: int, data: ProfileIn):
    _need(request, StaffRole.SALES, StaffRole.SUPPORT)
    t = get_object_or_404(Tenant, pk=tid)
    t.region, t.district, t.address = data.region.strip()[:60], data.district.strip()[:60], data.address.strip()[:200]
    t.limits = {k: v for k, v in {"branches": max(0, data.max_branches), "users": max(0, data.max_users)}.items() if v}
    t.save(update_fields=["region", "district", "address", "limits"])
    hq.audit(request.staff, "profile", t, region=t.region, district=t.district, limits=t.limits)
    return {"ok": True, "region": t.region, "district": t.district, "address": t.address, "limits": t.limits}


def flags_for_tenant(t: Tenant) -> list[dict]:
    return [{"code": f.code, "name": f.name, "description": f.description, "all": f.enabled_all, "on": f.enabled_all or t.pk in (f.tenants or [])}
            for f in FeatureFlag.objects.all()]


class FlagsIn(Schema):
    codes: list[str]


@router.put("/tenants/{int:tid}/flags", auth=hq_auth)
def tenant_flags(request, tid: int, data: FlagsIn):
    """Faqat shu restoran uchun funksiyani yoqish/o'chirish (hammaga yoqilgan bayroqlarga tegilmaydi)."""
    _need(request, StaffRole.SUPPORT, StaffRole.SALES)
    t = get_object_or_404(Tenant, pk=tid)
    want = set(data.codes)
    for f in FeatureFlag.objects.filter(enabled_all=False):
        ids = [x for x in (f.tenants or []) if x != t.pk] + ([t.pk] if f.code in want else [])
        if ids != (f.tenants or []):
            f.tenants = ids
            f.save(update_fields=["tenants"])
    reset_cache()
    hq.audit(request.staff, "tenant_flags", t, codes=sorted(want))
    return flags_for_tenant(t)


# ------------------------------------------------------------------ yangi restoran (shartnoma bo'yicha)
class NewTenantIn(Schema):
    name: str
    slug: str
    preset: str = "restaurant"
    owner_name: str = ""
    owner_phone: str
    region: str = ""
    district: str = ""
    address: str = ""
    branches: list[str] = []          # filial nomlari; bo'sh — «Asosiy filial»
    free_days: int = 30
    contract: ContractIn = ContractIn()


@router.post("/tenants", auth=hq_auth)
def tenant_create(request, data: NewTenantIn):
    """Shartnoma imzolangan restoranni HQ'dan ochish: sxema, egasi, filiallar, modullar (tarif bo'yicha), shartnoma, billing."""
    _need(request, StaffRole.SALES)
    from public.services import create_tenant
    slug = data.slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,30}", slug):
        raise HttpError(400, "Manzil: lotin harf, raqam va '-' (3–31 belgi).")
    if Tenant.objects.filter(slug=slug).exists():
        raise HttpError(409, "Bu manzil band — boshqasini tanlang.")
    if not data.name.strip():
        raise HttpError(400, "Restoran nomini yozing.")
    if data.preset not in PRESETS:
        raise HttpError(400, "Restoran turi noto'g'ri.")
    if not 0 <= data.free_days <= 365:
        raise HttpError(400, "Bepul davr 0–365 kun.")
    _check_contract(data.contract)
    try:
        from core.phone import normalize_uz
        phone = normalize_uz(data.owner_phone)
    except ValueError:
        raise HttpError(400, "Egasining telefon raqami noto'g'ri.") from None
    names = [b.strip()[:120] for b in data.branches if b.strip()][:50] or ["Asosiy filial"]
    host = request.get_host().split(":")[0]
    base = host if host.count(".") >= 1 and not host.startswith("127.") else settings.PLATFORM_DOMAIN
    from public.models import Plan
    full = Plan.objects.filter(is_active=True, allowed_modules__contains=["*"]).order_by("-max_branches", "-price_per_branch").values_list("code", flat=True).first()
    try:
        with transaction.atomic():
            t = create_tenant(name=data.name.strip(), slug=slug, owner_phone=phone, preset=data.preset, owner_name=data.owner_name.strip(),
                              plan_code=full, domain=f"{slug}.{base}", branch_name=names[0], trial_days=data.free_days)
            t.region, t.district, t.address = data.region.strip()[:60], data.district.strip()[:60], data.address.strip()[:200]
            t.save(update_fields=["region", "district", "address"])
            with schema_context(t.schema_name):
                from core.models import Branch
                for i, n in enumerate(names[1:], start=1):
                    Branch.objects.create(name=n, sort_order=i)
            cd = data.contract
            if cd.paid_from is None:
                cd.paid_from = (t.trial_ends_at or timezone.now()).date()
            c = _apply_contract(Contract(tenant=t, number=Contract.next_number()), cd)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    except IntegrityError:
        raise HttpError(409, "Bu manzil yoki telefon band.") from None
    _sync_ai(t, c.tariff)
    hq.collect(t)
    hq.audit(request.staff, "tenant_create", t, number=c.number, tariff=c.tariff, price=c.price, currency=c.currency, branches=len(names))
    try:
        from website.sales_ai import notify
        notify(f"🤝 <b>Shartnoma bo'yicha yangi restoran</b>\n🏪 {t.name} — {hq.primary_domain(t)}\n📄 {c.number} · {hq.TARIFF_UZ[c.tariff]} · "
               f"{c.price}{'$' if c.currency == 'USD' else ' so`m'}/oy\n📍 {t.region or '—'} {t.district}\n👤 {request.staff.user.full_name or request.staff.user.phone}")
    except Exception:
        pass
    return {"id": t.pk, "slug": t.slug, "domain": hq.primary_domain(t), "admin_url": f"{hq.tenant_base(t)}/admin/", "contract": contract_out(c),
            "owner_phone": phone, "branches": names}


# ------------------------------------------------------------------ hududlar
@router.get("/regions", auth=hq_auth)
def regions_summary(request):
    """Hudud bo'yicha: nechta restoran, filial, faol/sinov, oylik to'lov ($ ekvivalenti)."""
    st = hq.stats_by_tenant(7)
    out: dict[str, dict] = {}
    for t in hq.tenants_qs().select_related("contract"):
        r = out.setdefault(t.region or "Ko'rsatilmagan", {"region": t.region or "Ko'rsatilmagan", "tenants": 0, "branches": 0, "active": 0, "trial": 0,
                                                         "mrr_usd": 0.0, "districts": {}})
        br = st.get(t.pk, {}).get("branches", 0)
        r["tenants"] += 1
        r["branches"] += br
        stt = hq.status_of(t)
        r["active"] += stt == "active"
        r["trial"] += stt == "trial"
        if stt == "active":
            tr = hq.terms(t, br)
            r["mrr_usd"] += hq.to_usd(tr["amount"], tr["currency"])
        if t.district:
            r["districts"][t.district] = r["districts"].get(t.district, 0) + 1
    items = sorted(out.values(), key=lambda x: (-x["tenants"], x["region"]))
    for x in items:
        x["mrr_usd"] = round(x["mrr_usd"])
        x["districts"] = sorted([{"name": k, "tenants": v} for k, v in x["districts"].items()], key=lambda d: -d["tenants"])
    return {"items": items}


# ------------------------------------------------------------------ to'lov kalendari
@router.get("/payments/upcoming", auth=hq_auth)
def payments_upcoming(request, days: int = 45):
    hq.ensure_invoices()
    return {"items": hq.upcoming(max(1, min(days, 120))), "usd_rate": hq.usd_rate()}


# ------------------------------------------------------------------ vazifalar doskasi (kanban)
def sla_state(x: Ticket) -> str:
    if x.status == TicketStatus.CLOSED or not x.due_at:
        return "ok"
    left = (x.due_at - timezone.now()).total_seconds() / 3600
    return "late" if left < 0 else ("soon" if left < 4 else "ok")


def card(x: Ticket) -> dict:
    return {**_ticket_out(x), "kind": x.kind, "kind_label": TicketKind(x.kind).label, "due_at": x.due_at.isoformat() if x.due_at else None,
            "sla": sla_state(x), "sort": x.sort, "messages": x.messages.count() if hasattr(x, "messages") else 0, "body": x.body[:240]}


@router.get("/board", auth=hq_auth)
def board(request, mine: bool = False, tenant_id: Optional[int] = None, kind: Optional[str] = None, q: Optional[str] = None):
    """Doska: ustunlar holat bo'yicha; har ustunda tartib — qo'lda (sort), keyin muhimlik va muddat. Yopilganlar — oxirgi 14 kun."""
    qs = Ticket.objects.select_related("tenant", "assigned__user").filter(Q(closed_at__isnull=True) | Q(closed_at__gte=timezone.now() - timedelta(days=14)))
    if mine:
        qs = qs.filter(assigned=request.staff)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    if kind:
        qs = qs.filter(kind=kind)
    if q:
        qs = qs.filter(Q(subject__icontains=q) | Q(body__icontains=q) | Q(tenant__name__icontains=q))
    cols = {s.value: [] for s in TicketStatus}
    for x in qs[:500]:
        cols[x.status].append(x)
    far = timezone.now() + timedelta(days=3650)
    out = []
    for s in TicketStatus:
        items = sorted(cols[s.value], key=lambda x: (x.sort, PRIO_RANK.get(x.priority, 9), x.due_at or far))
        out.append({"code": s.value, "label": s.label, "items": [card(x) for x in items]})
    late = Ticket.objects.exclude(status=TicketStatus.CLOSED).filter(due_at__lt=timezone.now()).count()
    return {"columns": out, "late": late, "staff": [_staff_out(s) for s in PlatformStaff.objects.filter(is_active=True).select_related("user")],
            "kinds": [{"code": k.value, "label": k.label} for k in TicketKind], "priorities": [{"code": p.value, "label": p.label} for p in TicketPriority],
            "tenants": [{"id": t.pk, "name": t.name} for t in hq.tenants_qs()]}


class CardIn(Schema):
    subject: str
    body: str = ""
    tenant_id: Optional[int] = None
    kind: str = TicketKind.TASK
    priority: str = TicketPriority.NORMAL
    assigned_id: Optional[int] = None
    due_at: Optional[datetime] = None


@router.post("/tickets", auth=hq_auth)
def card_create(request, data: CardIn):
    if not data.subject.strip():
        raise HttpError(400, "Sarlavha yozing.")
    if data.kind not in TicketKind.values or data.priority not in TicketPriority.values:
        raise HttpError(400, "Tur yoki muhimlik noto'g'ri.")
    t = get_object_or_404(Tenant, pk=data.tenant_id) if data.tenant_id else None
    first = Ticket.objects.filter(status=TicketStatus.OPEN).order_by("sort").values_list("sort", flat=True).first()
    x = Ticket.objects.create(tenant=t, subject=data.subject.strip()[:200], body=data.body.strip(), kind=data.kind, priority=data.priority,
                              assigned=PlatformStaff.objects.filter(pk=data.assigned_id).first() if data.assigned_id else None,
                              due_at=data.due_at, author_name=request.staff.user.full_name or "HQ", sort=(first or 0) - 1)
    hq.audit(request.staff, "ticket_create", t, ticket=x.number, subject=x.subject)
    return card(Ticket.objects.select_related("tenant", "assigned__user").get(pk=x.pk))


class MoveIn(Schema):
    status: str
    before_id: Optional[int] = None     # shu kartaning ustiga qo'yiladi; bo'sh — ustun oxiriga


@router.post("/tickets/{int:kid}/move", auth=hq_auth)
def card_move(request, kid: int, data: MoveIn):
    """Kartani boshqa ustunga yoki ustun ichida yuqori/pastga surish."""
    if data.status not in TicketStatus.values:
        raise HttpError(400, "Noto'g'ri ustun.")
    x = get_object_or_404(Ticket, pk=kid)
    col = list(Ticket.objects.filter(status=data.status).exclude(pk=x.pk).order_by("sort", "pk").values_list("pk", "sort"))
    if data.before_id:
        idx = next((i for i, (pk, _) in enumerate(col) if pk == data.before_id), len(col))
    else:
        idx = len(col)
    prev = col[idx - 1][1] if idx > 0 else None
    nxt = col[idx][1] if idx < len(col) else None
    if prev is None and nxt is None:
        x.sort = 0
    elif prev is None:
        x.sort = nxt - 1
    elif nxt is None:
        x.sort = prev + 1
    else:
        x.sort = (prev + nxt) / 2
    if x.status != data.status:
        x.status = data.status
        x.closed_at = timezone.now() if data.status == TicketStatus.CLOSED else None
        if data.status == TicketStatus.PROGRESS and x.assigned_id is None:
            x.assigned = request.staff
    x.save()
    hq.audit(request.staff, "ticket_move", x.tenant, ticket=x.number, status=x.status)
    return card(Ticket.objects.select_related("tenant", "assigned__user").get(pk=x.pk))
