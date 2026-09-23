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
