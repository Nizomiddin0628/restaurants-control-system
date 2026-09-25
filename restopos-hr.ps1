# RestoPOS v11 — HR: vakansiyalar, Telegram ariza, nomzodlar, xodim profili, KPI
# Ishga tushirish (ildiz papkada!):  PS C:\Users\xalil\Desktop\restaurants\restopos>
#   powershell -ExecutionPolicy Bypass -File .\restopos-hr.ps1
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$PWD\backend\manage.py") -or -not (Test-Path "$PWD\frontend\apps\admin")) {
  Write-Host "XATO: skriptni restopos ildiz papkasida ishga tushiring." -ForegroundColor Red
  exit 1
}
if (-not (Test-Path "$PWD\backend\api\dashboard.py")) {
  Write-Host "XATO: avval v10 (boshqaruv paneli) o'rnatilgan bo'lishi kerak — git pull qiling." -ForegroundColor Red
  exit 1
}
$enc = New-Object Text.UTF8Encoding $false
function Put([string]$rel, [string]$text) {
  $path = Join-Path $PWD $rel
  $dir = Split-Path $path -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  [IO.File]::WriteAllText($path, $text.Replace("`r`n", "`n") + "`n", $enc)
  Write-Host ("  + " + $rel)
}

Put 'backend\integrations\telegram\api.py' @'
"""
Telegram webhook — /api/v1/telegram/webhook (restoran domenida).

1) Sir tekshiruvi (restoran boti sozlamasidagi webhook_secret yoki .env TELEGRAM_WEBHOOK_SECRET).
2) "Telegram bot" moduli yoqilgan bo'lsa — mijoz suhbati modules.telegram.services.handle_update() da.
3) Qolgani — xodimlar uchun: telefon orqali bog'lash, /vazifalar, /keldim, /ketdim.
"""
from __future__ import annotations

import json
import logging
import os

from django.http import JsonResponse
from ninja import Router

from core.auth import auth, require_perm
from core.models import User

from . import CONTACT_KEYBOARD, send_message, set_webhook

router = Router(tags=["telegram"])
log = logging.getLogger("telegram")


def _tenant_cfg(tenant) -> dict:
    return (((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("telegram") or {})


@router.post("/set-webhook", auth=auth)
def set_webhook_view(request):
    require_perm(request, "core.settings.edit")
    base = request.build_absolute_uri("/").rstrip("/")
    secret = _tenant_cfg(request.tenant).get("webhook_secret") or os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos")
    return set_webhook(base, secret)


@router.post("/webhook", auth=None)
def webhook(request):
    tenant = request.tenant
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    allowed = {s for s in (_tenant_cfg(tenant).get("webhook_secret"), os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos")) if s}
    if given not in allowed:
        return JsonResponse({"ok": False}, status=403)
    upd = json.loads(request.body or b"{}")
    process_update(tenant, upd, request.build_absolute_uri("/").rstrip("/"))
    return JsonResponse({"ok": True})


def process_update(tenant, upd: dict, base_url: str | None = None) -> None:
    """Bitta Telegram xabarini qayta ishlaydi — webhook ham, polling (telegram_polling) ham shuni chaqiradi."""

    if tenant.module_enabled("telegram"):
        try:
            from modules.telegram.services import handle_update
            if handle_update(tenant, upd, base_url):
                return
        except Exception:  # bot xatosi Telegram'ga 500 qaytarmasin (aks holda qayta-qayta yuboradi)
            log.exception("telegram bot handle_update xato")
            return

    msg = upd.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id:
        return
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")

    if contact and contact.get("phone_number"):
        phone = User.objects.normalize_phone(contact["phone_number"])
        user = User.objects.filter(phone=phone).first()
        if user:
            user.telegram_id = chat_id
            user.save(update_fields=["telegram_id"])
            send_message(chat_id, f"✅ <b>{user.full_name or phone}</b>, siz <b>{tenant.name}</b> tizimiga ulandingiz.\n"
                                  "Endi vazifalar, muddatlar va tasdiqlar shu yerga keladi.\n/vazifalar — ochiq vazifalarim")
        else:
            send_message(chat_id, "Bu raqam xodimlar ro'yxatida yo'q. Menejerga murojaat qiling.")
        return

    user = User.objects.filter(telegram_id=chat_id).first()
    if text.startswith("/start") or not user:
        send_message(chat_id, f"Salom! Bu <b>{tenant.name}</b> xodimlari uchun bot.\nTelefon raqamingizni ulashing:",
                     reply_markup=CONTACT_KEYBOARD)
        return

    if text.startswith("/vazifalar"):
        try:
            from modules.tasks.models import Task
            rows = Task.objects.live().filter(assignee=user, is_archived=False).open().select_related("column")[:10]
            if not rows:
                send_message(chat_id, "Ochiq vazifangiz yo'q 👍")
            else:
                lines = [f"#{t.number} {'⚠️ ' if t.is_overdue else ''}{t.title} — {t.column.name.get('uz')}"
                         + (f" (muddat {t.due_at:%d.%m %H:%M})" if t.due_at else "") for t in rows]
                send_message(chat_id, "<b>Ochiq vazifalarim</b>\n" + "\n".join(lines))
        except Exception:
            send_message(chat_id, "Vazifalar moduli yoqilmagan.")
        return

    if text.startswith("/keldim") or text.startswith("/ketdim"):
        try:
            from django.utils import timezone

            from modules.hr.models import Attendance, Employee
            e = Employee.objects.get(user=user)
            if text.startswith("/keldim"):
                if e.attendance.filter(check_out__isnull=True).exists():
                    send_message(chat_id, "Siz allaqachon smenadasiz.")
                else:
                    Attendance.objects.create(employee=e, branch=e.branch, source="telegram")
                    send_message(chat_id, f"✅ Keldingiz: {timezone.localtime():%H:%M}")
            else:
                a = e.attendance.filter(check_out__isnull=True).first()
                if a:
                    a.check_out = timezone.now(); a.save()
                    send_message(chat_id, f"👋 Ketdingiz: {timezone.localtime():%H:%M} · {a.hours} soat")
                    hr_cfg = (((tenant.settings or {}).get("modules") or {}).get("hr") or {})
                    if tenant.module_enabled("telegram") and hr_cfg.get("shift_feedback", True):
                        from modules.telegram.hr_flow import mood_markup
                        send_message(chat_id, "Bugungi smena qanday o'tdi?", reply_markup=mood_markup(a.pk))
                else:
                    send_message(chat_id, "Ochiq smena yo'q.")
        except Exception:
            send_message(chat_id, "Davomat moduli yoqilmagan yoki siz xodim sifatida ro'yxatda yo'qsiz.")
        return

    send_message(chat_id, "Buyruqlar: /vazifalar · /keldim · /ketdim")
    return
'@

Put 'backend\modules\hr\api.py' @'
"""Xodimlar API — /api/v1/hr/..."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm
from core.events import emit
from core.models import Branch, Membership, Role, User

from .models import Attendance, Employee, PayrollStatus, Payslip, Position, SalaryType, ShiftPlan, month_start

router = Router(tags=["hr"])


def _guard(request, perm: str):
    require_module(request, "hr")
    require_perm(request, perm)


class PositionIn(Schema):
    name: str
    department: str = ""
    default_salary_type: str = "monthly"
    default_rate: int = 0


class PositionOut(PositionIn):
    id: int
    employees_count: int = 0

    @staticmethod
    def resolve_employees_count(obj):
        return obj.employees.filter(is_active=True).count()


class EmployeeIn(Schema):
    full_name: str
    phone: str
    role_code: str = "cashier"
    branch_id: Optional[int] = None
    position_id: Optional[int] = None
    hire_date: Optional[date] = None
    salary_type: str = "monthly"
    rate: int = 0
    pinfl: str = ""
    passport: str = ""
    card_number: str = ""
    emergency_phone: str = ""
    note: str = ""
    is_active: bool = True
    telegram_id: Optional[int] = None


class EmployeeOut(Schema):
    id: int
    user_id: str
    full_name: str
    phone: str
    avatar: Optional[str] = None
    role_code: str = ""
    role_name: str = ""
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    position_id: Optional[int] = None
    position_name: Optional[str] = None
    hire_date: date
    salary_type: str
    rate: int
    pinfl: str
    passport: str
    card_number: str
    emergency_phone: str
    note: str
    is_active: bool
    telegram_id: Optional[int] = None
    on_shift: bool = False
    tasks: dict = {}

    @staticmethod
    def resolve_user_id(obj):
        return str(obj.user_id)

    @staticmethod
    def resolve_full_name(obj):
        return obj.user.full_name

    @staticmethod
    def resolve_phone(obj):
        return obj.user.phone

    @staticmethod
    def resolve_avatar(obj):
        return obj.user.avatar.url if obj.user.avatar else None

    @staticmethod
    def resolve_telegram_id(obj):
        return obj.user.telegram_id

    @staticmethod
    def resolve_role_code(obj):
        m = obj.user.memberships.select_related("role").first()
        return m.role.code if m else ""

    @staticmethod
    def resolve_role_name(obj):
        m = obj.user.memberships.select_related("role").first()
        return m.role.name if m else ""

    @staticmethod
    def resolve_branch_name(obj):
        return obj.branch.name if obj.branch_id else None

    @staticmethod
    def resolve_position_name(obj):
        return obj.position.name if obj.position_id else None

    @staticmethod
    def resolve_on_shift(obj):
        return obj.attendance.filter(check_out__isnull=True).exists()

    @staticmethod
    def resolve_tasks(obj):
        try:
            from modules.tasks.models import Task
            qs = Task.objects.live().filter(assignee=obj.user, is_archived=False)
            return {"open": qs.open().count(), "overdue": qs.overdue().count(),
                    "done_month": qs.filter(done_at__gte=timezone.now() - timedelta(days=30)).count()}
        except Exception:
            return {}


class ShiftIn(Schema):
    employee_id: int
    date: date
    start: str = "09:00"
    end: str = "18:00"
    branch_id: Optional[int] = None
    note: str = ""


class ShiftOut(Schema):
    id: int
    employee_id: int
    employee_name: str = ""
    date: date
    start: str
    end: str
    hours: float
    branch_id: Optional[int] = None
    note: str

    @staticmethod
    def resolve_employee_name(obj):
        return obj.employee.user.full_name

    @staticmethod
    def resolve_start(obj):
        return obj.start.strftime("%H:%M")

    @staticmethod
    def resolve_end(obj):
        return obj.end.strftime("%H:%M")


class AttendanceOut(Schema):
    id: int
    employee_id: int
    employee_name: str = ""
    check_in: datetime
    check_out: Optional[datetime] = None
    hours: float
    is_open: bool
    late_minutes: int
    source: str
    note: str

    @staticmethod
    def resolve_employee_name(obj):
        return obj.employee.user.full_name


class PayslipPatch(Schema):
    bonus: Optional[int] = None
    penalty: Optional[int] = None
    advance: Optional[int] = None
    note: Optional[str] = None


class PayslipOut(Schema):
    id: int
    employee_id: int
    employee_name: str = ""
    position: Optional[str] = None
    period: date
    salary_type: str
    rate: int
    hours: float
    shifts: int
    sales_base: int
    base: int
    bonus: int
    penalty: int
    advance: int
    total: int
    status: str
    paid_at: Optional[datetime] = None
    note: str

    @staticmethod
    def resolve_employee_name(obj):
        return obj.employee.user.full_name

    @staticmethod
    def resolve_position(obj):
        return obj.employee.position.name if obj.employee.position_id else None


# ------------------------------------------------------------------ meta
@router.get("/meta", auth=auth)
def meta(request):
    _guard(request, "hr.view")
    return {
        "positions": [PositionOut.from_orm(p).dict() for p in Position.objects.all()],
        "roles": [{"code": r.code, "name": r.name} for r in Role.objects.all()],
        "branches": [{"id": b.id, "name": b.name} for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True)],
        "salary_types": [{"code": s.value, "label": s.label} for s in SalaryType],
        "summary": {
            "employees": Employee.objects.filter(is_active=True).count(),
            "on_shift": Attendance.objects.filter(check_out__isnull=True).count(),
            "today_planned": ShiftPlan.objects.filter(date=timezone.localdate()).count(),
            "payroll_month": int(Payslip.objects.filter(period=month_start(timezone.localdate())).aggregate(s=Sum("total"))["s"] or 0),
        },
    }


# ------------------------------------------------------------------ lavozimlar
@router.post("/positions", response=PositionOut, auth=auth)
def create_position(request, data: PositionIn):
    _guard(request, "hr.edit")
    return Position.objects.create(**data.dict(), sort_order=Position.objects.count())


@router.put("/positions/{pid}", response=PositionOut, auth=auth)
def update_position(request, pid: int, data: PositionIn):
    _guard(request, "hr.edit")
    p = get_object_or_404(Position, pk=pid)
    for k, v in data.dict().items():
        setattr(p, k, v)
    p.save()
    return p


@router.delete("/positions/{pid}", auth=auth)
def delete_position(request, pid: int):
    _guard(request, "hr.edit")
    get_object_or_404(Position, pk=pid).delete()
    return {"ok": True}


# ------------------------------------------------------------------ xodimlar
def _employee_qs():
    return Employee.objects.select_related("user", "branch", "position").prefetch_related("user__memberships__role")


@router.get("/employees", response=list[EmployeeOut], auth=auth)
def list_employees(request, active: Optional[bool] = True, branch_id: Optional[int] = None, q: Optional[str] = None):
    _guard(request, "hr.view")
    qs = _employee_qs()
    if active is not None:
        qs = qs.filter(is_active=active)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if q:
        qs = qs.filter(user__full_name__icontains=q) | qs.filter(user__phone__icontains=q)
    return qs


@router.post("/employees", response=EmployeeOut, auth=auth)
def create_employee(request, data: EmployeeIn):
    with transaction.atomic():
        """Yangi xodim = foydalanuvchi (telefon bilan kiradi) + rol + xodim kartasi. Bitta forma, uch yozuv."""
        _guard(request, "hr.edit")
        phone = User.objects.normalize_phone(data.phone)
        user, created = User.objects.get_or_create(phone=phone, defaults={"full_name": data.full_name})
        if not created:
            user.full_name = data.full_name
        if data.telegram_id is not None:
            user.telegram_id = data.telegram_id
        user.save()
        role = get_object_or_404(Role, code=data.role_code)
        m, _ = Membership.objects.get_or_create(user=user, defaults={"role": role})
        if m.role_id != role.pk:
            m.role = role
            m.save()
        if data.branch_id:
            m.branches.set([data.branch_id])
        if hasattr(user, "employee"):
            raise HttpError(400, "Bu telefon raqamli xodim allaqachon bor.")
        fields = data.dict(exclude={"full_name", "phone", "role_code", "telegram_id"})
        fields["hire_date"] = fields["hire_date"] or timezone.localdate()
        e = Employee.objects.create(user=user, **fields)
        record(request, "create", e)
        emit("hr.employee_created", {"employee_id": e.pk, "user_id": str(user.pk)}, tenant=request.tenant)
        return _employee_qs().get(pk=e.pk)


@router.put("/employees/{eid}", response=EmployeeOut, auth=auth)
def update_employee(request, eid: int, data: EmployeeIn):
    with transaction.atomic():
        _guard(request, "hr.edit")
        e = get_object_or_404(_employee_qs(), pk=eid)
        before = snapshot(e)
        e.user.full_name = data.full_name
        if data.telegram_id is not None:
            e.user.telegram_id = data.telegram_id
        e.user.save()
        role = get_object_or_404(Role, code=data.role_code)
        m, _ = Membership.objects.get_or_create(user=e.user, defaults={"role": role})
        if m.role_id != role.pk:
            m.role = role
            m.save()
        if data.branch_id:
            m.branches.set([data.branch_id])
        for k, v in data.dict(exclude={"full_name", "phone", "role_code", "telegram_id"}).items():
            if k == "hire_date" and v is None:
                continue
            setattr(e, k, v)
        if not data.is_active and not e.fire_date:
            e.fire_date = timezone.localdate()
        e.save()
        record(request, "update", e, before=before)
        return _employee_qs().get(pk=e.pk)


@router.get("/employees/{eid}", response=EmployeeOut, auth=auth)
def get_employee(request, eid: int):
    _guard(request, "hr.view")
    return get_object_or_404(_employee_qs(), pk=eid)


@router.get("/employees/{eid}/card", auth=auth)
def employee_card(request, eid: int):
    """Xodim kartasi: vazifalari, davomati, oyliklari — bitta ekranda."""
    _guard(request, "hr.view")
    e = get_object_or_404(_employee_qs(), pk=eid)
    tasks = []
    try:
        from modules.tasks.models import Task
        for t in Task.objects.live().filter(assignee=e.user, is_archived=False).select_related("column")[:20]:
            tasks.append({"id": t.pk, "number": t.number, "title": t.title, "status": t.column.kind,
                          "priority": t.priority, "due_at": t.due_at, "is_overdue": t.is_overdue, "progress": t.progress})
    except Exception:
        pass
    month = month_start(timezone.localdate())
    att = Attendance.objects.filter(employee=e, check_in__date__gte=month)
    return {
        "employee": EmployeeOut.from_orm(e).dict(),
        "tasks": tasks,
        "attendance_month": {"days": att.count(), "hours": round(sum(a.hours for a in att), 1),
                             "late": att.filter(late_minutes__gt=0).count()},
        "payslips": [PayslipOut.from_orm(p).dict() for p in Payslip.objects.filter(employee=e)[:6]],
        "shifts_week": [ShiftOut.from_orm(s).dict() for s in ShiftPlan.objects.filter(
            employee=e, date__gte=timezone.localdate(), date__lt=timezone.localdate() + timedelta(days=7))],
    }


# ------------------------------------------------------------------ smena jadvali
@router.get("/shifts", response=list[ShiftOut], auth=auth)
def list_shifts(request, start: date, end: date, branch_id: Optional[int] = None):
    _guard(request, "hr.view")
    qs = ShiftPlan.objects.filter(date__gte=start, date__lte=end).select_related("employee__user")
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    return qs


@router.post("/shifts", response=ShiftOut, auth=auth)
def create_shift(request, data: ShiftIn):
    _guard(request, "hr.edit")
    d = data.dict()
    d["start"], d["end"] = time.fromisoformat(d["start"]), time.fromisoformat(d["end"])
    s, _ = ShiftPlan.objects.update_or_create(employee_id=d.pop("employee_id"), date=d.pop("date"), start=d.pop("start"), defaults=d)
    return s


@router.delete("/shifts/{sid}", auth=auth)
def delete_shift(request, sid: int):
    _guard(request, "hr.edit")
    get_object_or_404(ShiftPlan, pk=sid).delete()
    return {"ok": True}


@router.post("/shifts/copy-week", auth=auth)
def copy_week(request, from_start: date, to_start: date):
    """O'tgan hafta jadvalini keyingi haftaga nusxalash — menejer 1 klikda."""
    _guard(request, "hr.edit")
    n = 0
    for s in ShiftPlan.objects.filter(date__gte=from_start, date__lt=from_start + timedelta(days=7)):
        ShiftPlan.objects.get_or_create(employee=s.employee, date=s.date + (to_start - from_start), start=s.start,
                                        defaults={"end": s.end, "branch": s.branch, "note": s.note})
        n += 1
    return {"copied": n}


# ------------------------------------------------------------------ davomat
@router.get("/attendance", response=list[AttendanceOut], auth=auth)
def list_attendance(request, day: Optional[date] = None, employee_id: Optional[int] = None, limit: int = 200):
    _guard(request, "hr.view")
    qs = Attendance.objects.select_related("employee__user")
    if day:
        qs = qs.filter(check_in__date=day)
    if employee_id:
        qs = qs.filter(employee_id=employee_id)
    return qs[:limit]


@router.post("/attendance/check-in", response=AttendanceOut, auth=auth)
def check_in(request, employee_id: Optional[int] = None, source: str = "panel"):
    """Keldi. employee_id bo'lmasa — so'rov yuborgan xodimning o'zi (telefondan)."""
    _guard(request, "hr.view")
    e = get_object_or_404(Employee, pk=employee_id) if employee_id else get_object_or_404(Employee, user=request.auth)
    if employee_id and e.user_id != request.auth.pk:
        require_perm(request, "hr.edit")
    if e.attendance.filter(check_out__isnull=True).exists():
        raise HttpError(400, "Bu xodim allaqachon smenada.")
    now = timezone.now()
    plan = ShiftPlan.objects.filter(employee=e, date=timezone.localdate()).order_by("start").first()
    late = 0
    if plan:
        planned = timezone.make_aware(datetime.combine(plan.date, plan.start))
        late = max(0, int((now - planned).total_seconds() // 60))
    a = Attendance.objects.create(employee=e, branch=e.branch, source=source, late_minutes=late)
    emit("hr.checked_in", {"employee_id": e.pk, "late_minutes": late}, tenant=request.tenant)
    return a


@router.post("/attendance/check-out", response=AttendanceOut, auth=auth)
def check_out(request, employee_id: Optional[int] = None):
    _guard(request, "hr.view")
    e = get_object_or_404(Employee, pk=employee_id) if employee_id else get_object_or_404(Employee, user=request.auth)
    a = e.attendance.filter(check_out__isnull=True).first()
    if not a:
        raise HttpError(400, "Ochiq smena yo'q.")
    a.check_out = timezone.now()
    a.save()
    return a


# ------------------------------------------------------------------ oylik
@router.get("/payroll", response=list[PayslipOut], auth=auth)
def list_payroll(request, period: Optional[date] = None):
    _guard(request, "hr.payroll")
    p = month_start(period or timezone.localdate())
    return Payslip.objects.filter(period=p).select_related("employee__user", "employee__position")


@router.post("/payroll/compute", response=list[PayslipOut], auth=auth)
def compute_payroll(request, period: Optional[date] = None):
    with transaction.atomic():
        """Oylikni hisoblash: davomat soatlari, smenalar, savdo bazasi (percent) → har xodimga qoralama."""
        _guard(request, "hr.payroll")
        p = month_start(period or timezone.localdate())
        nxt = (p.replace(day=28) + timedelta(days=4)).replace(day=1)
        sales_total = 0
        try:
            from modules.pos.models import Order, OrderStatus
            sales_total = int(Order.objects.filter(status=OrderStatus.PAID, paid_at__date__gte=p, paid_at__date__lt=nxt)
                              .aggregate(s=Sum("total"))["s"] or 0)
        except Exception:
            pass
        out = []
        for e in Employee.objects.filter(is_active=True).select_related("user"):
            slip, _ = Payslip.objects.get_or_create(employee=e, period=p, defaults={"salary_type": e.salary_type, "rate": e.rate})
            if slip.status != PayrollStatus.DRAFT:
                out.append(slip)
                continue
            att = Attendance.objects.filter(employee=e, check_in__date__gte=p, check_in__date__lt=nxt, check_out__isnull=False)
            slip.salary_type, slip.rate = e.salary_type, e.rate
            slip.hours = round(sum(a.hours for a in att), 2)
            slip.shifts = att.values("check_in__date").distinct().count() or ShiftPlan.objects.filter(employee=e, date__gte=p, date__lt=nxt).count()
            slip.sales_base = sales_total
            slip.compute()
            slip.save()
            out.append(slip)
        return out


@router.patch("/payroll/{sid}", response=PayslipOut, auth=auth)
def patch_payslip(request, sid: int, data: PayslipPatch):
    _guard(request, "hr.payroll")
    s = get_object_or_404(Payslip, pk=sid)
    if s.status == PayrollStatus.PAID:
        raise HttpError(400, "To'langan oylikni o'zgartirib bo'lmaydi.")
    for k, v in data.dict(exclude_unset=True).items():
        setattr(s, k, v)
    s.compute()
    s.save()
    return s


@router.post("/payroll/{sid}/status", response=PayslipOut, auth=auth)
def payslip_status(request, sid: int, status: str):
    _guard(request, "hr.payroll")
    s = get_object_or_404(Payslip, pk=sid)
    if status not in PayrollStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    s.status = status
    s.paid_at = timezone.now() if status == PayrollStatus.PAID else None
    s.save()
    record(request, "payroll_status", s, after={"status": status})
    if status == PayrollStatus.PAID:
        emit("hr.payslip_paid", {"payslip_id": s.pk, "employee_id": s.employee_id, "total": s.total, "period": s.period.isoformat()},
             tenant=request.tenant)
    return s


from . import api_people  # noqa: E402,F401  (profil, KPI, vakansiyalar — shu routerga qo'shiladi)
'@

Put 'backend\modules\hr\api_people.py' @'
"""
HR API (2-qism) — /api/v1/hr/...: xodim profili, ish tarixi, hujjatlar, baholash, KPI, vakansiyalar, nomzodlar.
Asosiy router (`api.router`) ga ulanadi — alohida modul emas, «Xodimlar» modulining davomi.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.audit import record
from core.auth import auth

from . import kpi, recruit
from .api import EmployeeOut, _employee_qs, _guard, router
from .models import (
    REVIEW_CRITERIA,
    Application,
    DocKind,
    Employee,
    EmployeeDocument,
    PayrollStatus,
    Payslip,
    Review,
    ShiftFeedback,
    Stage,
    Vacancy,
    VacancyStatus,
    WorkHistory,
    month_start,
)


def _d(v):
    return v.isoformat() if v else None


def _month(s: Optional[str]) -> date:
    if s:
        try:
            y, m = s.split("-")[:2]
            return date(int(y), int(m), 1)
        except (ValueError, TypeError):
            raise HttpError(400, "Oy formati: YYYY-MM") from None
    return month_start(timezone.localdate())


def _media_url(f):
    try:
        return f.url if f else None
    except Exception:
        return None


# ================================================================== XODIM PROFILI
class ProfileIn(Schema):
    birth_date: Optional[date] = None
    gender: str = ""
    address: str = ""
    emergency_name: str = ""
    emergency_phone: str = ""
    education: str = ""
    languages: list[str] = []
    skills: list[str] = []
    about: str = ""
    medical_book_until: Optional[date] = None


def _wh_out(w: WorkHistory) -> dict:
    return {"id": w.pk, "company": w.company, "position": w.position, "start": w.start, "end": w.end,
            "reason_left": w.reason_left, "reference_phone": w.reference_phone, "note": w.note}


def _doc_out(x: EmployeeDocument) -> dict:
    today = timezone.localdate()
    return {"id": x.pk, "kind": x.kind, "kind_label": DocKind(x.kind).label, "title": x.title,
            "url": _media_url(x.file) or x.url or None, "expires_on": _d(x.expires_on),
            "expired": bool(x.expires_on and x.expires_on < today),
            "expiring": bool(x.expires_on and 0 <= (x.expires_on - today).days <= 30)}


def _review_out(r: Review) -> dict:
    return {"id": r.pk, "period": r.period.strftime("%Y-%m"), "scores": r.scores, "average": r.average,
            "strengths": r.strengths, "improve": r.improve, "goals": r.goals,
            "reviewer": r.reviewer.full_name if r.reviewer_id else None, "created_at": _d(r.created_at)}


@router.get("/employees/{int:eid}/profile", auth=auth)
def employee_profile(request, eid: int, month: Optional[str] = None):
    """To'liq xodim profili: shaxsiy ma'lumot, ish tarixi, hujjatlar, baholar, KPI, kayfiyat, qayerdan kelgani."""
    _guard(request, "hr.view")
    e = get_object_or_404(_employee_qs(), pk=eid)
    today = timezone.localdate()
    m = _month(month)
    app = Application.objects.filter(employee=e).select_related("vacancy").first()
    fb = list(ShiftFeedback.objects.filter(employee=e)[:12])
    tenure = (today - e.hire_date).days if e.hire_date else 0
    return {
        "employee": EmployeeOut.from_orm(e).dict(),
        "profile": {"birth_date": _d(e.birth_date), "age": (today.year - e.birth_date.year - ((today.month, today.day) < (e.birth_date.month, e.birth_date.day))) if e.birth_date else None,
                    "gender": e.gender, "address": e.address, "emergency_name": e.emergency_name, "emergency_phone": e.emergency_phone,
                    "education": e.education, "languages": e.languages, "skills": e.skills, "about": e.about,
                    "medical_book_until": _d(e.medical_book_until),
                    "medical_expired": bool(e.medical_book_until and e.medical_book_until < today),
                    "medical_expiring": bool(e.medical_book_until and 0 <= (e.medical_book_until - today).days <= 30),
                    "source": e.source, "fire_date": _d(e.fire_date), "fire_reason": e.fire_reason,
                    "tenure_days": tenure, "tenure_text": _tenure(tenure)},
        "work_history": [_wh_out(w) for w in e.work_history.all()],
        "documents": [_doc_out(x) for x in e.documents.all()],
        "reviews": [_review_out(r) for r in e.reviews.select_related("reviewer")[:12]],
        "kpi": {"month": m.strftime("%Y-%m"), **kpi.compute(e, m, request.tenant)},
        "kpi_history": [{"month": mm.strftime("%Y-%m"), **{k: v for k, v in kpi.compute(e, mm, request.tenant).items() if k in ("score", "grade")}}
                        for mm in _last_months(m, 6)],
        "feedback": [{"date": _d(f.date), "mood": f.mood, "comment": f.comment} for f in fb],
        "application": {"id": app.pk, "vacancy": app.vacancy.title if app.vacancy else None, "source": app.source,
                        "applied_at": _d(app.created_at), "answers": app.answers} if app else None,
        "criteria": [{"key": k, "label": v} for k, v in REVIEW_CRITERIA],
    }


def _tenure(days: int) -> str:
    if days < 31:
        return f"{days} kun"
    if days < 365:
        return f"{days // 30} oy"
    y, mo = divmod(days // 30, 12)
    return f"{y} yil" + (f" {mo} oy" if mo else "")


def _last_months(m: date, n: int) -> list[date]:
    out = [m]
    for _ in range(n - 1):
        prev = (out[0].replace(day=1) - timedelta(days=1)).replace(day=1)
        out.insert(0, prev)
    return out


@router.put("/employees/{int:eid}/profile", auth=auth)
def update_profile(request, eid: int, data: ProfileIn):
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee, pk=eid)
    if data.gender not in ("", "m", "f"):
        raise HttpError(400, "Jinsi: m yoki f")
    for k, v in data.dict().items():
        if isinstance(v, list):
            v = [str(x).strip() for x in v if str(x).strip()][:20]
        setattr(e, k, v)
    e.save()
    record(request, "update", e, after={"profile": True})
    return employee_profile(request, eid)


class WorkIn(Schema):
    company: str
    position: str = ""
    start: str = ""
    end: str = ""
    reason_left: str = ""
    reference_phone: str = ""
    note: str = ""


@router.post("/employees/{int:eid}/work-history", auth=auth)
def add_work(request, eid: int, data: WorkIn):
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee, pk=eid)
    if not data.company.strip():
        raise HttpError(400, "Ish joyi nomini yozing.")
    w = WorkHistory.objects.create(employee=e, **{k: (v or "").strip() for k, v in data.dict().items()})
    return _wh_out(w)


@router.put("/work-history/{int:wid}", auth=auth)
def update_work(request, wid: int, data: WorkIn):
    _guard(request, "hr.edit")
    w = get_object_or_404(WorkHistory, pk=wid)
    for k, v in data.dict().items():
        setattr(w, k, (v or "").strip())
    w.save()
    return _wh_out(w)


@router.delete("/work-history/{int:wid}", auth=auth)
def delete_work(request, wid: int):
    _guard(request, "hr.edit")
    get_object_or_404(WorkHistory, pk=wid).delete()
    return {"ok": True}


@router.post("/employees/{int:eid}/documents", auth=auth)
def add_document(request, eid: int, title: str = "", kind: str = "other", url: str = "", expires_on: Optional[date] = None,
                 file: Optional[UploadedFile] = File(None)):
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee, pk=eid)
    if kind not in DocKind.values:
        kind = DocKind.OTHER
    if not file and not url.startswith(("http://", "https://")):
        raise HttpError(400, "Fayl yuklang yoki havola (https://…) kiriting.")
    if file and file.size > 15 * 1024 * 1024:
        raise HttpError(400, "Fayl 15 MB dan katta bo'lmasin (katta fayl uchun havola qo'ying).")
    d = EmployeeDocument(employee=e, kind=kind, title=(title or DocKind(kind).label)[:160], url=url if not file else "", expires_on=expires_on)
    if file:
        d.file.save(file.name, file, save=False)
    d.save()
    if kind == DocKind.MEDBOOK and expires_on and (not e.medical_book_until or expires_on > e.medical_book_until):
        e.medical_book_until = expires_on
        e.save(update_fields=["medical_book_until"])
    record(request, "create", d)
    return _doc_out(d)


@router.delete("/documents/{int:did}", auth=auth)
def delete_document(request, did: int):
    _guard(request, "hr.edit")
    get_object_or_404(EmployeeDocument, pk=did).delete()
    return {"ok": True}


class FireIn(Schema):
    date: Optional[date] = None
    reason: str = ""


@router.post("/employees/{int:eid}/fire", auth=auth)
def fire(request, eid: int, data: FireIn):
    """Ishdan bo'shatish: karta arxivga (tarix saqlanadi), tizimga kirish yopiladi."""
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee.objects.select_related("user"), pk=eid)
    if not data.reason.strip():
        raise HttpError(400, "Sababini yozing (ichki ma'lumot).")
    e.is_active, e.fire_date, e.fire_reason = False, data.date or timezone.localdate(), data.reason.strip()[:200]
    e.save()
    if not e.user.is_superuser and not e.user.memberships.filter(role__code="owner").exists():
        e.user.is_active = False
        e.user.save(update_fields=["is_active"])
    record(request, "fire", e, after={"reason": e.fire_reason})
    return {"ok": True}


# ================================================================== BAHOLASH / KPI
class ReviewIn(Schema):
    month: Optional[str] = None
    scores: dict[str, int]
    strengths: str = ""
    improve: str = ""
    goals: str = ""


@router.post("/employees/{int:eid}/reviews", auth=auth)
def add_review(request, eid: int, data: ReviewIn):
    _guard(request, "hr.review")
    e = get_object_or_404(Employee, pk=eid)
    keys = {k for k, _ in REVIEW_CRITERIA}
    sc = {k: int(v) for k, v in (data.scores or {}).items() if k in keys and v}
    if len(sc) < 3:
        raise HttpError(400, "Kamida 3 ta mezonni baholang (1–5).")
    if any(not 1 <= v <= 5 for v in sc.values()):
        raise HttpError(400, "Baho 1 dan 5 gacha.")
    per = _month(data.month)
    r, _ = Review.objects.update_or_create(employee=e, period=per, reviewer=request.auth,
                                           defaults={"scores": sc, "strengths": data.strengths[:300], "improve": data.improve[:300], "goals": data.goals[:300]})
    record(request, "review", e, after={"period": per.isoformat(), "avg": r.average})
    if e.user.telegram_id and data.goals.strip():
        recruit.tg(request.tenant, e.user.telegram_id, f"📊 <b>{per:%m.%Y} oy bahongiz</b>: {r.average} / 5\n"
                                                        + (f"💪 {data.strengths}\n" if data.strengths else "") + f"🎯 Keyingi oy maqsadi: {data.goals}")
    return _review_out(r)


@router.get("/kpi", auth=auth)
def kpi_board(request, month: Optional[str] = None, branch_id: Optional[int] = None):
    _guard(request, "hr.review")
    m = _month(month)
    rows = kpi.leaderboard(m, request.tenant, branch_id)
    scored = [r for r in rows if r["score"] is not None]
    return {"month": m.strftime("%Y-%m"), "rows": rows, "criteria": [{"key": k, "label": v} for k, v in REVIEW_CRITERIA],
            "weights": [{"key": k, "label": kpi.LABELS[k], "weight": w} for k, w in kpi.WEIGHTS.items()],
            "summary": {"avg": round(sum(r["score"] for r in scored) / len(scored), 1) if scored else None,
                        "grades": {g: sum(1 for r in scored if r["grade"] == g) for g in "ABCD"},
                        "risk": sum(1 for r in rows if r["risk"]), "reviewed": sum(1 for r in rows if r["reviewed"]), "total": len(rows),
                        "bonus_total": sum(r["bonus_suggest"] for r in rows)}}


class BonusIn(Schema):
    month: Optional[str] = None
    employee_ids: list[int] = []


@router.post("/kpi/apply-bonus", auth=auth)
def kpi_apply_bonus(request, data: BonusIn):
    """KPI bo'yicha tavsiya bonusni shu oyning QORALAMA oyliklariga yozadi (tasdiqlanganlarga tegmaydi)."""
    _guard(request, "hr.payroll")
    m = _month(data.month)
    n = 0
    for r in kpi.leaderboard(m, request.tenant):
        if data.employee_ids and r["employee_id"] not in data.employee_ids:
            continue
        if not r["bonus_suggest"]:
            continue
        s = Payslip.objects.filter(employee_id=r["employee_id"], period=m, status=PayrollStatus.DRAFT).first()
        if s is None:
            continue
        s.bonus = r["bonus_suggest"]
        s.note = (s.note + f" · KPI {r['grade']} ({r['score']})").strip(" ·")[:200]
        s.compute()
        s.save()
        n += 1
    record(request, "kpi_bonus", model="Payslip", after={"month": m.isoformat(), "count": n})
    return {"updated": n}


# ================================================================== VAKANSIYALAR
class VacancyIn(Schema):
    title: str
    position_id: Optional[int] = None
    branch_id: Optional[int] = None
    role_code: str = "waiter"
    employment: str = "full"
    salary_from: int = 0
    salary_to: int = 0
    salary_note: str = ""
    schedule: str = ""
    summary: str = ""
    requirements: list[str] = []
    duties: list[str] = []
    benefits: list[str] = []
    image_url: str = ""
    video_url: str = ""
    link_url: str = ""
    questions: list[dict] = []
    status: str = VacancyStatus.DRAFT
    responsible_id: Optional[str] = None
    closes_on: Optional[date] = None


def vacancy_out(v: Vacancy, stats: bool = True) -> dict:
    out = {"id": v.pk, "title": v.title, "position_id": v.position_id, "position": v.position.name if v.position_id else None,
           "branch_id": v.branch_id, "branch": v.branch.name if v.branch_id else None, "role_code": v.role_code,
           "employment": v.employment, "employment_label": recruit.EMPLOYMENT.get(v.employment, v.employment),
           "salary_from": v.salary_from, "salary_to": v.salary_to, "salary_note": v.salary_note, "salary_text": recruit.salary_text(v),
           "schedule": v.schedule, "summary": v.summary, "requirements": v.requirements, "duties": v.duties, "benefits": v.benefits,
           "image": v.image_src, "image_url": v.image_url, "video_url": v.video_url, "link_url": v.link_url, "questions": v.questions,
           "status": v.status, "status_label": VacancyStatus(v.status).label, "is_open": recruit.is_open(v),
           "responsible_id": str(v.responsible_id) if v.responsible_id else None,
           "responsible": v.responsible.full_name if v.responsible_id else None, "closes_on": _d(v.closes_on), "views": v.views,
           "created_at": _d(v.created_at)}
    if stats:
        c = dict(v.applications.values_list("stage").annotate(n=Count("id")))
        out["applications"] = sum(c.values())
        out["by_stage"] = c
        out["new"] = c.get(Stage.NEW, 0)
    return out


def _clean_vacancy(data: VacancyIn) -> dict:
    d = data.dict()
    d["title"] = d["title"].strip()
    if not d["title"]:
        raise HttpError(400, "Vakansiya nomini yozing.")
    if d["status"] not in VacancyStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    for k in ("image_url", "video_url", "link_url"):
        if d[k] and not d[k].startswith(("http://", "https://")):
            raise HttpError(400, "Havola https:// bilan boshlanishi kerak.")
    for k in ("requirements", "duties", "benefits"):
        d[k] = [str(x).strip() for x in d[k] if str(x).strip()][:20]
    qs = []
    for q in d["questions"][:10]:
        t = str(q.get("text") or "").strip()
        if t:
            qs.append({"text": t[:200], "type": q.get("type") if q.get("type") in ("yesno", "text") else "text",
                       "must": str(q.get("must") or "").strip().lower()[:10]})
    d["questions"] = qs
    if d["salary_to"] and d["salary_from"] and d["salary_to"] < d["salary_from"]:
        raise HttpError(400, "Maosh «gacha» qiymati «dan»dan kichik bo'lmasin.")
    d["responsible_id"] = d.pop("responsible_id") or None
    return d


@router.get("/vacancies", auth=auth)
def list_vacancies(request):
    _guard(request, "hr.recruit")
    from website.views import _bot_link
    out = [vacancy_out(v) for v in Vacancy.objects.select_related("position", "branch", "responsible")]
    for x in out:
        x["public_path"] = f"/vacancies/{x['id']}/"
        x["bot_link"] = _bot_link(request, x["id"])
    return out


@router.post("/vacancies", auth=auth)
def create_vacancy(request, data: VacancyIn):
    _guard(request, "hr.recruit")
    v = Vacancy.objects.create(**_clean_vacancy(data))
    record(request, "create", v)
    return vacancy_out(v)


@router.put("/vacancies/{int:vid}", auth=auth)
def update_vacancy(request, vid: int, data: VacancyIn):
    _guard(request, "hr.recruit")
    v = get_object_or_404(Vacancy, pk=vid)
    for k, val in _clean_vacancy(data).items():
        setattr(v, k, val)
    v.save()
    record(request, "update", v)
    return vacancy_out(v)


@router.post("/vacancies/{int:vid}/image", auth=auth)
def vacancy_image(request, vid: int, file: UploadedFile = File(...)):
    _guard(request, "hr.recruit")
    v = get_object_or_404(Vacancy, pk=vid)
    if not (file.content_type or "").startswith("image/") or file.size > 8 * 1024 * 1024:
        raise HttpError(400, "Rasm (JPG/PNG), 8 MB gacha.")
    v.image.save(file.name, file, save=True)
    return vacancy_out(v)


@router.delete("/vacancies/{int:vid}", auth=auth)
def delete_vacancy(request, vid: int):
    _guard(request, "hr.recruit")
    v = get_object_or_404(Vacancy, pk=vid)
    if v.applications.exists():
        v.status = VacancyStatus.CLOSED
        v.save(update_fields=["status", "updated_at"])
        return {"ok": True, "closed": True}
    v.delete()
    return {"ok": True}


# ================================================================== NOMZODLAR
def app_out(a: Application, full: bool = False) -> dict:
    age = (timezone.localdate().year - a.birth_year) if a.birth_year else None
    out = {"id": a.pk, "vacancy_id": a.vacancy_id, "vacancy": a.vacancy.title if a.vacancy_id else None, "full_name": a.full_name,
           "phone": a.phone, "age": age, "city": a.city, "source": a.source, "stage": a.stage, "stage_label": Stage(a.stage).label,
           "rating": a.rating, "knocked_out": a.knocked_out, "tg": bool(a.tg_chat_id), "tg_username": a.tg_username,
           "photo": _media_url(a.photo), "interview_at": _d(a.interview_at), "interview_place": a.interview_place,
           "created_at": _d(a.created_at), "stage_changed_at": _d(a.stage_changed_at), "employee_id": a.employee_id,
           "experience_short": (a.experience or "")[:120]}
    if full:
        out.update({"experience": a.experience, "work_history": a.work_history, "answers": a.answers, "notes": a.notes,
                    "resume": _media_url(a.resume), "reject_reason": a.reject_reason, "birth_year": a.birth_year,
                    "events": [{"at": _d(ev.at), "kind": ev.kind, "text": ev.text, "actor": ev.actor.full_name if ev.actor_id else None}
                               for ev in a.events.select_related("actor")[:30]]})
    return out


@router.get("/applications", auth=auth)
def list_applications(request, vacancy_id: Optional[int] = None, stage: Optional[str] = None, q: str = ""):
    _guard(request, "hr.recruit")
    qs = Application.objects.select_related("vacancy")
    if vacancy_id:
        qs = qs.filter(vacancy_id=vacancy_id)
    if stage:
        qs = qs.filter(stage=stage)
    if q.strip():
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = Q(full_name__icontains=q.strip())
        if digits:
            cond |= Q(phone__contains=digits)
        qs = qs.filter(cond)
    return [app_out(a) for a in qs[:500]]


@router.get("/applications/{int:aid}", auth=auth)
def get_application(request, aid: int):
    _guard(request, "hr.recruit")
    return app_out(get_object_or_404(Application.objects.select_related("vacancy"), pk=aid), full=True)


class AppIn(Schema):
    vacancy_id: Optional[int] = None
    full_name: str
    phone: str
    birth_year: Optional[int] = None
    city: str = ""
    experience: str = ""
    work_history: list[dict] = []
    source: str = "manual"


@router.post("/applications", auth=auth)
def add_application(request, data: AppIn):
    """Qo'lda nomzod qo'shish (telefon orqali, tanish tavsiyasi)."""
    _guard(request, "hr.recruit")
    v = Vacancy.objects.filter(pk=data.vacancy_id).first() if data.vacancy_id else None
    try:
        a = recruit.create_application(request.tenant, v, full_name=data.full_name, phone=data.phone, experience=data.experience,
                                       work_history=data.work_history, birth_year=data.birth_year, city=data.city,
                                       source=data.source if data.source in ("manual", "referral") else "manual")
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    return app_out(a, full=True)


class PatchIn(Schema):
    rating: Optional[int] = None
    notes: Optional[str] = None


@router.patch("/applications/{int:aid}", auth=auth)
def patch_application(request, aid: int, data: PatchIn):
    _guard(request, "hr.recruit")
    a = get_object_or_404(Application, pk=aid)
    if data.rating is not None:
        a.rating = max(0, min(5, data.rating))
    if data.notes is not None:
        a.notes = data.notes[:3000]
    a.save()
    return app_out(a, full=True)


class StageIn(Schema):
    stage: str
    note: str = ""
    interview_at: Optional[datetime] = None
    place: str = ""
    reason: str = ""
    notify: bool = True


@router.post("/applications/{int:aid}/stage", auth=auth)
def move_application(request, aid: int, data: StageIn):
    _guard(request, "hr.recruit")
    a = get_object_or_404(Application.objects.select_related("vacancy"), pk=aid)
    try:
        recruit.move(request.tenant, a, data.stage, request.auth, note=data.note, interview_at=data.interview_at,
                     place=data.place, reason=data.reason, notify=data.notify)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    return app_out(a, full=True)


class HireIn(Schema):
    role_code: Optional[str] = None
    branch_id: Optional[int] = None
    position_id: Optional[int] = None
    salary_type: Optional[str] = None
    rate: Optional[int] = None
    hire_date: Optional[date] = None


@router.post("/applications/{int:aid}/hire", auth=auth)
def hire_application(request, aid: int, data: HireIn):
    _guard(request, "hr.recruit")
    require = request.auth.has_perm_code("hr.edit")
    if not require:
        raise HttpError(403, "Xodim qo'shish uchun hr.edit ruxsati kerak.")
    a = get_object_or_404(Application.objects.select_related("vacancy"), pk=aid)
    if a.stage == Stage.HIRED:
        raise HttpError(400, "Bu nomzod allaqachon qabul qilingan.")
    try:
        e = recruit.hire(request.tenant, a, request.auth, **data.dict())
    except ValueError as err:
        raise HttpError(400, str(err)) from None
    record(request, "hire", e, after={"application": a.pk})
    return {"ok": True, "employee_id": e.pk, "application": app_out(a, full=True)}


class MsgIn(Schema):
    text: str


@router.post("/applications/{int:aid}/message", auth=auth)
def message_candidate(request, aid: int, data: MsgIn):
    _guard(request, "hr.recruit")
    a = get_object_or_404(Application, pk=aid)
    if not a.tg_chat_id:
        raise HttpError(400, "Nomzod Telegram orqali ariza bermagan — telefon qiling: " + a.phone)
    if not data.text.strip():
        raise HttpError(400, "Xabar matnini yozing.")
    ok = recruit.tg(request.tenant, a.tg_chat_id, data.text.strip())
    recruit.event(a, "message", f"Xabar: {data.text.strip()[:300]}", request.auth)
    return {"ok": ok}


@router.get("/recruit/stats", auth=auth)
def recruit_stats(request):
    _guard(request, "hr.recruit")
    now = timezone.now()
    m = now - timedelta(days=30)
    apps = Application.objects.all()
    hired = apps.filter(stage=Stage.HIRED, stage_changed_at__gte=m)
    days = [(a.stage_changed_at - a.created_at).days for a in hired]
    return {"open": Vacancy.objects.filter(status=VacancyStatus.OPEN).count(),
            "applications_30d": apps.filter(created_at__gte=m).count(), "new": apps.filter(stage=Stage.NEW).count(),
            "interviews_upcoming": apps.filter(stage__in=[Stage.INTERVIEW, Stage.TRIAL], interview_at__gte=now).count(),
            "hired_30d": len(days), "time_to_hire": round(sum(days) / len(days), 1) if days else None,
            "by_stage": dict(apps.values_list("stage").annotate(n=Count("id"))),
            "by_source": dict(apps.values_list("source").annotate(n=Count("id")))}
'@

Put 'backend\modules\hr\demo.py' @'
"""Demo: lavozimlar, xodim kartalari, bu hafta smenalari, davomat, joriy oy oyligi."""
import random
from datetime import datetime, time, timedelta

from django.utils import timezone

from core.models import Branch, Membership

from .models import Attendance, Employee, Payslip, Position, ShiftPlan, month_start

POS = [("Menejer", "Boshqaruv", "monthly", 6_000_000), ("Kassir", "Kassa", "shift", 180_000), ("Oshpaz", "Oshxona", "monthly", 5_000_000),
       ("Ofitsiant", "Zal", "hourly", 22_000), ("Buxgalter", "Boshqaruv", "monthly", 4_500_000), ("Marketolog", "Boshqaruv", "monthly", 4_000_000)]
ROLE2POS = {"manager": "Menejer", "cashier": "Kassir", "cook": "Oshpaz", "accountant": "Buxgalter", "marketer": "Marketolog", "courier": "Ofitsiant"}


def seed_demo_hr() -> int:
    if Employee.objects.exists():
        return 0
    random.seed(3)
    positions = {n: Position.objects.get_or_create(name=n, defaults={"department": d, "default_salary_type": st, "default_rate": r, "sort_order": i})[0]
                 for i, (n, d, st, r) in enumerate(POS)}
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    n = 0
    today = timezone.localdate()
    for m in Membership.objects.select_related("user", "role").exclude(role__code="owner"):
        pos = positions.get(ROLE2POS.get(m.role.code, "Ofitsiant"))
        e = Employee.objects.create(user=m.user, position=pos, branch=branch, salary_type=pos.default_salary_type,
                                    rate=pos.default_rate, hire_date=today - timedelta(days=random.randint(40, 700)))
        # bu hafta va o'tgan hafta smenalari
        for d in range(-7, 7):
            day = today + timedelta(days=d)
            if day.weekday() == random.randint(0, 6):
                continue
            ShiftPlan.objects.create(employee=e, branch=branch, date=day, start=time(9, 0), end=time(18, 0) if pos.name != "Kassir" else time(23, 0))
        # o'tgan kunlar davomati
        for d in range(-7, 0):
            day = today + timedelta(days=d)
            if not ShiftPlan.objects.filter(employee=e, date=day).exists():
                continue
            late = random.choice([0, 0, 0, 12, 25])
            cin = timezone.make_aware(datetime.combine(day, time(9, late)))
            Attendance.objects.create(employee=e, branch=branch, check_in=cin, check_out=cin + timedelta(hours=9), late_minutes=late)
        n += 1
    # bugun smenada bo'lganlar
    for e in Employee.objects.all()[:4]:
        Attendance.objects.create(employee=e, branch=branch, check_in=timezone.now() - timedelta(hours=3))
    # joriy oy oyligi (qoralama)
    for e in Employee.objects.all():
        s = Payslip(employee=e, period=month_start(today), salary_type=e.salary_type, rate=e.rate, hours=160, shifts=22, sales_base=0)
        s.compute()
        s.save()
    return n


# ================================================================== ishga olish + profil + baholash (demo)
_C = "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width=640"
VACANCIES = [
    {"title": "Ofitsiant", "role_code": "waiter", "pos": "Ofitsiant", "employment": "shift", "salary_from": 3_500_000, "salary_to": 5_500_000,
     "salary_note": "+ choychaqa (o'rtacha 1–1,5 mln) va KPI bonus", "schedule": "2/2, 10:00–23:00",
     "summary": "Jamoamizga xushmuomala, tez va tartibli ofitsiant kerak. Tajriba bo'lmasa — 2 haftalik o'qitish kursini o'tkazamiz.",
     "requirements": ["18 yoshdan katta", "Xushmuomalalik va ozodalik", "Rus tilini bilish — afzallik", "Tibbiy daftarcha (bo'lmasa — yordam beramiz)"],
     "duties": ["Mehmonlarni kutib olish va joylashtirish", "Menyu bo'yicha maslahat, buyurtma olish (planshetda)", "Stolga xizmat va hisob-kitob", "Zal tozaligi"],
     "benefits": ["Bepul tushlik va kechki ovqat", "Rasmiy ishga joylashtirish", "Bepul forma", "Oylik o'z vaqtida, har oy 5-sanada", "Katta ofitsiantgacha o'sish"],
     "image": "Uzbek_palov_in_Yerevan_Food_Court.jpg", "video": "https://www.youtube.com/watch?v=jBe8e69ypcc", "status": "open",
     "questions": [{"text": "Kechki smenada (23:00 gacha) ishlay olasizmi?", "type": "yesno", "must": "ha"},
                   {"text": "Tibbiy daftarchangiz bormi?", "type": "yesno", "must": ""}, {"text": "Qachondan ishga chiqa olasiz?", "type": "text", "must": ""}]},
    {"title": "Oshpaz yordamchisi", "role_code": "cook", "pos": "Oshpaz", "employment": "full", "salary_from": 4_000_000, "salary_to": 5_000_000,
     "salary_note": "sinov muddatidan keyin oshiriladi", "schedule": "6/1, 08:00–18:00",
     "summary": "Osh va kabob sexiga yordamchi. Katta oshpaz qo'lida hunar o'rganasiz.",
     "requirements": ["Oshxonada 6 oydan tajriba — afzallik", "Pichoq bilan ishlash ko'nikmasi", "Gigiyena qoidalariga rioya", "Tibbiy daftarcha majburiy"],
     "duties": ["Sabzavot va go'sht tayyorlash (zagatovka)", "Zirvak, salatlar", "Ish joyi va inventar tozaligi", "Mahsulotni FIFO bo'yicha joylash"],
     "benefits": ["Bepul ovqat", "Rasmiy ishga joylashtirish", "Oshpazlik kursi — kompaniya hisobidan"],
     "image": "Plov_Tashkent.jpg", "video": "https://www.youtube.com/watch?v=oLTaMPjAgLo", "status": "open",
     "questions": [{"text": "Ertalab 08:00 da ish boshlay olasizmi?", "type": "yesno", "must": "ha"},
                   {"text": "Oshxonada qancha ishlagansiz?", "type": "text", "must": ""}]},
    {"title": "Kassir", "role_code": "cashier", "pos": "Kassir", "employment": "shift", "salary_from": 3_800_000, "salary_to": 4_500_000,
     "salary_note": "", "schedule": "2/2, 09:00–23:00",
     "summary": "Kassada ishlash, mehmonlar bilan muloqot. Kassa dasturini 1 kunda o'rgatamiz.",
     "requirements": ["Diqqatlilik va halollik", "Kompyuter/planshet bilan ishlay olish", "20 yoshdan katta"],
     "duties": ["Buyurtmalarni kassaga kiritish", "Naqd va karta to'lovlarini qabul qilish", "Smena oxirida kassa hisoboti"],
     "benefits": ["Bepul ovqat", "Rasmiy ishga joylashtirish", "Qulay grafik"],
     "image": "Samarqand_noni.jpg", "video": "", "status": "open",
     "questions": [{"text": "Oldin kassada ishlaganmisiz?", "type": "yesno", "must": ""}]},
    {"title": "Kuryer (o'z mashinasi bilan)", "role_code": "courier", "pos": "Ofitsiant", "employment": "part", "salary_from": 0, "salary_to": 0,
     "salary_note": "har yetkazish uchun 15 000 so'm + yoqilg'i", "schedule": "moslashuvchan",
     "summary": "Toshkent bo'ylab buyurtma yetkazish.", "requirements": ["Haydovchilik guvohnomasi (B)", "O'z avtomobili"],
     "duties": ["Buyurtmani o'z vaqtida yetkazish"], "benefits": ["Kunlik to'lov"],
     "image": "Shashlik.jpg", "video": "", "status": "paused", "questions": []},
]
FIRST = ["Aziz", "Bekzod", "Dilnoza", "Feruza", "Javohir", "Kamola", "Laziz", "Madina", "Nigora", "Oybek", "Sevara", "Temur", "Ulug'bek", "Zarina",
         "Shohruh", "Mohira", "Anvar", "Gulchehra"]
LAST_M = ["Rashidov", "Tursunov", "Xolmatov", "Ismoilov", "Abdullayev", "Normatov", "Qodirov", "Mirzayev", "Sobirov"]
PREV = [("«Rayhon» milliy taomlari", "ofitsiant"), ("Evos", "kassir"), ("«Caravan» restorani", "ofitsiant"), ("Safia", "sotuvchi-kassir"),
        ("«Besh qozon» osh markazi", "oshpaz yordamchisi"), ("Oqtepa Lavash", "kassir"), ("«Afsona» restorani", "ofitsiant"),
        ("Chayxana «Navvat»", "oshpaz"), ("KFC Chilonzor", "oshxona xodimi"), ("Bellissimo", "kuryer")]
STAGE_PLAN = [("new", 5), ("screen", 3), ("interview", 3), ("trial", 2), ("offer", 1), ("rejected", 3)]


def _name(rnd, i):
    f = FIRST[i % len(FIRST)]
    last = LAST_M[rnd.randrange(len(LAST_M))]
    female = f in ("Dilnoza", "Feruza", "Kamola", "Madina", "Nigora", "Sevara", "Zarina", "Mohira", "Gulchehra")
    return f"{f} {last + 'a' if female else last}"


def seed_demo_recruit_people(reviewer=None) -> dict:
    """Vakansiyalar + nomzodlar (barcha bosqichlarda) + xodim profili, ish tarixi, hujjatlar, baholar, kayfiyat."""
    from . import recruit
    from .models import (
        REVIEW_CRITERIA,
        Application,
        ApplicationEvent,
        DocKind,
        EmployeeDocument,
        Review,
        ShiftFeedback,
        Stage,
        Vacancy,
        WorkHistory,
    )
    if Vacancy.objects.exists():
        return {"vacancies": 0}
    rnd = random.Random(11)
    now, today = timezone.now(), timezone.localdate()
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    positions = {p.name: p for p in Position.objects.all()}
    vacs = []
    for v in VACANCIES:
        vacs.append(Vacancy.objects.create(
            title=v["title"], role_code=v["role_code"], position=positions.get(v["pos"]), branch=branch, employment=v["employment"],
            salary_from=v["salary_from"], salary_to=v["salary_to"], salary_note=v["salary_note"], schedule=v["schedule"], summary=v["summary"],
            requirements=v["requirements"], duties=v["duties"], benefits=v["benefits"], image_url=_C.format(v["image"]), video_url=v["video"],
            questions=v["questions"], status=v["status"], responsible=reviewer, views=rnd.randint(40, 380)))
    # --- nomzodlar
    n, i = 0, 0
    places = ["Chilonzor filiali, 2-qavat ofis", "Bosh ofis, menejer xonasi"]
    for stage, cnt in STAGE_PLAN:
        for _ in range(cnt):
            v = vacs[i % 3]
            i += 1
            comp, pos = PREV[rnd.randrange(len(PREV))]
            yes = rnd.random() > (0.5 if stage == "rejected" else 0.1)
            raw = [{"i": k, "a": ("Ha" if yes or k else "Yo'q") if q["type"] == "yesno" else rnd.choice(["Dushanbadan", "Ertadan", "1 haftadan keyin", "2 yil"])}
                   for k, q in enumerate(v.questions)]
            answers, ko = recruit.check_answers(v, raw)
            created = now - timedelta(days=rnd.randint(0, 3) if stage == "new" else rnd.randint(3, 20), hours=rnd.randint(0, 10))
            src = rnd.choice(["site", "site", "telegram", "telegram", "telegram", "referral"])
            a = Application.objects.create(
                vacancy=v, full_name=_name(rnd, i), phone=f"+99893{rnd.randint(1000000, 9999999)}", birth_year=rnd.randint(1990, 2006),
                city="Toshkent", source=src, tg_chat_id=(700000 + i) if src == "telegram" else None,
                tg_username=f"user{700 + i}" if src == "telegram" else "",
                experience=rnd.choice(["", "Tajribam bor, mehmon bilan ishlashni yaxshi ko'raman.", f"{comp}da {rnd.randint(1, 3)} yil ishlaganman.",
                                       "Talabaman, kechki smenalarda ishlamoqchiman."]),
                work_history=[{"company": comp, "position": pos, "years": f"{rnd.randint(2018, 2023)}–{rnd.randint(2024, 2026)}"}],
                answers=answers, knocked_out=ko, stage=stage, rating=rnd.choice([0, 3, 4, 4, 5]) if stage != "new" else 0,
                interview_at=(now + timedelta(days=rnd.randint(1, 4), hours=rnd.randint(-3, 3))) if stage in ("interview", "trial") else None,
                interview_place=places[rnd.randrange(2)] if stage in ("interview", "trial") else "",
                reject_reason=rnd.choice(["Kechki smenaga chiqa olmaydi", "Tajriba yetarli emas", "Maosh kutilmasi yuqori"]) if stage == "rejected" else "",
                notes="Suhbatda yaxshi taassurot qoldirdi." if stage in ("offer", "trial") else "",
                stage_changed_at=created + timedelta(days=1) if stage != "new" else created)
            Application.objects.filter(pk=a.pk).update(created_at=created)
            ApplicationEvent.objects.create(application=a, at=created, kind="created",
                                            text=f"Ariza: {dict(site='sayt', telegram='Telegram bot', referral='xodim tavsiyasi').get(src, src)}")
            if stage != "new":
                ApplicationEvent.objects.create(application=a, at=created + timedelta(days=1), actor=reviewer, kind="stage",
                                                text=f"Bosqich: {Stage(stage).label}" + (f" · {a.reject_reason}" if a.reject_reason else ""))
            n += 1
    # --- mavjud xodimlar: profil, ish tarixi, hujjat, baho, kayfiyat
    emps = list(Employee.objects.filter(is_active=True).select_related("user"))
    first_hired = None
    langs = [["o'zbek", "rus"], ["o'zbek"], ["o'zbek", "rus", "ingliz"]]
    skills = {"Oshpaz": ["osh", "kabob", "zagatovka"], "Kassir": ["kassa", "Excel"], "Ofitsiant": ["xizmat", "upsell"],
              "Menejer": ["jamoa boshqaruvi", "inventarizatsiya"], "Buxgalter": ["1C", "soliq hisoboti"], "Marketolog": ["SMM", "Canva"]}
    this_m = month_start(today)
    prev_m = month_start(this_m - timedelta(days=1))
    for k, e in enumerate(emps):
        pos = e.position.name if e.position_id else "Ofitsiant"
        female = (e.user.full_name or "").split(" ")[-1].endswith("a")
        e.birth_date = today.replace(year=today.year - rnd.randint(20, 42), day=1) + timedelta(days=rnd.randint(0, 27))
        e.gender = "f" if female else "m"
        e.address = rnd.choice(["Chilonzor tumani, 9-kvartal", "Yunusobod tumani, 4-mavze", "Sergeli tumani", "Olmazor tumani, Qorasaroy ko'chasi"])
        e.education = rnd.choice(["O'rta maxsus (kollej)", "Oliy — TDIU", "Oshpazlik kolleji, 2019", "O'rta maktab"])
        e.languages = langs[k % 3]
        e.skills = skills.get(pos, ["xizmat"])
        e.emergency_name = rnd.choice(["Onasi", "Otasi", "Turmush o'rtog'i", "Akasi"])
        e.emergency_phone = e.emergency_phone or f"+99890{rnd.randint(1000000, 9999999)}"
        # tibbiy daftarcha: ko'pchiligi joyida, 2 tasi tugayapti, 1 tasi o'tgan — ogohlantirish ko'rinsin
        e.medical_book_until = today + timedelta(days=(-5 if k == 2 else 12 if k in (4, 7) else rnd.randint(60, 330)))
        e.source = rnd.choice(["vakansiya", "tanish tavsiyasi", "Telegram kanal", "OLX.uz"])
        e.about = "Mas'uliyatli, jamoada yaxshi ishlaydi." if k % 2 else ""
        e.save()
        comp, p = PREV[k % len(PREV)]
        WorkHistory.objects.create(employee=e, company=comp, position=p, start=str(rnd.randint(2016, 2020)), end=str(rnd.randint(2021, 2024)),
                                   reason_left=rnd.choice(["Uyga uzoq edi", "Maosh past edi", "O'qishga kirdi", "Kompaniya yopildi"]),
                                   reference_phone=f"+99897{rnd.randint(1000000, 9999999)}")
        if k % 3 == 0:
            c2, p2 = PREV[(k + 3) % len(PREV)]
            WorkHistory.objects.create(employee=e, company=c2, position=p2, start="2014", end=str(rnd.randint(2015, 2016)))
        EmployeeDocument.objects.create(employee=e, kind=DocKind.CONTRACT, title=f"Mehnat shartnomasi №{100 + k}",
                                        url="https://drive.google.com/file/d/demo-contract/view")
        EmployeeDocument.objects.create(employee=e, kind=DocKind.MEDBOOK, title="Tibbiy daftarcha", expires_on=e.medical_book_until,
                                        url="https://drive.google.com/file/d/demo-medbook/view")
        base = rnd.choice([3, 4, 4, 4, 5, 5])
        for period in (prev_m, this_m):
            if period == this_m and k % 4 == 3:
                continue              # har to'rtinchisi hali baholanmagan
            sc = {c: max(1, min(5, base + rnd.choice([-1, 0, 0, 1]))) for c, _ in REVIEW_CRITERIA}
            Review.objects.create(employee=e, reviewer=reviewer, period=period, scores=sc,
                                  strengths=rnd.choice(["Mehmon bilan muomalasi a'lo", "Tez ishlaydi", "Intizomli", "Jamoaga yordam beradi"]),
                                  improve=rnd.choice(["", "Kechikishni kamaytirish", "Ish joyi tozaligi", "Menyuni yaxshiroq bilish"]),
                                  goals=rnd.choice(["O'rtacha chekni 10% oshirish", "Oy davomida kechikmaslik", "«Gigiyena» kursini tugatish"]))
        mood_base = 2 if k == 5 else rnd.choice([3, 3, 4])       # bittasi «xavf» ostida
        for att in Attendance.objects.filter(employee=e, check_out__isnull=False):
            ShiftFeedback.objects.create(employee=e, attendance=att, date=timezone.localtime(att.check_in).date(),
                                         mood=max(1, min(4, mood_base + rnd.choice([-1, 0, 0, 1]))),
                                         comment=rnd.choice(["", "", "Mehmon ko'p edi", "Oshxonada kechikish bo'ldi"]))
        if first_hired is None and pos in ("Kassir", "Ofitsiant"):
            first_hired = e
    # bitta qabul qilingan nomzod — «qayerdan kelgan» profilda ko'rinsin
    if first_hired:
        hv = vacs[2] if first_hired.position and first_hired.position.name == "Kassir" else vacs[0]
        a = Application.objects.create(vacancy=hv, full_name=first_hired.user.full_name, phone=first_hired.user.phone, birth_year=first_hired.birth_date.year,
                                       source="telegram", stage=Stage.HIRED, rating=5, employee=first_hired,
                                       answers=recruit.check_answers(hv, [{"i": 0, "a": "Ha"}, {"i": 1, "a": "Ha"}, {"i": 2, "a": "Darhol"}])[0],
                                       stage_changed_at=now - timedelta(days=30))
        Application.objects.filter(pk=a.pk).update(created_at=now - timedelta(days=38))
        n += 1
    return {"vacancies": len(vacs), "applications": n, "profiles": len(emps)}
'@

Put 'backend\modules\hr\kpi.py' @'
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
'@

Put 'backend\modules\hr\management\__init__.py' @'

'@

Put 'backend\modules\hr\management\commands\__init__.py' @'

'@

Put 'backend\modules\hr\management\commands\seed_hr.py' @'
"""
Mavjud restoranga HR demo: vakansiyalar (saytda ko'rinadi), nomzodlar, xodim profillari, ish tarixi, hujjatlar, baholar:
    python manage.py seed_hr                  (standart: lazzat)
    python manage.py seed_hr --slug namuna
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.utils import schema_context

from public.models import Tenant


class Command(BaseCommand):
    help = "HR demo: ishga olish, profil, KPI"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="lazzat")

    def handle(self, *args, **opts):
        t = Tenant.objects.filter(slug=opts["slug"]).first()
        if t is None:
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        with schema_context(t.schema_name):
            connection.set_tenant(t)
            from core.models import Membership
            from modules.hr.demo import seed_demo_hr, seed_demo_recruit_people
            seed_demo_hr()
            owner = Membership.objects.filter(role__code="owner").select_related("user").first()
            r = seed_demo_recruit_people(owner.user if owner else None)
        connection.set_schema_to_public()
        if not r.get("vacancies"):
            self.stdout.write("Vakansiyalar allaqachon bor — demo qo'shilmadi")
        else:
            self.stdout.write(f"Vakansiya: {r['vacancies']} · nomzod: {r['applications']} · profil: {r['profiles']}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
'@

Put 'backend\modules\hr\migrations\0002_recruit_profile_kpi.py' @'
# Generated by Django 5.1.15 on 2026-09-25 13:06

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_normalize_phones"),
        ("hr", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="about",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="employee",
            name="birth_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="education",
            field=models.CharField(
                blank=True,
                help_text="masalan: Toshkent oshpazlik kolleji, 2019",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="emergency_name",
            field=models.CharField(
                blank=True,
                help_text="favqulodda aloqa: kim (ona, turmush o'rtog'i…)",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="fire_reason",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="employee",
            name="gender",
            field=models.CharField(blank=True, help_text="m | f", max_length=1),
        ),
        migrations.AddField(
            model_name="employee",
            name="languages",
            field=models.JSONField(
                blank=True, default=list, help_text='["o\'zbek", "rus"]'
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="medical_book_until",
            field=models.DateField(
                blank=True, help_text="tibbiy daftarcha amal qilish muddati", null=True
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="skills",
            field=models.JSONField(
                blank=True, default=list, help_text='["tandir", "kassa", "Excel"]'
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="source",
            field=models.CharField(
                blank=True,
                help_text="qayerdan kelgan: vakansiya, tavsiya…",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="about",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="birth_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="education",
            field=models.CharField(
                blank=True,
                help_text="masalan: Toshkent oshpazlik kolleji, 2019",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="emergency_name",
            field=models.CharField(
                blank=True,
                help_text="favqulodda aloqa: kim (ona, turmush o'rtog'i…)",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="fire_reason",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="gender",
            field=models.CharField(blank=True, help_text="m | f", max_length=1),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="languages",
            field=models.JSONField(
                blank=True, default=list, help_text='["o\'zbek", "rus"]'
            ),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="medical_book_until",
            field=models.DateField(
                blank=True, help_text="tibbiy daftarcha amal qilish muddati", null=True
            ),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="skills",
            field=models.JSONField(
                blank=True, default=list, help_text='["tandir", "kassa", "Excel"]'
            ),
        ),
        migrations.AddField(
            model_name="historicalemployee",
            name="source",
            field=models.CharField(
                blank=True,
                help_text="qayerdan kelgan: vakansiya, tavsiya…",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="Application",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("full_name", models.CharField(max_length=120)),
                ("phone", models.CharField(db_index=True, max_length=20)),
                ("birth_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("city", models.CharField(blank=True, max_length=80)),
                (
                    "experience",
                    models.TextField(
                        blank=True, help_text="o'zi haqida / tajriba (erkin matn)"
                    ),
                ),
                (
                    "work_history",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text='[{"company": "", "position": "", "years": ""}]',
                    ),
                ),
                (
                    "answers",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text='[{"q": "...", "a": "...", "ok": true}]',
                    ),
                ),
                ("photo", models.ImageField(blank=True, upload_to="hr/candidates/")),
                ("resume", models.FileField(blank=True, upload_to="hr/resumes/")),
                (
                    "source",
                    models.CharField(
                        default="site",
                        help_text="site | telegram | manual | referral",
                        max_length=12,
                    ),
                ),
                ("tg_chat_id", models.BigIntegerField(blank=True, null=True)),
                ("tg_username", models.CharField(blank=True, max_length=64)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("new", "Yangi ariza"),
                            ("screen", "Ko'rib chiqilmoqda"),
                            ("interview", "Suhbat"),
                            ("trial", "Sinov kuni"),
                            ("offer", "Taklif"),
                            ("hired", "Qabul qilindi"),
                            ("rejected", "Rad etildi"),
                        ],
                        db_index=True,
                        default="new",
                        max_length=10,
                    ),
                ),
                (
                    "knocked_out",
                    models.BooleanField(
                        default=False, help_text="majburiy savolga mos javob bermagan"
                    ),
                ),
                (
                    "rating",
                    models.PositiveSmallIntegerField(default=0, help_text="0–5 yulduz"),
                ),
                ("notes", models.TextField(blank=True)),
                ("interview_at", models.DateTimeField(blank=True, null=True)),
                ("interview_place", models.CharField(blank=True, max_length=160)),
                ("reject_reason", models.CharField(blank=True, max_length=200)),
                (
                    "stage_changed_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="hr.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ApplicationEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "kind",
                    models.CharField(
                        default="note",
                        help_text="created | stage | note | message | interview",
                        max_length=16,
                    ),
                ),
                ("text", models.CharField(blank=True, max_length=400)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="hr.application",
                    ),
                ),
            ],
            options={
                "ordering": ["-at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="EmployeeDocument",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("contract", "Mehnat shartnomasi"),
                            ("medbook", "Tibbiy daftarcha"),
                            ("passport", "Pasport nusxasi"),
                            ("diploma", "Diplom / sertifikat"),
                            ("other", "Boshqa"),
                        ],
                        default="other",
                        max_length=10,
                    ),
                ),
                ("title", models.CharField(max_length=160)),
                ("file", models.FileField(blank=True, upload_to="hr/docs/%Y/")),
                (
                    "url",
                    models.URLField(
                        blank=True,
                        help_text="fayl o'rniga havola (Google Drive va h.k.)",
                        max_length=500,
                    ),
                ),
                ("expires_on", models.DateField(blank=True, null=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="hr.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["kind", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Review",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "period",
                    models.DateField(db_index=True, help_text="oyning 1-sanasi"),
                ),
                (
                    "scores",
                    models.JSONField(default=dict, help_text='{"discipline": 4, ...}'),
                ),
                ("strengths", models.CharField(blank=True, max_length=300)),
                ("improve", models.CharField(blank=True, max_length=300)),
                ("goals", models.CharField(blank=True, max_length=300)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to="hr.employee",
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-period", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ShiftFeedback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "date",
                    models.DateField(
                        db_index=True, default=django.utils.timezone.localdate
                    ),
                ),
                (
                    "mood",
                    models.PositiveSmallIntegerField(help_text="1 — yomon … 4 — a'lo"),
                ),
                ("comment", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "attendance",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedback",
                        to="hr.attendance",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback",
                        to="hr.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="Vacancy",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=140)),
                (
                    "role_code",
                    models.CharField(
                        default="waiter",
                        help_text="qabul qilinganda beriladigan rol",
                        max_length=40,
                    ),
                ),
                (
                    "employment",
                    models.CharField(
                        default="full",
                        help_text="full | part | shift | intern",
                        max_length=20,
                    ),
                ),
                ("salary_from", models.BigIntegerField(default=0)),
                ("salary_to", models.BigIntegerField(default=0)),
                (
                    "salary_note",
                    models.CharField(
                        blank=True,
                        help_text="masalan: + choychaqa, bonus",
                        max_length=120,
                    ),
                ),
                (
                    "schedule",
                    models.CharField(
                        blank=True, help_text="2/2, 10:00–22:00", max_length=120
                    ),
                ),
                ("summary", models.CharField(blank=True, max_length=300)),
                ("requirements", models.JSONField(blank=True, default=list)),
                ("duties", models.JSONField(blank=True, default=list)),
                ("benefits", models.JSONField(blank=True, default=list)),
                ("image", models.ImageField(blank=True, upload_to="hr/vacancies/")),
                ("image_url", models.URLField(blank=True, max_length=500)),
                (
                    "video_url",
                    models.URLField(
                        blank=True,
                        help_text="YouTube / Instagram / Drive",
                        max_length=500,
                    ),
                ),
                (
                    "link_url",
                    models.URLField(
                        blank=True,
                        help_text="qo'shimcha havola (masalan, jamoa haqida)",
                        max_length=500,
                    ),
                ),
                (
                    "questions",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text='[{"text": "Kechki smenada ishlay olasizmi?", "type": "yesno", "must": "ha"}]',
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Qoralama"),
                            ("open", "Ochiq"),
                            ("paused", "To'xtatilgan"),
                            ("closed", "Yopilgan"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=8,
                    ),
                ),
                ("closes_on", models.DateField(blank=True, null=True)),
                ("views", models.PositiveIntegerField(default=0)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                (
                    "branch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="vacancies",
                        to="core.branch",
                    ),
                ),
                (
                    "position",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="vacancies",
                        to="hr.position",
                    ),
                ),
                (
                    "responsible",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "-created_at"],
            },
        ),
        migrations.AddField(
            model_name="application",
            name="vacancy",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="applications",
                to="hr.vacancy",
            ),
        ),
        migrations.CreateModel(
            name="WorkHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.CharField(max_length=160)),
                ("position", models.CharField(blank=True, max_length=120)),
                (
                    "start",
                    models.CharField(
                        blank=True, help_text="2019-03 yoki 2019", max_length=20
                    ),
                ),
                (
                    "end",
                    models.CharField(
                        blank=True, help_text="bo'sh — hozirgacha", max_length=20
                    ),
                ),
                ("reason_left", models.CharField(blank=True, max_length=200)),
                (
                    "reference_phone",
                    models.CharField(
                        blank=True, help_text="tavsiya beruvchi telefon", max_length=20
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=300)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="work_history",
                        to="hr.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-start", "-id"],
            },
        ),
    ]
'@

Put 'backend\modules\hr\models.py' @'
"""
Xodimlar (HR) moduli: lavozim, xodim kartasi (maosh sharti), smena jadvali, davomat, oylik hisob-kitobi.

Maosh turlari: monthly (oylik stavka) · hourly (soatbay) · shift (smenabay) · percent (savdodan %).
Oylik = baza (turga qarab) + bonus − jarima − avans. Natija moliya modulida "Labor cost" sifatida P&L'ga tushadi.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Branch, TimeStamped, User


class SalaryType(models.TextChoices):
    MONTHLY = "monthly", "Oylik stavka"
    HOURLY = "hourly", "Soatbay"
    SHIFT = "shift", "Smenabay"
    PERCENT = "percent", "Savdodan %"


class Position(TimeStamped):
    name = models.CharField(max_length=80)
    department = models.CharField(max_length=60, blank=True, help_text="Oshxona, Zal, Kassa, Boshqaruv…")
    default_salary_type = models.CharField(max_length=8, choices=SalaryType.choices, default=SalaryType.MONTHLY)
    default_rate = models.BigIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Employee(TimeStamped):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee")
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    hire_date = models.DateField(default=timezone.localdate)
    fire_date = models.DateField(null=True, blank=True)
    salary_type = models.CharField(max_length=8, choices=SalaryType.choices, default=SalaryType.MONTHLY)
    rate = models.BigIntegerField(default=0, help_text="so'm: oylik / soat / smena; percent uchun — foiz×100 (2.5% = 250)")
    pinfl = models.CharField(max_length=14, blank=True)
    passport = models.CharField(max_length=12, blank=True)
    card_number = models.CharField(max_length=20, blank=True, help_text="oylik tushadigan karta")
    emergency_phone = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    # --- shaxsiy profil (HR kartasi)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, blank=True, help_text="m | f")
    address = models.CharField(max_length=255, blank=True)
    emergency_name = models.CharField(max_length=120, blank=True, help_text="favqulodda aloqa: kim (ona, turmush o'rtog'i…)")
    education = models.CharField(max_length=255, blank=True, help_text="masalan: Toshkent oshpazlik kolleji, 2019")
    languages = models.JSONField(default=list, blank=True, help_text='["o\'zbek", "rus"]')
    skills = models.JSONField(default=list, blank=True, help_text='["tandir", "kassa", "Excel"]')
    about = models.TextField(blank=True)
    medical_book_until = models.DateField(null=True, blank=True, help_text="tibbiy daftarcha amal qilish muddati")
    source = models.CharField(max_length=20, blank=True, help_text="qayerdan kelgan: vakansiya, tavsiya…")
    fire_reason = models.CharField(max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["user__full_name"]

    def __str__(self) -> str:
        return self.user.full_name or self.user.phone


class ShiftPlan(TimeStamped):
    """Smena jadvali (rejalashtirilgan)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="shifts")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateField(db_index=True)
    start = models.TimeField(default="09:00")
    end = models.TimeField(default="18:00")
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["date", "start"]
        unique_together = [("employee", "date", "start")]

    @property
    def hours(self) -> float:
        s = datetime.combine(self.date, self.start)
        e = datetime.combine(self.date, self.end)
        if e <= s:
            e += timedelta(days=1)
        return round((e - s).total_seconds() / 3600, 2)


class Attendance(TimeStamped):
    """Davomat: keldi / ketdi. Manba: panel, kassa PIN, Telegram, QR (keyin)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    check_in = models.DateTimeField(default=timezone.now, db_index=True)
    check_out = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=12, default="panel")
    late_minutes = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-check_in"]

    @property
    def hours(self) -> float:
        end = self.check_out or timezone.now()
        return round((end - self.check_in).total_seconds() / 3600, 2)

    @property
    def is_open(self) -> bool:
        return self.check_out is None


class PayrollStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    APPROVED = "approved", "Tasdiqlangan"
    PAID = "paid", "To'langan"


class Payslip(TimeStamped):
    """Bir xodimning bir oylik hisob-kitobi."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payslips")
    period = models.DateField(help_text="oyning 1-sanasi", db_index=True)
    salary_type = models.CharField(max_length=8, choices=SalaryType.choices)
    rate = models.BigIntegerField(default=0)
    hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    shifts = models.PositiveIntegerField(default=0)
    sales_base = models.BigIntegerField(default=0, help_text="percent turi uchun savdo bazasi")
    base = models.BigIntegerField(default=0)
    bonus = models.BigIntegerField(default=0)
    penalty = models.BigIntegerField(default=0)
    advance = models.BigIntegerField(default=0)
    total = models.BigIntegerField(default=0)
    status = models.CharField(max_length=8, choices=PayrollStatus.choices, default=PayrollStatus.DRAFT)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-period", "employee__user__full_name"]
        unique_together = [("employee", "period")]

    def compute(self) -> None:
        r = Decimal(self.rate)
        if self.salary_type == SalaryType.MONTHLY:
            self.base = int(r)
        elif self.salary_type == SalaryType.HOURLY:
            self.base = int(r * Decimal(self.hours))
        elif self.salary_type == SalaryType.SHIFT:
            self.base = int(r * self.shifts)
        else:  # percent: rate = foiz × 100
            self.base = int(Decimal(self.sales_base) * r / 10000)
        self.total = self.base + self.bonus - self.penalty - self.advance


def month_start(d: date) -> date:
    return d.replace(day=1)



# ================================================================== XODIM PROFILI
class WorkHistory(TimeStamped):
    """Oldingi ish joylari (qabul qilishda nomzod anketasidan ko'chadi)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="work_history")
    company = models.CharField(max_length=160)
    position = models.CharField(max_length=120, blank=True)
    start = models.CharField(max_length=20, blank=True, help_text="2019-03 yoki 2019")
    end = models.CharField(max_length=20, blank=True, help_text="bo'sh — hozirgacha")
    reason_left = models.CharField(max_length=200, blank=True)
    reference_phone = models.CharField(max_length=20, blank=True, help_text="tavsiya beruvchi telefon")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-start", "-id"]


class DocKind(models.TextChoices):
    CONTRACT = "contract", "Mehnat shartnomasi"
    MEDBOOK = "medbook", "Tibbiy daftarcha"
    PASSPORT = "passport", "Pasport nusxasi"
    DIPLOMA = "diploma", "Diplom / sertifikat"
    OTHER = "other", "Boshqa"


class EmployeeDocument(TimeStamped):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=10, choices=DocKind.choices, default=DocKind.OTHER)
    title = models.CharField(max_length=160)
    file = models.FileField(upload_to="hr/docs/%Y/", blank=True)
    url = models.URLField(max_length=500, blank=True, help_text="fayl o'rniga havola (Google Drive va h.k.)")
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["kind", "-created_at"]


# ================================================================== BAHOLASH
REVIEW_CRITERIA = [
    ("discipline", "Intizom va o'z vaqtida kelish"),
    ("quality", "Ish sifati va standartlarga rioya"),
    ("speed", "Tezlik"),
    ("service", "Mehmon bilan muomala"),
    ("hygiene", "Gigiyena va tozalik"),
    ("teamwork", "Jamoada ishlash"),
]


class Review(TimeStamped):
    """Menejer bahosi (odatda oyiga bir marta): mezonlar 1–5, izoh, keyingi oy maqsadi."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    period = models.DateField(help_text="oyning 1-sanasi", db_index=True)
    scores = models.JSONField(default=dict, help_text='{"discipline": 4, ...}')
    strengths = models.CharField(max_length=300, blank=True)
    improve = models.CharField(max_length=300, blank=True)
    goals = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-period", "-created_at"]

    @property
    def average(self) -> float | None:
        vals = [int(v) for v in (self.scores or {}).values() if v]
        return round(sum(vals) / len(vals), 2) if vals else None


class ShiftFeedback(models.Model):
    """Smenadan keyin xodim bahosi (Telegram: 😀 🙂 😐 🙁) — kayfiyat va ketib qolish xavfini erta ko'rish uchun."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="feedback")
    attendance = models.OneToOneField(Attendance, null=True, blank=True, on_delete=models.SET_NULL, related_name="feedback")
    date = models.DateField(default=timezone.localdate, db_index=True)
    mood = models.PositiveSmallIntegerField(help_text="1 — yomon … 4 — a'lo")
    comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date", "-id"]


# ================================================================== ISHGA OLISH
class VacancyStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    OPEN = "open", "Ochiq"
    PAUSED = "paused", "To'xtatilgan"
    CLOSED = "closed", "Yopilgan"


class Vacancy(TimeStamped):
    title = models.CharField(max_length=140)
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="vacancies")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="vacancies")
    role_code = models.CharField(max_length=40, default="waiter", help_text="qabul qilinganda beriladigan rol")
    employment = models.CharField(max_length=20, default="full", help_text="full | part | shift | intern")
    salary_from = models.BigIntegerField(default=0)
    salary_to = models.BigIntegerField(default=0)
    salary_note = models.CharField(max_length=120, blank=True, help_text="masalan: + choychaqa, bonus")
    schedule = models.CharField(max_length=120, blank=True, help_text="2/2, 10:00–22:00")
    summary = models.CharField(max_length=300, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    duties = models.JSONField(default=list, blank=True)
    benefits = models.JSONField(default=list, blank=True)
    image = models.ImageField(upload_to="hr/vacancies/", blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    video_url = models.URLField(max_length=500, blank=True, help_text="YouTube / Instagram / Drive")
    link_url = models.URLField(max_length=500, blank=True, help_text="qo'shimcha havola (masalan, jamoa haqida)")
    questions = models.JSONField(default=list, blank=True,
                                 help_text='[{"text": "Kechki smenada ishlay olasizmi?", "type": "yesno", "must": "ha"}]')
    status = models.CharField(max_length=8, choices=VacancyStatus.choices, default=VacancyStatus.DRAFT, db_index=True)
    responsible = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    closes_on = models.DateField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def image_src(self) -> str | None:
        return self.image.url if self.image else (self.image_url or None)


class Stage(models.TextChoices):
    NEW = "new", "Yangi ariza"
    SCREEN = "screen", "Ko'rib chiqilmoqda"
    INTERVIEW = "interview", "Suhbat"
    TRIAL = "trial", "Sinov kuni"
    OFFER = "offer", "Taklif"
    HIRED = "hired", "Qabul qilindi"
    REJECTED = "rejected", "Rad etildi"


class Application(TimeStamped):
    vacancy = models.ForeignKey(Vacancy, null=True, blank=True, on_delete=models.SET_NULL, related_name="applications")
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, db_index=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    city = models.CharField(max_length=80, blank=True)
    experience = models.TextField(blank=True, help_text="o'zi haqida / tajriba (erkin matn)")
    work_history = models.JSONField(default=list, blank=True, help_text='[{"company": "", "position": "", "years": ""}]')
    answers = models.JSONField(default=list, blank=True, help_text='[{"q": "...", "a": "...", "ok": true}]')
    photo = models.ImageField(upload_to="hr/candidates/", blank=True)
    resume = models.FileField(upload_to="hr/resumes/", blank=True)
    source = models.CharField(max_length=12, default="site", help_text="site | telegram | manual | referral")
    tg_chat_id = models.BigIntegerField(null=True, blank=True)
    tg_username = models.CharField(max_length=64, blank=True)
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.NEW, db_index=True)
    knocked_out = models.BooleanField(default=False, help_text="majburiy savolga mos javob bermagan")
    rating = models.PositiveSmallIntegerField(default=0, help_text="0–5 yulduz")
    notes = models.TextField(blank=True)
    interview_at = models.DateTimeField(null=True, blank=True)
    interview_place = models.CharField(max_length=160, blank=True)
    reject_reason = models.CharField(max_length=200, blank=True)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    stage_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class ApplicationEvent(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=16, default="note", help_text="created | stage | note | message | interview")
    text = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
'@

Put 'backend\modules\hr\module.json' @'
{
  "code": "hr",
  "name": {
    "uz": "Xodimlar va oylik",
    "ru": "Сотрудники и зарплата",
    "en": "Staff & payroll"
  },
  "version": "1.0.0",
  "phase": 1,
  "implemented": true,
  "order": 70,
  "depends": [],
  "permissions": [
    "hr.view",
    "hr.edit",
    "hr.payroll",
    "hr.recruit",
    "hr.review",
    "hr.*"
  ],
  "nav": [
    {
      "route": "/hr",
      "label": {
        "uz": "Xodimlar",
        "ru": "Сотрудники",
        "en": "Staff"
      },
      "icon": "users",
      "order": 70,
      "perm": "hr.view"
    },
    {
      "route": "/recruiting",
      "label": {
        "uz": "Ishga olish",
        "ru": "Найм",
        "en": "Hiring"
      },
      "icon": "megaphone",
      "order": 71,
      "perm": "hr.recruit"
    },
    {
      "route": "/kpi",
      "label": {
        "uz": "Baholash va KPI",
        "ru": "Оценка и KPI",
        "en": "Performance"
      },
      "icon": "star",
      "order": 72,
      "perm": "hr.review"
    }
  ],
  "settings_schema": {
    "type": "object",
    "properties": {
      "late_tolerance_minutes": {
        "type": "integer",
        "title": "Kechikish uchun ruxsat (daqiqa)",
        "default": 10
      },
      "payroll_day": {
        "type": "integer",
        "title": "Oylik to'lash kuni",
        "default": 5
      },
      "careers_intro": {
        "type": "string",
        "title": "Vakansiyalar sahifasi matni",
        "default": "Biz bilan ishlang: barqaror maosh, bepul ovqat, o'qitish va o'sish imkoniyati."
      },
      "shift_feedback": {
        "type": "boolean",
        "title": "Smenadan keyin kayfiyat so'rovi (Telegram)",
        "default": true
      }
    }
  }
}
'@

Put 'backend\modules\hr\recruit.py' @'
"""
Ishga olish (ATS): vakansiya → ariza (sayt yoki Telegram) → bosqichlar → qabul (xodim kartasi o'zi ochiladi).

Restoran uchun muhim (Harri / Workstream tajribasi):
  • ariza 2 daqiqada, telefondan — ortiqcha maydon yo'q;
  • «majburiy» savollar (masalan, kechki smena) — mos kelmasa ariza belgilanadi, lekin o'chirilmaydi;
  • har bosqichda nomzodga Telegram xabar (suhbat vaqti, joyi) — kelmay qolish kamayadi.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from core.models import Membership, Role, User

from .models import Application, ApplicationEvent, Employee, Stage, Vacancy, VacancyStatus, WorkHistory

log = logging.getLogger("hr")

EMPLOYMENT = {"full": "To'liq stavka", "part": "Yarim stavka", "shift": "Smenali", "intern": "Amaliyot / o'quvchi"}


def normalize_phone(p: str) -> str:
    digits = "".join(ch for ch in (p or "") if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    return User.objects.normalize_phone(digits) if len(digits) >= 9 else ""


def salary_text(v: Vacancy) -> str:
    f = lambda x: f"{x:,}".replace(",", " ")  # noqa: E731
    if v.salary_from and v.salary_to:
        s = f"{f(v.salary_from)} – {f(v.salary_to)} so'm"
    elif v.salary_from:
        s = f"{f(v.salary_from)} so'mdan"
    elif v.salary_to:
        s = f"{f(v.salary_to)} so'mgacha"
    else:
        s = "Suhbatda kelishiladi"
    return s + (f" · {v.salary_note}" if v.salary_note else "")


def is_open(v: Vacancy) -> bool:
    return v.status == VacancyStatus.OPEN and not (v.closes_on and v.closes_on < timezone.localdate())


def check_answers(v: Vacancy, answers: list[dict]) -> tuple[list[dict], bool]:
    """Javoblarni savollar bilan birlashtiradi; «must» (majburiy javob) mos kelmasa — knocked_out."""
    out, knocked = [], False
    given = {str(a.get("i")): str(a.get("a") or "").strip() for a in answers or []}
    for i, q in enumerate(v.questions or []):
        a = given.get(str(i), "")
        must = str(q.get("must") or "").strip().lower()
        ok = True
        if must:
            ok = a.strip().lower().startswith(must[:2])
            knocked = knocked or not ok
        out.append({"q": q.get("text", ""), "a": a, "ok": ok, "must": must})
    return out, knocked


def tg(tenant, chat_id, text: str, markup: dict | None = None) -> bool:
    if not chat_id or tenant is None:
        return False
    try:
        if tenant.module_enabled("telegram"):
            from modules.telegram.services import say
            return say(tenant, chat_id, text, markup)
        from integrations.telegram import send_message
        return send_message(chat_id, text, reply_markup=markup)
    except Exception:
        log.exception("hr telegram")
        return False


def _staff_notify(tenant, app: Application) -> None:
    v = app.vacancy
    text = (f"🧑‍🍳 <b>Yangi ariza</b>: {app.full_name}, {app.phone}\n"
            f"Vakansiya: <b>{v.title if v else '—'}</b> · manba: {app.source}"
            + ("\n⚠️ Majburiy savolga mos emas" if app.knocked_out else "")
            + "\nAdmin panel → Ishga olish")
    if v and v.responsible and v.responsible.telegram_id:
        tg(tenant, v.responsible.telegram_id, text)
    try:
        from modules.telegram.services import conf
        chat = (conf(tenant).get("notify_staff_chat_id") or "").strip() if tenant.module_enabled("telegram") else ""
        if chat:
            tg(tenant, chat, text)
    except Exception:
        pass


def event(app: Application, kind: str, text: str, actor=None) -> None:
    ApplicationEvent.objects.create(application=app, kind=kind, text=text[:400], actor=actor)


def create_application(tenant, vacancy: Vacancy | None, *, full_name: str, phone: str, answers=None, experience: str = "",
                       work_history=None, birth_year=None, city: str = "", source: str = "site", tg_chat_id=None,
                       tg_username: str = "", photo=None, resume=None) -> Application:
    ph = normalize_phone(phone)
    if not ph:
        raise ValueError("Telefon raqam noto'g'ri. Masalan: +998 90 123 45 67")
    if not (full_name or "").strip():
        raise ValueError("Ismingizni yozing.")
    ans, knocked = check_answers(vacancy, answers or []) if vacancy else ([], False)
    dup = Application.objects.filter(phone=ph, vacancy=vacancy).exclude(stage__in=[Stage.HIRED, Stage.REJECTED]).first()
    if dup:                                            # takror ariza — yangilab qo'yamiz, ikkinchi karta ochmaymiz
        dup.answers, dup.knocked_out = ans or dup.answers, knocked
        dup.experience = experience or dup.experience
        dup.tg_chat_id = tg_chat_id or dup.tg_chat_id
        dup.save()
        event(dup, "note", f"Qayta ariza yubordi ({source})")
        return dup
    app = Application.objects.create(vacancy=vacancy, full_name=full_name.strip()[:120], phone=ph, answers=ans, knocked_out=knocked,
                                     experience=(experience or "")[:3000], work_history=work_history or [], birth_year=birth_year,
                                     city=city[:80], source=source, tg_chat_id=tg_chat_id, tg_username=(tg_username or "")[:64])
    if photo:
        app.photo.save(photo.name, photo, save=True)
    if resume:
        app.resume.save(resume.name, resume, save=True)
    event(app, "created", f"Ariza keldi: {source}")
    _staff_notify(tenant, app)
    if tg_chat_id:
        tg(tenant, tg_chat_id, f"✅ Arizangiz qabul qilindi: <b>{vacancy.title if vacancy else 'ish'}</b>.\n"
                               "Mas'ul 1–2 kun ichida ko'rib chiqadi va shu yerga yozadi. Rahmat!")
    return app


def _fmt_dt(d) -> str:
    return timezone.localtime(d).strftime("%d.%m.%Y, %H:%M") if d else ""


def move(tenant, app: Application, stage: str, actor=None, *, note: str = "", interview_at=None, place: str = "",
         reason: str = "", notify: bool = True) -> Application:
    if stage not in Stage.values:
        raise ValueError("Noto'g'ri bosqich")
    if stage == Stage.HIRED:
        raise ValueError("Qabul qilish uchun «Qabul qilish» tugmasidan foydalaning.")
    if stage in (Stage.INTERVIEW, Stage.TRIAL) and not interview_at:
        raise ValueError("Suhbat / sinov kuni vaqtini tanlang.")
    if stage == Stage.REJECTED and not reason.strip():
        raise ValueError("Rad etish sababini yozing (nomzodga ko'rinmaydi).")
    app.stage = stage
    app.stage_changed_at = timezone.now()
    if interview_at:
        app.interview_at, app.interview_place = interview_at, place or app.interview_place
    if stage == Stage.REJECTED:
        app.reject_reason = reason.strip()
    app.save()
    title = app.vacancy.title if app.vacancy else "vakansiya"
    event(app, "stage", f"{Stage(stage).label}" + (f" · {_fmt_dt(interview_at)}" if interview_at else "") + (f" · {note}" if note else ""), actor)
    if notify and app.tg_chat_id:
        msgs = {
            Stage.SCREEN: f"👀 Arizangiz ko'rib chiqilmoqda: <b>{title}</b>.",
            Stage.INTERVIEW: f"📅 <b>Suhbatga taklif</b> — {title}\n🕒 {_fmt_dt(app.interview_at)}\n📍 {app.interview_place or tenant.name}\n"
                             "Pasport va (bo'lsa) tibbiy daftarchani olib keling. Kela olmasangiz, shu yerga yozing.",
            Stage.TRIAL: f"🧑‍🍳 <b>Sinov kuni</b> — {title}\n🕒 {_fmt_dt(app.interview_at)}\n📍 {app.interview_place or tenant.name}\nQulay kiyim va poyabzal bilan keling.",
            Stage.OFFER: f"🎉 Sizga ish taklif qilamiz: <b>{title}</b>!\nTafsilotlar uchun mas'ul qo'ng'iroq qiladi.",
            Stage.REJECTED: f"Rahmat, {app.full_name}! Hozircha «{title}» bo'yicha boshqa nomzodni tanladik. "
                            "Ma'lumotlaringizni saqlab qo'ydik — yangi vakansiya bo'lsa, xabar beramiz.",
        }
        if msgs.get(stage):
            tg(tenant, app.tg_chat_id, msgs[stage] + (f"\n\n{note}" if note and stage != Stage.REJECTED else ""))
            event(app, "message", "Nomzodga Telegram xabar yuborildi")
    return app


@transaction.atomic
def hire(tenant, app: Application, actor=None, *, role_code: str | None = None, branch_id=None, position_id=None,
         salary_type: str | None = None, rate: int | None = None, hire_date=None) -> Employee:
    v = app.vacancy
    code = role_code or (v.role_code if v else "waiter")
    role = Role.objects.filter(code=code).first()
    if role is None:
        raise ValueError(f"Rol topilmadi: {code}")
    u, _ = User.objects.get_or_create(phone=app.phone, defaults={"full_name": app.full_name})
    if not u.full_name:
        u.full_name = app.full_name
    if app.tg_chat_id and not u.telegram_id:
        u.telegram_id = app.tg_chat_id
    u.is_active = True
    u.save()
    Membership.objects.get_or_create(user=u, role=role)
    pos = (v.position if v else None)
    if position_id:
        from .models import Position
        pos = Position.objects.filter(pk=position_id).first() or pos
    st = salary_type or (pos.default_salary_type if pos else "monthly")
    r = rate if rate is not None else (v.salary_from if v and v.salary_from and st == "monthly" else (pos.default_rate if pos else 0))
    e, created = Employee.objects.get_or_create(user=u, defaults={
        "position": pos, "branch_id": branch_id or (v.branch_id if v else None), "salary_type": st, "rate": r,
        "hire_date": hire_date or timezone.localdate(), "source": "vakansiya", "about": app.experience[:2000]})
    if not created:
        e.is_active, e.fire_date = True, None
        e.position = pos or e.position
        e.save()
    if app.birth_year and not e.birth_date:
        from datetime import date
        try:
            e.birth_date = date(int(app.birth_year), 1, 1)
            e.save(update_fields=["birth_date"])
        except ValueError:
            pass
    for w in app.work_history or []:
        if (w.get("company") or "").strip():
            WorkHistory.objects.get_or_create(employee=e, company=w["company"].strip()[:160],
                                              defaults={"position": (w.get("position") or "")[:120], "start": str(w.get("years") or "")[:20]})
    app.stage, app.employee, app.stage_changed_at = Stage.HIRED, e, timezone.now()
    app.save()
    event(app, "stage", f"Qabul qilindi → xodim kartasi #{e.pk}", actor)
    if app.tg_chat_id:
        tg(tenant, app.tg_chat_id, f"🎉 <b>{tenant.name}</b> jamoasiga xush kelibsiz, {app.full_name}!\n"
                                   "Botda «📱 Telefonni ulashish» tugmasini bosing — smena, vazifa va o'qitish xabarlari shu yerga keladi.\n"
                                   "Keldim / ketdim: /keldim · /ketdim")
    return e
'@

Put 'backend\modules\telegram\hr_flow.py' @'
"""
Telegram bot — HR suhbatlari («Xodimlar» moduli yoqilgan bo'lsa):

1) Ariza: saytdagi «Telegram orqali ariza» → t.me/<bot>?start=job_<id>  yoki botda «💼 Vakansiyalar».
   Qadamlar: ism → telefon (tugma) → tug'ilgan yil → vakansiya savollari → tajriba → oldingi ish joyi → yuborish.
   Har qadamda «✖️ Bekor qilish». 2 daqiqa, rezyume shart emas.
2) Kayfiyat: /ketdim dan keyin «Smena qanday o'tdi?» 😀 🙂 😐 🙁 (callback mood:<attendance>:<1-4>).
"""
from __future__ import annotations

from .models import BotUser

BTN_JOBS, BTN_SKIP2, BTN_SEND = "💼 Vakansiyalar", "⏭ O'tkazib yuborish", "✅ Arizani yuborish"
MOODS = {4: "😀", 3: "🙂", 2: "😐", 1: "🙁"}


def hr_on(tenant) -> bool:
    return tenant.module_enabled("hr")


def open_jobs():
    from modules.hr import recruit
    from modules.hr.models import Vacancy, VacancyStatus
    return [v for v in Vacancy.objects.filter(status=VacancyStatus.OPEN) if recruit.is_open(v)]


def _kb(*rows):
    from .services import BTN_CANCEL
    return {"keyboard": [*rows, [BTN_CANCEL]], "resize_keyboard": True}


def show_jobs(tenant, bu: BotUser) -> bool:
    from modules.hr import recruit

    from .services import say
    jobs = open_jobs()
    if not jobs:
        say(tenant, bu.chat_id, "Hozircha ochiq vakansiya yo'q. Keyinroq qayta kiring 🙂")
        return True
    lines = [f"💼 <b>{tenant.name} — vakansiyalar</b>"]
    lines += [f"• <b>{v.title}</b> — {recruit.salary_text(v)}" for v in jobs[:10]]
    say(tenant, bu.chat_id, "\n".join(lines) + "\n\nQaysi biriga ariza berasiz? 👇",
        {"inline_keyboard": [[{"text": f"📝 {v.title}", "callback_data": f"job:{v.pk}"}] for v in jobs[:10]]})
    return True


def start_apply(tenant, bu: BotUser, vid: int) -> bool:
    from modules.hr import recruit
    from modules.hr.models import Vacancy

    from .services import say
    v = Vacancy.objects.filter(pk=vid).first()
    if v is None or not recruit.is_open(v):
        say(tenant, bu.chat_id, "Bu vakansiya yopilgan. Boshqalarini ko'ring: «💼 Vakansiyalar».")
        return True
    lines = [f"📝 <b>{v.title}</b>", f"💰 {recruit.salary_text(v)}"]
    if v.schedule:
        lines.append(f"🕒 {v.schedule}")
    if v.requirements:
        lines.append("\n<b>Talablar:</b>\n" + "\n".join(f"• {x}" for x in v.requirements[:6]))
    lines.append("\nAriza 2 daqiqa oladi. <b>Ism familiyangizni</b> yozing:")
    bu.state = {"step": "rec_name", "job": v.pk, "d": {"answers": []}}
    bu.save(update_fields=["state"])
    say(tenant, bu.chat_id, "\n".join(lines), _kb([bu.full_name] if bu.full_name else []))
    return True


def step(tenant, bu: BotUser, msg: dict, text: str) -> bool:
    """Ariza suhbatining navbatdagi qadami. True — xabar shu yerda qayta ishlandi."""
    from modules.hr import recruit
    from modules.hr.models import Vacancy

    from .services import BTN_PHONE, main_keyboard, normalize, say
    st = dict(bu.state or {})
    d = st.get("d") or {"answers": []}
    v = Vacancy.objects.filter(pk=st.get("job")).first()
    if v is None:
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Vakansiya topilmadi.", main_keyboard(tenant, bu, None))
        return True
    s = st.get("step")

    def go(nxt: str, prompt: str, markup=None):
        st.update(step=nxt, d=d)
        bu.state = st
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, prompt, markup or _kb())

    if s == "rec_name":
        if len(text) < 3:
            return go("rec_name", "Iltimos, ism familiyangizni to'liq yozing:") or True
        d["name"] = text[:120]
        if bu.phone:
            d["phone"] = bu.phone
            go("rec_year", f"📱 Telefon: {bu.phone}\n\nTug'ilgan yilingiz? (masalan 1999)", _kb())
        else:
            go("rec_phone", "📱 Telefon raqamingizni ulashing (tugma) yoki yozing:",
               {"keyboard": [[{"text": BTN_PHONE, "request_contact": True}]], "resize_keyboard": True})
        return True
    if s == "rec_phone":
        c = msg.get("contact") or {}
        ph = normalize(c.get("phone_number") or text)
        if not ph or len(ph) < 12:
            return go("rec_phone", "Raqam noto'g'ri. Masalan: +998 90 123 45 67",
                      {"keyboard": [[{"text": BTN_PHONE, "request_contact": True}]], "resize_keyboard": True}) or True
        d["phone"] = ph
        if not bu.phone:
            bu.phone = ph
            bu.save(update_fields=["phone"])
        go("rec_year", "Tug'ilgan yilingiz? (masalan 1999)")
        return True
    if s == "rec_year":
        y = "".join(ch for ch in text if ch.isdigit())
        if not (len(y) == 4 and 1950 < int(y) < 2012):
            return go("rec_year", "4 xonali yil yozing, masalan 1999:") or True
        d["year"] = int(y)
        st["qi"] = 0
        return _ask_q(tenant, bu, st, d, v, go)
    if s == "rec_q":
        i = int(st.get("qi", 0))
        d["answers"].append({"i": i, "a": text[:300]})
        st["qi"] = i + 1
        return _ask_q(tenant, bu, st, d, v, go)
    if s == "rec_exp":
        d["exp"] = "" if text == BTN_SKIP2 else text[:3000]
        go("rec_prev", "Oxirgi ish joyingiz va lavozimingiz? (masalan: «Rayhon» restorani, ofitsiant, 2 yil)", _kb([BTN_SKIP2]))
        return True
    if s == "rec_prev":
        d["prev"] = "" if text == BTN_SKIP2 else text[:200]
        summary = [f"<b>Arizangiz:</b> {v.title}", f"👤 {d.get('name')}", f"📱 {d.get('phone')}", f"🎂 {d.get('year')}"]
        for a in d["answers"]:
            q = (v.questions or [])[a["i"]]["text"] if a["i"] < len(v.questions or []) else ""
            summary.append(f"❓ {q} — <b>{a['a']}</b>")
        if d.get("exp"):
            summary.append(f"📝 {d['exp'][:200]}")
        if d.get("prev"):
            summary.append(f"🏢 {d['prev']}")
        go("rec_confirm", "\n".join(summary) + "\n\nHammasi to'g'rimi?", _kb([BTN_SEND]))
        return True
    if s == "rec_confirm":
        if text != BTN_SEND:
            return go("rec_confirm", "Yuborish uchun «✅ Arizani yuborish» tugmasini bosing yoki bekor qiling.", _kb([BTN_SEND])) or True
        wh = [{"company": d["prev"], "position": "", "years": ""}] if d.get("prev") else []
        frm = msg.get("from") or {}
        try:
            recruit.create_application(tenant, v, full_name=d.get("name", ""), phone=d.get("phone", ""), answers=d["answers"],
                                       experience=d.get("exp", ""), work_history=wh, birth_year=d.get("year"), source="telegram",
                                       tg_chat_id=bu.chat_id, tg_username=frm.get("username") or bu.username)
        except ValueError as e:
            say(tenant, bu.chat_id, f"Xato: {e}")
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Asosiy menyu 👇", main_keyboard(tenant, bu, None))
        return True
    return False


def _ask_q(tenant, bu, st, d, v, go) -> bool:
    qs = v.questions or []
    i = int(st.get("qi", 0))
    if i < len(qs):
        q = qs[i]
        mk = _kb(["Ha", "Yo'q"]) if q.get("type") == "yesno" else _kb()
        go("rec_q", f"❓ {q.get('text')}", mk)
        return True
    go("rec_exp", "O'zingiz haqingizda qisqacha: tajriba, qachondan ishga chiqa olasiz?", _kb([BTN_SKIP2]))
    return True


# ------------------------------------------------------------------ kayfiyat (smenadan keyin)
def mood_markup(att_id: int) -> dict:
    return {"inline_keyboard": [[{"text": MOODS[n], "callback_data": f"mood:{att_id}:{n}"} for n in (4, 3, 2, 1)]]}


def save_mood(tenant, chat_id: int, att_id: int, mood: int) -> str:
    from modules.hr.models import Attendance, ShiftFeedback
    a = Attendance.objects.select_related("employee__user").filter(pk=att_id, employee__user__telegram_id=chat_id).first()
    if a is None or mood not in MOODS:
        return "Topilmadi"
    ShiftFeedback.objects.update_or_create(attendance=a, defaults={"employee": a.employee, "mood": mood,
                                                                    "date": a.check_in.date()})
    return {4: "Zo'r! Rahmat 🙌", 3: "Rahmat!", 2: "Tushunarli. Nima yaxshilash kerak — yozib qoldirishingiz mumkin.",
            1: "Afsus 😔 Menejeringizga aytamiz — yozib qoldiring, nima bo'ldi?"}[mood]


def handle_callback(tenant, cq: dict) -> bool:
    from integrations.telegram import call

    from .services import touch
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id") or (cq.get("from") or {}).get("id")
    reply = ""
    if data.startswith("job:") and hr_on(tenant):
        bu = touch({"from": cq.get("from") or {}, "chat": {"id": chat_id}})
        start_apply(tenant, bu, int(data.split(":")[1]))
    elif data.startswith("mood:") and hr_on(tenant):
        _, att, n = data.split(":")
        reply = save_mood(tenant, chat_id, int(att), int(n))
    else:
        return False
    try:
        from .services import token
        call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": reply[:190]}, token(tenant))
    except Exception:
        pass
    return True
'@

Put 'backend\modules\telegram\services.py' @'
"""
Telegram bot "miyasi": har restoran o'z boti (token sozlamada), mijoz bilan suhbat, Mini App tekshiruvi.

handle_update(tenant, update, base_url) → True bo'lsa xabar shu yerda ko'rib chiqildi.
False — xodimlar buyruqlari (/vazifalar, /keldim, /ketdim) eski ishlovchiga o'tadi.

Mini App xavfsizligi: Telegram yuborgan initData HMAC-SHA256 bilan tekshiriladi
(secret = HMAC_SHA256(key="WebAppData", msg=bot_token)). Soxta buyurtma yuborib bo'lmaydi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from django.conf import settings as dj_settings
from django.utils import timezone

from core.models import User
from integrations.telegram import call, send_message

from .models import Audience, BotUser, Broadcast, BroadcastStatus

log = logging.getLogger("tgbot")

_DEFAULTS = {k: v.get("default") for k, v in json.loads(
    (Path(__file__).parent / "module.json").read_text(encoding="utf-8"))["settings_schema"]["properties"].items()}

STAFF_COMMANDS = ("/vazifalar", "/keldim", "/ketdim")
BTN_MENU, BTN_BOOK, BTN_ORDERS, BTN_CONTACT, BTN_PHONE, BTN_CANCEL = (
    "🍔 Menyu va buyurtma", "📅 Stol bron qilish", "🧾 Buyurtmalarim", "☎️ Aloqa", "📱 Telefonni ulashish", "✖️ Bekor qilish")
BTN_BONUS, BTN_SKIP = "🎁 Bonuslarim", "⏭ O'tkazib yuborish"


# ------------------------------------------------------------------ sozlamalar
def conf(tenant) -> dict:
    saved = ((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("telegram") or {}
    return {**_DEFAULTS, **saved}


def token(tenant) -> str | None:
    return (conf(tenant).get("bot_token") or "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN") or None


def say(tenant, chat_id, text: str, markup: dict | None = None) -> bool:
    return send_message(chat_id, text, token=token(tenant), reply_markup=markup)


def miniapp_url(base_url: str | None) -> str | None:
    """Mini App faqat https orqali ochiladi (Telegram talabi)."""
    if base_url and base_url.startswith("https://"):
        return base_url.rstrip("/") + "/tg/"
    return None


def main_keyboard(tenant, bu: BotUser, base_url: str | None) -> dict:
    cfg = conf(tenant)
    url = miniapp_url(base_url)
    rows = [[{"text": BTN_MENU, "web_app": {"url": url}} if url else {"text": BTN_MENU}]]
    second = []
    if cfg.get("enable_booking") and tenant.module_enabled("reservations"):
        second.append({"text": BTN_BOOK})
    second.append({"text": BTN_ORDERS})
    rows.append(second)
    extra = []
    if tenant.module_enabled("crm"):
        extra.append({"text": BTN_BONUS})
    if tenant.module_enabled("hr") and not bu.staff_id:
        from .hr_flow import open_jobs
        if open_jobs():
            extra.append({"text": "💼 Vakansiyalar"})
    if extra:
        rows.append(extra)
    rows.append([{"text": BTN_PHONE, "request_contact": True}] if not bu.phone else [{"text": BTN_CONTACT}])
    return {"keyboard": rows, "resize_keyboard": True}


# ------------------------------------------------------------------ yordamchilar
def normalize(phone: str) -> str:
    return User.objects.normalize_phone(phone) if phone else ""


def touch(msg: dict) -> BotUser:
    frm = msg.get("from") or {}
    chat = msg.get("chat") or {}
    bu, _ = BotUser.objects.get_or_create(chat_id=chat.get("id"))
    name = " ".join(x for x in [frm.get("first_name"), frm.get("last_name")] if x)
    bu.full_name = name or bu.full_name
    bu.username = frm.get("username") or bu.username
    bu.language = (frm.get("language_code") or bu.language or "uz")[:5]
    bu.last_seen_at = timezone.now()
    bu.is_blocked = False
    bu.save()
    return bu


def _orders_for(phone: str, n: int = 5):
    from modules.pos.models import Order
    return list(Order.objects.filter(customer_phone=phone).order_by("-created_at")[:n])


STATUS_UZ = {"open": "qabul qilindi", "paid": "to'langan", "cancelled": "bekor qilingan"}
TYPE_UZ = {"delivery": "yetkazib berish", "takeaway": "olib ketish", "dine_in": "zalda"}


def money(v: int) -> str:
    return f"{int(v):,}".replace(",", " ")


# ------------------------------------------------------------------ asosiy ishlovchi
def handle_update(tenant, update: dict, base_url: str | None = None) -> bool:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        cq = update.get("callback_query")
        if cq:
            from . import hr_flow
            hr_flow.handle_callback(tenant, cq)
        return bool(cq or update.get("my_chat_member"))
    chat = msg.get("chat") or {}
    if chat.get("type") not in (None, "private"):
        return True                         # guruhlarda javob bermaymiz (xodimlar guruhi — faqat bildirishnoma uchun)
    text = (msg.get("text") or "").strip()
    bu = touch(msg)

    # --- ishga ariza suhbati (HR) — kontakt ham shu yerda qabul qilinadi
    if str((bu.state or {}).get("step") or "").startswith("rec_") and text not in (BTN_CANCEL, "/cancel") and not text.startswith("/start"):
        from . import hr_flow
        if hr_flow.step(tenant, bu, msg, text):
            return True
    if text.startswith("/start job_") and tenant.module_enabled("hr"):
        from . import hr_flow
        vid = text.split("job_", 1)[1].split()[0]
        return hr_flow.start_apply(tenant, bu, int(vid)) if vid.isdigit() else hr_flow.show_jobs(tenant, bu)

    # --- telefon ulashildi
    contact = msg.get("contact")
    if contact and contact.get("phone_number"):
        if contact.get("user_id") and contact["user_id"] != chat.get("id"):
            say(tenant, bu.chat_id, "Iltimos, o'zingizning raqamingizni ulashing — tugmani bosing 👇", main_keyboard(tenant, bu, base_url))
            return True
        bu.phone = normalize(contact["phone_number"])
        staff = User.objects.filter(phone=bu.phone, is_active=True).first()
        if staff:
            staff.telegram_id = bu.chat_id
            staff.save(update_fields=["telegram_id"])
            bu.staff = staff
        bu.save()
        if staff:
            say(tenant, bu.chat_id, f"✅ <b>{staff.full_name or bu.phone}</b>, siz <b>{tenant.name}</b> xodimi sifatida ulandingiz.\n"
                                    "Vazifalar, o'qitish va tasdiqlar shu yerga keladi.\n/vazifalar · /keldim · /ketdim",
                main_keyboard(tenant, bu, base_url))
        else:
            say(tenant, bu.chat_id, "✅ Rahmat! Raqamingiz saqlandi — endi buyurtmalaringiz va bonuslaringiz shu yerda.",
                main_keyboard(tenant, bu, base_url))
        if tenant.module_enabled("crm"):
            from modules.crm import services as crm
            c, _ = crm.get_or_create(tenant, bu.phone, bu.full_name, source="telegram")
            if c and not c.birthday and not staff:
                bu.state = {"step": "crm_bday"}
                bu.save(update_fields=["state"])
                bonus = int(crm.conf(tenant).get("birthday_bonus") or 0)
                say(tenant, bu.chat_id, "🎂 Tug'ilgan kuningizni yozing (masalan <b>25.09.1995</b>)"
                    + (f" — o'sha kuni <b>{money(bonus)} so'm</b> sovg'a bonus olasiz!" if bonus else ""),
                    {"keyboard": [[BTN_SKIP]], "resize_keyboard": True})
        return True

    # --- xodim buyruqlari — eski ishlovchiga
    if bu.staff_id and text.split(" ")[0].split("@")[0] in STAFF_COMMANDS:
        return False

    # --- bekor qilish / start
    if text in (BTN_CANCEL, "/cancel"):
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Bekor qilindi.", main_keyboard(tenant, bu, base_url))
        return True
    if text.startswith("/start") or text == "/menu":
        bu.state = {}
        bu.save(update_fields=["state"])
        cfg = conf(tenant)
        say(tenant, bu.chat_id, f"<b>{tenant.name}</b>\n{cfg.get('welcome_text') or ''}", main_keyboard(tenant, bu, base_url))
        return True

    # --- bron suhbati davom etmoqda
    step = (bu.state or {}).get("step")
    if step and step.startswith("book_"):
        return _booking_step(tenant, bu, text, base_url)
    if step == "crm_bday":
        if text in (BTN_MENU, BTN_BOOK, BTN_ORDERS, BTN_CONTACT, BTN_BONUS) or text.startswith("/"):
            bu.state = {}                       # mijoz boshqa tugmani bosdi — so'rovni tashlab, o'shani bajaramiz
            bu.save(update_fields=["state"])
        else:
            return _birthday_step(tenant, bu, text, base_url)

    if text == BTN_BONUS or text == "/bonus":
        return _bonus_info(tenant, bu, base_url)

    if (text == "💼 Vakansiyalar" or text == "/vakansiyalar") and tenant.module_enabled("hr"):
        from . import hr_flow
        return hr_flow.show_jobs(tenant, bu)

    if text == BTN_BOOK:
        if not (conf(tenant).get("enable_booking") and tenant.module_enabled("reservations")):
            say(tenant, bu.chat_id, "Hozircha bot orqali bron qilib bo'lmaydi — qo'ng'iroq qiling.", main_keyboard(tenant, bu, base_url))
            return True
        if not bu.phone:
            say(tenant, bu.chat_id, "Bron uchun avval telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
            return True
        bu.state = {"step": "book_guests"}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Necha kishi bo'lasiz?", {"keyboard": [["1", "2", "3", "4"], ["5", "6", "8", "10"], [BTN_CANCEL]], "resize_keyboard": True})
        return True

    if text == BTN_ORDERS or text == "/buyurtmalarim":
        if not bu.phone:
            say(tenant, bu.chat_id, "Buyurtmalaringizni ko'rish uchun telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
            return True
        if not tenant.module_enabled("pos"):
            say(tenant, bu.chat_id, "Buyurtmalar tarixi hozircha mavjud emas.")
            return True
        rows = _orders_for(bu.phone)
        if not rows:
            say(tenant, bu.chat_id, "Hali buyurtmangiz yo'q. «" + BTN_MENU + "» tugmasini bosing 🙂", main_keyboard(tenant, bu, base_url))
        else:
            lines = [f"#{o.number} · {o.created_at.astimezone(timezone.get_current_timezone()):%d.%m %H:%M} · {money(o.total)} so'm · {STATUS_UZ.get(o.status, o.status)}" for o in rows]
            say(tenant, bu.chat_id, "<b>Oxirgi buyurtmalaringiz</b>\n" + "\n".join(lines)
                + f"\n\nJami: {bu.orders_count} ta buyurtma · {money(bu.spent_total)} so'm", main_keyboard(tenant, bu, base_url))
        return True

    if text == BTN_MENU:
        url = miniapp_url(base_url)
        if url:
            say(tenant, bu.chat_id, "Menyuni ochish uchun pastdagi tugmani bosing 👇",
                {"inline_keyboard": [[{"text": "🍔 Menyuni ochish", "web_app": {"url": url}}]]})
        else:
            say(tenant, bu.chat_id, _menu_text(), main_keyboard(tenant, bu, base_url))
        return True

    if text == BTN_CONTACT:
        say(tenant, bu.chat_id, _contact_text(tenant), main_keyboard(tenant, bu, base_url))
        return True

    if bu.staff_id and text.startswith("/"):
        return False
    say(tenant, bu.chat_id, "Quyidagi tugmalardan birini tanlang 👇", main_keyboard(tenant, bu, base_url))
    return True


def _menu_text() -> str:
    from modules.catalog.services import current_snapshot
    snap = current_snapshot() or {"categories": []}
    lines = []
    for c in snap["categories"][:6]:
        lines.append(f"\n<b>{c['name'].get('uz')}</b>")
        for p in c["products"][:8]:
            lines.append(f"• {p['name'].get('uz')} — {money(p['price'])} so'm")
    return ("<b>Taomnoma</b>" + "\n".join(lines)) if lines else "Taomnoma hali e'lon qilinmagan."


def _contact_text(tenant) -> str:
    try:
        from modules.cms.models import SiteSettings
        s = SiteSettings.get()
        parts = [f"<b>{s.title or tenant.name}</b>"]
        if s.phone:
            parts.append(f"☎️ {s.phone}")
        if s.address:
            parts.append(f"📍 {s.address}")
        return "\n".join(parts)
    except Exception:
        return tenant.name


# ------------------------------------------------------------------ bron suhbati
def _slots(day, guests: int, tenant) -> list[str]:
    from modules.reservations.services import free_tables
    now = timezone.localtime()
    out = []
    for h in range(11, 23):
        for m in (0, 30):
            at = timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m))
            if at < now + timedelta(minutes=30):
                continue
            if free_tables(at, 90, guests, tenant=tenant):
                out.append(f"{h:02d}:{m:02d}")
    return out


def _booking_step(tenant, bu: BotUser, text: str, base_url) -> bool:
    st = dict(bu.state or {})
    today = timezone.localdate()
    days = {"Bugun": today, "Ertaga": today + timedelta(days=1), "Indinga": today + timedelta(days=2)}
    if st["step"] == "book_guests":
        if not text.isdigit() or not (1 <= int(text) <= 30):
            say(tenant, bu.chat_id, "Mehmonlar sonini raqam bilan yozing (masalan: 4).")
            return True
        st.update(step="book_day", guests=int(text))
        bu.state = st
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Qaysi kunga?", {"keyboard": [list(days.keys()), [BTN_CANCEL]], "resize_keyboard": True})
        return True
    if st["step"] == "book_day":
        if text not in days:
            say(tenant, bu.chat_id, "Tugmalardan birini tanlang: Bugun / Ertaga / Indinga.")
            return True
        day = days[text]
        slots = _slots(day, st["guests"], tenant)
        if not slots:
            say(tenant, bu.chat_id, f"{text} {st['guests']} kishilik bo'sh stol qolmagan 😔 Boshqa kunni tanlang.",
                {"keyboard": [list(days.keys()), [BTN_CANCEL]], "resize_keyboard": True})
            return True
        st.update(step="book_time", day=day.isoformat())
        bu.state = st
        bu.save(update_fields=["state"])
        rows = [slots[i:i + 4] for i in range(0, min(len(slots), 16), 4)] + [[BTN_CANCEL]]
        say(tenant, bu.chat_id, "Soatni tanlang (bo'sh vaqtlar):", {"keyboard": rows, "resize_keyboard": True})
        return True
    if st["step"] == "book_time":
        try:
            hh, mm = (int(x) for x in text.split(":"))
            day = datetime.fromisoformat(st["day"]).date()
            at = timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm))
        except Exception:
            say(tenant, bu.chat_id, "Vaqtni tugmadan tanlang (masalan: 19:00).")
            return True
        res = create_booking(tenant, bu, at, st["guests"])
        bu.state = {}
        bu.save(update_fields=["state"])
        if res is None:
            say(tenant, bu.chat_id, "Afsus, bu vaqt hozirgina band bo'ldi. Qaytadan urinib ko'ring.", main_keyboard(tenant, bu, base_url))
        else:
            tbl = f" · stol {res.table.number}" if res.table else ""
            say(tenant, bu.chat_id, f"✅ Bron qilindi!\n📅 {at:%d.%m.%Y} · ⏰ {at:%H:%M} · 👥 {res.guests} kishi{tbl}\n"
                                    "Kutamiz! O'zgartirish uchun qo'ng'iroq qiling.", main_keyboard(tenant, bu, base_url))
            notify_staff(tenant, f"📅 <b>Yangi bron (Telegram)</b>\n{bu.full_name or bu.phone} · {bu.phone}\n"
                                 f"{at:%d.%m %H:%M} · {res.guests} kishi{tbl}")
        return True
    bu.state = {}
    bu.save(update_fields=["state"])
    return True


def create_booking(tenant, bu: BotUser, at, guests: int):
    from modules.reservations.models import Reservation
    from modules.reservations.services import auto_table, free_tables
    if not free_tables(at, 90, guests, tenant=tenant):
        return None
    res = Reservation(guest_name=bu.full_name or bu.phone, phone=bu.phone, guests=guests, starts_at=at,
                      duration_minutes=90, source="telegram")
    res.table = auto_table(res, tenant=tenant)
    res.save()
    return res


def notify_staff(tenant, text: str) -> None:
    chat = (conf(tenant).get("notify_staff_chat_id") or "").strip()
    if chat:
        say(tenant, chat, text)


# ------------------------------------------------------------------ Mini App: initData tekshiruvi
class InitDataError(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age_hours: int = 24) -> dict:
    """Telegram WebApp initData'ni tekshiradi va foydalanuvchi ma'lumotini qaytaradi."""
    if not init_data or not bot_token:
        raise InitDataError("initData yoki token yo'q")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise InitDataError("imzo noto'g'ri")
    auth_date = int(pairs.get("auth_date", "0") or 0)
    if auth_date and timezone.now().timestamp() - auth_date > max_age_hours * 3600:
        raise InitDataError("initData eskirgan")
    try:
        return json.loads(pairs.get("user", "{}"))
    except ValueError as e:
        raise InitDataError("user noto'g'ri") from e


def sign_init_data(user: dict, bot_token: str, auth_date: int | None = None) -> str:
    """Testlar va dev uchun: haqiqiy Telegram kabi imzolangan initData yasaydi."""
    from urllib.parse import urlencode
    pairs = {"auth_date": str(auth_date or int(timezone.now().timestamp())), "query_id": "AAH-dev", "user": json.dumps(user, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def miniapp_user(tenant, init_data: str) -> BotUser | None:
    """initData → BotUser. Token yo'q bo'lsa (dev rejim) — tekshiruvsiz, mehmon sifatida."""
    tok = token(tenant)
    if not tok:
        if dj_settings.DEBUG:
            return None
        raise InitDataError("Bot sozlanmagan")
    user = verify_init_data(init_data, tok)
    if not user.get("id"):
        raise InitDataError("user yo'q")
    bu, _ = BotUser.objects.get_or_create(chat_id=user["id"])
    bu.full_name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or bu.full_name
    bu.username = user.get("username") or bu.username
    bu.last_seen_at = timezone.now()
    bu.save()
    return bu


# ------------------------------------------------------------------ ommaviy xabar
def audience_qs(audience: str):
    qs = BotUser.objects.filter(is_blocked=False)
    if audience == Audience.WITH_PHONE:
        qs = qs.exclude(phone="")
    elif audience == Audience.BUYERS:
        qs = qs.filter(orders_count__gt=0)
    return qs


def send_broadcast(tenant, b: Broadcast) -> Broadcast:
    tok = token(tenant)
    markup = {"inline_keyboard": [[{"text": b.button_text, "url": b.button_url}]]} if b.button_text and b.button_url else None
    sent = failed = 0
    users = list(audience_qs(b.audience))
    for u in users:
        r = call("sendMessage", {"chat_id": u.chat_id, "text": b.text, "parse_mode": "HTML",
                                 **({"reply_markup": markup} if markup else {})}, tok)
        if r.get("ok"):
            sent += 1
        else:
            failed += 1
            if r.get("error_code") == 403:          # botni bloklagan
                BotUser.objects.filter(pk=u.pk).update(is_blocked=True)
    b.total, b.sent, b.failed = len(users), sent, failed
    b.status, b.sent_at = BroadcastStatus.SENT, timezone.now()
    b.save()
    return b


# ------------------------------------------------------------------ bonus (CRM moduli yoqilgan bo'lsa)
def _birthday_step(tenant, bu: BotUser, text: str, base_url) -> bool:
    from datetime import date as _date
    bu.state = {}
    if text != BTN_SKIP:
        parts = [p for p in text.replace("/", ".").replace("-", ".").replace(" ", ".").split(".") if p]
        try:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            y = y + 1900 if y < 100 and y > 30 else (y + 2000 if y < 100 else y)
            bd = _date(y, m, d)
            if not (1920 <= bd.year <= timezone.localdate().year - 5):
                raise ValueError
        except (ValueError, IndexError):
            bu.state = {"step": "crm_bday"}
            bu.save(update_fields=["state"])
            say(tenant, bu.chat_id, "Tushunmadim 🙂 Kun.oy.yil ko'rinishida yozing, masalan <b>25.09.1995</b>",
                {"keyboard": [[BTN_SKIP]], "resize_keyboard": True})
            return True
        from modules.crm.models import Customer
        Customer.objects.filter(phone=bu.phone, birthday__isnull=True).update(birthday=bd)
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, f"🎉 Saqlandi: {bd:%d.%m.%Y}. Tug'ilgan kuningizda sovg'a kutib turadi!", main_keyboard(tenant, bu, base_url))
        return True
    bu.save(update_fields=["state"])
    say(tenant, bu.chat_id, "Mayli. Kerak bo'lsa keyin yozishingiz mumkin.", main_keyboard(tenant, bu, base_url))
    return True


def _bonus_info(tenant, bu: BotUser, base_url) -> bool:
    if not tenant.module_enabled("crm"):
        say(tenant, bu.chat_id, "Bonus tizimi hozircha yoqilmagan.", main_keyboard(tenant, bu, base_url))
        return True
    if not bu.phone:
        say(tenant, bu.chat_id, "Bonuslaringizni ko'rish uchun telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
        return True
    from modules.crm import services as crm
    from modules.crm.models import Promo
    c, _ = crm.get_or_create(tenant, bu.phone, bu.full_name, source="telegram")
    cfg = crm.conf(tenant)
    lvl = crm.level_of(c, cfg)
    lines = [f"🎁 <b>Bonus balansingiz: {money(c.balance)} so'm</b>",
             f"Daraja: <b>{lvl['name']}</b> — har xariddan {lvl['percent']}% qaytadi"]
    if lvl["next"]:
        lines.append(f"{lvl['next']} darajagacha: {money(lvl['next_left'])} so'm xarid")
    lines.append(f"Bonus bilan chekning {cfg['max_pay_percent']}% gacha to'lash mumkin — kassada raqamingizni ayting.")
    promos = [p for p in Promo.objects.filter(is_active=True)[:10] if not (p.ends_on and p.ends_on < timezone.localdate())]
    if promos:
        lines.append("\n<b>Aksiyalar</b>")
        lines += [f"• {p.name}" + (f" — promokod <code>{p.code}</code>" if p.code else "") for p in promos[:6]]
    say(tenant, bu.chat_id, "\n".join(lines), main_keyboard(tenant, bu, base_url))
    return True
'@

Put 'backend\public\management\commands\bootstrap_dev.py' @'
"""
Dev muhitini bir buyruq bilan tayyorlash:
public sxema migratsiyasi → tariflar → 'localhost' public domeni → demo tenant 'lazzat' (lazzat.localhost).
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Domain, Plan, Tenant
from public.services import create_tenant


class Command(BaseCommand):
    help = "Dev: migratsiya + tariflar + platforma domeni + demo tenant"

    def handle(self, *args, **options):
        call_command("migrate_schemas", "--shared", verbosity=0)
        for code, name, price, mods in [
            ("start", "Start", 199_000, ["catalog", "cms", "pos", "fiscal", "payments", "telegram", "reports"]),
            ("pro", "Pro", 490_000, ["*"]),
            ("network", "Tarmoq", 990_000, ["*"]),
        ]:
            Plan.objects.update_or_create(code=code, defaults={"name": name, "price_per_branch": price, "allowed_modules": mods, "max_branches": 1 if code == "start" else 100})

        if not Tenant.objects.filter(schema_name="public").exists():
            public = Tenant(schema_name="public", name="Platforma", slug="public", enabled_modules=[])
            public.save()
            Domain.objects.get_or_create(tenant=public, domain="localhost", defaults={"is_primary": True})
            self.stdout.write("public tenant + localhost domeni yaratildi")

        if not Tenant.objects.filter(slug="lazzat").exists():
            t = create_tenant(name="Lazzat", slug="lazzat", owner_phone="998901234567", preset="fast_food",
                              owner_name="Akmal T.", plan_code="pro", domain="lazzat.localhost")
            with schema_context(t.schema_name):
                from modules.catalog.demo import seed_demo_menu
                from modules.finance.demo import seed_demo_expenses
                from modules.hr.demo import seed_demo_hr
                from modules.inventory.demo import seed_demo_inventory
                from modules.pos.demo import seed_demo_orders
                from modules.reservations.demo import seed_demo_reservations
                from modules.tables.demo import seed_demo_tables
                from modules.tasks.demo import seed_demo_tasks
                seed_demo_menu()
                seed_demo_tasks()
                seed_demo_inventory(t)      # tex-kartalar → taom tannarxi real
                seed_demo_orders()          # 14 kunlik savdo → hisobotlar
                seed_demo_hr()              # xodimlar, smena, davomat, oylik
                from core.models import Membership
                from modules.hr.demo import seed_demo_recruit_people
                seed_demo_recruit_people(Membership.objects.filter(role__code="owner").first().user)
                seed_demo_expenses()        # ijara, kommunal, marketing
                seed_demo_tables()          # zal xaritasi: 2 zal, 14 stol
                seed_demo_reservations()    # bugungi/ertangi bronlar + navbat
                from modules.training.demo import seed_demo_training
                seed_demo_training()        # kurslar, testlar, standartlar, topshiriqlar
                from modules.crm.demo import seed_demo_crm
                seed_demo_crm(t)            # mijozlar, bonus tarixi, aksiyalar
            from public.services import set_modules
            set_modules(t, [*t.enabled_modules, "training", "crm"])
            self.stdout.write(self.style.SUCCESS("Demo tenant: http://lazzat.localhost:8000  (egasi: +998901234567, OTP dev rejimida javobda qaytadi)"))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
'@

Put 'backend\public\showcase.py' @'
"""
Namuna restoran «Navro'z milliy taomlar» — barcha imkoniyatlarni ko'rsatish va sinash uchun to'liq soxta baza.

Hamma ma'lumot to'qima (ismlar, telefonlar, mijozlar). Narxlar esa haqiqatga yaqin — 2026-yil Toshkent:
  • bozor narxlari (pul24.uz, 2026-06-01): mol go'shti 75–106 ming, qo'y 90–130 ming, guruch 12 mingdan, pomidor ≤13 ming…
  • osh markazlarida 1 porsiya osh Toshkentda 30 200 so'm (uz24.uz, 2024) → 2026-yil o'rta restoranda 42–60 ming
  • somsa, lag'mon, kabob — hostella.uz (2026) va o'rta toifadagi restoran menyulari darajasida
Tannarx tex-kartalardan hisoblanadi (food cost ≈ 28–38%).

Ishga tushirish:  python manage.py seed_showcase          → http://namuna.localhost:8000
                  python manage.py seed_showcase --reset  → o'chirib, qaytadan yaratadi
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import F
from django.utils import timezone
from django_tenants.utils import schema_context

SLUG = "namuna"
NAME = "Navro'z milliy taomlar"
OWNER_PHONE = "+998901234567"          # demo egasi (Lazzat bilan bir xil — eslab qolish oson)
EXTRA_OWNERS = [("+998888203830", "Nizomiddin")]   # loyiha egasi o'z raqami bilan ham kira oladi

# ------------------------------------------------------------------ taomnoma
CATS = [("Osh", "Плов", "Plov"), ("Sho'rvalar", "Супы", "Soups"), ("Issiq taomlar", "Горячие блюда", "Main dishes"),
        ("Kaboblar", "Шашлыки", "Kebabs"), ("Somsa va non", "Самса и хлеб", "Samsa & bread"), ("Salatlar", "Салаты", "Salads"),
        ("Shirinliklar", "Десерты", "Desserts"), ("Ichimliklar", "Напитки", "Drinks")]

# (kategoriya, nomi uz, nomi ru, tavsif, narx, vazn g, kkal, teglar, modifikator guruhlari)
MENU = [
    ("Osh", "To'y oshi", "Свадебный плов", "Devzira guruch, mol go'shti, sariq sabzi, no'xat va mayiz bilan", 48000, 400, 780, ["hit"], ["porsiya"]),
    ("Osh", "Choyxona oshi", "Чайханский плов", "Qo'y go'shti va dumba yog'ida, ko'p sabzili", 42000, 380, 820, [], ["porsiya"]),
    ("Osh", "Samarqand oshi", "Самаркандский плов", "Qatlam-qatlam, go'sht ustida, sabzi alohida qovurilgan", 45000, 400, 760, [], ["porsiya"]),
    ("Osh", "Qazili osh", "Плов с казы", "To'y oshi + uy qazisi va bedana tuxumi", 62000, 450, 950, ["new"], ["porsiya"]),
    ("Sho'rvalar", "Sho'rva", "Шурпа", "Qo'y go'shti, kartoshka, sabzi va ko'katlar bilan", 38000, 450, 420, [], []),
    ("Sho'rvalar", "Mastava", "Мастава", "Guruchli sho'rva, suzma bilan", 30000, 400, 380, [], []),
    ("Sho'rvalar", "Chuchvara sho'rva", "Суп с чучварой", "Qo'lda tugilgan chuchvara, qatiq bilan", 32000, 400, 410, [], []),
    ("Sho'rvalar", "Mosh xo'rda", "Маш-кхурда", "Mosh, guruch va go'sht — uy taomi", 28000, 400, 360, [], []),
    ("Issiq taomlar", "Qovurma lag'mon", "Жареный лагман", "Qo'lda cho'zilgan xamir, mol go'shti va sabzavot", 40000, 380, 690, ["hit"], ["achchiqlik"]),
    ("Issiq taomlar", "Suyuq lag'mon", "Лагман", "Go'shtli sabzavotli sho'rva va cho'zma xamir", 35000, 450, 540, [], ["achchiqlik"]),
    ("Issiq taomlar", "Manti (5 dona)", "Манты (5 шт)", "Qo'y go'shti va piyoz, bug'da pishirilgan", 36000, 300, 620, [], []),
    ("Issiq taomlar", "Dimlama", "Димлама", "Go'sht va sabzavotlar o'z sharbatida dimlangan", 45000, 450, 560, [], []),
    ("Issiq taomlar", "Qozon kabob", "Казан-кабоб", "Qo'y go'shti va kartoshka qozonda qovurilgan", 69000, 450, 980, ["hit"], []),
    ("Issiq taomlar", "Norin", "Нарын", "Mayda to'g'ralgan xamir va qazi, sovuq holda", 38000, 300, 540, [], []),
    ("Kaboblar", "Qo'y go'shti kabob", "Шашлык из баранины", "1 six, piyoz va non bilan", 28000, 160, 420, ["hit"], ["garnir"]),
    ("Kaboblar", "Mol go'shti kabob", "Шашлык из говядины", "1 six", 26000, 160, 380, [], ["garnir"]),
    ("Kaboblar", "Jigar kabob", "Шашлык из печени", "1 six, dumba bilan", 22000, 150, 350, [], ["garnir"]),
    ("Kaboblar", "Lula kabob", "Люля-кебаб", "Qiyma, ziravorlar bilan", 26000, 150, 390, [], ["garnir"]),
    ("Kaboblar", "Tovuq kabob", "Шашлык из курицы", "1 six, marinadlangan", 20000, 170, 290, [], ["garnir"]),
    ("Somsa va non", "Tandir somsa", "Самса тандырная", "Qo'y go'shti va dumba", 13000, 150, 380, ["hit"], []),
    ("Somsa va non", "Qovoqli somsa", "Самса с тыквой", "Mavsumiy, yengil", 9000, 150, 260, [], []),
    ("Somsa va non", "Obi non", "Лепёшка", "Tandirda yopilgan", 5000, 400, 900, [], []),
    ("Somsa va non", "Patir non", "Патыр", "Qatlamli, sutli", 9000, 350, 1050, [], []),
    ("Salatlar", "Achchiq-chuchuk", "Ачик-чучук", "Pomidor, piyoz, achchiq qalampir", 15000, 250, 70, [], []),
    ("Salatlar", "Toshkent salati", "Салат «Ташкент»", "Ko'k turp, mol go'shti, tuxum", 32000, 250, 380, [], []),
    ("Salatlar", "Suzma ko'katlar bilan", "Сюзьма с зеленью", "Uy suzmasi", 14000, 200, 240, [], []),
    ("Salatlar", "Olivye", "Оливье", "Tovuq go'shti bilan", 26000, 250, 420, [], []),
    ("Salatlar", "Ko'k salat", "Зелёный салат", "Bodring, pomidor, ko'katlar", 18000, 250, 90, ["veg"], []),
    ("Shirinliklar", "Chak-chak", "Чак-чак", "Asal bilan", 18000, 150, 520, [], []),
    ("Shirinliklar", "Halvo", "Халва", "Uy halvosi", 20000, 120, 560, [], []),
    ("Ichimliklar", "Ko'k choy (choynak)", "Зелёный чай (чайник)", "", 8000, 800, 0, [], []),
    ("Ichimliklar", "Qora choy (choynak)", "Чёрный чай (чайник)", "", 8000, 800, 0, [], []),
    ("Ichimliklar", "Limonli choy", "Чай с лимоном", "Limon va asal", 15000, 800, 60, [], []),
    ("Ichimliklar", "Kompot (1 l)", "Компот (1 л)", "Quritilgan mevalardan", 20000, 1000, 240, [], []),
    ("Ichimliklar", "Ayron", "Айран", "Uy ayroni, 0,4 l", 12000, 400, 120, [], []),
    ("Ichimliklar", "Coca-Cola 0,5", "Coca-Cola 0,5", "", 12000, 500, 210, [], []),
    ("Ichimliklar", "Suv 0,5", "Вода 0,5", "Gazsiz", 5000, 500, 0, [], []),
]

# ------------------------------------------------------------------ xomashyo (nom, kategoriya, birlik, narx, min qoldiq, boshlang'ich kirim)
ING = [
    ("Mol go'shti", "Go'sht", "kg", 95000, 10, 45), ("Qo'y go'shti", "Go'sht", "kg", 115000, 8, 40),
    ("Dumba", "Go'sht", "kg", 85000, 3, 10), ("Tovuq go'shti", "Go'sht", "kg", 45000, 5, 20),
    ("Mol jigari", "Go'sht", "kg", 60000, 2, 6), ("Qazi", "Go'sht", "kg", 180000, 3, 2),
    ("Guruch (devzira)", "Don", "kg", 28000, 20, 80), ("Un", "Don", "kg", 6500, 25, 100),
    ("No'xat", "Don", "kg", 18000, 3, 10), ("Mosh", "Don", "kg", 20000, 2, 8), ("Mayiz", "Quruq", "kg", 40000, 2, 5),
    ("Sariq sabzi", "Sabzavot", "kg", 6000, 20, 90), ("Piyoz", "Sabzavot", "kg", 5000, 15, 60),
    ("Kartoshka", "Sabzavot", "kg", 5000, 20, 60), ("Pomidor", "Sabzavot", "kg", 12000, 8, 25),
    ("Bodring", "Sabzavot", "kg", 10000, 5, 15), ("Bolgar qalampir", "Sabzavot", "kg", 12000, 3, 10),
    ("Karam", "Sabzavot", "kg", 4000, 5, 15), ("Qovoq", "Sabzavot", "kg", 5000, 5, 15), ("Ko'k turp", "Sabzavot", "kg", 6000, 3, 8),
    ("Sarimsoq", "Sabzavot", "kg", 25000, 2, 4), ("Ko'katlar", "Sabzavot", "kg", 20000, 1, 3), ("Limon", "Meva", "kg", 50000, 2, 1),
    ("Paxta yog'i", "Yog'", "l", 24000, 20, 60), ("Tuxum", "Sut", "dona", 1500, 60, 300), ("Suzma", "Sut", "kg", 35000, 3, 12),
    ("Mayonez", "Sous", "kg", 30000, 2, 6), ("Ziravorlar", "Quruq", "kg", 60000, 1, 3), ("Tuz", "Quruq", "kg", 3000, 3, 10),
    ("Shakar", "Quruq", "kg", 12000, 5, 15), ("Asal", "Quruq", "kg", 90000, 1, 3),
    ("Ko'k choy", "Choy", "kg", 90000, 1, 3), ("Qora choy", "Choy", "kg", 80000, 1, 3), ("Quritilgan meva", "Quruq", "kg", 45000, 2, 6),
    ("Obi non (tayyor)", "Non", "dona", 3000, 40, 120), ("Patir (tayyor)", "Non", "dona", 5500, 20, 40),
    ("Chak-chak (tayyor)", "Shirinlik", "kg", 60000, 2, 4), ("Halvo (tayyor)", "Shirinlik", "kg", 70000, 2, 3),
    ("Coca-Cola 0,5", "Ichimlik", "dona", 7500, 24, 96), ("Suv 0,5", "Ichimlik", "dona", 2500, 24, 96),
]

# taom → [(xomashyo, miqdor: g / ml / dona, chiqindi %)]
RECIPES = {
    "To'y oshi": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 90, 8), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10), ("Paxta yog'i", 45, 0),
                  ("No'xat", 15, 0), ("Mayiz", 8, 0), ("Sarimsoq", 10, 5), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Choyxona oshi": [("Guruch (devzira)", 150, 0), ("Qo'y go'shti", 70, 8), ("Dumba", 20, 0), ("Sariq sabzi", 150, 10), ("Piyoz", 40, 10),
                      ("Paxta yog'i", 30, 0), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Samarqand oshi": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 100, 8), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10), ("Paxta yog'i", 40, 0),
                       ("No'xat", 15, 0), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Qazili osh": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 80, 8), ("Qazi", 50, 0), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10),
                   ("Paxta yog'i", 45, 0), ("No'xat", 15, 0), ("Tuxum", 1, 0), ("Ziravorlar", 3, 0)],
    "Sho'rva": [("Qo'y go'shti", 90, 10), ("Kartoshka", 120, 15), ("Sariq sabzi", 60, 10), ("Piyoz", 40, 10), ("Pomidor", 40, 5),
                ("Bolgar qalampir", 20, 10), ("Ko'katlar", 5, 0), ("Ziravorlar", 2, 0)],
    "Mastava": [("Guruch (devzira)", 50, 0), ("Mol go'shti", 60, 8), ("Kartoshka", 60, 15), ("Sariq sabzi", 50, 10), ("Piyoz", 30, 10),
                ("Pomidor", 30, 5), ("Paxta yog'i", 15, 0), ("Suzma", 30, 0)],
    "Chuchvara sho'rva": [("Un", 80, 0), ("Mol go'shti", 70, 8), ("Piyoz", 40, 10), ("Suzma", 30, 0), ("Ko'katlar", 5, 0)],
    "Mosh xo'rda": [("Mosh", 60, 0), ("Guruch (devzira)", 40, 0), ("Mol go'shti", 50, 8), ("Piyoz", 30, 10), ("Paxta yog'i", 15, 0), ("Suzma", 30, 0)],
    "Qovurma lag'mon": [("Un", 150, 0), ("Tuxum", 1, 0), ("Mol go'shti", 90, 8), ("Bolgar qalampir", 40, 10), ("Pomidor", 50, 5),
                        ("Piyoz", 40, 10), ("Sarimsoq", 5, 5), ("Paxta yog'i", 30, 0)],
    "Suyuq lag'mon": [("Un", 130, 0), ("Mol go'shti", 80, 8), ("Kartoshka", 60, 15), ("Bolgar qalampir", 30, 10), ("Pomidor", 40, 5), ("Piyoz", 30, 10)],
    "Manti (5 dona)": [("Un", 120, 0), ("Qo'y go'shti", 90, 8), ("Dumba", 20, 0), ("Piyoz", 100, 10), ("Ziravorlar", 2, 0)],
    "Dimlama": [("Mol go'shti", 110, 8), ("Kartoshka", 150, 15), ("Sariq sabzi", 80, 10), ("Karam", 100, 10), ("Pomidor", 60, 5),
                ("Bolgar qalampir", 40, 10), ("Piyoz", 50, 10)],
    "Qozon kabob": [("Qo'y go'shti", 170, 10), ("Kartoshka", 200, 15), ("Paxta yog'i", 40, 0), ("Piyoz", 40, 10), ("Ziravorlar", 3, 0)],
    "Norin": [("Un", 100, 0), ("Qazi", 40, 0), ("Mol go'shti", 30, 5), ("Piyoz", 30, 10)],
    "Qo'y go'shti kabob": [("Qo'y go'shti", 75, 5), ("Dumba", 15, 0), ("Piyoz", 30, 10), ("Ziravorlar", 1, 0)],
    "Mol go'shti kabob": [("Mol go'shti", 80, 5), ("Piyoz", 30, 10), ("Ziravorlar", 1, 0)],
    "Jigar kabob": [("Mol jigari", 90, 5), ("Dumba", 15, 0), ("Piyoz", 30, 10)],
    "Lula kabob": [("Mol go'shti", 40, 5), ("Qo'y go'shti", 35, 5), ("Dumba", 10, 0), ("Piyoz", 30, 10), ("Ziravorlar", 2, 0)],
    "Tovuq kabob": [("Tovuq go'shti", 120, 10), ("Paxta yog'i", 10, 0), ("Ziravorlar", 2, 0)],
    "Tandir somsa": [("Un", 70, 0), ("Qo'y go'shti", 30, 5), ("Dumba", 10, 0), ("Piyoz", 40, 10)],
    "Qovoqli somsa": [("Un", 70, 0), ("Qovoq", 100, 15), ("Piyoz", 20, 10), ("Dumba", 10, 0)],
    "Obi non": [("Obi non (tayyor)", 1, 0)],
    "Patir non": [("Patir (tayyor)", 1, 0)],
    "Achchiq-chuchuk": [("Pomidor", 150, 5), ("Piyoz", 40, 10), ("Ko'katlar", 3, 0)],
    "Toshkent salati": [("Mol go'shti", 60, 8), ("Ko'k turp", 100, 15), ("Tuxum", 1, 0), ("Mayonez", 30, 0), ("Ko'katlar", 5, 0)],
    "Suzma ko'katlar bilan": [("Suzma", 150, 0), ("Ko'katlar", 5, 0)],
    "Olivye": [("Kartoshka", 60, 15), ("Tovuq go'shti", 50, 10), ("Tuxum", 1, 0), ("Bodring", 30, 5), ("Mayonez", 40, 0)],
    "Ko'k salat": [("Bodring", 100, 5), ("Pomidor", 80, 5), ("Ko'katlar", 10, 0), ("Paxta yog'i", 10, 0)],
    "Chak-chak": [("Chak-chak (tayyor)", 150, 0)],
    "Halvo": [("Halvo (tayyor)", 120, 0)],
    "Ko'k choy (choynak)": [("Ko'k choy", 8, 0)],
    "Qora choy (choynak)": [("Qora choy", 8, 0)],
    "Limonli choy": [("Qora choy", 8, 0), ("Limon", 40, 10), ("Asal", 20, 0)],
    "Kompot (1 l)": [("Quritilgan meva", 150, 0), ("Shakar", 60, 0)],
    "Ayron": [("Suzma", 120, 0), ("Tuz", 2, 0)],
    "Coca-Cola 0,5": [("Coca-Cola 0,5", 1, 0)],
    "Suv 0,5": [("Suv 0,5", 1, 0)],
}

# xodimlar: vazifalar demosi ro'yxati (+ zal va oshxona uchun qo'shimchalar)
EXTRA_STAFF = [("+998901110011", "Bobur Rahmonov", "waiter"), ("+998901110012", "Shahzoda Umarova", "waiter"),
               ("+998901110013", "Otabek Nurmatov", "waiter"), ("+998901110014", "Ravshan Hakimov", "cook"),
               ("+998901110015", "Farhod Tursunov", "cook"), ("+998901110016", "Elyor Qosimov", "courier")]

# Taom rasmlari — Wikimedia Commons (erkin litsenziya: CC BY-SA / CC BY / PD; muallif — fayl sahifasida).
# Rasm bazaga yuklanmaydi, havola saqlanadi; havola ochilmasa kassa va sayt bosh harfni ko'rsatadi.
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width=640"
PHOTOS = {
    "To'y oshi": "Plov_Tashkent.jpg",
    "Choyxona oshi": "Uzbek_palov_in_Yerevan_Food_Court.jpg",
    "Samarqand oshi": "Samarkand_Zigir-pilaf.jpg",
    "Qazili osh": "Plov_Tashkent.jpg",
    "Sho'rva": "Shorpo.jpg",
    "Mastava": "Мастава.jpg",
    "Chuchvara sho'rva": "Chuchvara.jpg",
    "Mosh xo'rda": "Мастава.jpg",
    "Qovurma lag'mon": "Лагман.jpg",
    "Suyuq lag'mon": "Uyghur_Lagman.jpg",
    "Manti (5 dona)": "Uzbek_Manti_(bright).jpg",
    "Dimlama": "Dimlama_(16425713838).jpg",
    "Qozon kabob": "Qozon_kabob_(Uzbek_national_cuisine).jpg",
    "Norin": "Naryn_tashkent_2024.jpg",
    "Qo'y go'shti kabob": "Barbecued_lamb_sticks.jpg",
    "Mol go'shti kabob": "Shashlik.jpg",
    "Jigar kabob": "Shashlik.jpg",
    "Lula kabob": "Lula_kebab.jpg",
    "Tovuq kabob": "Shashlik.jpg",
    "Tandir somsa": "Ouzbékistan-Samsas.jpg",
    "Qovoqli somsa": "Самса.jpg",
    "Obi non": "Samarqand_noni.jpg",
    "Patir non": "Патир-нон-02.jpg",
    "Achchiq-chuchuk": "سالاد_شیرازی.jpg",
    "Suzma ko'katlar bilan": "Turkish_strained_yogurt.jpg",
    "Olivye": "Салат_Оливье_03.jpg",
    "Ko'k salat": "سالاد_شیرازی.jpg",
    "Chak-chak": "Чак-чак.jpg",
    "Halvo": "Orient_sweets_(special_halva)_Samarkand,_Siyab.jpg",
    "Ko'k choy (choynak)": "Green_Tea.jpg",
    "Qora choy (choynak)": "Cup_of_black_tea.jpg",
    "Limonli choy": "Russiantea1.jpg",
    "Kompot (1 l)": "Peach_kompot.jpg",
    "Ayron": "Fresh_ayran.jpg",
    "Coca-Cola 0,5": "6_Coca-Cola_bottles.jpg",
    "Suv 0,5": "PET_Bottle_Water.jpg",
}

# O'qitish videolari (YouTube, ochiq): dars nomi → havola
VIDEOS = {
    "Zirvak": "https://www.youtube.com/watch?v=nPCynUmy-uA",
    "Guruch solish va damlash": "https://www.youtube.com/watch?v=CEXa3aEiTJU",
    "Forma va tashqi ko'rinish": "https://www.youtube.com/watch?v=FOM3SUFY030",
    "Mahsulotlarni saqlash": "https://www.youtube.com/watch?v=wxFj4_TBjeg",
    "Kutib olish": "https://www.youtube.com/watch?v=jBe8e69ypcc",
    "Shikoyat bilan ishlash": "https://www.youtube.com/watch?v=zrnL0FUYz4M",
    "Pichoq bilan xavfsiz ishlash": "https://www.youtube.com/watch?v=oLTaMPjAgLo",
    "O't o'chirgich (PASS usuli)": "https://www.youtube.com/watch?v=heVKavoFhKA",
}
LESSON_LINKS = {
    "Qo'lni to'g'ri yuvish": [("JSST: qo'l yuvish plakati (PDF)", "https://www.who.int/docs/default-source/patient-safety/how-to-handwash-poster.pdf")],
}
SAFETY_COURSE = {
    "title": "Oshxona xavfsizligi", "category": "Xavfsizlik", "roles": ["cook", "manager"], "due_days": 14,
    "description": "Pichoq, olov va issiq idish bilan xavfsiz ishlash — jarohatsiz smena.",
    "lessons": [
        ("Pichoq bilan xavfsiz ishlash", "Pichoq o'tkir bo'lsin, taxta sirpanmasin (ostiga nam sochiq), barmoqlar «mushuk panjasi» holatida.",
         ["O'tkir pichoq — xavfsizroq", "Taxta ostida nam sochiq", "«Mushuk panjasi»"]),
        ("O't o'chirgich (PASS usuli)", "P — chekani torting, A — shlangni olov tagiga qarating, S — bosing, S — u yoqdan-bu yoqqa suring. Yog' yonsa — suv sepilmaydi!",
         ["PASS", "Yog'ga suv sepilmaydi", "O't o'chirgich joyi — eshik yonida"]),
    ],
    "quiz": ("Xavfsizlik testi", 120, [
        ("Qozondagi yog' yonib ketsa nima qilinadi?", ["Suv sepiladi", "Qopqoq yopiladi / o't o'chirgich", "Qochiladi", "Pufiladi"], 1, "Yog'ga suv — portlashga olib keladi."),
        ("PASS da birinchi harakat?", ["Bosish", "Chekani tortish", "Surish", "Qaratish"], 1, "Avval chekani torting."),
        ("Qaysi pichoq xavfsizroq?", ["O'tmas", "O'tkir", "Farqi yo'q", "Plastik"], 1, "O'tmas pichoq sirpanadi — jarohat ko'proq."),
    ]),
}

OSH_COURSE = {
    "title": "Osh tayyorlash standarti", "category": "Oshxona", "roles": ["cook", "manager"], "due_days": 7,
    "description": "Zirvakdan damlashgacha — har qozon bir xil ta'm, rang va porsiyada bo'lishi uchun.",
    "lessons": [
        ("Mahsulot tanlash va tayyorlash", "Devzira guruch 1 soat oldin ivitiladi, sabzi somoncha to'g'raladi (3–4 mm), go'sht 50–60 g bo'laklarga bo'linadi.",
         ["Guruch — 1 soat ivitish", "Sabzi — somoncha 3–4 mm", "Go'sht — 50–60 g bo'lak"]),
        ("Zirvak", "Yog' tutun chiqquncha qizdiriladi, piyoz tillarang bo'lguncha, keyin go'sht va sabzi. Zirvak 40 daqiqa qaynaydi.",
         ["Yog' harorati", "Piyoz — tillarang", "Zirvak — 40 daqiqa"]),
        ("Guruch solish va damlash", "Guruch tekis yoyiladi, suv 1,5 barmoq ustida. Suv singgach — tepasi to'planadi, 25 daqiqa dam.",
         ["Suv — 1,5 barmoq", "Olov pasaytiriladi", "Dam — 25 daqiqa"]),
        ("Porsiya va berish", "Porsiya: 150 g guruch, 90 g go'sht, sabzi ustida. Lagan issiq bo'lishi shart, achchiq-chuchuk bilan.",
         ["Tarozida porsiya", "Issiq lagan", "Salat bilan"]),
    ],
    "quiz": ("Osh standarti — yakuniy test", 240, [
        ("Devzira guruch necha vaqt ivitiladi?", ["10 daqiqa", "1 soat", "1 kun", "Ivitilmaydi"], 1, "1 soat — guruch bir tekis pishadi."),
        ("Zirvak necha daqiqa qaynaydi?", ["5", "15", "40", "90"], 2, "40 daqiqa — go'sht yumshaydi, sabzi shirasini beradi."),
        ("Suv guruch ustida qancha bo'ladi?", ["Guruch bilan barobar", "1,5 barmoq", "5 barmoq", "Suv qo'yilmaydi"], 1, "1,5 barmoq — ortiqcha bo'lsa osh bo'tqa bo'ladi."),
        ("Bir porsiyada qancha go'sht bo'ladi?", ["30 g", "90 g", "200 g", "Ko'z bilan"], 1, "Standart — 90 g, tarozida."),
        ("Osh qanday idishda beriladi?", ["Sovuq likopchada", "Issiq laganda", "Qog'ozda", "Farqi yo'q"], 1, "Issiq lagan — osh sovib qolmaydi."),
    ]),
}


# ------------------------------------------------------------------ yordamchilar
def _tenant_exists():
    from public.models import Tenant
    return Tenant.objects.filter(slug=SLUG).first()


def drop() -> bool:
    """Namuna restoranni butunlay o'chiradi (sxema bilan). Faqat shu namunaga tegadi."""
    from public.models import Domain, Tenant
    t = Tenant.objects.filter(slug=SLUG).first()
    if t is None:
        return False
    schema = t.schema_name
    Domain.objects.filter(tenant=t).delete()
    Tenant.objects.filter(pk=t.pk).delete()
    with connection.cursor() as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return True


def build(domain: str = "namuna.localhost", log=print):
    from public.services import create_tenant, set_modules
    if _tenant_exists():
        raise RuntimeError("Namuna restoran allaqachon bor. Qaytadan yaratish uchun: --reset")
    t = create_tenant(name=NAME, slug=SLUG, owner_phone=OWNER_PHONE, preset="restaurant", owner_name="Bahodir Qodirov",
                      plan_code="pro", domain=domain, branch_name="Chilonzor filiali", trial_days=30)
    set_modules(t, [*t.enabled_modules, "training", "crm"])
    log(f"Restoran yaratildi: {t.name} ({domain})")
    with schema_context(t.schema_name):
        connection.set_tenant(t)
        _staff(t, log)
        _menu(t, log)
        _inventory(t, log)
        _operations(t, log)
        _training(t, log)
        _crm_and_telegram(t, log)
        _site(t, log)
        _kitchen_now(t, log)
    connection.set_schema_to_public()
    return t


def _staff(t, log):
    from core.models import Membership, Role, User
    from modules.tasks.demo import STAFF
    roles = {r.code: r for r in Role.objects.all()}
    for phone, name in EXTRA_OWNERS:
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        Membership.objects.get_or_create(user=u, role=roles["owner"])
    n = 0
    for phone, name, code in [*STAFF, *EXTRA_STAFF]:
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        Membership.objects.get_or_create(user=u, role=roles[code])
        n += 1
    log(f"Xodimlar: {n}")


def _menu(t, log):
    from modules.catalog import services as cat_services
    from modules.catalog.models import Category, Modifier, ModifierGroup, Product
    cats = {}
    for i, (uz, ru, en) in enumerate(CATS):
        cats[uz] = Category.objects.create(name={"uz": uz, "ru": ru, "en": en}, sort_order=i)
    groups = {}
    g = ModifierGroup.objects.create(name={"uz": "Porsiya", "ru": "Порция", "en": "Portion"}, min_select=1, max_select=1)
    for j, (n, ru, p) in enumerate([("To'liq", "Полная", 0), ("Yarim", "Половина", -12000), ("Katta (1,5)", "Большая", 18000)]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": ru, "en": n}, price=p, is_default=(j == 0), sort_order=j)
    groups["porsiya"] = g
    g = ModifierGroup.objects.create(name={"uz": "Achchiqlik", "ru": "Острота", "en": "Spiciness"}, min_select=1, max_select=1)
    for j, n in enumerate(["Oddiy", "O'rtacha", "Achchiq"]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": n, "en": n}, price=0, is_default=(j == 0), sort_order=j)
    groups["achchiqlik"] = g
    g = ModifierGroup.objects.create(name={"uz": "Garnir", "ru": "Гарнир", "en": "Side"}, min_select=0, max_select=2)
    for j, (n, ru, p) in enumerate([("Marinadlangan piyoz", "Маринованный лук", 0), ("Non", "Лепёшка", 5000), ("Achchiq sous", "Острый соус", 3000)]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": ru, "en": n}, price=p, sort_order=j)
    groups["garnir"] = g
    for i, (cat, uz, ru, desc, price, w, kcal, tags, gcodes) in enumerate(MENU):
        p = Product.objects.create(category=cats[cat], name={"uz": uz, "ru": ru, "en": uz}, description={"uz": desc, "ru": desc, "en": desc},
                                   price=price, weight_g=w, kcal=kcal, tags=tags, sort_order=i)
        p.modifier_groups.set([groups[c] for c in gcodes])
        if uz in PHOTOS:
            Product.objects.filter(pk=p.pk).update(image_url=COMMONS.format(PHOTOS[uz]),
                                                   custom_data={"image_credit": "Wikimedia Commons (erkin litsenziya)"})
    Product.objects.filter(name__uz="Norin").update(in_stop_list=True)      # stop-list namunasi
    cat_services.publish(by="namuna", note="Boshlang'ich taomnoma", tenant=t)
    log(f"Taomnoma: {len(MENU)} taom, {len(CATS)} bo'lim")


def _inventory(t, log):
    from modules.catalog.models import Product
    from modules.inventory.models import Ingredient, Recipe, RecipeLine, Supplier
    from modules.inventory.services import create_purchase, recompute_all
    sups = {k: Supplier.objects.create(name=n, phone=ph) for k, n, ph in [
        ("go'sht", "Go'sht ulgurji (Chorsu bozori)", "+998901230001"), ("don", "Guruch va un ulgurji savdo", "+998901230002"),
        ("sabzavot", "Sabzavot va ko'kat (Parkent bozori)", "+998901230003"), ("ichimlik", "Ichimliklar distribyutori", "+998901230004")]}
    sup_of = {"Go'sht": "go'sht", "Don": "don", "Quruq": "don", "Choy": "don", "Yog'": "don", "Ichimlik": "ichimlik", "Non": "sabzavot"}
    ings = {}
    for name, cat, unit, price, mn, _ in ING:
        ings[name] = Ingredient.objects.create(name={"uz": name, "ru": name, "en": name}, category=cat, unit=unit, price=0,
                                               min_stock=mn, supplier=sups[sup_of.get(cat, "sabzavot")])
    today = timezone.localdate()
    # 4 hafta kirimlari: har hafta bozorlik, narxlar biroz o'zgaradi (tarix grafik bo'sh bo'lmasin)
    rnd = random.Random(21)
    for wk in (21, 14, 7, 0):
        for key, sup in sups.items():
            lines = [{"ingredient_id": ings[n].pk, "qty": round(q / 4 if wk else q, 2),
                      "unit_price": int(price * (1 + rnd.uniform(-0.06, 0.06)))}
                     for n, cat, unit, price, mn, q in ING if sup_of.get(cat, "sabzavot") == key]
            if lines:
                create_purchase(lines=lines, supplier=sup, date=today - timedelta(days=wk), note=f"Haftalik bozorlik ({sup.name})", tenant=t)
    # kam qolgan xomashyo (ogohlantirish namunasi)
    for n, left in [("Qazi", Decimal("1.2")), ("Limon", Decimal("0.4")), ("Mayonez", Decimal("1.0"))]:
        Ingredient.objects.filter(pk=ings[n].pk).update(stock=left)
    for pname, lines in RECIPES.items():
        p = Product.objects.get(name__uz=pname)
        r = Recipe.objects.create(product=p)
        for i, (iname, qty, waste) in enumerate(lines):
            RecipeLine.objects.create(recipe=r, ingredient=ings[iname], qty=Decimal(qty), waste_percent=Decimal(waste), sort_order=i)
    recompute_all(t)
    log(f"Ombor: {len(ING)} xomashyo, {len(RECIPES)} tex-karta, 4 hafta kirim")


def _operations(t, log):
    from modules.hr.demo import seed_demo_hr
    from modules.pos.demo import seed_demo_orders
    from modules.pos.models import Order, OrderStatus
    from modules.reservations.demo import seed_demo_reservations
    from modules.tables.demo import seed_demo_tables
    from modules.tasks.demo import seed_demo_tasks
    tasks = seed_demo_tasks()
    pop = {"To'y oshi": 6, "Choyxona oshi": 4, "Samarqand oshi": 3, "Qazili osh": 2, "Qo'y go'shti kabob": 4, "Mol go'shti kabob": 3,
           "Lula kabob": 2, "Tandir somsa": 4, "Obi non": 5, "Ko'k choy (choynak)": 5, "Qora choy (choynak)": 3, "Achchiq-chuchuk": 3,
           "Qovurma lag'mon": 3, "Sho'rva": 2, "Manti (5 dona)": 2, "Coca-Cola 0,5": 2, "Qozon kabob": 1.5}
    orders = seed_demo_orders(days=65, per_day=(100, 135), weights=pop)
    _branches(t)
    # zalda o'tirganlarga stol raqami — hisobot va stol tarixi haqiqiy ko'rinsin
    rnd = random.Random(5)
    for o in Order.objects.filter(type="dine_in", status=OrderStatus.PAID).only("id")[:4000]:
        Order.objects.filter(pk=o.pk).update(table_no=str(rnd.randint(1, 10)))
    hr = seed_demo_hr()
    _payroll_rates()
    from core.models import Membership
    from modules.hr.demo import seed_demo_recruit_people
    own = Membership.objects.filter(role__code="owner").select_related("user").first()
    rec = seed_demo_recruit_people(own.user if own else None)
    log(f"HR: vakansiya {rec.get('vacancies', 0)} · nomzod {rec.get('applications', 0)} · profil {rec.get('profiles', 0)}")
    _payroll_history()
    exp = _expenses()
    tables = seed_demo_tables()
    res = seed_demo_reservations()
    log(f"Kassa: {orders} chek (65 kun) · vazifalar: {tasks} · xodim kartalari: {hr} · chiqimlar: {exp} · stollar: {tables} · bronlar: {res}")


def _branches(t):
    """3 ta filial: savdo 50 / 30 / 20 % — filiallar jadvali va filial tanlagichi bo'sh turmasin. ~1,2% chek bekor qilingan."""
    from core.models import Branch
    from modules.pos.models import CashShift, Order, OrderStatus
    main = Branch.objects.filter(deleted_at__isnull=True).first()
    b2 = Branch.objects.create(name="Yunusobod filiali", address="Toshkent sh., Yunusobod tumani, 4-kvartal (namuna)", phone="+998712000001", sort_order=1)
    b3 = Branch.objects.create(name="Sergeli filiali", address="Toshkent sh., Sergeli tumani, 7-kvartal (namuna)", phone="+998712000002", sort_order=2)
    rnd = random.Random(17)
    ids = list(Order.objects.values_list("id", flat=True))
    to2, to3, cancel = [], [], []
    for i in ids:
        x = rnd.random()
        (to2 if x < 0.30 else to3 if x < 0.50 else []).append(i)
        if rnd.random() < 0.012:
            cancel.append(i)
    Order.objects.filter(pk__in=to2).update(branch=b2)
    Order.objects.filter(pk__in=to3).update(branch=b3)
    Order.objects.filter(pk__in=cancel, status=OrderStatus.PAID).update(
        status=OrderStatus.CANCELLED, cancel_reason="Mijoz bekor qildi", cancelled_at=F("paid_at"), paid_at=None)
    CashShift.objects.filter(branch__isnull=True).update(branch=main)
    return [main, b2, b3]


def _payroll_history():
    """O'tgan 2 oy oyliklari (to'langan) — mehnat xarajati va oylik tarixi taqqoslansin."""
    from modules.hr.models import Employee, PayrollStatus, Payslip
    first = timezone.localdate().replace(day=1)
    rnd = random.Random(4)
    for k in (1, 2):
        per = first
        for _ in range(k):
            per = (per - timedelta(days=1)).replace(day=1)
        for e in Employee.objects.all():
            s = Payslip(employee=e, period=per, salary_type=e.salary_type, rate=e.rate, hours=rnd.choice([168, 176, 184]),
                        shifts=rnd.choice([24, 26, 27]), bonus=rnd.choice([0, 0, 200_000, 400_000]), penalty=rnd.choice([0, 0, 0, 50_000]),
                        status=PayrollStatus.PAID, paid_at=timezone.now() - timedelta(days=30 * k - 5))
            s.compute()
            s.save()


def _expenses() -> int:
    """O'rta restoran (120 o'rin) oylik xarajatlari, 2026: ijara ~30 mln, kommunal ~7 mln, aylanmadan soliq 4%…"""
    from django.db.models import Sum

    from modules.finance.models import Expense, ExpenseCategory, ensure_categories
    from modules.pos.models import Order
    ensure_categories()
    cats = {c.code: c for c in ExpenseCategory.objects.all()}
    today = timezone.localdate()
    rnd = random.Random(13)
    n = 0
    first = today.replace(day=1)
    months = [first]
    for _ in range(2):
        months.insert(0, (months[0] - timedelta(days=1)).replace(day=1))
    for m in months:
        nxt = (m + timedelta(days=32)).replace(day=1)
        rev = Order.objects.filter(status="paid", paid_at__date__gte=m, paid_at__date__lt=nxt).aggregate(s=Sum("total"))["s"] or 0
        rows = [("rent", 30_000_000, 3, "Ijara (oylik)"), ("utilities", rnd.randint(6_500_000, 8_000_000), 10, "Svet, gaz, suv"),
                ("tax", int(rev * 0.04), 15, "Aylanmadan soliq 4%"), ("software", 490_000, 2, "RestoPOS obuna"),
                ("marketing", 2_500_000, 5, "Instagram va Telegram reklama"), ("packaging", 1_400_000, 8, "Olib ketish idishlari"),
                ("repair", rnd.choice([450_000, 900_000, 1_200_000]), 18, "Tandir va qozon ta'miri"),
                ("delivery", rnd.randint(1_800_000, 2_600_000), 25, "Kuryer yoqilg'isi / Yandex"), ("other", 700_000, 20, "Xo'jalik mollari")]
        for code, amount, day, note in rows:
            d = m + timedelta(days=day - 1)
            if d <= today and code in cats and amount:
                Expense.objects.create(date=d, category=cats[code], amount=amount, note=note)
                n += 1
    return n


def _payroll_rates():
    """Toshkent o'rta restorani 2026: menejer ~5 mln, oshpaz ~4,5 mln, ofitsiant soatbay + chaychaqa, kassir smenabay."""
    from modules.hr.models import Employee, Payslip, Position
    rates = {"Menejer": 5_000_000, "Oshpaz": 4_500_000, "Kassir": 150_000, "Ofitsiant": 16_000, "Buxgalter": 3_500_000, "Marketolog": 3_000_000}
    for name, r in rates.items():
        Position.objects.filter(name=name).update(default_rate=r)
        Employee.objects.filter(position__name=name).update(rate=r)
    for s in Payslip.objects.select_related("employee"):
        s.rate = s.employee.rate
        s.compute()
        s.save()


def _training(t, log):
    from modules.training.demo import COURSES, seed_demo_training
    n = seed_demo_training(courses=[OSH_COURSE, COURSES[1], COURSES[2], SAFETY_COURSE],
                           cook_task=("Oshni standart bo'yicha damlang", "Bitta qozon oshni darsdagi tartibda damlab, laganda porsiya rasmini yuboring."))
    from modules.training.models import Lesson, LessonFile
    for title, url in VIDEOS.items():
        Lesson.objects.filter(title=title, video_url="").update(video_url=url)
    for title, links in LESSON_LINKS.items():
        for les in Lesson.objects.filter(title=title):
            for lt, url in links:
                LessonFile.objects.create(lesson=les, title=lt, url=url)
    vids = Lesson.objects.exclude(video_url="").count()
    log(f"O'qitish: {n} kurs, {vids} ta video dars, testlar, standartlar, topshiriqlar")


def _crm_and_telegram(t, log):
    from modules.crm.demo import seed_demo_crm
    from modules.crm.models import Customer, Promo
    from modules.pos.models import Order
    from modules.telegram.models import Audience, BotUser, Broadcast, BroadcastStatus
    n = seed_demo_crm(t)
    Promo.objects.filter(code="LAZZAT10").update(name="NAVROZ10 promokod", code="NAVROZ10", description="Instagram va Telegram kanal obunachilari uchun")
    Promo.objects.filter(name__startswith="Happy hour").update(name="Tushlik vaqti −15%", description="Har kuni 12:00–15:00 butun menyuga", hour_from=12, hour_to=15)
    rnd = random.Random(9)
    now = timezone.now()
    tg = list(Customer.objects.filter(source="telegram")) + list(Customer.objects.exclude(source="telegram").order_by("?")[:12])
    for i, c in enumerate(tg):
        BotUser.objects.create(chat_id=700_000_000 + i, phone=c.phone, full_name=c.name, username="",
                               orders_count=0, spent_total=0, last_seen_at=now - timedelta(days=rnd.randint(0, 20)))
    for i in range(14):                                  # telefon ulashmagan obunachilar ham bo'ladi
        BotUser.objects.create(chat_id=710_000_000 + i, full_name=rnd.choice(["Aziz", "Madina", "Sherzod", "Laylo", "Temur", "Kamola"]),
                               last_seen_at=now - timedelta(days=rnd.randint(0, 30)), is_blocked=(i % 7 == 0))
    # mijoz buyurtmalarining bir qismi Telegram Mini App'dan kelgan
    phones = [c.phone for c in tg]
    ids = list(Order.objects.filter(customer_phone__in=phones, status="paid").values_list("id", flat=True))
    rnd.shuffle(ids)
    Order.objects.filter(pk__in=ids[: len(ids) // 3]).update(source="telegram", type="delivery")
    for bu in BotUser.objects.exclude(phone=""):
        qs = Order.objects.filter(customer_phone=bu.phone, status="paid", source="telegram")
        BotUser.objects.filter(pk=bu.pk).update(orders_count=qs.count(), spent_total=sum(qs.values_list("total", flat=True)))
    total = BotUser.objects.filter(is_blocked=False).count()
    for text, days, aud in [("🌷 Navro'z bayrami munosabati bilan butun menyuga −15%! 21–23-mart. Bron: botda «Stol bron qilish»", 12, Audience.ALL),
                            ("🆕 Yangi taom: Qazili osh — uy qazisi va bedana tuxumi bilan. Tatib ko'ring!", 5, Audience.ALL)]:
        Broadcast.objects.create(text=text, audience=aud, status=BroadcastStatus.SENT, total=total, sent=total - 2, failed=2,
                                 sent_at=now - timedelta(days=days))
    Broadcast.objects.create(text="Sizni sog'indik! Shu hafta NAVROZ10 promokodi bilan −10% 🙂", audience=Audience.BUYERS)
    tcfg = {"welcome_text": "Assalomu alaykum! «Navro'z» — milliy taomlar. Menyu, yetkazib berish va stol bron — shu yerda 👇",
            "delivery_fee": 15000, "free_delivery_from": 150000, "min_order": 50000, "allow_dine_in": True}
    mods = dict((t.settings or {}).get("modules") or {})
    mods["telegram"] = {**(mods.get("telegram") or {}), **tcfg}
    mods["crm"] = {**(mods.get("crm") or {}), "welcome_bonus": 10000, "birthday_bonus": 50000}
    t.settings = {**(t.settings or {}), "modules": mods}
    t.save(update_fields=["settings"])
    log(f"Mijozlar: {n} · Telegram obunachilar: {BotUser.objects.count()} · xabarlar: {Broadcast.objects.count()}")


def _site(t, log):
    from modules.cms.models import SiteSettings
    s = SiteSettings.get()
    s.title = NAME
    s.tagline = {"uz": "Toshkentning mazali oshi va kaboblari — 2016-yildan beri", "ru": "Вкусный плов и шашлык Ташкента — с 2016 года",
                 "en": "Tashkent's tasty plov and kebabs — since 2016"}
    s.phone = "+998712000000"
    s.address = "Toshkent sh., Chilonzor tumani, 9-kvartal (namuna manzil)"
    s.delivery = {"free_from": 150000, "fee": 15000, "eta_min": 35, "eta_max": 50}
    s.theme = {**(s.theme or {}), "primary": "#B5452B", "accent": "#1E6F5C", "bg": "#FBF6EE", "ink": "#23170F"}
    s.save()
    from core.models import Branch
    from modules.cms.models import SiteSection
    Branch.objects.update(address="Toshkent sh., Chilonzor tumani, 9-kvartal (namuna)", phone="+998712000000")
    for sec in SiteSection.objects.all():
        if sec.type == "hero":
            sec.props = {**sec.props, "title": "Toshkentning haqiqiy oshi va kaboblari",
                         "subtitle": "Qozon oshi, tandir somsa va kaboblar — zalda, olib ketish yoki 35–50 daqiqada yetkazib berish",
                         "cta": "Buyurtma berish"}
        elif sec.type == "bonus":
            sec.props = {**sec.props, "percent": 3}
        sec.save()
    log("Sayt: sarlavha, aloqa, yetkazib berish, rang, filial manzili")


def _kitchen_now(t, log):
    """Hozir oshxonada tayyorlanayotgan 4 ta buyurtma — oshxona ekrani va kassa «ochiq» holati bo'sh turmasin."""
    from core.events import emit
    from core.models import User
    from modules.catalog.models import Product
    from modules.pos.models import CashShift, Order, OrderItem
    shift = CashShift.objects.filter(closed_at__isnull=True).first()
    cashier = User.objects.filter(memberships__role__code="cashier").first()
    rnd = random.Random(3)
    prods = list(Product.objects.filter(in_stop_list=False))
    from modules.kds.models import Ticket, TicketStatus
    plan = [("dine_in", "4", "new"), ("dine_in", "VIP-1", "cooking"), ("takeaway", "", "new"), ("delivery", "", "cooking"),
            ("dine_in", "7", "ready"), ("dine_in", "2", "cooking"), ("delivery", "", "ready"), ("takeaway", "", "new")]
    cooks = list(User.objects.filter(memberships__role__code="cook"))
    for k, (typ, table, kst) in enumerate(plan):
        o = Order.objects.create(shift=shift, branch=shift.branch if shift else None, cashier=cashier, type=typ, table_no=table, source="telegram" if typ == "delivery" else "pos",
                                 note="Piyozsiz" if k == 1 else "")
        for p in rnd.sample(prods, k=rnd.randint(2, 4)):
            OrderItem.objects.create(order=o, product=p, name=p.name["uz"], qty=rnd.randint(1, 3), price=p.price, cost=p.cost)
        o.recalc()
        o.save()
        emit("pos.order_created", {"order_id": o.pk, "number": o.number, "total": o.total, "_tenant": t}, tenant=t)
        started = timezone.now() - timedelta(minutes=rnd.randint(4, 14))
        upd = {"status": kst}
        if kst in (TicketStatus.COOKING, TicketStatus.READY):
            upd.update(started_at=started, cook=rnd.choice(cooks) if cooks else None)
        if kst == TicketStatus.READY:
            upd["ready_at"] = started + timedelta(minutes=rnd.randint(6, 11))
        Ticket.objects.filter(order=o).update(**upd)
        Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - timedelta(minutes=(8 - k) * 3))
    log("Oshxona ekrani: 8 ta faol buyurtma (yangi / tayyorlanmoqda / tayyor)")
'@

Put 'backend\tests\test_hr_people.py' @'
"""
HR (2-qism): vakansiya → saytdan / Telegramdan ariza (majburiy savol) → bosqichlar (suhbat vaqti majburiy) →
qabul (xodim kartasi + ish tarixi) → profil, hujjat, baho → KPI reytingi va bonus → smenadan keyingi kayfiyat.
"""
import json
import os
from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


@pytest.fixture
def hr(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "hr", "telegram", "pos", "training", "tasks"}))
    with schema_context("lazzat"):
        from modules.hr.models import Application, Vacancy
        Application.objects.all().delete()
        Vacancy.objects.all().delete()
    yield


def _vac(api, **kw):
    body = {"title": "Ofitsiant", "role_code": "waiter", "salary_from": 3_000_000, "salary_to": 4_500_000, "schedule": "2/2, 10:00–23:00",
            "requirements": ["18 yoshdan katta", "Rus tilini bilish — afzallik"], "duties": ["Mehmonni kutib olish"], "benefits": ["Bepul tushlik"],
            "video_url": "https://www.youtube.com/watch?v=jBe8e69ypcc", "status": "open",
            "questions": [{"text": "Kechki smenada ishlay olasizmi?", "type": "yesno", "must": "ha"}, {"text": "Qachon ishga chiqa olasiz?", "type": "text"}]}
    body.update(kw)
    r = api.post("/api/v1/hr/vacancies", body)
    assert r.status_code == 200, r.content
    return r.json()


@pytest.mark.django_db
def test_vacancy_public_pages_and_site_application(api, client, hr):
    v = _vac(api)
    assert v["salary_text"].startswith("3 000 000 – 4 500 000") and v["is_open"]
    draft = _vac(api, title="Yashirin", status="draft")
    lst = client.get("/vacancies/", **H)
    assert lst.status_code == 200 and "Ofitsiant" in lst.content.decode() and "Yashirin" not in lst.content.decode()
    page = client.get(f"/vacancies/{v['id']}/", **H)
    assert page.status_code == 200 and "youtube.com/embed/jBe8e69ypcc" in page.content.decode()
    assert client.get(f"/vacancies/{draft['id']}/", **H).status_code == 200            # yopiq — «yopilgan» xabari
    r = client.post(f"/vacancies/{v['id']}/", {"full_name": "Bobur Aliyev", "phone": "90 123 45 67", "birth_year": "2001",
                                               "q0": "Yo'q", "q1": "Dushanbadan", "prev_company": "Rayhon", "prev_position": "ofitsiant"}, **H)
    assert r.status_code == 200 and "qabul qilindi" in r.content.decode()
    apps = api.get("/api/v1/hr/applications").json()
    assert len(apps) == 1 and apps[0]["phone"] == "+998901234567"
    a = api.get(f"/api/v1/hr/applications/{apps[0]['id']}").json()
    assert a["knocked_out"] is True and a["answers"][0]["ok"] is False and a["work_history"][0]["company"] == "Rayhon"
    # takror ariza — ikkinchi karta ochilmaydi
    client.post(f"/vacancies/{v['id']}/", {"full_name": "Bobur Aliyev", "phone": "+998901234567", "q0": "Ha"}, **H)
    assert len(api.get("/api/v1/hr/applications").json()) == 1


@pytest.mark.django_db
def test_telegram_application_flow(client, api, hr):
    v = _vac(api)

    def hook(text=None, contact=None):
        m = {"message_id": 1, "chat": {"id": 7700, "type": "private"}, "from": {"id": 7700, "first_name": "Laylo", "username": "laylo_uz"}}
        if text is not None:
            m["text"] = text
        if contact:
            m["contact"] = contact
        return client.post("/api/v1/telegram/webhook", data=json.dumps({"update_id": 1, "message": m}), content_type="application/json",
                           HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    for step in [f"/start job_{v['id']}", "Laylo Karimova"]:
        assert hook(step).status_code == 200
    hook(contact={"phone_number": "998935550077", "user_id": 7700})
    for step in ["1998", "Ha", "Ertaga", "Kafe'da 1 yil ishlaganman", "«Oqtepa», kassir, 1 yil", "✅ Arizani yuborish"]:
        hook(step)
    with schema_context("lazzat"):
        from modules.hr.models import Application
        a = Application.objects.get(phone="+998935550077")
        assert a.source == "telegram" and a.tg_chat_id == 7700 and a.birth_year == 1998 and not a.knocked_out
        assert a.answers[1]["a"] == "Ertaga" and a.work_history[0]["company"].startswith("«Oqtepa»")


@pytest.mark.django_db
def test_stages_and_hire_creates_employee(api, hr):
    v = _vac(api)
    a = api.post("/api/v1/hr/applications", {"vacancy_id": v["id"], "full_name": "Sardor Nazarov", "phone": "+998935550088", "birth_year": 1997,
                                             "work_history": [{"company": "Evos", "position": "kassir", "years": "2021–2023"}]}).json()
    assert api.post(f"/api/v1/hr/applications/{a['id']}/stage", {"stage": "interview"}).status_code == 400      # vaqt majburiy
    at = (timezone.now() + timedelta(days=1)).isoformat()
    r = api.post(f"/api/v1/hr/applications/{a['id']}/stage", {"stage": "interview", "interview_at": at, "place": "Chilonzor filiali"})
    assert r.status_code == 200 and r.json()["stage"] == "interview"
    assert api.post(f"/api/v1/hr/applications/{a['id']}/stage", {"stage": "rejected"}).status_code == 400       # sabab majburiy
    h = api.post(f"/api/v1/hr/applications/{a['id']}/hire", {"rate": 3_500_000})
    assert h.status_code == 200, h.content
    eid = h.json()["employee_id"]
    p = api.get(f"/api/v1/hr/employees/{eid}/profile").json()
    assert p["employee"]["role_code"] == "waiter" and p["employee"]["rate"] == 3_500_000
    assert p["work_history"][0]["company"] == "Evos" and p["application"]["vacancy"] == "Ofitsiant" and p["profile"]["source"] == "vakansiya"
    assert api.post(f"/api/v1/hr/applications/{a['id']}/hire", {}).status_code == 400                           # ikki marta emas


@pytest.mark.django_db
def test_profile_documents_review_and_kpi(api, hr):
    e = api.post("/api/v1/hr/employees", {"full_name": "KPI Kassir", "phone": "+998935550099", "role_code": "cashier", "salary_type": "monthly", "rate": 4_000_000}).json()
    soon = (timezone.localdate() + timedelta(days=10)).isoformat()
    r = api.put(f"/api/v1/hr/employees/{e['id']}/profile", {"birth_date": "1995-05-20", "education": "Oshpazlik kolleji", "languages": ["o'zbek", "rus"],
                                                            "skills": ["kassa"], "medical_book_until": soon})
    assert r.status_code == 200 and r.json()["profile"]["medical_expiring"] is True and r.json()["profile"]["age"] >= 30
    assert api.post(f"/api/v1/hr/employees/{e['id']}/work-history", {"company": "Safia", "position": "kassir", "start": "2020", "end": "2023"}).status_code == 200
    d = api.post(f"/api/v1/hr/employees/{e['id']}/documents?title=Shartnoma&kind=contract&url=https://drive.google.com/file/d/abc/view")
    assert d.status_code == 200 and d.json()["kind_label"] == "Mehnat shartnomasi"
    assert api.post(f"/api/v1/hr/employees/{e['id']}/documents?title=x").status_code == 400
    assert api.post(f"/api/v1/hr/employees/{e['id']}/reviews", {"scores": {"discipline": 5}}).status_code == 400     # kamida 3 mezon
    rv = api.post(f"/api/v1/hr/employees/{e['id']}/reviews", {"scores": {"discipline": 5, "quality": 4, "speed": 4, "service": 5}, "goals": "O'rtacha chekni oshirish"})
    assert rv.status_code == 200 and rv.json()["average"] == 4.5
    # davomat: 2 smena reja, 2 marta keldi (biri kechikib)
    with schema_context("lazzat"):
        from modules.hr.models import Attendance, Employee, ShiftPlan
        emp = Employee.objects.get(pk=e["id"])
        today = timezone.localdate()
        for k, late in ((1, 0), (2, 25)):
            d0 = today - timedelta(days=k) if today.day > 2 else today
            ShiftPlan.objects.get_or_create(employee=emp, date=d0, start="09:00", defaults={"end": "18:00"})
            Attendance.objects.create(employee=emp, check_in=timezone.now() - timedelta(days=k if today.day > 2 else 0, hours=1), late_minutes=late)
    board = api.get("/api/v1/hr/kpi").json()
    row = next(x for x in board["rows"] if x["employee_id"] == e["id"])
    assert row["score"] is not None and row["grade"] in "ABCD" and "review" in row["parts"] and "punctuality" in row["parts"]
    assert row["parts"]["review"]["value"] == 88                                                             # (4.5−1)/4
    api.post("/api/v1/hr/payroll/compute")
    res = api.post("/api/v1/hr/kpi/apply-bonus", {"employee_ids": [e["id"]]}).json()
    assert res["updated"] in (0, 1)


@pytest.mark.django_db
def test_shift_mood_callback(client, api, hr):
    e = api.post("/api/v1/hr/employees", {"full_name": "Mood Oshpaz", "phone": "+998935550111", "role_code": "cook", "telegram_id": 8800}).json()
    with schema_context("lazzat"):
        from modules.hr.models import Attendance, ShiftFeedback
        a = Attendance.objects.create(employee_id=e["id"], check_out=timezone.now())
    cq = {"update_id": 5, "callback_query": {"id": "cb1", "data": f"mood:{a.pk}:2", "from": {"id": 8800}, "message": {"chat": {"id": 8800}}}}
    r = client.post("/api/v1/telegram/webhook", data=json.dumps(cq), content_type="application/json",
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    assert r.status_code == 200
    with schema_context("lazzat"):
        assert ShiftFeedback.objects.get(attendance=a).mood == 2
    # boshqa odam bu tugmani bosa olmaydi
    cq["callback_query"]["from"] = {"id": 9999}
    cq["callback_query"]["message"]["chat"]["id"] = 9999
    cq["callback_query"]["data"] = f"mood:{a.pk}:4"
    client.post("/api/v1/telegram/webhook", data=json.dumps(cq), content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    with schema_context("lazzat"):
        assert ShiftFeedback.objects.get(attendance=a).mood == 2


@pytest.mark.django_db
def test_demo_seed_and_admin_endpoints(api, client, hr):
    api.post("/api/v1/hr/employees", {"full_name": "Demo Ofitsiant", "phone": "+998935550222", "role_code": "waiter", "salary_type": "monthly", "rate": 4_000_000})
    with schema_context("lazzat"):
        from modules.hr.demo import seed_demo_hr, seed_demo_recruit_people
        seed_demo_hr()
        r = seed_demo_recruit_people()
    assert r["vacancies"] == 4 and r["applications"] >= 17, r
    vs = api.get("/api/v1/hr/vacancies").json()
    assert all(v["public_path"].startswith("/vacancies/") for v in vs) and sum(v["applications"] for v in vs) >= 17
    assert sum(1 for v in vs if v["is_open"]) == 3
    st = api.get("/api/v1/hr/recruit/stats").json()
    assert st["open"] == 3 and st["by_stage"]["rejected"] == 3
    board = api.get("/api/v1/hr/kpi").json()
    assert r["profiles"] >= 1 and board["summary"]["reviewed"] >= 1 and any(x["score"] is not None for x in board["rows"])
    eid = board["rows"][0]["employee_id"]
    p = api.get(f"/api/v1/hr/employees/{eid}/profile").json()
    assert p["work_history"] and p["documents"] and len(p["kpi_history"]) == 6
    page = client.get("/vacancies/", **H).content.decode()
    assert "Oshpaz yordamchisi" in page and "Kuryer" not in page
'@

Put 'backend\website\static\site.css' @'
/* RestoPOS — restoran sayti. 4 ekran sinfi: telefon ≤600, planshet 601–1024, kompyuter 1025–1920, TV ≥1921 / [data-density=tv].
   Tema ranglari inline <style> orqali :root ga tenant temasidan keladi (--primary, --accent, --bg, --ink). */

:root {
  --primary: #D9482B; --accent: #0F6E63; --bg: #FFF6EA; --ink: #1C1512;
  --surface: #FFFFFF; --muted: #6B5D55; --line: #EBD9C6; --tint: #F3E4D3; --ok: #1E7F4F;
  --radius: 16px; --gutter: 16px; --maxw: 1280px;
  --fs-body: clamp(15px, 1vw + 10px, 17px); --fs-h1: clamp(34px, 5vw, 68px); --fs-h2: clamp(26px, 3vw, 40px);
  --touch: 44px; --font: 'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif;
  color-scheme: light;
}
:root[data-theme="dark"] {
  --bg: #1A1412; --surface: #241D1A; --ink: #F5EDE4; --muted: #B3A398; --line: #3D322C; --tint: #332924;
  color-scheme: dark;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #1A1412; --surface: #241D1A; --ink: #F5EDE4; --muted: #B3A398; --line: #3D322C; --tint: #332924; color-scheme: dark; } }

*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; font-family: var(--font); font-size: var(--fs-body); line-height: 1.5; background: var(--bg); color: var(--ink); }
img { max-width: 100%; display: block; }
a { color: inherit; }
button, input, select { font: inherit; }
.container { width: 100%; max-width: var(--maxw); margin: 0 auto; padding: 0 var(--gutter); }
.h1 { font-size: var(--fs-h1); line-height: 1.02; font-weight: 800; letter-spacing: -0.03em; margin: 0; }
.h2 { font-size: var(--fs-h2); line-height: 1.1; font-weight: 800; letter-spacing: -0.02em; margin: 0; }
.muted { color: var(--muted); }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: var(--touch); padding: 10px 18px; border-radius: 999px; border: 0; background: var(--primary); color: #fff; font-weight: 700; text-decoration: none; cursor: pointer; }
.btn.secondary { background: var(--surface); color: var(--ink); border: 1px solid var(--line); }
.btn:focus-visible, a:focus-visible, button:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
.chip { display: inline-flex; align-items: center; padding: 6px 12px; border-radius: 999px; background: var(--tint); font-size: 0.85em; font-weight: 700; }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (min-width: 601px) { .grid { gap: 16px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); } }

/* ---- header */
.hdr { position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
.hdr .container { display: flex; align-items: center; gap: 16px; min-height: 64px; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 800; text-decoration: none; font-size: 1.15em; }
.brand .logo { width: 36px; height: 36px; border-radius: 10px; background: var(--primary); color: #fff; display: grid; place-items: center; font-weight: 800; }
.nav { display: none; gap: 20px; margin-left: auto; font-weight: 600; }
.nav a { text-decoration: none; padding: 8px 0; }
.jobs-n { display: inline-grid; place-items: center; min-width: 20px; height: 20px; padding: 0 6px; border-radius: 99px; background: var(--primary); color: #fff; font-size: 12px; font-weight: 800; margin-left: 4px; }
.lang { display: flex; gap: 2px; padding: 3px; background: var(--tint); border-radius: 999px; font-size: 0.8em; font-weight: 700; }
.lang a { padding: 5px 10px; border-radius: 999px; text-decoration: none; color: var(--muted); }
.lang a.on { background: var(--ink); color: var(--bg); }
.burger { margin-left: auto; width: var(--touch); height: var(--touch); border-radius: 12px; border: 1px solid var(--line); background: var(--surface); display: grid; place-items: center; }
.mnav { display: none; flex-direction: column; gap: 4px; padding: 8px 0 12px; }
.mnav.open { display: flex; }
.mnav a { padding: 12px; border-radius: 10px; text-decoration: none; font-weight: 600; background: var(--surface); }

/* ---- sections */
.section { padding: 40px 0; }
.hero { display: grid; gap: 24px; }
.hero-card { border-radius: 28px; background: var(--primary); color: #fff; padding: 28px; min-height: 240px; position: relative; overflow: hidden; display: flex; align-items: flex-end; }
.hero-card::before { content: ""; position: absolute; right: -60px; top: -60px; width: 260px; height: 260px; border-radius: 50%; background: rgba(255,255,255,0.18); }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.stat { padding: 14px; text-align: left; }
.stat b { display: block; font-size: 1.6em; font-weight: 800; }
.order-bar { display: flex; flex-direction: column; gap: 10px; }
.toggle { display: flex; padding: 4px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; }
.toggle { flex-shrink: 0; }
.toggle button { flex: 1; min-height: var(--touch); padding: 0 14px; border: 0; border-radius: 10px; background: transparent; font-weight: 700; color: var(--muted); white-space: nowrap; }
.toggle button.on { background: var(--ink); color: var(--bg); }
.addr { display: flex; align-items: center; gap: 10px; padding: 0 14px; min-height: var(--touch); background: var(--surface); border: 1px solid var(--line); border-radius: 14px; }
.addr input { flex: 1; border: 0; outline: 0; background: transparent; color: var(--ink); min-width: 0; }

.cats { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; scrollbar-width: none; -webkit-overflow-scrolling: touch; }
.cats::-webkit-scrollbar { display: none; }
.cats a { flex: 0 0 auto; padding: 10px 16px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); text-decoration: none; font-weight: 700; white-space: nowrap; min-height: var(--touch); display: inline-flex; align-items: center; }
.cats a.on { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.dish { display: flex; flex-direction: column; overflow: hidden; }
.dish .ph { aspect-ratio: 1; background: var(--tint); display: grid; place-items: center; color: var(--muted); font-size: 0.85em; object-fit: cover; }
.dish .ph-empty { background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 22%, var(--tint)), var(--tint) 70%); }
.dish .ph-empty span { font-size: 3.2em; font-weight: 800; color: var(--primary); opacity: .55; line-height: 1; }
.dish a.add { display: grid; place-items: center; text-decoration: none; }
.dish .body { display: flex; flex-direction: column; gap: 6px; padding: 14px; flex: 1; }
.dish .name { font-weight: 800; display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.dish .foot { display: flex; justify-content: space-between; align-items: center; margin-top: auto; }
.dish .price { font-weight: 800; font-size: 1.1em; }
.dish .add { width: 40px; height: 40px; border-radius: 12px; border: 0; background: var(--ink); color: var(--bg); font-size: 22px; font-weight: 700; cursor: pointer; }

.bonus { border-radius: 28px; background: var(--ink); color: var(--bg); padding: 28px; display: grid; gap: 18px; }
.bonus .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.bonus .tile { padding: 16px; border-radius: 16px; background: color-mix(in srgb, var(--bg) 12%, transparent); }
.bonus .tile b { display: block; font-size: 1.8em; font-weight: 800; color: var(--primary); }

.branch { display: flex; gap: 14px; align-items: center; padding: 14px; }
.branch .n { width: 48px; height: 48px; border-radius: 14px; background: var(--tint); display: grid; place-items: center; font-weight: 800; color: var(--primary); flex-shrink: 0; }
.steps { display: grid; gap: 14px; }
.step { display: flex; gap: 12px; }
.step .num { width: 32px; height: 32px; border-radius: 50%; background: var(--ink); color: var(--bg); display: grid; place-items: center; font-weight: 800; flex-shrink: 0; }
.contact { display: grid; gap: 12px; }
.ftr { border-top: 1px solid var(--line); padding: 24px 0; font-size: 0.85em; color: var(--muted); display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; }

/* ---- planshet */
@media (min-width: 601px) {
  :root { --gutter: 24px; }
  .dish .ph { aspect-ratio: 4/3; }
  .hero { grid-template-columns: 1.2fr 1fr; align-items: center; }
  .order-bar { flex-direction: row; }
  .section { padding: 56px 0; }
}
/* ---- kompyuter */
@media (min-width: 1025px) {
  :root { --gutter: 40px; }
  .nav { display: flex; }
  .burger, .mnav { display: none !important; }
  .grid { grid-template-columns: repeat(4, 1fr); }
  .two { display: grid; grid-template-columns: 1.4fr 1fr; gap: 24px; align-items: start; }
}
/* ---- TV / juda katta ekran: 10-fut UI */
@media (min-width: 1921px) { :root { --maxw: 1800px; --fs-body: 22px; --touch: 64px; --gutter: 64px; } }
[data-density="tv"] { --fs-body: 26px; --fs-h1: 72px; --fs-h2: 52px; --touch: 72px; --gutter: 56px; --radius: 24px; }

/* ---- TV menyu-bord */
.board { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; background: #141416; color: #F2F1EC; }
.board { overflow-x: hidden; }
.board-hdr { display: flex; justify-content: space-between; align-items: center; gap: 24px; padding: 24px 56px; border-bottom: 1px solid #2E2E34; }
.board-hdr > div:first-child, #clock { flex-shrink: 0; white-space: nowrap; }
.board-cats { display: flex; gap: 12px; flex: 1; min-width: 0; justify-content: center; flex-wrap: wrap; }
.board-cats span { padding: 10px 20px; border-radius: 999px; background: #2E2E34; font-weight: 700; white-space: nowrap; }
.board-cats span.on { background: #F2F1EC; color: #141416; }
.board-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; padding: 32px 56px; align-content: start; }
.board-item { display: flex; justify-content: space-between; gap: 16px; padding: 22px 26px; border-radius: 20px; background: #1E1E22; border: 1px solid #2E2E34; }
.board-item .nm { font-weight: 800; font-size: 1.15em; }
.board-item .ds { color: #A19F96; font-size: 0.8em; }
.board-item .pr { font-weight: 800; font-size: 1.3em; white-space: nowrap; }
.board-page { display: none; }
.board-page.on { display: contents; }
@media (max-width: 1400px) { .board-grid { grid-template-columns: repeat(2, 1fr); padding: 24px 32px; } .board-hdr { padding: 20px 32px; } }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
'@

Put 'backend\website\templates\platform\index.html' @'
{% load static site_tags %}<!doctype html>
<html lang="uz"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ platform }} — restoran, kafe va fast-food uchun to'liq boshqaruv</title>
<meta name="description" content="Kassa + fiskal, taomnoma, ombor, hodimlar, Telegram buyurtma — so'mda narxlangan, 15 kun bepul.">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap">
<link rel="stylesheet" href="{% static 'site.css' %}">
<style>:root{--primary:#0F6E63;--accent:#D9482B;--bg:#F4F3EE;--ink:#17171A;--surface:#fff;--line:#E4E2DA;--tint:#E3F0EC;--muted:#6B6A63}</style>
</head>
<body>
<header class="hdr"><div class="container"><a class="brand" href="/"><span class="logo">R</span>{{ platform }}</a>
<nav class="nav"><a href="#features">Imkoniyatlar</a><a href="#pricing">Narxlar</a><a href="/signup/">Bepul boshlash</a></nav>
<a class="btn" href="/signup/" style="margin-left:auto">15 kun bepul</a></div></header>
<main>
<section class="section container hero">
  <div style="display:flex;flex-direction:column;gap:20px">
    <span class="chip" style="align-self:flex-start;color:var(--primary)">So'mda narxlangan · fiskal ichida · Telegram-first</span>
    <h1 class="h1">Restoraningizni bitta paneldan boshqaring</h1>
    <p class="muted" style="font-size:1.15em;margin:0;max-width:560px">Kassa va fiskal chek, taomnoma va tannarx, ombor, hodimlar va o'qitish, Telegram buyurtma, yetkazib berish — egasi o'zi sozlaydi, dasturchisiz. Har restoranga alohida baza.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><a class="btn" href="/signup/">15 daqiqada ishga tushiring</a><a class="btn secondary" href="https://t.me/xn0827">Telegram orqali savol</a><a class="btn secondary" href="tel:+998712000000">+998 71 200 00 00</a></div>
  </div>
  <div class="card" style="padding:24px;display:grid;gap:12px">
    {% for code, p in presets.items %}<div class="branch" style="padding:10px 0;border-bottom:1px solid var(--line)"><span class="n">{{ forloop.counter }}</span><div style="flex:1"><b>{{ p.name }}</b><div class="muted" style="font-size:.9em">{{ p.modules|length }} modul tayyor preset</div></div></div>{% endfor %}
  </div>
</section>
<section class="section container" id="features"><h2 class="h2" style="margin-bottom:16px">Nima bor</h2>
  <div class="grid">
    {% for f in "Kassa (POS) va fiskal chek — offline ham ishlaydi|Taomnoma, tex-karta, tannarx va bozor narxi|Ombor: Didox kirim, avto-chiqim, inventarizatsiya|Hodimlar: smena, davomat, ish haqi qoidalari|O'qitish: o'z videolaringiz, testlar, SanQvaN jurnallari|Telegram bot + Mini App, bonus tizimi|Yetkazib berish: kuryerlar, zonalar, agregatorlar|Sayt va TV menyu-bord — telefon, planshet, kompyuter, TV"|split:"|" %}
    <div class="card" style="padding:18px"><b>{{ f }}</b></div>
    {% endfor %}
  </div>
</section>
<section class="section container" id="pricing"><h2 class="h2" style="margin-bottom:16px">Narxlar — filial uchun oyiga</h2>
  <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">
    {% for p in plans %}<div class="card" style="padding:22px;display:flex;flex-direction:column;gap:8px"><b style="font-size:1.2em">{{ p.name }}</b><span style="font-size:2em;font-weight:800">{{ p.price_per_branch|money }} <span style="font-size:.5em;font-weight:600" class="muted">so'm/oy</span></span><span class="muted">{{ p.max_branches }} filialgacha · {% if '*' in p.allowed_modules %}barcha modullar{% else %}{{ p.allowed_modules|length }} modul{% endif %}</span><a class="btn" href="/signup/?plan={{ p.code }}" style="margin-top:auto">15 kun bepul</a></div>{% empty %}<p class="muted">Tariflar: `python manage.py bootstrap_dev`</p>{% endfor %}
  </div>
</section>
</main>
<footer class="container ftr"><span>© {{ platform }} · O'zbekiston</span><span>Ma'lumotlar O'zbekistonda saqlanadi · IT Park rezidenti</span></footer>
</body></html>
'@

Put 'backend\website\templates\site\base.html' @'
{% load static site_tags %}<!doctype html>
<html lang="{{ lang }}" data-theme="{% if theme.dark_default %}dark{% else %}light{% endif %}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{% block title %}{{ site.seo.title|default:site.title|default:tenant.name }}{% endblock %}</title>
<meta name="description" content="{{ site.seo.description|default:'' }}">
<meta name="theme-color" content="{{ theme.primary }}">
<link rel="manifest" href="/manifest.webmanifest">
{% if site.favicon %}<link rel="icon" href="{{ site.favicon.url }}">{% else %}<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27%3E%3Crect width=%2732%27 height=%2732%27 rx=%278%27 fill=%27%23D9482B%27/%3E%3C/svg%3E">{% endif %}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap">
<link rel="stylesheet" href="{% static 'site.css' %}">
<style>
  :root { --primary: {{ theme.primary|default:'#D9482B' }}; --accent: {{ theme.accent|default:'#0F6E63' }}; --bg: {{ theme.bg|default:'#FFF6EA' }}; --ink: {{ theme.ink|default:'#1C1512' }}; --radius: {{ theme.radius|default:16 }}px; }
  {{ site.custom_css|safe }}
</style>
<script src="https://unpkg.com/htmx.org@2.0.3" defer></script>
{% block head %}{% endblock %}
</head>
<body>
{% block body %}
<header class="hdr">
  <div class="container">
    <a class="brand" href="/">
      {% if site.logo %}<img src="{{ site.logo.url }}" alt="" style="width:36px;height:36px;border-radius:10px;object-fit:cover">{% else %}<span class="logo">{{ site.title|default:tenant.name|slice:":1" }}</span>{% endif %}
      <span>{{ site.title|default:tenant.name }}</span>
    </a>
    <nav class="nav">
      {% for s in sections %}{% if s.type != 'hero' and s.type != 'menu' %}<a href="/#{{ s.type }}">{{ s.title|t:lang|default:s.get_type_display }}</a>{% endif %}{% endfor %}
      <a href="/menu/">{% if lang == 'ru' %}Меню{% elif lang == 'en' %}Menu{% else %}Taomnoma{% endif %}</a>
      {% if jobs_count %}<a href="/vacancies/">{% if lang == 'ru' %}Вакансии{% elif lang == 'en' %}Careers{% else %}Vakansiyalar{% endif %} <span class="jobs-n">{{ jobs_count }}</span></a>{% endif %}
    </nav>
    {% if languages|length > 1 %}<div class="lang">{% for l in languages %}<a href="?lang={{ l }}" class="{% if l == lang %}on{% endif %}">{{ l|upper }}</a>{% endfor %}</div>{% endif %}
    {% if site.telegram %}<a class="btn" href="https://t.me/{{ site.telegram|cut:'@'|cut:'https://t.me/' }}" style="display:none" id="tgBtn">Telegram</a>{% endif %}
    <button class="burger" aria-label="Menyu" onclick="document.getElementById('mnav').classList.toggle('open')">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
    </button>
  </div>
  <div class="container"><nav class="mnav" id="mnav">
    {% for s in sections %}{% if s.type != 'hero' and s.type != 'menu' %}<a href="/#{{ s.type }}" onclick="document.getElementById('mnav').classList.remove('open')">{{ s.title|t:lang|default:s.get_type_display }}</a>{% endif %}{% endfor %}
    <a href="/menu/">{% if lang == 'ru' %}Меню{% elif lang == 'en' %}Menu{% else %}Taomnoma{% endif %}</a>
    {% if jobs_count %}<a href="/vacancies/">{% if lang == 'ru' %}Вакансии{% elif lang == 'en' %}Careers{% else %}Vakansiyalar{% endif %} ({{ jobs_count }})</a>{% endif %}
  </nav></div>
</header>
<main>{% block content %}{% endblock %}</main>
<footer class="container ftr">
  <span>© {{ site.title|default:tenant.name }}{% if site.address %} · {{ site.address }}{% endif %}</span>
  <span>{% if site.phone %}<a href="tel:{{ site.phone }}">{{ site.phone }}</a>{% endif %}{% if site.instagram %} · <a href="https://instagram.com/{{ site.instagram|cut:'@' }}">Instagram</a>{% endif %}{% if jobs_count %} · <a href="/vacancies/">Vakansiyalar</a>{% endif %} · <a href="/tv/menu-board/">TV</a> · <a href="/admin/">Boshqaruv</a></span>
</footer>
<script>
  // Mavjud tema tanlovi (mijoz brauzeri) — localStorage bo'lmasa ham ishlaydi
  try { const t = localStorage.getItem('theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
  // TV / katta ekran aniqlash: pult bilan ishlaydigan brauzerlar uchun zichlik
  if (window.matchMedia('(min-width: 1921px)').matches || /SmartTV|SMART-TV|Tizen|WebOS|BRAVIA|AFTT|Android TV/i.test(navigator.userAgent)) document.documentElement.dataset.density = 'tv';
  const tg = document.getElementById('tgBtn'); if (tg && window.innerWidth > 1024) tg.style.display = 'inline-flex';
</script>
{% endblock %}
</body>
</html>
'@

Put 'backend\website\templates\site\vacancies.html' @'
{% extends "site/base.html" %}{% load site_tags %}
{% block title %}Vakansiyalar — {{ site.title|default:tenant.name }}{% endblock %}
{% block content %}
<section class="section container jobs">
  <span class="chip">💼 Biz bilan ishlang</span>
  <h1 class="h2" style="margin:12px 0 8px">Vakansiyalar</h1>
  <p class="muted" style="max-width:62ch;margin:0 0 24px">{{ intro }}</p>
  <div class="jgrid">
    {% for j in jobs %}
    <a class="card job" href="/vacancies/{{ j.v.id }}/">
      {% if j.v.image_src %}<img class="jimg" src="{{ j.v.image_src }}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">{% endif %}
      <div class="jb">
        <b class="jt">{{ j.v.title }}</b>
        <span class="jsal">{{ j.salary }}</span>
        <span class="muted jm">{{ j.employment }}{% if j.v.schedule %} · {{ j.v.schedule }}{% endif %}{% if j.v.branch %} · {{ j.v.branch.name }}{% endif %}</span>
        {% if j.v.summary %}<p class="muted" style="margin:6px 0 0">{{ j.v.summary }}</p>{% endif %}
        <span class="jgo">Batafsil va ariza →</span>
      </div>
    </a>
    {% empty %}
    <div class="card" style="padding:24px"><b>Hozircha ochiq vakansiya yo'q.</b><p class="muted" style="margin:6px 0 0">Keyinroq qayta kiring yoki bizga qo'ng'iroq qiling{% if site.phone %}: <a href="tel:{{ site.phone }}">{{ site.phone }}</a>{% endif %}.</p></div>
    {% endfor %}
  </div>
</section>
<style>
.jgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 16px; }
.job { display: flex; flex-direction: column; overflow: hidden; text-decoration: none; color: var(--ink); transition: transform .15s, box-shadow .15s; }
.job:hover { transform: translateY(-2px); box-shadow: 0 10px 30px rgba(0,0,0,.08); }
.jimg { width: 100%; aspect-ratio: 16/9; object-fit: cover; background: var(--tint); }
.jb { padding: 16px; display: flex; flex-direction: column; gap: 4px; }
.jt { font-size: 1.15em; } .jsal { font-weight: 800; color: var(--primary); } .jm { font-size: .9em; }
.jgo { margin-top: 10px; font-weight: 700; color: var(--accent); }
</style>
{% endblock %}
'@

Put 'backend\website\templates\site\vacancy.html' @'
{% extends "site/base.html" %}{% load site_tags %}
{% block title %}{% if v %}{{ v.title }} — {% endif %}Vakansiya — {{ site.title|default:tenant.name }}{% endblock %}
{% block content %}
<section class="section container vac">
  <a href="/vacancies/" class="muted" style="text-decoration:none">← Barcha vakansiyalar</a>
  {% if closed %}
    <div class="card" style="padding:24px;margin-top:16px"><b>Bu vakansiya yopilgan.</b> <a href="/vacancies/">Boshqa vakansiyalar</a></div>
  {% else %}
  <div class="vgrid">
    <article class="vmain">
      <h1 class="h2" style="margin:10px 0 6px">{{ v.title }}</h1>
      <div class="vtags"><span class="chip">💰 {{ salary }}</span><span class="chip">{{ employment }}</span>{% if v.schedule %}<span class="chip">🕒 {{ v.schedule }}</span>{% endif %}{% if v.branch %}<span class="chip">📍 {{ v.branch.name }}</span>{% endif %}</div>
      {% if v.summary %}<p class="lead">{{ v.summary }}</p>{% endif %}
      {% if media.kind == 'youtube' or media.kind == 'vimeo' or media.kind == 'drive' %}
        <div class="vid"><iframe src="{{ media.embed }}" title="Video" allow="accelerometer; encrypted-media; picture-in-picture" allowfullscreen loading="lazy"></iframe></div>
      {% elif media.kind == 'video' %}<video class="vid" src="{{ media.src }}" controls playsinline></video>
      {% elif v.image_src %}<img class="vimg" src="{{ v.image_src }}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">{% endif %}
      {% if media.kind == 'link' or media.kind == 'image' %}<p><a class="btn secondary" href="{{ media.src }}" target="_blank" rel="noopener">▶ Videoni ochish</a></p>{% endif %}
      {% if v.duties %}<h3>Vazifalar</h3><ul class="vl">{% for x in v.duties %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}
      {% if v.requirements %}<h3>Talablar</h3><ul class="vl">{% for x in v.requirements %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}
      {% if v.benefits %}<h3>Biz taklif qilamiz</h3><ul class="vl ok">{% for x in v.benefits %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}
      {% if v.link_url %}<p><a href="{{ v.link_url }}" target="_blank" rel="noopener">🔗 Batafsil ma'lumot</a></p>{% endif %}
    </article>

    <aside class="card vapply" id="apply">
      {% if sent %}
        <div class="done"><div style="font-size:48px">✅</div><b>Arizangiz qabul qilindi!</b><p class="muted">1–2 kun ichida siz bilan bog'lanamiz. Rahmat!</p></div>
      {% else %}
        <b style="font-size:1.15em">Ariza qoldirish</b>
        <p class="muted" style="margin:4px 0 12px">2 daqiqa · rezyume shart emas</p>
        {% if bot_link %}<a class="btn tgb" href="{{ bot_link }}" target="_blank" rel="noopener">✈ Telegram orqali ariza berish</a><div class="or"><span>yoki shu yerda</span></div>{% endif %}
        {% if error %}<div class="err">{{ error }}</div>{% endif %}
        <form method="post" enctype="multipart/form-data">{% csrf_token %}
          <input type="text" name="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px" aria-hidden="true">
          <label>Ism familiya *<input name="full_name" required maxlength="120" value="{{ form.full_name|default:'' }}" autocomplete="name"></label>
          <label>Telefon *<input name="phone" required type="tel" inputmode="tel" placeholder="+998 90 123 45 67" value="{{ form.phone|default:'' }}" autocomplete="tel"></label>
          <div class="two"><label>Tug'ilgan yil<input name="birth_year" inputmode="numeric" maxlength="4" placeholder="1998" value="{{ form.birth_year|default:'' }}"></label>
          <label>Tuman / shahar<input name="city" maxlength="80" value="{{ form.city|default:'' }}"></label></div>
          {% for i, q in questions %}
            <label>{{ q.text }}{% if q.must %} *{% endif %}
              {% if q.type == 'yesno' %}<span class="yn"><label><input type="radio" name="q{{ i }}" value="Ha" required> Ha</label><label><input type="radio" name="q{{ i }}" value="Yo'q"> Yo'q</label></span>
              {% else %}<input name="q{{ i }}" maxlength="300">{% endif %}
            </label>
          {% endfor %}
          <label>Oldingi ish joyi<input name="prev_company" maxlength="160" placeholder="masalan: «Rayhon» restorani"></label>
          <div class="two"><label>Lavozim<input name="prev_position" maxlength="120" placeholder="ofitsiant"></label><label>Necha yil<input name="prev_years" maxlength="20" placeholder="2 yil"></label></div>
          <label>O'zingiz haqingizda<textarea name="experience" rows="3" maxlength="3000" placeholder="Tajriba, qachon ishga chiqa olasiz…">{{ form.experience|default:'' }}</textarea></label>
          <label>Rasm (ixtiyoriy)<input type="file" name="photo" accept="image/*"></label>
          <button class="btn" type="submit" style="width:100%">Arizani yuborish</button>
          <small class="muted">Yuborish orqali ma'lumotlaringiz faqat ishga olish uchun ishlatilishiga rozilik bildirasiz.</small>
        </form>
      {% endif %}
    </aside>
  </div>
  {% endif %}
</section>
<style>
.vgrid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 28px; align-items: start; margin-top: 8px; }
.vtags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.lead { font-size: 1.1em; line-height: 1.55; }
.vid { width: 100%; aspect-ratio: 16/9; border: 0; border-radius: var(--radius); background: #000; display: block; margin: 12px 0; }
.vid iframe { width: 100%; height: 100%; border: 0; border-radius: var(--radius); }
.vimg { width: 100%; border-radius: var(--radius); margin: 12px 0; aspect-ratio: 16/9; object-fit: cover; }
.vmain h3 { margin: 22px 0 8px; }
.vl { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; line-height: 1.5; }
.vl.ok { list-style: none; padding-left: 0; } .vl.ok li::before { content: "✓ "; color: var(--accent); font-weight: 800; }
.vapply { padding: 20px; position: sticky; top: 84px; display: flex; flex-direction: column; }
.vapply form { display: flex; flex-direction: column; gap: 10px; }
.vapply label { display: flex; flex-direction: column; gap: 4px; font-weight: 700; font-size: .92em; }
.vapply input:not([type=radio]):not([type=file]), .vapply textarea { font: inherit; font-weight: 400; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--line); background: var(--bg); color: var(--ink); }
.vapply .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.yn { display: flex; gap: 16px; font-weight: 400; } .yn label { flex-direction: row; align-items: center; gap: 6px; font-weight: 600; }
.tgb { background: #229ED9; width: 100%; } .or { text-align: center; margin: 14px 0; position: relative; color: var(--muted); font-size: .9em; }
.or::before { content: ""; position: absolute; left: 0; right: 0; top: 50%; border-top: 1px solid var(--line); } .or span { position: relative; background: var(--surface); padding: 0 10px; }
.err { background: #fdecea; color: #b3261e; padding: 10px 12px; border-radius: 12px; margin-bottom: 10px; font-weight: 600; }
.done { text-align: center; padding: 20px 0; display: flex; flex-direction: column; gap: 6px; align-items: center; }
@media (max-width: 900px) { .vgrid { grid-template-columns: 1fr; } .vapply { position: static; } }
</style>
{% endblock %}
'@

Put 'backend\website\urls.py' @'
from django.urls import path, re_path

from . import views

urlpatterns = [
    path("", views.home, name="site_home"),
    path("menu/", views.menu, name="site_menu"),
    path("tv/menu-board/", views.menu_board, name="site_menu_board"),
    path("tg/", views.miniapp, name="site_miniapp"),
    path("vacancies/", views.vacancies, name="site_vacancies"),
    path("vacancies/<int:vid>/", views.vacancy, name="site_vacancy"),
    path("manifest.webmanifest", views.manifest, name="site_manifest"),
    re_path(r"^admin(?:/.*)?$", views.admin_spa, name="admin_spa"),
]
'@

Put 'backend\website\views.py' @'
"""
Restoran sayti (tenant domenida): bo'limlar CMS'dan, taomnoma e'lon qilingan snapshotdan.
Sahifalar: / (landing), /menu (to'liq taomnoma, HTMX filtr), /tv/menu-board (TV rejimi), /admin (SPA).
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_page

from core.models import Branch
from modules.catalog.services import current_snapshot
from modules.cms.models import SiteSection, SiteSettings


def _lang(request, site: SiteSettings) -> str:
    lang = request.GET.get("lang") or request.COOKIES.get("lang") or site.default_language or "uz"
    return lang if lang in (site.languages or ["uz"]) else (site.default_language or "uz")


def _ctx(request):
    site = SiteSettings.get()
    lang = _lang(request, site)
    menu = current_snapshot() or {"categories": []} if request.tenant.module_enabled("catalog") else {"categories": []}
    return {
        "site": site, "lang": lang, "theme": site.theme, "tenant": request.tenant,
        "sections": SiteSection.objects.filter(is_enabled=True),
        "menu": menu, "branches": Branch.objects.filter(is_active=True, deleted_at__isnull=True),
        "languages": site.languages or ["uz"], "platform": settings.PLATFORM_NAME,
        "jobs_count": _jobs_count(request),
    }


def _jobs_count(request) -> int:
    if not request.tenant.module_enabled("hr"):
        return 0
    from modules.hr.models import Vacancy, VacancyStatus
    return Vacancy.objects.filter(status=VacancyStatus.OPEN).count()


def home(request):
    if not request.tenant.module_enabled("cms"):
        return render(request, "site/offline.html", status=404)
    resp = render(request, "site/home.html", _ctx(request))
    if request.GET.get("lang"):
        resp.set_cookie("lang", request.GET["lang"], max_age=365 * 86400)
    return resp


def menu(request):
    """To'liq taomnoma. `?cat=<id>` + HX-Request → faqat taomlar bo'lagi (HTMX)."""
    ctx = _ctx(request)
    cat_id = request.GET.get("cat")
    cats = ctx["menu"]["categories"]
    ctx["active_cat"] = int(cat_id) if cat_id and cat_id.isdigit() else (cats[0]["id"] if cats else None)
    template = "site/_menu_items.html" if request.headers.get("HX-Request") else "site/menu.html"
    return render(request, template, ctx)


@cache_page(30)
def menu_board(request):
    """TV rejimi: 10-fut interfeys, kategoriyalar avtomatik aylanadi (pult shart emas)."""
    ctx = _ctx(request)
    ctx["rotate"] = int(request.tenant.settings.get("menu_board_rotate_seconds", 12))
    return render(request, "site/menu_board.html", ctx)


def miniapp(request):
    """Telegram Mini App (/tg/) — bot ichida ochiladigan menyu va savat. Buyurtma /api/v1/bot/miniapp/order ga ketadi."""
    if not request.tenant.module_enabled("telegram"):
        return render(request, "site/offline.html", status=404)
    from modules.telegram.services import conf
    ctx = _ctx(request)
    cfg = conf(request.tenant)
    ctx["rules"] = {k: cfg[k] for k in ("allow_delivery", "allow_pickup", "allow_dine_in", "delivery_fee", "free_delivery_from", "min_order")}
    return render(request, "site/miniapp.html", ctx)


def admin_spa(request, path: str = ""):
    """Boshqaruv paneli (Vue SPA). VITE_DEV=1 bo'lsa Vite dev-serverga ulanadi, aks holda build'ni beradi."""
    if settings.VITE_DEV:
        return render(request, "site/admin_dev.html", {"vite": settings.VITE_URL})
    built = settings.BASE_DIR / "website" / "static" / "admin" / "index.html"
    if built.exists():
        return HttpResponse(built.read_text(encoding="utf-8"))
    return HttpResponse("Admin build topilmadi: frontend'da `pnpm build` ni bajaring (yoki VITE_DEV=1).", status=503)


def manifest(request):
    """PWA manifest — sayt/Mini App telefonga o'rnatiladi; keyin Capacitor ilova shu konfiguratsiyani oladi."""
    site = SiteSettings.get()
    return JsonResponse({
        "name": site.title or request.tenant.name, "short_name": (site.title or request.tenant.name)[:12],
        "start_url": "/", "display": "standalone", "background_color": site.theme.get("bg", "#ffffff"),
        "theme_color": site.theme.get("primary", "#D9482B"),
        "icons": [{"src": site.logo.url, "sizes": "512x512", "type": "image/png"}] if site.logo else [],
    })


# ------------------------------------------------------------------ vakansiyalar (HR moduli)
def _bot_link(request, vid: int) -> str | None:
    if not request.tenant.module_enabled("telegram"):
        return None
    from modules.telegram.services import conf
    u = (conf(request.tenant).get("bot_username") or "").strip().lstrip("@")
    return f"https://t.me/{u}?start=job_{vid}" if u else None


def _media(v) -> dict:
    from modules.training.media import info
    return info(v.video_url) if v.video_url else {}


def vacancies(request):
    """/vacancies/ — ochiq vakansiyalar ro'yxati."""
    if not request.tenant.module_enabled("hr"):
        return render(request, "site/offline.html", status=404)
    from modules.hr import recruit
    from modules.hr.models import Vacancy, VacancyStatus
    ctx = _ctx(request)
    rows = [v for v in Vacancy.objects.filter(status=VacancyStatus.OPEN).select_related("branch") if recruit.is_open(v)]
    ctx["jobs"] = [{"v": v, "salary": recruit.salary_text(v), "employment": recruit.EMPLOYMENT.get(v.employment, "")} for v in rows]
    ctx["intro"] = (((request.tenant.settings or {}).get("modules") or {}).get("hr") or {}).get(
        "careers_intro", "Biz bilan ishlang: barqaror maosh, bepul ovqat, o'qitish va o'sish imkoniyati.")
    return render(request, "site/vacancies.html", ctx)


def vacancy(request, vid: int):
    """/vacancies/<id>/ — to'liq ma'lumot + ariza (Telegram bot yoki shu yerda forma)."""
    if not request.tenant.module_enabled("hr"):
        return render(request, "site/offline.html", status=404)
    from django.db.models import F

    from modules.hr import recruit
    from modules.hr.models import Vacancy
    v = Vacancy.objects.select_related("branch").filter(pk=vid).first()
    if v is None or not recruit.is_open(v):
        ctx = _ctx(request)
        ctx["closed"] = True
        return render(request, "site/vacancy.html", ctx, status=404 if v is None else 200)
    ctx = _ctx(request)
    ctx.update({"v": v, "salary": recruit.salary_text(v), "employment": recruit.EMPLOYMENT.get(v.employment, ""),
                "bot_link": _bot_link(request, v.pk), "media": _media(v), "questions": list(enumerate(v.questions or []))})
    if request.method == "POST":
        if request.POST.get("website"):                       # bot to'ldiradigan yashirin maydon (spam)
            ctx["sent"] = True
            return render(request, "site/vacancy.html", ctx)
        answers = [{"i": i, "a": request.POST.get(f"q{i}", "")} for i, _ in enumerate(v.questions or [])]
        by = request.POST.get("birth_year", "").strip()
        wh = [{"company": request.POST.get("prev_company", "").strip(), "position": request.POST.get("prev_position", "").strip(),
               "years": request.POST.get("prev_years", "").strip()}] if request.POST.get("prev_company", "").strip() else []
        photo = request.FILES.get("photo")
        if photo and (photo.size > 5 * 1024 * 1024 or not (photo.content_type or "").startswith("image/")):
            photo = None
        try:
            recruit.create_application(request.tenant, v, full_name=request.POST.get("full_name", ""), phone=request.POST.get("phone", ""),
                                       answers=answers, experience=request.POST.get("experience", ""), work_history=wh,
                                       birth_year=int(by) if by.isdigit() and 1950 < int(by) < 2012 else None,
                                       city=request.POST.get("city", ""), source="site", photo=photo)
            ctx["sent"] = True
        except ValueError as e:
            ctx["error"] = str(e)
            ctx["form"] = request.POST
    else:
        Vacancy.objects.filter(pk=v.pk).update(views=F("views") + 1)
    return render(request, "site/vacancy.html", ctx)
'@

Put 'frontend\apps\admin\src\router\index.ts' @'
import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    {
      path: '/', component: () => import('@/layouts/AppShell.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue'), meta: { module: 'catalog' } },
        { path: 'tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { module: 'tasks' } },
        { path: 'pos', name: 'pos', component: () => import('@/views/PosView.vue'), meta: { module: 'pos' } },
        { path: 'kds', name: 'kds', component: () => import('@/views/KdsView.vue'), meta: { module: 'kds' } },
        { path: 'tables', name: 'tables', component: () => import('@/views/TablesView.vue'), meta: { module: 'tables' } },
        { path: 'reservations', name: 'reservations', component: () => import('@/views/ReservationsView.vue'), meta: { module: 'reservations' } },
        { path: 'inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue'), meta: { module: 'inventory' } },
        { path: 'hr', name: 'hr', component: () => import('@/views/HrView.vue'), meta: { module: 'hr' } },
        { path: 'hr/employee/:id', name: 'hr-employee', component: () => import('@/views/EmployeeProfileView.vue'), meta: { module: 'hr', title: 'Xodim profili' } },
        { path: 'recruiting', name: 'recruiting', component: () => import('@/views/RecruitView.vue'), meta: { module: 'hr', title: 'Ishga olish' } },
        { path: 'kpi', name: 'kpi', component: () => import('@/views/KpiView.vue'), meta: { module: 'hr', title: 'Baholash va KPI' } },
        { path: 'reports', name: 'reports', component: () => import('@/views/ReportsView.vue'), meta: { module: 'finance' } },
        { path: 'training', name: 'training', component: () => import('@/views/TrainingView.vue'), meta: { module: 'training' } },
        { path: 'training/course/:id', name: 'training-course', component: () => import('@/views/TrainingCourseView.vue'), meta: { module: 'training' } },
        { path: 'training/lesson/:id', name: 'training-lesson', component: () => import('@/views/TrainingLessonView.vue'), meta: { module: 'training' } },
        { path: 'training/quiz/:id', name: 'training-quiz', component: () => import('@/views/TrainingQuizView.vue'), meta: { module: 'training' } },
        { path: 'training/certificate/:id', name: 'training-cert', component: () => import('@/views/TrainingCertView.vue'), meta: { module: 'training' } },
        { path: 'crm', name: 'crm', component: () => import('@/views/CrmView.vue'), meta: { module: 'crm', title: 'Mijozlar va bonus' } },
        { path: 'telegram', name: 'telegram', component: () => import('@/views/TelegramView.vue'), meta: { module: 'telegram' } },
        { path: 'site', name: 'site', component: () => import('@/views/SiteView.vue'), meta: { module: 'cms' } },
        { path: 'branches', name: 'branches', component: () => import('@/views/BranchesView.vue') },
        { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue') },
        { path: 'modules', name: 'modules', component: () => import('@/views/ModulesView.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
        { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue'), meta: { title: "O'zgarishlar tarixi" } },
        { path: ':pathMatch(.*)*', redirect: '/' },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const a = useAuth()
  if (to.meta.public) return true
  if (!a.me) { try { await a.load() } catch { return '/login' } }
  if (to.meta.module && !a.me!.tenant.enabled_modules.includes(to.meta.module as string)) return '/modules'
  return true
})
'@

Put 'frontend\apps\admin\src\views\EmployeeProfileView.vue' @'
<script setup lang="ts">
/**
 * Xodimning to'liq profili: shaxsiy ma'lumot · oldingi ish joylari · hujjatlar (tibbiy daftarcha muddati) ·
 * KPI (oylik, 6 oy tarixi) · menejer baholari · smenadan keyingi kayfiyat · qayerdan (qaysi vakansiyadan) kelgani.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { uploadWithProgress } from '@/components/training/upload'

const a = useAuth(), route = useRoute(), router = useRouter()
const P = ref<any>(null)
const tab = ref<'info' | 'kpi' | 'history' | 'docs'>((route.query.tab as any) || 'info')
const canEdit = computed(() => a.can('hr.edit'))
const eid = computed(() => Number(route.params.id))
async function load() {
  try { P.value = await api.get(`/hr/employees/${eid.value}/profile`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); router.replace('/hr') }
}
onMounted(load)

const p2 = (n: number) => String(n).padStart(2, '0')
const dmy = (s?: string | null) => { if (!s) return '—'; const d = new Date(s); return `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.${d.getFullYear()}` }
const GTONE: Record<string, any> = { A: 'ok', B: 'info', C: 'warn', D: 'danger', '—': 'neutral' }
const MOOD = ['', '🙁', '😐', '🙂', '😀']

// ---- shaxsiy ma'lumot
const edit = ref<any>(null)
function startEdit() {
  const x = P.value.profile, e = P.value.employee
  edit.value = { birth_date: x.birth_date || '', gender: x.gender || '', address: x.address, emergency_name: x.emergency_name, emergency_phone: e.emergency_phone,
    education: x.education, languages: (x.languages || []).join(', '), skills: (x.skills || []).join(', '), about: x.about, medical_book_until: x.medical_book_until || '' }
}
async function saveEdit() {
  const b = { ...edit.value, birth_date: edit.value.birth_date || null, medical_book_until: edit.value.medical_book_until || null,
    languages: edit.value.languages.split(',').map((s: string) => s.trim()).filter(Boolean), skills: edit.value.skills.split(',').map((s: string) => s.trim()).filter(Boolean) }
  try { P.value = await api.put(`/hr/employees/${eid.value}/profile`, b); edit.value = null; toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- ish tarixi
const wh = ref<any>(null)
function newWork() { wh.value = { id: null, company: '', position: '', start: '', end: '', reason_left: '', reference_phone: '', note: '' } }
async function saveWork() {
  try { wh.value.id ? await api.put(`/hr/work-history/${wh.value.id}`, wh.value) : await api.post(`/hr/employees/${eid.value}/work-history`, wh.value); wh.value = null; await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delWork(w: any) { if (confirm('O\'chirilsinmi?')) { await api.del(`/hr/work-history/${w.id}`); await load() } }

// ---- hujjatlar
const doc = ref<any>(null)
const upPct = ref<number | null>(null)
const KINDS = [{ value: 'contract', label: 'Mehnat shartnomasi' }, { value: 'medbook', label: 'Tibbiy daftarcha' }, { value: 'passport', label: 'Pasport nusxasi' }, { value: 'diploma', label: 'Diplom / sertifikat' }, { value: 'other', label: 'Boshqa' }]
function newDoc() { doc.value = { title: '', kind: 'contract', url: '', expires_on: '', file: null as File | null } }
async function saveDoc() {
  const d = doc.value
  const qs = new URLSearchParams({ title: d.title, kind: d.kind, ...(d.url ? { url: d.url } : {}), ...(d.expires_on ? { expires_on: d.expires_on } : {}) }).toString()
  try {
    if (d.file) { upPct.value = 0; await uploadWithProgress(`/hr/employees/${eid.value}/documents?${qs}`, d.file, (p) => (upPct.value = p)) }
    else await api.post(`/hr/employees/${eid.value}/documents?${qs}`)
    doc.value = null; await load(); toast('Hujjat qo\'shildi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { upPct.value = null }
}
async function delDoc(x: any) { if (confirm(`«${x.title}» o'chirilsinmi?`)) { await api.del(`/hr/documents/${x.id}`); await load() } }

// ---- baholash
const rv = ref<any>(null)
function newReview() { rv.value = { month: P.value.kpi.month, scores: Object.fromEntries(P.value.criteria.map((c: any) => [c.key, 0])), strengths: '', improve: '', goals: '' } }
async function saveReview() {
  try { await api.post(`/hr/employees/${eid.value}/reviews`, rv.value); rv.value = null; await load(); toast('Baho saqlandi — KPI yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- ishdan bo'shatish
async function fire() {
  const reason = prompt('Ishdan bo\'shatish sababi (ichki):'); if (!reason) return
  try { await api.post(`/hr/employees/${eid.value}/fire`, { reason }); toast('Karta arxivga o\'tdi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const crit = (k: string) => P.value?.criteria.find((c: any) => c.key === k)?.label ?? k
</script>

<template>
  <div v-if="P" class="pf">
    <RouterLink to="/hr" class="back"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /> Xodimlar</RouterLink>

    <header class="hero">
      <UiAvatar :name="P.employee.full_name" :src="P.employee.avatar" :size="76" :online="P.employee.on_shift" />
      <div class="hi">
        <h1>{{ P.employee.full_name }}</h1>
        <p>{{ P.employee.position_name || P.employee.role_name }} · {{ P.employee.branch_name || '—' }} · <a :href="`tel:${P.employee.phone}`">{{ P.employee.phone }}</a></p>
        <div class="chips">
          <UiChip tone="neutral">Ishda: {{ P.profile.tenure_text }}</UiChip>
          <UiChip v-if="P.employee.telegram_id" tone="ok">Telegram ulangan</UiChip>
          <UiChip v-if="P.profile.medical_expired" tone="danger">⚠ Tibbiy daftarcha muddati o'tgan</UiChip>
          <UiChip v-else-if="P.profile.medical_expiring" tone="warn">Tibbiy daftarcha tugayapti: {{ dmy(P.profile.medical_book_until) }}</UiChip>
          <UiChip v-if="!P.employee.is_active" tone="danger">Ishdan ketgan · {{ dmy(P.profile.fire_date) }}</UiChip>
          <UiChip v-if="P.kpi.risk" tone="danger">Ketib qolish xavfi</UiChip>
        </div>
      </div>
      <div class="kpibox" :class="GTONE[P.kpi.grade]">
        <span>KPI · {{ P.kpi.month }}</span><b>{{ P.kpi.score ?? '—' }}</b><em>{{ P.kpi.grade }}</em>
      </div>
    </header>

    <nav class="tabs">
      <button :class="{ on: tab === 'info' }" @click="tab = 'info'"><UiIcon name="users" :size="15" /> Ma'lumot</button>
      <button :class="{ on: tab === 'kpi' }" @click="tab = 'kpi'"><UiIcon name="star" :size="15" /> KPI va baholar</button>
      <button :class="{ on: tab === 'history' }" @click="tab = 'history'"><UiIcon name="archive" :size="15" /> Ish tarixi</button>
      <button :class="{ on: tab === 'docs' }" @click="tab = 'docs'"><UiIcon name="paperclip" :size="15" /> Hujjatlar <small v-if="P.documents.length">{{ P.documents.length }}</small></button>
    </nav>

    <!-- MA'LUMOT -->
    <div v-if="tab === 'info'" class="two">
      <UiCard title="Shaxsiy ma'lumot">
        <template #actions><UiButton v-if="canEdit" size="s" variant="secondary" @click="startEdit"><UiIcon name="edit" :size="14" /> O'zgartirish</UiButton></template>
        <dl class="dl">
          <dt>Tug'ilgan sana</dt><dd>{{ dmy(P.profile.birth_date) }}<template v-if="P.profile.age"> · {{ P.profile.age }} yosh</template></dd>
          <dt>Jinsi</dt><dd>{{ P.profile.gender === 'm' ? 'Erkak' : P.profile.gender === 'f' ? 'Ayol' : '—' }}</dd>
          <dt>Manzil</dt><dd>{{ P.profile.address || '—' }}</dd>
          <dt>Ma'lumoti</dt><dd>{{ P.profile.education || '—' }}</dd>
          <dt>Tillar</dt><dd><UiChip v-for="l in P.profile.languages" :key="l" tone="neutral">{{ l }}</UiChip><span v-if="!P.profile.languages.length">—</span></dd>
          <dt>Ko'nikmalar</dt><dd><UiChip v-for="s in P.profile.skills" :key="s" tone="info">{{ s }}</UiChip><span v-if="!P.profile.skills.length">—</span></dd>
          <dt>Favqulodda aloqa</dt><dd>{{ P.profile.emergency_name || '—' }} <a v-if="P.employee.emergency_phone" :href="`tel:${P.employee.emergency_phone}`">{{ P.employee.emergency_phone }}</a></dd>
          <dt>Tibbiy daftarcha</dt><dd :class="{ bad: P.profile.medical_expired }">{{ dmy(P.profile.medical_book_until) }}</dd>
          <dt>O'zi haqida</dt><dd class="pre">{{ P.profile.about || '—' }}</dd>
        </dl>
      </UiCard>
      <div class="col">
        <UiCard title="Ish sharoiti">
          <dl class="dl">
            <dt>Maosh</dt><dd><b>{{ money(P.employee.rate) }}</b> / {{ ({ monthly: 'oy', hourly: 'soat', shift: 'smena', percent: '% savdo' } as any)[P.employee.salary_type] }}</dd>
            <dt>Ishga kirgan</dt><dd>{{ dmy(P.employee.hire_date) }}</dd>
            <dt>Qayerdan kelgan</dt><dd>{{ P.application ? `Vakansiya: ${P.application.vacancy} (${P.application.source})` : (P.profile.source || '—') }}</dd>
            <dt>Karta</dt><dd>{{ P.employee.card_number || '—' }}</dd>
          </dl>
          <UiButton v-if="canEdit && P.employee.is_active" size="s" variant="ghost" @click="fire">Ishdan bo'shatish…</UiButton>
        </UiCard>
        <UiCard v-if="P.application?.answers?.length" title="Ariza javoblari">
          <div v-for="(x, i) in P.application.answers" :key="i" class="ans"><span>{{ x.q }}</span><b :class="{ bad: !x.ok }">{{ x.a || '—' }}</b></div>
        </UiCard>
        <UiCard title="Kayfiyat (smenadan keyin)">
          <div class="moods"><span v-for="(f, i) in P.feedback" :key="i" :title="`${dmy(f.date)} ${f.comment}`">{{ MOOD[f.mood] }}</span></div>
          <p v-if="!P.feedback.length" class="mut">Hali baho yo'q — /ketdim dan keyin bot so'raydi.</p>
        </UiCard>
      </div>
    </div>

    <!-- KPI -->
    <div v-else-if="tab === 'kpi'" class="two">
      <UiCard :title="`KPI · ${P.kpi.month}`" :subtitle="P.kpi.bonus_suggest ? `Tavsiya bonus: ${money(P.kpi.bonus_suggest)} so'm` : 'Ball — mavjud ko\'rsatkichlarning og\'irlikli o\'rtachasi'">
        <div v-for="(x, k) in P.kpi.parts" :key="k" class="kp">
          <span class="kl"><b>{{ x.label }}</b><small>{{ x.text }} · og'irlik {{ x.weight }}</small></span>
          <span class="kb"><i :style="{ width: x.value + '%' }" :class="x.value >= 85 ? 'a' : x.value >= 70 ? 'b' : x.value >= 50 ? 'c' : 'd'"></i></span>
          <b class="kv">{{ x.value }}</b>
        </div>
        <p v-if="!Object.keys(P.kpi.parts).length" class="mut">Bu oy uchun ma'lumot yo'q.</p>
        <div class="hist">
          <div v-for="h in P.kpi_history" :key="h.month" class="hb"><span class="bar"><i :style="{ height: (h.score ?? 0) + '%' }" :class="GTONE[h.grade]"></i></span><small>{{ h.month.slice(5) }}</small><b>{{ h.score ?? '—' }}</b></div>
        </div>
      </UiCard>
      <UiCard title="Menejer baholari">
        <template #actions><UiButton v-if="a.can('hr.review')" size="s" @click="newReview"><UiIcon name="star" :size="14" /> Baholash</UiButton></template>
        <div v-for="r in P.reviews" :key="r.id" class="rv">
          <header><b>{{ r.period }}</b><UiChip tone="info">{{ r.average }} / 5</UiChip><small>{{ r.reviewer }}</small></header>
          <div class="sc"><span v-for="(v, k) in r.scores" :key="k">{{ crit(String(k)) }}: <b>{{ '★'.repeat(v) }}</b></span></div>
          <p v-if="r.strengths">💪 {{ r.strengths }}</p><p v-if="r.improve">🔧 {{ r.improve }}</p><p v-if="r.goals">🎯 {{ r.goals }}</p>
        </div>
        <UiEmpty v-if="!P.reviews.length" title="Hali baho yo'q" text="Oyiga bir marta baholang — KPI ning 20%." />
      </UiCard>
    </div>

    <!-- ISH TARIXI -->
    <UiCard v-else-if="tab === 'history'" title="Oldingi ish joylari" subtitle="Nomzod anketasidan o'zi ko'chadi — qo'shimcha ma'lumot qo'shish mumkin">
      <template #actions><UiButton v-if="canEdit" size="s" @click="newWork"><UiIcon name="plus" :size="14" /> Qo'shish</UiButton></template>
      <div class="tl">
        <div v-for="w in P.work_history" :key="w.id" class="ti">
          <span class="dot"></span>
          <div><b>{{ w.company }}</b><span class="mut"> · {{ w.position || 'lavozim ko\'rsatilmagan' }}</span>
            <div class="mut">{{ w.start || '?' }} — {{ w.end || 'hozirgacha' }}<template v-if="w.reason_left"> · ketish sababi: {{ w.reason_left }}</template></div>
            <div v-if="w.reference_phone" class="mut">Tavsiya: <a :href="`tel:${w.reference_phone}`">{{ w.reference_phone }}</a></div>
            <div v-if="w.note">{{ w.note }}</div></div>
          <span class="sp"></span>
          <template v-if="canEdit"><UiButton size="s" variant="ghost" @click="wh = { ...w }"><UiIcon name="edit" :size="14" /></UiButton><UiButton size="s" variant="ghost" @click="delWork(w)"><UiIcon name="trash" :size="14" /></UiButton></template>
        </div>
        <UiEmpty v-if="!P.work_history.length" title="Ma'lumot yo'q" />
      </div>
    </UiCard>

    <!-- HUJJATLAR -->
    <UiCard v-else title="Hujjatlar" subtitle="Fayl yuklang yoki havola qo'ying (Google Drive) — baza tejaladi">
      <template #actions><UiButton v-if="canEdit" size="s" @click="newDoc"><UiIcon name="plus" :size="14" /> Hujjat</UiButton></template>
      <div v-for="x in P.documents" :key="x.id" class="doc">
        <span class="di"><UiIcon name="paperclip" :size="16" /></span>
        <span class="dn"><b>{{ x.title }}</b><small>{{ x.kind_label }}<template v-if="x.expires_on"> · muddati {{ dmy(x.expires_on) }}</template></small></span>
        <UiChip v-if="x.expired" tone="danger">muddati o'tgan</UiChip><UiChip v-else-if="x.expiring" tone="warn">tugayapti</UiChip>
        <a v-if="x.url" :href="x.url" target="_blank" rel="noopener" class="lnk">Ochish</a>
        <UiButton v-if="canEdit" size="s" variant="ghost" @click="delDoc(x)"><UiIcon name="trash" :size="14" /></UiButton>
      </div>
      <UiEmpty v-if="!P.documents.length" title="Hujjat yo'q" text="Mehnat shartnomasi va tibbiy daftarcha — birinchi navbatda." />
    </UiCard>

    <!-- DRAWERS -->
    <UiDrawer :open="!!edit" title="Shaxsiy ma'lumot" @close="edit = null">
      <template v-if="edit">
        <div class="g2"><UiInput v-model="edit.birth_date" type="date" label="Tug'ilgan sana" /><UiSelect v-model="edit.gender" label="Jinsi" :options="[{ value: '', label: '—' }, { value: 'm', label: 'Erkak' }, { value: 'f', label: 'Ayol' }]" /></div>
        <UiInput v-model="edit.address" label="Manzil" />
        <UiInput v-model="edit.education" label="Ma'lumoti" placeholder="Oshpazlik kolleji, 2019" />
        <UiInput v-model="edit.languages" label="Tillar (vergul bilan)" placeholder="o'zbek, rus" />
        <UiInput v-model="edit.skills" label="Ko'nikmalar (vergul bilan)" placeholder="tandir, kassa, latte-art" />
        <div class="g2"><UiInput v-model="edit.emergency_name" label="Favqulodda aloqa — kim" placeholder="Onasi" /><UiInput v-model="edit.emergency_phone" label="Uning telefoni" /></div>
        <UiInput v-model="edit.medical_book_until" type="date" label="Tibbiy daftarcha amal qiladi" />
        <label class="fld"><span>O'zi haqida</span><textarea v-model="edit.about" rows="4"></textarea></label>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="edit = null">Bekor</UiButton><UiButton variant="brand" @click="saveEdit">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!wh" :title="wh?.id ? 'Ish joyini o\'zgartirish' : 'Oldingi ish joyi'" @close="wh = null">
      <template v-if="wh">
        <UiInput v-model="wh.company" label="Ish joyi" placeholder="«Rayhon» restorani" />
        <UiInput v-model="wh.position" label="Lavozim" />
        <div class="g2"><UiInput v-model="wh.start" label="Boshlagan (yil yoki oy)" placeholder="2019-03" /><UiInput v-model="wh.end" label="Tugatgan" placeholder="bo'sh — hozirgacha" /></div>
        <UiInput v-model="wh.reason_left" label="Ketish sababi" />
        <UiInput v-model="wh.reference_phone" label="Tavsiya beruvchi telefon" />
        <UiInput v-model="wh.note" label="Izoh" />
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="wh = null">Bekor</UiButton><UiButton variant="brand" @click="saveWork">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!doc" title="Hujjat qo'shish" @close="doc = null">
      <template v-if="doc">
        <UiSelect v-model="doc.kind" label="Turi" :options="KINDS" />
        <UiInput v-model="doc.title" label="Nomi" placeholder="Mehnat shartnomasi №12" />
        <UiInput v-model="doc.url" label="Havola (ixtiyoriy)" placeholder="https://drive.google.com/…" />
        <label class="fld"><span>yoki fayl (15 MB gacha)</span><input type="file" @change="doc.file = ($event.target as HTMLInputElement).files?.[0] ?? null" /></label>
        <UiInput v-model="doc.expires_on" type="date" label="Amal qilish muddati (ixtiyoriy)" />
        <div v-if="upPct !== null" class="kb"><i class="b" :style="{ width: upPct + '%' }"></i></div>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="doc = null">Bekor</UiButton><UiButton variant="brand" @click="saveDoc">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!rv" :title="`Baholash · ${rv?.month ?? ''}`" @close="rv = null">
      <template v-if="rv">
        <div v-for="c in P.criteria" :key="c.key" class="star">
          <span>{{ c.label }}</span>
          <span class="st"><button v-for="n in 5" :key="n" type="button" :class="{ on: rv.scores[c.key] >= n }" :aria-label="`${n} yulduz`" @click="rv.scores[c.key] = n">★</button></span>
        </div>
        <UiInput v-model="rv.strengths" label="Kuchli tomoni" placeholder="Mehmon bilan juda yaxshi muomala" />
        <UiInput v-model="rv.improve" label="Nimani yaxshilash kerak" placeholder="Kechikish" />
        <UiInput v-model="rv.goals" label="Keyingi oy maqsadi (xodimga Telegram'da boradi)" placeholder="O'rtacha chekni 85 000 ga chiqarish" />
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="rv = null">Bekor</UiButton><UiButton variant="brand" @click="saveReview">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.pf { display: flex; flex-direction: column; gap: 16px; max-width: 1180px; }
.back { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-weight: 700; text-decoration: none; }
.hero { display: flex; gap: 18px; align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 18px; flex-wrap: wrap; }
.hi { flex: 1; min-width: 220px; } .hi h1 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; }
.hi p { margin: 4px 0 8px; color: var(--muted); } .hi a { color: var(--accent); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.kpibox { display: flex; flex-direction: column; align-items: center; min-width: 110px; padding: 12px 16px; border-radius: 16px; background: var(--surface-2); border: 1px solid var(--line); }
.kpibox span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .kpibox b { font-family: var(--font-display); font-size: 34px; line-height: 1.1; }
.kpibox em { font-style: normal; font-weight: 800; font-size: var(--fs-s); padding: 1px 10px; border-radius: 99px; background: var(--surface-3); }
.kpibox.ok em { background: var(--ok-tint); color: var(--ok); } .kpibox.info em { background: var(--info-tint); color: var(--info); }
.kpibox.warn em { background: var(--warn-tint); color: var(--warn-ink); } .kpibox.danger em { background: var(--danger-tint); color: var(--danger); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 10px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.two { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 16px; align-items: start; }
.col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.dl { display: grid; grid-template-columns: 150px 1fr; gap: 10px 14px; margin: 0; font-size: var(--fs-s); }
.dl dt { color: var(--muted); font-weight: 700; } .dl dd { margin: 0; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.dl dd.pre { white-space: pre-line; } .bad { color: var(--danger); font-weight: 700; }
.ans { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .ans span { color: var(--muted); }
.moods { display: flex; flex-wrap: wrap; gap: 6px; font-size: 24px; }
.mut { color: var(--muted); font-size: var(--fs-s); margin: 0; }
.kp { display: grid; grid-template-columns: minmax(0, 1fr) 140px 40px; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line-2); }
.kl { display: flex; flex-direction: column; } .kl small { color: var(--muted); font-size: var(--fs-xs); }
.kb { height: 8px; border-radius: 99px; background: var(--surface-3); overflow: hidden; display: block; }
.kb i { display: block; height: 100%; border-radius: 99px; background: var(--accent); }
.kb i.a { background: var(--ok); } .kb i.b { background: var(--info); } .kb i.c { background: var(--warn); } .kb i.d { background: var(--danger); }
.kv { text-align: right; font-variant-numeric: tabular-nums; }
.hist { display: flex; gap: 10px; align-items: flex-end; margin-top: 16px; height: 120px; }
.hb { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; }
.hb .bar { flex: 1; width: 100%; max-width: 36px; background: var(--surface-3); border-radius: 8px; display: flex; align-items: flex-end; overflow: hidden; }
.hb .bar i { width: 100%; border-radius: 8px; background: var(--series-mute); } .hb .bar i.ok { background: var(--ok); } .hb .bar i.info { background: var(--info); } .hb .bar i.warn { background: var(--warn); } .hb .bar i.danger { background: var(--danger); }
.hb small { color: var(--muted); font-size: var(--fs-xs); } .hb b { font-size: var(--fs-xs); }
.rv { padding: 10px 0; border-bottom: 1px solid var(--line-2); display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); }
.rv header { display: flex; gap: 8px; align-items: center; } .rv header small { color: var(--muted); margin-left: auto; }
.sc { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--muted); font-size: var(--fs-xs); } .sc b { color: var(--series-4); letter-spacing: 1px; }
.rv p { margin: 0; }
.tl { display: flex; flex-direction: column; }
.ti { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); align-items: flex-start; }
.dot { width: 12px; height: 12px; border-radius: 50%; background: var(--accent); margin-top: 4px; flex-shrink: 0; } .sp { flex: 1; }
.doc { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line-2); }
.di { width: 34px; height: 34px; border-radius: 10px; background: var(--surface-3); display: grid; place-items: center; color: var(--accent); }
.dn { flex: 1; display: flex; flex-direction: column; min-width: 0; } .dn small { color: var(--muted); font-size: var(--fs-xs); }
.lnk { color: var(--accent); font-weight: 700; text-decoration: none; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fld { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fld textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; font: inherit; background: var(--surface); color: var(--ink); }
.star { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 0; font-size: var(--fs-s); font-weight: 600; }
.st button { border: 0; background: none; font-size: 26px; color: var(--line); cursor: pointer; padding: 0 2px; line-height: 1; } .st button.on { color: var(--series-4); }
@media (max-width: 900px) { .two { grid-template-columns: 1fr; } .dl { grid-template-columns: 120px 1fr; } .kp { grid-template-columns: minmax(0, 1fr) 80px 34px; } }
</style>
'@

Put 'frontend\apps\admin\src\views\HrView.vue' @'
<script setup lang="ts">
import { RouterLink } from 'vue-router'
/**
 * Xodimlar: ro'yxat + karta (lavozim, maosh sharti, rol, vazifalari, davomati, oyliklari) ·
 * smena jadvali (hafta) · davomat (keldi/ketdi) · oylik (hisoblash → tasdiqlash → to'lash).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth()
type Tab = 'employees' | 'schedule' | 'attendance' | 'payroll'
const tab = ref<Tab>('employees')
const meta = ref<any>(null)
const employees = ref<any[]>([])
const card = ref<any>(null)
const drawer = ref(false)
const form = ref<any>(null)
const q = ref('')
const canEdit = computed(() => a.can('hr.edit'))

const SAL: Record<string, string> = { monthly: 'oylik', hourly: 'soat', shift: 'smena', percent: '% savdo' }
const ROLE_TONE: Record<string, any> = { owner: 'accent', manager: 'info', cashier: 'ok', cook: 'warn' }

async function load() {
  meta.value = await api.get('/hr/meta')
  employees.value = await api.get('/hr/employees', { q: q.value || undefined })
}
onMounted(load)

async function openCard(e: any) { card.value = await api.get(`/hr/employees/${e.id}/card`) }
function openForm(e?: any) {
  form.value = e ? { ...e, hire_date: e.hire_date, telegram_id: e.telegram_id ?? null } : {
    full_name: '', phone: '+998', role_code: 'cashier', branch_id: meta.value?.branches[0]?.id ?? null, position_id: null,
    salary_type: 'monthly', rate: 0, pinfl: '', passport: '', card_number: '', emergency_phone: '', note: '', is_active: true, telegram_id: null,
  }
  drawer.value = true
}
function onPosition(v: string) {
  form.value.position_id = v ? Number(v) : null
  const p = meta.value.positions.find((x: any) => x.id === Number(v))
  if (p) { form.value.salary_type = p.default_salary_type; form.value.rate = p.default_rate }
}
async function save() {
  const b = { ...form.value, rate: Number(form.value.rate), branch_id: form.value.branch_id ? Number(form.value.branch_id) : null, position_id: form.value.position_id ? Number(form.value.position_id) : null }
  try {
    form.value.id ? await api.put(`/hr/employees/${form.value.id}`, b) : await api.post('/hr/employees', b)
    drawer.value = false; await load(); if (card.value) card.value = await api.get(`/hr/employees/${card.value.employee.id}/card`); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- jadval
const weekStart = ref(monday(new Date()))
function monday(d: Date) { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x }
const days = computed(() => Array.from({ length: 7 }, (_, i) => { const d = new Date(weekStart.value); d.setDate(d.getDate() + i); return d }))
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const shifts = ref<any[]>([])
async function loadShifts() { shifts.value = await api.get('/hr/shifts', { start: iso(days.value[0]), end: iso(days.value[6]) }) }
watch([tab, weekStart], () => { if (tab.value === 'schedule') loadShifts(); if (tab.value === 'attendance') loadAtt(); if (tab.value === 'payroll') loadPayroll() })
const shiftOf = (eid: number, d: Date) => shifts.value.find(s => s.employee_id === eid && s.date === iso(d))
async function toggleShift(e: any, d: Date) {
  if (!canEdit.value) return
  const s = shiftOf(e.id, d)
  if (s) { await api.del(`/hr/shifts/${s.id}`) } else {
    const p = prompt('Smena vaqti (09:00-18:00):', '09:00-18:00'); if (!p) return
    const [st, en] = p.split('-').map(x => x.trim())
    await api.post('/hr/shifts', { employee_id: e.id, date: iso(d), start: st, end: en, branch_id: e.branch_id })
  }
  await loadShifts()
}
async function copyWeek() {
  const prev = new Date(weekStart.value); prev.setDate(prev.getDate() - 7)
  const r = await api.post(`/hr/shifts/copy-week?from_start=${iso(prev)}&to_start=${iso(weekStart.value)}`)
  toast(`${r.copied} smena nusxalandi`); await loadShifts()
}
const shiftWeek = (n: number) => { const d = new Date(weekStart.value); d.setDate(d.getDate() + 7 * n); weekStart.value = d }

// ---- davomat
const att = ref<any[]>([])
async function loadAtt() { att.value = await api.get('/hr/attendance', { day: iso(new Date()) }) }
async function checkIn(e: any) { try { await api.post(`/hr/attendance/check-in?employee_id=${e.id}`); await loadAtt(); await load(); toast('Keldi ✓') } catch (x: any) { toast(x.detail ?? 'Xato', 'danger') } }
async function checkOut(e: any) { try { await api.post(`/hr/attendance/check-out?employee_id=${e.id}`); await loadAtt(); await load(); toast('Ketdi ✓') } catch (x: any) { toast(x.detail ?? 'Xato', 'danger') } }

// ---- oylik
const period = ref(new Date().toISOString().slice(0, 7))
const payroll = ref<any[]>([])
async function loadPayroll() { payroll.value = await api.get('/hr/payroll', { period: period.value + '-01' }) }
async function compute() { payroll.value = await api.post(`/hr/payroll/compute?period=${period.value}-01`); toast('Hisoblandi') }
async function patchSlip(s: any, k: string, v: any) { const r = await api.patch(`/hr/payroll/${s.id}`, { [k]: Number(v) }); Object.assign(s, r) }
async function setStatus(s: any, st: string) { try { Object.assign(s, await api.post(`/hr/payroll/${s.id}/status?status=${st}`)) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
const payrollTotal = computed(() => payroll.value.reduce((x, s) => x + s.total, 0))
const fmtT = (s: string) => new Date(s).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' })
const fmtD = (s: string) => new Date(s).toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit', year: 'numeric' })
</script>

<template>
  <div class="hr">
    <div v-if="meta" class="kpis">
      <div class="kpi"><b>{{ meta.summary.employees }}</b><span>Xodim</span></div>
      <div class="kpi"><b>{{ meta.summary.on_shift }}</b><span>Hozir smenada</span></div>
      <div class="kpi"><b>{{ meta.summary.today_planned }}</b><span>Bugun rejada</span></div>
      <div class="kpi"><b>{{ money(meta.summary.payroll_month) }}</b><span>Shu oy oylik fondi</span></div>
    </div>
    <nav class="tabs">
      <button :class="{ on: tab === 'employees' }" @click="tab = 'employees'"><UiIcon name="users" :size="15" /> Xodimlar</button>
      <button :class="{ on: tab === 'schedule' }" @click="tab = 'schedule'"><UiIcon name="calendar" :size="15" /> Smena jadvali</button>
      <button :class="{ on: tab === 'attendance' }" @click="tab = 'attendance'"><UiIcon name="clock" :size="15" /> Davomat</button>
      <button v-if="a.can('hr.payroll')" :class="{ on: tab === 'payroll' }" @click="tab = 'payroll'"><UiIcon name="receipt" :size="15" /> Oylik</button>
    </nav>

    <!-- XODIMLAR -->
    <div v-if="tab === 'employees'" class="split">
      <div class="lst-wrap">
        <div class="bar"><UiInput v-model="q" placeholder="Ism yoki telefon" @keydown.enter="load()" /><UiButton v-if="canEdit" variant="brand" @click="openForm()"><UiIcon name="plus" :size="15" /> Xodim</UiButton></div>
        <div class="lst">
          <button v-for="e in employees" :key="e.id" class="emp" :class="{ sel: card?.employee.id === e.id }" @click="openCard(e)">
            <UiAvatar :name="e.full_name" :src="e.avatar" :online="e.on_shift" />
            <span class="nm"><b>{{ e.full_name }}</b><small>{{ e.position_name ?? '—' }} · {{ e.branch_name ?? '' }}</small></span>
            <UiChip :tone="ROLE_TONE[e.role_code] ?? 'neutral'">{{ e.role_name }}</UiChip>
            <span class="sal">{{ money(e.rate) }}<small>/{{ SAL[e.salary_type] }}</small></span>
            <span class="tk" :class="{ warn: e.tasks.overdue }"><UiIcon name="check" :size="12" /> {{ e.tasks.open ?? 0 }}<i v-if="e.tasks.overdue"> · {{ e.tasks.overdue }} kechikkan</i></span>
          </button>
          <UiEmpty v-if="!employees.length" title="Xodim yo'q" text="«Xodim» tugmasi bilan qo'shing — telefon raqami bilan kiradi." />
        </div>
      </div>

      <aside v-if="card" class="card">
        <header><UiAvatar :name="card.employee.full_name" :src="card.employee.avatar" :size="52" />
          <div><h3>{{ card.employee.full_name }}</h3><p>{{ card.employee.position_name ?? '—' }} · {{ card.employee.role_name }} · {{ card.employee.phone }}</p></div>
          <UiButton v-if="canEdit" size="s" variant="secondary" @click="openForm(card.employee)"><UiIcon name="edit" :size="14" /></UiButton>
          <button class="x" @click="card = null"><UiIcon name="x" /></button></header>
        <div class="stats">
          <div><span>Maosh</span><b>{{ money(card.employee.rate) }}<small>/{{ SAL[card.employee.salary_type] }}</small></b></div>
          <div><span>Shu oy davomat</span><b>{{ card.attendance_month.days }} kun · {{ card.attendance_month.hours }} s</b></div>
          <div><span>Kechikish</span><b :class="{ danger: card.attendance_month.late }">{{ card.attendance_month.late }} marta</b></div>
          <div><span>Ishga kirgan</span><b>{{ fmtD(card.employee.hire_date) }}</b></div>
        </div>
        <div class="acts">
          <RouterLink :to="`/hr/employee/${card.employee.id}`" class="full">To'liq profil →</RouterLink>
          <UiButton v-if="!card.employee.on_shift" size="s" @click="checkIn(card.employee)"><UiIcon name="clock" :size="14" /> Keldi</UiButton>
          <UiButton v-else size="s" variant="secondary" @click="checkOut(card.employee)">Ketdi</UiButton>
          <UiChip v-if="card.employee.telegram_id" tone="ok">Telegram ulangan</UiChip><UiChip v-else tone="neutral">Telegram: botga /start → telefon</UiChip>
        </div>
        <h4>Vazifalari <small>{{ card.tasks.length }}</small></h4>
        <ul class="tl">
          <li v-for="t in card.tasks" :key="t.id"><RouterLink :to="`/tasks`">#{{ t.number }}</RouterLink> {{ t.title }}
            <UiChip :tone="t.status === 'done' ? 'ok' : t.is_overdue ? 'danger' : t.status === 'review' ? 'info' : 'warn'">{{ t.is_overdue ? 'kechikkan' : ({ backlog: 'yangi', active: 'jarayonda', review: 'tekshiruvda', done: 'bajarildi' } as Record<string, string>)[t.status] }}</UiChip></li>
          <li v-if="!card.tasks.length" class="mut">Vazifa yo'q</li>
        </ul>
        <h4>Bu hafta smenalari</h4>
        <div class="chips"><UiChip v-for="s in card.shifts_week" :key="s.id" tone="neutral">{{ s.date.slice(5) }} · {{ s.start }}–{{ s.end }}</UiChip><span v-if="!card.shifts_week.length" class="mut">Rejalashtirilmagan</span></div>
        <h4>Oyliklar</h4>
        <div v-for="p in card.payslips" :key="p.id" class="slip"><span>{{ p.period.slice(0, 7) }}</span><b>{{ money(p.total) }}</b><UiChip :tone="p.status === 'paid' ? 'ok' : p.status === 'approved' ? 'info' : 'neutral'">{{ ({ draft: 'qoralama', approved: 'tasdiqlangan', paid: 'to\'langan' } as Record<string, string>)[p.status] }}</UiChip></div>
      </aside>
      <UiEmpty v-else title="Xodimni tanlang" text="Karta: maosh, davomat, vazifalar, oyliklar — bir joyda." />
    </div>

    <!-- JADVAL -->
    <div v-else-if="tab === 'schedule'" class="sched">
      <div class="bar"><UiButton size="s" variant="ghost" @click="shiftWeek(-1)">‹</UiButton><b>{{ days[0].toLocaleDateString('uz-UZ', { day: '2-digit', month: 'short' }) }} — {{ days[6].toLocaleDateString('uz-UZ', { day: '2-digit', month: 'short' }) }}</b><UiButton size="s" variant="ghost" @click="shiftWeek(1)">›</UiButton>
        <div class="sp"></div><UiButton v-if="canEdit" size="s" variant="secondary" @click="copyWeek()"><UiIcon name="repeat" :size="14" /> O'tgan haftadan nusxa</UiButton></div>
      <div class="grid"><div class="gh">Xodim</div><div v-for="d in days" :key="d.toDateString()" class="gh" :class="{ today: d.toDateString() === new Date().toDateString() }">{{ d.toLocaleDateString('uz-UZ', { weekday: 'short' }) }}<br /><small>{{ d.getDate() }}</small></div>
        <template v-for="e in employees" :key="e.id">
          <div class="gn"><b>{{ e.full_name }}</b><small>{{ e.position_name }}</small></div>
          <button v-for="d in days" :key="d.toDateString()" class="gc" :class="{ has: shiftOf(e.id, d) }" @click="toggleShift(e, d)">
            <span v-if="shiftOf(e.id, d)">{{ shiftOf(e.id, d).start }}–{{ shiftOf(e.id, d).end }}</span><span v-else class="mut">+</span>
          </button>
        </template>
      </div>
      <p class="hint">Katakni bosing — smena qo'shiladi/olinadi. Xodim Telegram botda /keldim /ketdim yozsa, davomat o'zi yoziladi.</p>
    </div>

    <!-- DAVOMAT -->
    <div v-else-if="tab === 'attendance'" class="att">
      <div class="lst">
        <div v-for="e in employees" :key="e.id" class="a-row">
          <UiAvatar :name="e.full_name" :src="e.avatar" :online="e.on_shift" />
          <span class="nm"><b>{{ e.full_name }}</b><small>{{ e.position_name }}</small></span>
          <span v-if="att.find(x => x.employee_id === e.id)" class="mut">keldi {{ fmtT(att.find(x => x.employee_id === e.id).check_in) }}<template v-if="att.find(x => x.employee_id === e.id).check_out"> · ketdi {{ fmtT(att.find(x => x.employee_id === e.id).check_out) }} · {{ att.find(x => x.employee_id === e.id).hours }} s</template>
            <UiChip v-if="att.find(x => x.employee_id === e.id).late_minutes" tone="danger">{{ att.find(x => x.employee_id === e.id).late_minutes }} daq kech</UiChip></span>
          <span v-else class="mut">bugun kelmagan</span>
          <span class="sp"></span>
          <UiButton v-if="!e.on_shift" size="s" @click="checkIn(e)">Keldi</UiButton>
          <UiButton v-else size="s" variant="secondary" @click="checkOut(e)">Ketdi</UiButton>
        </div>
      </div>
    </div>

    <!-- OYLIK -->
    <div v-else class="pay">
      <div class="bar"><input v-model="period" type="month" class="month" @change="loadPayroll()" /><UiButton size="s" variant="secondary" @click="compute()"><UiIcon name="repeat" :size="14" /> Hisoblash</UiButton><div class="sp"></div><b class="tot">Jami: {{ money(payrollTotal) }}</b></div>
      <div class="lst">
        <div class="p-h"><span>Xodim</span><span>Tur</span><span>Stavka</span><span>Soat / smena</span><span>Baza</span><span>Bonus</span><span>Jarima</span><span>Avans</span><span>Jami</span><span>Holat</span></div>
        <div v-for="s in payroll" :key="s.id" class="p-r">
          <span class="nm"><b>{{ s.employee_name }}</b><small>{{ s.position }}</small></span>
          <span class="mut">{{ SAL[s.salary_type] }}</span>
          <span>{{ money(s.rate) }}</span>
          <span class="mut">{{ s.hours }} s / {{ s.shifts }}</span>
          <span>{{ money(s.base) }}</span>
          <span><input :value="s.bonus" type="number" :disabled="s.status === 'paid'" @change="patchSlip(s, 'bonus', ($event.target as HTMLInputElement).value)" /></span>
          <span><input :value="s.penalty" type="number" :disabled="s.status === 'paid'" @change="patchSlip(s, 'penalty', ($event.target as HTMLInputElement).value)" /></span>
          <span><input :value="s.advance" type="number" :disabled="s.status === 'paid'" @change="patchSlip(s, 'advance', ($event.target as HTMLInputElement).value)" /></span>
          <span><b>{{ money(s.total) }}</b></span>
          <span class="st">
            <UiChip :tone="s.status === 'paid' ? 'ok' : s.status === 'approved' ? 'info' : 'neutral'">{{ ({ draft: 'qoralama', approved: 'tasdiq', paid: 'to\'landi' } as Record<string, string>)[s.status] }}</UiChip>
            <UiButton v-if="s.status === 'draft'" size="s" variant="ghost" @click="setStatus(s, 'approved')">Tasdiq</UiButton>
            <UiButton v-else-if="s.status === 'approved'" size="s" variant="ghost" @click="setStatus(s, 'paid')">To'landi</UiButton>
          </span>
        </div>
        <UiEmpty v-if="!payroll.length" title="Bu oy uchun hisob yo'q" text="«Hisoblash» — davomat va stavkalardan qoralama tuziladi." />
      </div>
      <p class="hint">Oylik P&L hisobotida «Mehnat» qatoriga tushadi. Baza: oylik = stavka · soatbay = stavka × soat · smenabay = stavka × smena · % = savdo × foiz.</p>
    </div>

    <UiDrawer :open="drawer" :title="form?.id ? 'Xodim kartasi' : 'Yangi xodim'" width="560px" @close="drawer = false">
      <template v-if="form && meta">
        <div class="grid2">
          <UiInput v-model="form.full_name" label="F.I.O." /><UiInput v-model="form.phone" label="Telefon (login)" :disabled="!!form.id" />
          <UiSelect v-model="form.role_code" label="Rol (ruxsatlar)" :options="meta.roles.map((r: any) => ({ value: r.code, label: r.name }))" />
          <UiSelect :model-value="String(form.position_id ?? '')" label="Lavozim" :options="[{ value: '', label: '—' }, ...meta.positions.map((p: any) => ({ value: String(p.id), label: p.name }))]" @update:model-value="onPosition" />
          <UiSelect :model-value="String(form.branch_id ?? '')" label="Filial" :options="meta.branches.map((b: any) => ({ value: String(b.id), label: b.name }))" @update:model-value="v => form.branch_id = Number(v)" />
          <label class="fl"><span>Ishga kirgan sana</span><input v-model="form.hire_date" type="date" /></label>
          <UiSelect v-model="form.salary_type" label="Maosh turi" :options="meta.salary_types.map((s: any) => ({ value: s.code, label: s.label }))" />
          <UiInput v-model="form.rate" type="number" :label="form.salary_type === 'percent' ? 'Foiz × 100 (2.5% = 250)' : 'Stavka (so\'m)'" />
          <UiInput v-model="form.card_number" label="Karta raqami (oylik)" /><UiInput v-model="form.pinfl" label="PINFL" />
          <UiInput v-model="form.passport" label="Pasport" /><UiInput v-model="form.emergency_phone" label="Favqulodda aloqa" />
        </div>
        <UiInput v-model="form.note" label="Izoh" />
        <label class="fl chk"><input v-model="form.is_active" type="checkbox" /> Faol xodim (o'chirilsa — ishdan bo'shagan sana yoziladi)</label>
      </template>
      <template #footer><UiButton variant="ghost" @click="drawer = false">Bekor</UiButton><UiButton variant="brand" @click="save()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.hr { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px 14px; display: flex; flex-direction: column; }
.kpi b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; } .kpi span { font-size: var(--fs-xs); color: var(--muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 9px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.split { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; align-items: start; }
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.lst { display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); overflow: hidden; }
.emp { display: grid; grid-template-columns: 36px 1.6fr auto 1fr 1fr; gap: 10px; align-items: center; padding: 10px 14px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; cursor: pointer; }
.emp:hover, .emp.sel { background: var(--accent-tint); }
.ava { width: 34px; height: 34px; border-radius: 10px; background: var(--surface-3); color: var(--ink-2); display: grid; place-items: center; font-size: 11px; font-weight: 800; position: relative; }
.ava.on::after { content: ''; position: absolute; right: -2px; bottom: -2px; width: 10px; height: 10px; border-radius: 50%; background: var(--ok); border: 2px solid var(--surface); }
.ava.big { width: 48px; height: 48px; font-size: 15px; }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { color: var(--muted); font-size: var(--fs-xs); }
.sal { font-size: var(--fs-s); } .sal small { color: var(--muted); }
.tk { font-size: var(--fs-xs); color: var(--muted); display: inline-flex; align-items: center; gap: 4px; } .tk.warn { color: var(--danger); } .tk i { font-style: normal; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 14px; display: flex; flex-direction: column; gap: 10px; position: sticky; top: calc(var(--topbar-h) + var(--gutter)); }
.card header { display: flex; gap: 10px; align-items: center; } .card h3 { margin: 0; font-family: var(--font-display); } .card p { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.card header > div { flex: 1; } .x { border: 0; background: transparent; cursor: pointer; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; } .stats div { background: var(--surface-2); border-radius: var(--radius); padding: 8px 10px; display: flex; flex-direction: column; }
.stats span { font-size: var(--fs-xs); color: var(--muted); } .stats b { font-size: var(--fs-b); } .stats small { color: var(--muted); font-weight: 600; }
.acts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.card h4 { margin: 6px 0 0; font-size: var(--fs-s); } .card h4 small { color: var(--muted); }
.tl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); } .tl li { display: flex; gap: 6px; align-items: center; }
.chips { display: flex; gap: 4px; flex-wrap: wrap; }
.slip { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; font-size: var(--fs-s); align-items: center; }
.mut { color: var(--muted); font-size: var(--fs-xs); } .danger { color: var(--danger); }
.grid { display: grid; grid-template-columns: 180px repeat(7, 1fr); gap: 4px; }
.gh { font-size: var(--fs-xs); font-weight: 800; color: var(--muted); text-align: center; padding: 6px; } .gh.today { color: var(--accent); }
.gn { display: flex; flex-direction: column; padding: 6px; font-size: var(--fs-s); } .gn small { color: var(--muted); font-size: 10px; }
.gc { min-height: 44px; border: 1px dashed var(--line); border-radius: var(--radius-s); background: var(--surface); cursor: pointer; font-size: 11px; font-weight: 700; }
.gc.has { background: var(--accent-tint); color: var(--accent); border-style: solid; border-color: var(--accent); }
.hint { color: var(--muted); font-size: var(--fs-xs); margin: 8px 0 0; }
.a-row { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.month { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; min-height: var(--touch); }
.tot { font-family: var(--font-display); font-size: var(--fs-l); }
.p-h, .p-r { display: grid; grid-template-columns: 1.6fr .7fr 1fr .9fr 1fr .8fr .8fr .8fr 1fr 1.4fr; gap: 6px; align-items: center; padding: 8px 12px; font-size: var(--fs-s); }
.p-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); } .p-r { border-top: 1px solid var(--line-2); }
.p-r input { width: 100%; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 4px 6px; font-size: var(--fs-s); }
.st { display: flex; gap: 4px; align-items: center; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fl { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.fl input[type=date] { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; min-height: var(--touch); background: var(--surface); }
.fl.chk { flex-direction: row; align-items: center; gap: 8px; margin-top: 8px; }
@media (max-width: 1100px) { .split { grid-template-columns: 1fr; } .card { position: static; } .kpis { grid-template-columns: 1fr 1fr; } .grid { grid-template-columns: 120px repeat(7, 1fr); } }
@media (max-width: 600px) { .emp { grid-template-columns: 36px 1fr; } .emp > :nth-child(n+3) { display: none; } .p-h { display: none; } .p-r { grid-template-columns: 1fr 1fr; } .grid2 { grid-template-columns: 1fr; } .grid { grid-template-columns: 90px repeat(7, 1fr); font-size: 10px; } }
.full { font-weight: 800; color: var(--accent); text-decoration: none; font-size: var(--fs-s); align-self: center; margin-right: auto; }
</style>
'@

Put 'frontend\apps\admin\src\views\KpiView.vue' @'
<script setup lang="ts">
/**
 * Baholash va KPI: oylik reyting (tizim ma'lumotidan avtomatik + menejer bahosi), A/B/C/D daraja,
 * «xavf» (kayfiyat past / davomat past), tavsiya bonus → qoralama oylikka bir tugma bilan yozish.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiInput, UiKpi, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter()
const now = new Date()
const ym = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
const month = ref(ym(now)), branch = ref<string>('')
const D = ref<any>(null), branches = ref<any[]>([]), loading = ref(false)
const MONTHS = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentyabr', 'Oktyabr', 'Noyabr', 'Dekabr']
const monthOpts = Array.from({ length: 6 }, (_, i) => { const d = new Date(now.getFullYear(), now.getMonth() - i, 1); return { value: ym(d), label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` } })
const GT: Record<string, any> = { A: 'ok', B: 'info', C: 'warn', D: 'danger', '—': 'neutral' }
const PARTS = ['attendance', 'punctuality', 'training', 'tasks', 'role', 'review']
const SHORT: Record<string, string> = { attendance: 'Davomat', punctuality: 'Vaqtida', training: 'O\'qitish', tasks: 'Vazifa', role: 'Natija', review: 'Baho' }
const short = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 2).replace('.', ',')} mln` : n >= 1e3 ? `${Math.round(n / 1e3)} ming` : String(n))
const MOOD = (m: number | null) => (m == null ? '—' : m >= 3.5 ? '😀' : m >= 2.75 ? '🙂' : m >= 2 ? '😐' : '🙁')

async function load() {
  loading.value = true
  try { D.value = await api.get(`/hr/kpi?month=${month.value}${branch.value ? `&branch_id=${branch.value}` : ''}`) } finally { loading.value = false }
}
onMounted(async () => { load(); branches.value = (await api.get('/hr/meta').catch(() => ({ branches: [] }))).branches })
watch([month, branch], load)

const rows = computed(() => D.value?.rows ?? [])
const top3 = computed(() => rows.value.filter((r: any) => r.score != null).slice(0, 3))
const tone = (v: number) => (v >= 85 ? 'a' : v >= 70 ? 'b' : v >= 50 ? 'c' : 'd')
const brOpts = computed(() => [{ value: '', label: 'Barcha filiallar' }, ...branches.value.map((b: any) => ({ value: String(b.id), label: b.name }))])
const isCurrent = computed(() => month.value === ym(now))

// baholash
const rv = ref<any>(null)
function review(r: any) { rv.value = { row: r, month: D.value.month, scores: Object.fromEntries(D.value.criteria.map((c: any) => [c.key, 0])), strengths: '', improve: '', goals: '' } }
async function saveReview() {
  const { row, ...b } = rv.value
  try { await api.post(`/hr/employees/${row.employee_id}/reviews`, b); rv.value = null; toast('Baho saqlandi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const pick = ref<Set<number>>(new Set())
const bonusRows = computed(() => rows.value.filter((r: any) => r.bonus_suggest > 0))
function toggleAll() { pick.value = pick.value.size === bonusRows.value.length ? new Set() : new Set(bonusRows.value.map((r: any) => r.employee_id)) }
async function applyBonus() {
  const ids = [...pick.value]
  if (!ids.length) return toast('Xodimlarni belgilang', 'danger')
  if (!confirm(`${ids.length} xodimga KPI bonusi qoralama oylikka yozilsinmi?`)) return
  try { const r = await api.post('/hr/kpi/apply-bonus', { month: D.value.month, employee_ids: ids }); toast(r.updated ? `${r.updated} ta oylikka yozildi` : 'Qoralama oylik topilmadi — avval «Oylik»da hisoblang', r.updated ? 'ok' : 'danger'); pick.value = new Set() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div class="kp">
    <header class="top">
      <div><h1>Baholash va KPI</h1><p>Ball tizimdagi haqiqiy ma'lumotdan: davomat, kechikish, o'qitish, vazifalar, ish natijasi + menejer bahosi</p></div>
      <div class="flt"><UiSelect v-model="month" :options="monthOpts" /><UiSelect v-model="branch" :options="brOpts" /></div>
    </header>

    <template v-if="D">
      <div class="kpis">
        <UiKpi label="O'rtacha ball" :value="D.summary.avg ?? '—'" />
        <UiKpi label="A daraja" :value="D.summary.grades.A" tone="ok" />
        <UiKpi label="D daraja" :value="D.summary.grades.D" :tone="D.summary.grades.D ? 'danger' : 'muted'" />
        <UiKpi label="Xavf ostida" :value="D.summary.risk" :tone="D.summary.risk ? 'warn' : 'muted'" note="kayfiyat yoki davomat past" />
        <UiKpi label="Baholangan" :value="`${D.summary.reviewed}/${D.summary.total}`" note="menejer bahosi" />
        <UiKpi label="Tavsiya bonus" :value="short(D.summary.bonus_total)" note="A — 10%, B — 5%" />
      </div>

      <div v-if="top3.length" class="podium">
        <button v-for="(r, i) in top3" :key="r.employee_id" type="button" class="pd" :class="`p${i + 1}`" @click="router.push(`/hr/employee/${r.employee_id}?tab=kpi`)">
          <span class="medal">{{ ['🥇', '🥈', '🥉'][i] }}</span>
          <UiAvatar :name="r.full_name" :src="r.avatar" :size="52" />
          <b>{{ r.full_name }}</b><small>{{ r.position || '—' }}</small>
          <span class="sc">{{ r.score }}</span>
        </button>
      </div>

      <UiCard title="Reyting" :subtitle="`Og'irliklar: ${D.weights.map((w: any) => `${w.label} ${w.weight}`).join(' · ')}. Ma'lumot yo'q ko'rsatkich hisobga olinmaydi.`" :padded="false">
        <template #actions>
          <UiButton v-if="a.can('hr.payroll') && bonusRows.length" size="s" variant="secondary" @click="toggleAll">{{ pick.size === bonusRows.length ? 'Belgini olish' : 'Bonuslilarni belgilash' }}</UiButton>
          <UiButton v-if="a.can('hr.payroll') && bonusRows.length" size="s" variant="brand" :disabled="!pick.size" @click="applyBonus">Bonusni oylikka yozish ({{ pick.size }})</UiButton>
        </template>
        <div class="tw">
          <table>
            <thead><tr><th></th><th>#</th><th>Xodim</th><th class="c">Ball</th><th v-for="p in PARTS" :key="p" class="c">{{ SHORT[p] }}</th><th class="c">Kayfiyat</th><th class="r">Bonus</th><th></th></tr></thead>
            <tbody>
              <tr v-for="r in rows" :key="r.employee_id" :class="{ risk: r.risk }">
                <td><input v-if="r.bonus_suggest" type="checkbox" :checked="pick.has(r.employee_id)" :aria-label="`${r.full_name} bonus`" @change="pick.has(r.employee_id) ? pick.delete(r.employee_id) : pick.add(r.employee_id)" /></td>
                <td class="rk">{{ r.rank ?? '—' }}</td>
                <td><button type="button" class="who" @click="router.push(`/hr/employee/${r.employee_id}?tab=kpi`)"><UiAvatar :name="r.full_name" :src="r.avatar" :size="30" /><span><b>{{ r.full_name }}</b><small>{{ r.position || '—' }}<template v-if="r.branch"> · {{ r.branch }}</template></small></span></button></td>
                <td class="c"><span class="score"><b>{{ r.score ?? '—' }}</b><UiChip :tone="GT[r.grade]">{{ r.grade }}</UiChip></span></td>
                <td v-for="p in PARTS" :key="p" class="c">
                  <span v-if="r.parts[p]" class="cell" :title="r.parts[p].text"><i :class="tone(r.parts[p].value)" :style="{ width: r.parts[p].value + '%' }"></i><em>{{ r.parts[p].value }}</em></span>
                  <span v-else class="na">—</span>
                </td>
                <td class="c" :title="r.mood ? `${r.mood} / 4 · ${r.mood_count} smena` : ''">{{ MOOD(r.mood) }}</td>
                <td class="r">{{ r.bonus_suggest ? money(r.bonus_suggest) : '—' }}</td>
                <td><UiButton v-if="a.can('hr.review')" size="s" :variant="r.reviewed ? 'ghost' : 'secondary'" @click="review(r)">{{ r.reviewed ? 'Qayta' : 'Baholash' }}</UiButton></td>
              </tr>
            </tbody>
          </table>
          <UiEmpty v-if="!rows.length" title="Xodim yo'q" />
        </div>
      </UiCard>
      <p class="note">💡 {{ isCurrent ? 'Joriy oy — ball kun sayin yangilanadi.' : 'O\'tgan oy natijasi.' }} Xavf belgisi: smenadan keyingi kayfiyat o'rtachasi 2.5 dan past yoki davomat 70% dan kam — xodim bilan suhbatlashing.</p>
    </template>

    <UiDrawer :open="!!rv" :title="`Baholash · ${rv?.row.full_name ?? ''}`" @close="rv = null">
      <template v-if="rv">
        <div v-for="c in D.criteria" :key="c.key" class="star">
          <span>{{ c.label }}</span>
          <span class="st"><button v-for="n in 5" :key="n" type="button" :class="{ on: rv.scores[c.key] >= n }" :aria-label="`${n} yulduz`" @click="rv.scores[c.key] = n">★</button></span>
        </div>
        <p class="mut">Kamida 3 mezonni baholang.</p>
        <UiInput v-model="rv.strengths" label="Kuchli tomoni" />
        <UiInput v-model="rv.improve" label="Nimani yaxshilash kerak" />
        <UiInput v-model="rv.goals" label="Keyingi oy maqsadi (xodimga Telegram'da boradi)" />
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="rv = null">Bekor</UiButton><UiButton variant="brand" @click="saveReview">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.kp { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.top h1 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; } .top p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); max-width: 620px; }
.flt { display: flex; gap: 8px; min-width: 320px; } .flt > * { flex: 1; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.podium { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.pd { border: 1px solid var(--line); background: var(--surface); border-radius: 16px; padding: 14px; display: flex; flex-direction: column; align-items: center; gap: 4px; cursor: pointer; font: inherit; color: var(--ink); position: relative; }
.pd.p1 { border-color: var(--series-4); box-shadow: 0 0 0 1px var(--series-4) inset; }
.pd small { color: var(--muted); font-size: var(--fs-xs); } .medal { position: absolute; top: 8px; left: 10px; font-size: 22px; }
.pd .sc { font-family: var(--font-display); font-size: 26px; font-weight: 800; }
.tw { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
th { text-align: left; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; padding: 10px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 8px; border-bottom: 1px solid var(--line-2); vertical-align: middle; }
tr.risk td:nth-child(3) { box-shadow: inset 3px 0 0 var(--danger); }
.c { text-align: center; } .r { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; } .rk { color: var(--muted); font-weight: 800; }
.who { display: flex; gap: 8px; align-items: center; border: 0; background: none; cursor: pointer; font: inherit; color: var(--ink); text-align: left; padding: 0; }
.who span { display: flex; flex-direction: column; } .who small { color: var(--muted); font-size: var(--fs-xs); }
.score { display: inline-flex; gap: 6px; align-items: center; } .score b { font-size: 16px; font-variant-numeric: tabular-nums; }
.cell { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; width: 56px; }
.cell i { display: block; height: 6px; border-radius: 99px; align-self: flex-start; }
.cell i.a { background: var(--ok); } .cell i.b { background: var(--info); } .cell i.c { background: var(--warn); } .cell i.d { background: var(--danger); }
.cell em { font-style: normal; font-size: var(--fs-xs); font-variant-numeric: tabular-nums; } .na { color: var(--line); }
.note, .mut { color: var(--muted); font-size: var(--fs-s); margin: 0; } .sp { flex: 1; }
.star { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 0; font-size: var(--fs-s); font-weight: 600; }
.st button { border: 0; background: none; font-size: 26px; color: var(--line); cursor: pointer; padding: 0 2px; line-height: 1; } .st button.on { color: var(--series-4); }
@media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, 1fr); } .podium { grid-template-columns: 1fr; } .flt { min-width: 0; width: 100%; } }
</style>
'@

Put 'frontend\apps\admin\src\views\RecruitView.vue' @'
<script setup lang="ts">
/**
 * Ishga olish: vakansiyalar (saytda va Telegram botda chiqadi) + nomzodlar taxtasi (bosqichlar bo'yicha).
 * Nomzod kartasi: javoblar, oldingi ish joylari, baho, izoh, tarix; suhbatga chaqirish (vaqt + joy → Telegram xabar),
 * rad etish (sabab), qabul qilish → xodim kartasi avtomatik ochiladi.
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiKpi, UiSelect, money, toast } from '@restopos/ui'
import { uploadWithProgress, fmtDateTime } from '@/components/training/upload'

const router = useRouter()
const tab = ref<'board' | 'vacancies'>('board')
const V = ref<any[]>([]), A = ref<any[]>([]), S = ref<any>(null), M = ref<any>(null)
const fVac = ref<string>(''), q = ref('')

const STAGES = [
  { key: 'new', label: 'Yangi', tone: 'info' }, { key: 'screen', label: 'Ko\'rib chiqilmoqda', tone: 'neutral' },
  { key: 'interview', label: 'Suhbat', tone: 'accent' }, { key: 'trial', label: 'Sinov kuni', tone: 'warn' },
  { key: 'offer', label: 'Taklif', tone: 'warn' }, { key: 'hired', label: 'Qabul qilindi', tone: 'ok' }, { key: 'rejected', label: 'Rad etildi', tone: 'danger' },
] as const
const SRC: Record<string, string> = { site: 'Sayt', telegram: 'Telegram', manual: 'Qo\'lda', referral: 'Tavsiya' }
const EMP = [{ value: 'full', label: 'To\'liq stavka' }, { value: 'part', label: 'Yarim stavka' }, { value: 'shift', label: 'Smenali' }, { value: 'intern', label: 'Amaliyot / o\'quvchi' }]
const VST = [{ value: 'draft', label: 'Qoralama' }, { value: 'open', label: 'Ochiq — saytda ko\'rinadi' }, { value: 'paused', label: 'To\'xtatilgan' }, { value: 'closed', label: 'Yopilgan' }]
const VTONE: Record<string, any> = { open: 'ok', draft: 'neutral', paused: 'warn', closed: 'danger' }

async function load() {
  const [v, a, s] = await Promise.all([api.get('/hr/vacancies'), api.get('/hr/applications'), api.get('/hr/recruit/stats')])
  V.value = v; A.value = a; S.value = s
  if (!M.value) M.value = await api.get('/hr/meta').catch(() => ({ positions: [], roles: [], branches: [], salary_types: [] }))
}
onMounted(load)

const filtered = computed(() => {
  const s = q.value.trim().toLowerCase()
  return A.value.filter((a) => (!fVac.value || String(a.vacancy_id) === fVac.value) && (!s || a.full_name.toLowerCase().includes(s) || a.phone.includes(s)))
})
const col = (k: string) => filtered.value.filter((a) => a.stage === k)
const vacOpts = computed(() => [{ value: '', label: 'Barcha vakansiyalar' }, ...V.value.map((v) => ({ value: String(v.id), label: `${v.title} (${v.applications})` }))])
const ago = (s: string) => { const h = Math.round((Date.now() - new Date(s).getTime()) / 36e5); return h < 1 ? 'hozir' : h < 24 ? `${h} soat oldin` : `${Math.round(h / 24)} kun oldin` }

// ------------------------------------------------ vakansiya muharriri
const ed = ref<any>(null), imgFile = ref<File | null>(null), saving = ref(false)
function newVac() {
  ed.value = { id: null, title: '', role_code: 'waiter', position_id: null, branch_id: null, employment: 'full', salary_from: 0, salary_to: 0, salary_note: '',
    schedule: '', summary: '', requirements: [''], duties: [''], benefits: ['Bepul ovqat', 'Rasmiy ishga joylashtirish'], image_url: '', video_url: '', link_url: '',
    questions: [{ text: 'Kechki smenada ishlay olasizmi?', type: 'yesno', must: 'ha' }], status: 'draft', closes_on: '' }
  imgFile.value = null
}
function editVac(v: any) {
  ed.value = JSON.parse(JSON.stringify({ ...v, closes_on: v.closes_on || '', requirements: v.requirements.length ? v.requirements : [''], duties: v.duties.length ? v.duties : [''], benefits: v.benefits.length ? v.benefits : [''] }))
  imgFile.value = null
}
async function saveVac() {
  const e = ed.value; saving.value = true
  const body = { ...e, salary_from: Number(e.salary_from) || 0, salary_to: Number(e.salary_to) || 0, position_id: e.position_id || null, branch_id: e.branch_id || null, closes_on: e.closes_on || null }
  try {
    let v = e.id ? await api.put(`/hr/vacancies/${e.id}`, body) : await api.post('/hr/vacancies', body)
    if (imgFile.value) v = await uploadWithProgress(`/hr/vacancies/${v.id}/image`, imgFile.value)
    ed.value = null; toast(v.is_open ? 'Saqlandi — saytda va botda ko\'rinadi' : 'Saqlandi'); await load()
  } catch (err: any) { toast(err.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
async function delVac(v: any) {
  if (!confirm(`«${v.title}» o'chirilsinmi? (arizalar bo'lsa — yopiladi)`)) return
  const r = await api.del(`/hr/vacancies/${v.id}`); toast(r.closed ? 'Arizalar bor — vakansiya yopildi' : 'O\'chirildi'); await load()
}
const copy = (s: string) => { navigator.clipboard?.writeText(s); toast('Havola nusxalandi') }
const siteLink = (v: any) => location.origin + v.public_path
const roleOpts = computed(() => (M.value?.roles || []).map((r: any) => ({ value: r.code, label: r.name })))
const posOpts = computed(() => [{ value: '', label: '—' }, ...(M.value?.positions || []).map((p: any) => ({ value: p.id, label: p.name }))])
const brOpts = computed(() => [{ value: '', label: 'Barcha filiallar' }, ...(M.value?.branches || []).map((b: any) => ({ value: b.id, label: b.name }))])

// ------------------------------------------------ nomzod kartasi
const C = ref<any>(null), act = ref<any>(null), msg = ref('')
async function openApp(a: any) { C.value = await api.get(`/hr/applications/${a.id}`); act.value = null; msg.value = '' }
async function patch(b: any) { C.value = await api.patch(`/hr/applications/${C.value.id}`, b); const i = A.value.findIndex((x) => x.id === C.value.id); if (i >= 0) A.value[i] = { ...A.value[i], rating: C.value.rating } }
function startMove(stage: string) {
  const need = stage === 'interview' || stage === 'trial'
  if (!need && stage !== 'rejected' && stage !== 'hired') return doMove({ stage })
  if (stage === 'hired') {
    const v = V.value.find((x) => x.id === C.value.vacancy_id)
    act.value = { kind: 'hire', role_code: v?.role_code || 'waiter', branch_id: v?.branch_id || '', position_id: v?.position_id || '', salary_type: 'monthly', rate: v?.salary_from || 0 }
    return
  }
  const t = new Date(Date.now() + 864e5); t.setHours(11, 0, 0, 0)
  const loc = new Date(t.getTime() - t.getTimezoneOffset() * 6e4).toISOString().slice(0, 16)
  act.value = { kind: stage, stage, interview_at: need ? loc : '', place: '', reason: '', note: '', notify: true }
}
async function doMove(b: any) {
  try {
    const body = { ...b }; if (body.interview_at) body.interview_at = new Date(body.interview_at).toISOString(); else delete body.interview_at
    C.value = await api.post(`/hr/applications/${C.value.id}/stage`, body); act.value = null; toast(`Bosqich: ${C.value.stage_label}`); await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function hire() {
  const x = act.value
  try {
    const r = await api.post(`/hr/applications/${C.value.id}/hire`, { role_code: x.role_code, branch_id: x.branch_id || null, position_id: x.position_id || null, salary_type: x.salary_type, rate: Number(x.rate) || 0 })
    toast('Xodim kartasi ochildi 🎉'); C.value = null; act.value = null; await load(); router.push(`/hr/employee/${r.employee_id}`)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function send() {
  try { await api.post(`/hr/applications/${C.value.id}/message`, { text: msg.value }); msg.value = ''; toast('Telegram\'ga yuborildi'); C.value = await api.get(`/hr/applications/${C.value.id}`) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
// qo'lda nomzod
const add = ref<any>(null)
async function saveAdd() {
  try { const a = await api.post('/hr/applications', { ...add.value, vacancy_id: add.value.vacancy_id || null, birth_year: Number(add.value.birth_year) || null }); add.value = null; await load(); openApp(a) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const nextStages = computed(() => {
  if (!C.value) return []
  const order = ['new', 'screen', 'interview', 'trial', 'offer', 'hired']
  const i = order.indexOf(C.value.stage)
  return C.value.stage === 'hired' ? [] : STAGES.filter((s) => s.key !== C.value.stage && (order.indexOf(s.key) > i || s.key === 'rejected' || C.value.stage === 'rejected'))
})
</script>

<template>
  <div class="rc">
    <header class="top">
      <div><h1>Ishga olish</h1><p>Vakansiya → saytda va Telegram botda ariza → suhbat → sinov kuni → xodim kartasi</p></div>
      <div class="acts">
        <UiButton variant="secondary" @click="add = { full_name: '', phone: '', vacancy_id: fVac || '', birth_year: '', experience: '', source: 'manual' }"><UiIcon name="plus" :size="16" /> Nomzod</UiButton>
        <UiButton variant="brand" @click="newVac"><UiIcon name="megaphone" :size="16" /> Vakansiya</UiButton>
      </div>
    </header>

    <div v-if="S" class="kpis">
      <UiKpi label="Ochiq vakansiya" :value="S.open" />
      <UiKpi label="Yangi ariza" :value="S.new" />
      <UiKpi label="Ariza (30 kun)" :value="S.applications_30d" />
      <UiKpi label="Kutilayotgan suhbat" :value="S.interviews_upcoming" />
      <UiKpi label="Qabul (30 kun)" :value="S.hired_30d" />
      <UiKpi label="O'rtacha yollash" :value="S.time_to_hire != null ? `${S.time_to_hire} kun` : '—'" />
    </div>

    <nav class="tabs">
      <button :class="{ on: tab === 'board' }" @click="tab = 'board'"><UiIcon name="columns" :size="15" /> Nomzodlar <small>{{ A.length }}</small></button>
      <button :class="{ on: tab === 'vacancies' }" @click="tab = 'vacancies'"><UiIcon name="megaphone" :size="15" /> Vakansiyalar <small>{{ V.length }}</small></button>
    </nav>

    <!-- NOMZODLAR TAXTASI -->
    <template v-if="tab === 'board'">
      <div class="flt"><UiSelect v-model="fVac" :options="vacOpts" /><UiInput v-model="q" placeholder="Ism yoki telefon…" /></div>
      <div class="board">
        <section v-for="s in STAGES" :key="s.key" class="colm">
          <header><UiChip :tone="s.tone as any">{{ s.label }}</UiChip><b>{{ col(s.key).length }}</b></header>
          <button v-for="a in col(s.key)" :key="a.id" class="card" :class="{ ko: a.knocked_out }" @click="openApp(a)">
            <span class="nm">{{ a.full_name }}<em v-if="a.rating">{{ '★'.repeat(a.rating) }}</em></span>
            <span class="vc">{{ a.vacancy || 'Vakansiyasiz' }}<template v-if="a.age"> · {{ a.age }} yosh</template></span>
            <span v-if="a.interview_at && (a.stage === 'interview' || a.stage === 'trial')" class="iv"><UiIcon name="calendar" :size="12" /> {{ fmtDateTime(a.interview_at) }}</span>
            <span class="ft"><span class="src">{{ SRC[a.source] || a.source }}</span><span v-if="a.knocked_out" class="kot">talabga mos emas</span><span class="ago">{{ ago(a.created_at) }}</span></span>
          </button>
          <p v-if="!col(s.key).length" class="none">—</p>
        </section>
      </div>
    </template>

    <!-- VAKANSIYALAR -->
    <div v-else class="vgrid">
      <article v-for="v in V" :key="v.id" class="vac">
        <div class="vimg" :style="v.image ? { backgroundImage: `url(${v.image})` } : {}"><UiIcon v-if="!v.image" name="megaphone" :size="30" /><UiChip :tone="VTONE[v.status]" class="vs">{{ v.status_label }}</UiChip></div>
        <div class="vb">
          <h3>{{ v.title }}</h3>
          <p class="sal">{{ v.salary_text }}</p>
          <p class="mut">{{ v.employment_label }}<template v-if="v.schedule"> · {{ v.schedule }}</template><template v-if="v.branch"> · {{ v.branch }}</template></p>
          <div class="vst">
            <span><b>{{ v.applications }}</b> ariza</span><span><b>{{ v.new }}</b> yangi</span><span><b>{{ v.by_stage?.hired || 0 }}</b> qabul</span><span><b>{{ v.views }}</b> ko'rildi</span>
          </div>
          <div class="vl">
            <button v-if="v.is_open" type="button" @click="copy(siteLink(v))"><UiIcon name="globe" :size="13" /> Sayt havolasi</button>
            <button v-if="v.bot_link" type="button" @click="copy(v.bot_link)"><UiIcon name="send" :size="13" /> Bot havolasi</button>
            <a v-if="v.is_open" :href="v.public_path" target="_blank" rel="noopener"><UiIcon name="eye" :size="13" /> Ko'rish</a>
          </div>
          <div class="vbtn">
            <UiButton size="s" variant="secondary" @click="fVac = String(v.id); tab = 'board'">Nomzodlar</UiButton>
            <UiButton size="s" variant="ghost" @click="editVac(v)"><UiIcon name="edit" :size="14" /></UiButton>
            <UiButton size="s" variant="ghost" @click="delVac(v)"><UiIcon name="trash" :size="14" /></UiButton>
          </div>
        </div>
      </article>
      <UiEmpty v-if="!V.length" title="Vakansiya yo'q" text="Birinchi vakansiyani yarating — saytda «Vakansiyalar» bo'limi va botda «💼 Vakansiyalar» tugmasi paydo bo'ladi." />
    </div>

    <!-- VAKANSIYA MUHARRIRI -->
    <UiDrawer :open="!!ed" :title="ed?.id ? 'Vakansiyani tahrirlash' : 'Yangi vakansiya'" width="640px" @close="ed = null">
      <template v-if="ed">
        <UiInput v-model="ed.title" label="Lavozim nomi" placeholder="Ofitsiant" />
        <div class="g3">
          <UiSelect v-model="ed.role_code" label="Tizimdagi rol" :options="roleOpts" />
          <UiSelect v-model="ed.position_id" label="Lavozim (maosh uchun)" :options="posOpts" />
          <UiSelect v-model="ed.branch_id" label="Filial" :options="brOpts" />
        </div>
        <div class="g3">
          <UiInput v-model="ed.salary_from" type="number" label="Maosh — dan" suffix="so'm" />
          <UiInput v-model="ed.salary_to" type="number" label="gacha" suffix="so'm" />
          <UiSelect v-model="ed.employment" label="Bandlik" :options="EMP" />
        </div>
        <div class="g2"><UiInput v-model="ed.salary_note" label="Maosh izohi" placeholder="+ choychaqa, KPI bonus" /><UiInput v-model="ed.schedule" label="Ish grafigi" placeholder="2/2, 10:00–23:00" /></div>
        <label class="fld"><span>Qisqacha tavsif</span><textarea v-model="ed.summary" rows="3" placeholder="Jamoamizga tajribali va xushmuomala ofitsiant kerak…"></textarea></label>
        <div v-for="k in (['requirements', 'duties', 'benefits'] as const)" :key="k" class="lst">
          <span class="lh">{{ { requirements: 'Talablar', duties: 'Majburiyatlar', benefits: 'Biz taklif qilamiz' }[k] }}</span>
          <div v-for="(_, i) in ed[k]" :key="i" class="lr"><input v-model="ed[k][i]" /><button type="button" aria-label="O'chirish" @click="ed[k].splice(i, 1)">✕</button></div>
          <button type="button" class="addl" @click="ed[k].push('')">+ qator</button>
        </div>
        <div class="media">
          <span class="lh">Rasm, video, havola</span>
          <UiInput v-model="ed.image_url" label="Rasm havolasi" placeholder="https://…" />
          <label class="fld"><span>yoki rasm yuklash (8 MB gacha)</span><input type="file" accept="image/*" @change="imgFile = ($event.target as HTMLInputElement).files?.[0] ?? null" /></label>
          <UiInput v-model="ed.video_url" label="Video (YouTube / Drive / mp4)" placeholder="https://youtube.com/watch?v=…" />
          <UiInput v-model="ed.link_url" label="Qo'shimcha havola" placeholder="Instagram, to'liq tavsif…" />
        </div>
        <div class="lst">
          <span class="lh">Saralash savollari <small>(«majburiy javob» — boshqa javob bersa «talabga mos emas» belgisi)</small></span>
          <div v-for="(x, i) in ed.questions" :key="i" class="qr">
            <input v-model="x.text" placeholder="Savol" />
            <select v-model="x.type"><option value="yesno">Ha / Yo'q</option><option value="text">Matn</option></select>
            <select v-if="x.type === 'yesno'" v-model="x.must"><option value="">farqi yo'q</option><option value="ha">«Ha» shart</option><option value="yo'q">«Yo'q» shart</option></select>
            <button type="button" aria-label="O'chirish" @click="ed.questions.splice(i, 1)">✕</button>
          </div>
          <button v-if="ed.questions.length < 10" type="button" class="addl" @click="ed.questions.push({ text: '', type: 'text', must: '' })">+ savol</button>
        </div>
        <div class="g2"><UiSelect v-model="ed.status" label="Holat" :options="VST" /><UiInput v-model="ed.closes_on" type="date" label="Qabul tugaydi (ixtiyoriy)" /></div>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="ed = null">Bekor</UiButton><UiButton variant="brand" :loading="saving" @click="saveVac">Saqlash</UiButton></template>
    </UiDrawer>

    <!-- NOMZOD KARTASI -->
    <UiDrawer :open="!!C" :title="C?.full_name" width="600px" @close="C = null">
      <template v-if="C">
        <div class="ch">
          <UiChip :tone="(STAGES.find((s) => s.key === C.stage)?.tone as any)">{{ C.stage_label }}</UiChip>
          <UiChip tone="neutral">{{ SRC[C.source] || C.source }}</UiChip>
          <UiChip v-if="C.knocked_out" tone="danger">Majburiy talabga mos emas</UiChip>
          <span class="sp"></span>
          <span class="rate"><button v-for="n in 5" :key="n" type="button" :class="{ on: C.rating >= n }" :aria-label="`${n}`" @click="patch({ rating: C.rating === n ? 0 : n })">★</button></span>
        </div>
        <dl class="dl">
          <dt>Vakansiya</dt><dd>{{ C.vacancy || '—' }}</dd>
          <dt>Telefon</dt><dd><a :href="`tel:${C.phone}`">{{ C.phone }}</a><template v-if="C.tg_username"> · <a :href="`https://t.me/${C.tg_username}`" target="_blank" rel="noopener">@{{ C.tg_username }}</a></template></dd>
          <dt>Yoshi</dt><dd>{{ C.age ? `${C.age} (${C.birth_year})` : '—' }}</dd>
          <dt v-if="C.interview_at">Uchrashuv</dt><dd v-if="C.interview_at">{{ fmtDateTime(C.interview_at) }} · {{ C.interview_place || '—' }}</dd>
          <dt v-if="C.reject_reason">Rad sababi</dt><dd v-if="C.reject_reason">{{ C.reject_reason }}</dd>
        </dl>
        <div v-if="C.photo" class="ph"><img :src="C.photo" alt="Nomzod rasmi" /></div>
        <h4>Savollarga javob</h4>
        <div v-for="(x, i) in C.answers" :key="i" class="ans"><span>{{ x.q }}</span><b :class="{ bad: x.ok === false }">{{ x.a || '—' }}</b></div>
        <p v-if="!C.answers?.length" class="mut">Savol yo'q</p>
        <h4>Tajriba</h4>
        <p class="pre">{{ C.experience || '—' }}</p>
        <div v-for="(w, i) in C.work_history" :key="i" class="wh"><b>{{ w.company }}</b> <span class="mut">{{ w.position }} {{ w.years }}</span></div>
        <label class="fld"><span>Ichki izoh (nomzod ko'rmaydi)</span><textarea :value="C.notes" rows="2" @change="patch({ notes: ($event.target as HTMLTextAreaElement).value })"></textarea></label>

        <template v-if="!act && C.stage !== 'hired'">
          <h4>Keyingi qadam</h4>
          <div class="mv"><UiButton v-for="s in nextStages" :key="s.key" size="s" :variant="s.key === 'hired' ? 'brand' : s.key === 'rejected' ? 'danger' : 'secondary'" @click="startMove(s.key)">{{ s.key === 'hired' ? '✓ Ishga qabul qilish' : s.label }}</UiButton></div>
        </template>
        <div v-else-if="act && act.kind !== 'hire'" class="box">
          <h4>{{ STAGES.find((s) => s.key === act.stage)?.label }}</h4>
          <template v-if="act.stage !== 'rejected'">
            <div class="g2"><UiInput v-model="act.interview_at" type="datetime-local" label="Sana va vaqt" /><UiInput v-model="act.place" label="Joy" placeholder="Chilonzor filiali, 2-qavat" /></div>
          </template>
          <UiInput v-else v-model="act.reason" label="Sabab (nomzodga muloyim xabar boradi, sabab — ichki)" placeholder="Tajriba yetarli emas" />
          <label class="chk"><input v-model="act.notify" type="checkbox" :disabled="!C.tg" /> Telegram orqali nomzodga xabar yuborish {{ C.tg ? '' : '(Telegram ulanmagan — telefon qiling)' }}</label>
          <div class="mv"><UiButton variant="ghost" size="s" @click="act = null">Bekor</UiButton><UiButton size="s" @click="doMove({ stage: act.stage, interview_at: act.interview_at, place: act.place, reason: act.reason, notify: act.notify })">Tasdiqlash</UiButton></div>
        </div>
        <div v-else-if="act?.kind === 'hire'" class="box">
          <h4>Ishga qabul qilish — xodim kartasi ochiladi</h4>
          <div class="g2"><UiSelect v-model="act.role_code" label="Rol" :options="roleOpts" /><UiSelect v-model="act.branch_id" label="Filial" :options="brOpts" /></div>
          <div class="g2"><UiSelect v-model="act.salary_type" label="Maosh turi" :options="(M?.salary_types || []).map((s: any) => ({ value: s.code, label: s.label }))" /><UiInput v-model="act.rate" type="number" label="Stavka" suffix="so'm" /></div>
          <p class="mut">Tizimga kirish: telefon {{ C.phone }} · ish tarixi anketadan ko'chiriladi{{ C.tg ? ' · Telegram\'ga tabrik boradi' : '' }}.</p>
          <div class="mv"><UiButton variant="ghost" size="s" @click="act = null">Bekor</UiButton><UiButton variant="brand" size="s" @click="hire">Qabul qilish · {{ money(Number(act.rate) || 0) }}</UiButton></div>
        </div>
        <UiButton v-if="C.employee_id" variant="secondary" @click="router.push(`/hr/employee/${C.employee_id}`)">Xodim profilini ochish →</UiButton>

        <template v-if="C.tg">
          <h4>Telegram xabar</h4>
          <div class="send"><input v-model="msg" placeholder="Assalomu alaykum! Ertaga 11:00 da kela olasizmi?" @keydown.enter="msg && send()" /><UiButton size="s" :disabled="!msg" @click="send"><UiIcon name="send" :size="14" /></UiButton></div>
        </template>
        <h4>Tarix</h4>
        <ul class="ev"><li v-for="(e, i) in C.events" :key="i"><small>{{ fmtDateTime(e.at) }}<template v-if="e.actor"> · {{ e.actor }}</template></small>{{ e.text }}</li></ul>
      </template>
    </UiDrawer>

    <UiDrawer :open="!!add" title="Nomzod qo'shish (qo'lda)" @close="add = null">
      <template v-if="add">
        <UiInput v-model="add.full_name" label="Ism familiya" />
        <UiInput v-model="add.phone" label="Telefon" placeholder="+998 90 123 45 67" />
        <UiSelect v-model="add.vacancy_id" label="Vakansiya" :options="vacOpts" />
        <div class="g2"><UiInput v-model="add.birth_year" type="number" label="Tug'ilgan yil" /><UiSelect v-model="add.source" label="Manba" :options="[{ value: 'manual', label: 'Qo\'lda / telefon' }, { value: 'referral', label: 'Xodim tavsiyasi' }]" /></div>
        <label class="fld"><span>Tajriba</span><textarea v-model="add.experience" rows="3"></textarea></label>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="add = null">Bekor</UiButton><UiButton variant="brand" @click="saveAdd">Qo'shish</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.rc { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.top h1 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; } .top p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); }
.acts { display: flex; gap: 8px; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 10px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); } .tabs small { background: var(--surface-3); border-radius: 99px; padding: 0 7px; }
.flt { display: flex; gap: 10px; max-width: 640px; } .flt > * { flex: 1; }
.board { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(220px, 1fr); gap: 12px; overflow-x: auto; padding-bottom: 8px; }
.colm { background: var(--surface-2); border: 1px solid var(--line); border-radius: 16px; padding: 10px; display: flex; flex-direction: column; gap: 8px; min-height: 200px; }
.colm header { display: flex; justify-content: space-between; align-items: center; padding: 2px 4px 6px; }
.card { text-align: left; border: 1px solid var(--line); background: var(--surface); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; gap: 4px; cursor: pointer; font: inherit; color: var(--ink); }
.card:hover { border-color: var(--accent); } .card.ko { border-left: 3px solid var(--danger); }
.nm { font-weight: 800; display: flex; justify-content: space-between; gap: 6px; } .nm em { font-style: normal; color: var(--series-4); font-size: var(--fs-xs); }
.vc, .ago, .src { font-size: var(--fs-xs); color: var(--muted); }
.iv { font-size: var(--fs-xs); font-weight: 700; color: var(--accent); display: inline-flex; gap: 4px; align-items: center; }
.ft { display: flex; gap: 6px; align-items: center; } .ago { margin-left: auto; } .kot { font-size: 10px; font-weight: 800; color: var(--danger); }
.none { color: var(--muted); text-align: center; margin: 8px 0; }
.vgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.vac { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; }
.vimg { height: 130px; background: var(--surface-3) center / cover; display: grid; place-items: center; color: var(--muted); position: relative; }
.vs { position: absolute; top: 10px; left: 10px; }
.vb { padding: 14px; display: flex; flex-direction: column; gap: 6px; flex: 1; } .vb h3 { margin: 0; font-size: 17px; font-weight: 800; }
.sal { margin: 0; font-weight: 800; color: var(--accent); } .mut { color: var(--muted); font-size: var(--fs-s); margin: 0; }
.vst { display: flex; gap: 12px; font-size: var(--fs-xs); color: var(--muted); flex-wrap: wrap; } .vst b { color: var(--ink); font-size: var(--fs-s); }
.vl { display: flex; gap: 10px; flex-wrap: wrap; } .vl button, .vl a { border: 0; background: none; color: var(--accent); font-weight: 700; font-size: var(--fs-xs); cursor: pointer; display: inline-flex; gap: 4px; align-items: center; padding: 0; text-decoration: none; }
.vbtn { display: flex; gap: 6px; margin-top: auto; padding-top: 6px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; } .g3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.fld { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fld textarea, .lr input, .qr input, .qr select, .send input { border: 1px solid var(--line); border-radius: var(--radius); padding: 9px 10px; font: inherit; background: var(--surface); color: var(--ink); min-width: 0; }
.lst, .media { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--line-2); padding-top: 10px; }
.lh { font-weight: 800; font-size: var(--fs-s); } .lh small { font-weight: 500; color: var(--muted); }
.lr, .qr { display: flex; gap: 6px; } .lr input, .qr input { flex: 1; }
.lr button, .qr button { border: 0; background: var(--surface-3); border-radius: 8px; width: 34px; cursor: pointer; color: var(--muted); }
.addl { align-self: flex-start; border: 0; background: none; color: var(--accent); font-weight: 700; cursor: pointer; padding: 2px 0; }
.ch { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; } .sp { flex: 1; }
.rate button { border: 0; background: none; font-size: 22px; color: var(--line); cursor: pointer; padding: 0 1px; } .rate button.on { color: var(--series-4); }
.dl { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; margin: 0; font-size: var(--fs-s); } .dl dt { color: var(--muted); font-weight: 700; } .dl dd { margin: 0; } .dl a { color: var(--accent); }
.ph img { max-width: 160px; border-radius: 12px; }
h4 { margin: 8px 0 0; font-size: var(--fs-s); font-weight: 800; }
.ans { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .ans span { color: var(--muted); } .bad { color: var(--danger); }
.pre { white-space: pre-line; margin: 0; font-size: var(--fs-s); } .wh { font-size: var(--fs-s); }
.mv { display: flex; gap: 6px; flex-wrap: wrap; }
.box { display: flex; flex-direction: column; gap: 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 14px; padding: 12px; }
.chk { display: flex; gap: 8px; align-items: center; font-size: var(--fs-s); }
.send { display: flex; gap: 6px; } .send input { flex: 1; }
.ev { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); }
.ev li { display: flex; flex-direction: column; border-left: 2px solid var(--line); padding-left: 10px; } .ev small { color: var(--muted); font-size: var(--fs-xs); }
@media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, 1fr); } .g3 { grid-template-columns: 1fr; } .flt { flex-direction: column; } }
</style>
'@

Write-Host ""
Write-Host "Tayyor: 29 ta fayl yangilandi." -ForegroundColor Green
Write-Host "Endi: cd backend; python manage.py migrate_schemas; python manage.py seed_hr; cd ..\frontend; pnpm build" -ForegroundColor Yellow
