"""
Restoran tomoni: platforma bilan munosabat — /api/v1/platform/...

  • ma'lumot ulashish roziligi (daromad statistikasi HQ da ko'rinsinmi; «mijozlarimiz» ro'yxatida chiqishga rozilik),
  • yordamga vaqtinchalik kirish ruxsati (1 soat / 1 kun / 3 kun), bekor qilish, kim qachon kirgani,
  • murojaatlar (tiketlar): yozish, javob olish.
Hammasi public sxemadagi jadvallar — django-tenants search_path (tenant, public) orqali ko'rinadi.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_perm

router = Router(tags=["platform"])


def _t(request):
    return request.tenant


def _owner(request):
    """Rozilik va ruxsatni faqat restoran o'zi boshqaradi — platforma yordami (hatto kirgan bo'lsa ham) o'zgartira olmaydi."""
    require_perm(request, "core.settings.edit")
    if request.auth.memberships.filter(role__code="platform_support").exists():
        raise HttpError(403, "Platforma yordami bu sozlamani o'zgartira olmaydi — faqat restoran egasi.")


def _p(t) -> dict:
    return dict((t.settings or {}).get("platform") or {})


def _save_p(t, p: dict) -> None:
    s = dict(t.settings or {})
    s["platform"] = p
    t.settings = s
    t.save(update_fields=["settings"])


@router.get("/status", auth=auth)
def status(request):
    from public import hq
    from public.models import SupportSession
    t = _t(request)
    acc = hq.active_access(t)
    p = _p(t)
    return {
        "platform": settings.PLATFORM_NAME,
        "consent": hq.consent(t),
        "access": {"until": acc.until.isoformat(), "granted_by": acc.granted_by, "reason": acc.reason} if acc else None,
        "access_request": p.get("access_request"),
        "sessions": [{"at": s.started_at.isoformat(), "staff": s.staff_name, "reason": s.reason} for s in SupportSession.objects.filter(tenant=t)[:15]],
        "can_manage": request.auth.has_perm_code("core.settings.edit") and not request.auth.memberships.filter(role__code="platform_support").exists(),
    }


class ConsentIn(Schema):
    share_finance: bool
    showcase: bool = False


@router.put("/consent", auth=auth)
def consent(request, data: ConsentIn):
    _owner(request)
    t = _t(request)
    p = _p(t)
    p.update(share_finance=data.share_finance, showcase=data.showcase)
    _save_p(t, p)
    record(request, "update", model="Platforma", after=data.dict())
    return {"ok": True}


class GrantIn(Schema):
    hours: int = 24
    reason: str = ""


@router.post("/access", auth=auth)
def grant(request, data: GrantIn):
    """Egasi yordamga kirishga ruxsat beradi (1–72 soat)."""
    _owner(request)
    from public.models import SupportAccess
    if not 1 <= data.hours <= 72:
        raise HttpError(400, "Ruxsat 1 soatdan 72 soatgacha bo'lishi mumkin.")
    t = _t(request)
    SupportAccess.objects.filter(tenant=t, revoked_at__isnull=True).update(revoked_at=timezone.now())
    a = SupportAccess.objects.create(tenant=t, granted_by=request.auth.full_name or request.auth.phone,
                                     until=timezone.now() + timedelta(hours=data.hours), reason=data.reason.strip())
    p = _p(t)
    p.pop("access_request", None)
    _save_p(t, p)
    record(request, "grant_support", model="Platforma", after={"hours": data.hours, "until": a.until.isoformat()})
    return {"ok": True, "until": a.until.isoformat()}


@router.delete("/access", auth=auth)
def revoke(request):
    _owner(request)
    from public.models import SupportAccess
    t = _t(request)
    n = SupportAccess.objects.filter(tenant=t, revoked_at__isnull=True).update(revoked_at=timezone.now())
    p = _p(t)
    p.pop("access_request", None)
    _save_p(t, p)
    record(request, "revoke_support", model="Platforma", after={"revoked": n})
    return {"ok": True}


# ------------------------------------------------------------------ murojaatlar
class TicketIn(Schema):
    subject: str
    body: str = ""
    priority: str = "normal"
    branch_name: str = ""


def _ticket(x, full=False) -> dict:
    from public.models import TicketPriority, TicketStatus
    d = {"id": x.pk, "number": x.number, "subject": x.subject, "status": x.status, "status_label": TicketStatus(x.status).label,
         "priority": x.priority, "priority_label": TicketPriority(x.priority).label, "branch": x.branch_name, "author": x.author_name,
         "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat()}
    if full:
        d["body"] = x.body
        d["messages"] = [{"from_staff": m.from_staff, "author": m.author_name, "body": m.body, "at": m.created_at.isoformat()} for m in x.messages.all()]
    return d


@router.get("/tickets", auth=auth)
def my_tickets(request):
    from public.models import Ticket
    return [_ticket(x) for x in Ticket.objects.filter(tenant=_t(request))[:100]]


@router.post("/tickets", auth=auth)
def create_ticket(request, data: TicketIn):
    from public.models import Ticket, TicketPriority
    if not data.subject.strip():
        raise HttpError(400, "Muammoni qisqacha yozing.")
    pr = data.priority if data.priority in TicketPriority.values else TicketPriority.NORMAL
    x = Ticket.objects.create(tenant=_t(request), subject=data.subject.strip()[:200], body=data.body.strip(), priority=pr,
                              branch_name=data.branch_name[:120], author_name=request.auth.full_name or "", author_phone=request.auth.phone)
    record(request, "create", model="Murojaat", object_id=x.number, after={"subject": x.subject})
    try:
        from website.sales_ai import notify
        icon = {"critical": "🔴", "high": "🟠"}.get(x.priority, "🟡")
        notify(f"{icon} <b>Yangi murojaat #{x.number}</b> — {x.tenant.name}\n{x.subject}\n👤 {x.author_name or '—'} {x.author_phone}"
               f"{(chr(10) + '🏪 ' + x.branch_name) if x.branch_name else ''}")
    except Exception:
        pass
    return _ticket(x, full=True)


@router.get("/tickets/{int:kid}", auth=auth)
def get_ticket(request, kid: int):
    from public.models import Ticket
    return _ticket(get_object_or_404(Ticket, pk=kid, tenant=_t(request)), full=True)


class MsgIn(Schema):
    body: str
    close: Optional[bool] = False


@router.post("/tickets/{int:kid}/messages", auth=auth)
def reply(request, kid: int, data: MsgIn):
    from public.models import Ticket, TicketMessage, TicketStatus
    x = get_object_or_404(Ticket, pk=kid, tenant=_t(request))
    if data.body.strip():
        TicketMessage.objects.create(ticket=x, from_staff=False, author_name=request.auth.full_name or "", body=data.body.strip())
    if data.close:
        x.status, x.closed_at = TicketStatus.CLOSED, timezone.now()
    elif x.status in (TicketStatus.WAITING, TicketStatus.CLOSED):
        x.status, x.closed_at = TicketStatus.OPEN, None
    x.save()
    return _ticket(x, full=True)
