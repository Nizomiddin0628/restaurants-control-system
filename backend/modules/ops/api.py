"""Tuzilma va standartlar API — /api/v1/ops/..."""
from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm

from . import services
from .models import Department, Freq, Level, PositionProfile, Scope

router = Router(tags=["ops"])


def _guard(request, perm: str):
    require_module(request, "ops")
    require_perm(request, perm)


def _position(pid: int):
    from modules.hr.models import Position
    return get_object_or_404(Position.objects.select_related("profile__department", "profile__reports_to"), pk=pid)


class DepartmentIn(Schema):
    name: str
    icon: str = "🏢"
    color: str = "#2F80ED"
    description: str = ""


class Resp(Schema):
    text: str
    freq: str = Freq.DAILY


class PositionIn(Schema):
    name: str
    icon: str = "👤"
    code: str = ""
    department_id: Optional[int] = None
    reports_to_id: Optional[int] = None
    level: int = Level.STAFF
    scope: str = Scope.BRANCH
    purpose: str = ""
    responsibilities: list[Resp] = []
    role_code: str = ""
    headcount: int = 0
    default_salary_type: str = "monthly"
    default_rate: int = 0


class LinksIn(Schema):
    courses: Optional[list[int]] = None
    standards: Optional[list[int]] = None


class MoveIn(Schema):
    reports_to_id: Optional[int] = None


def _dept_out(d: Department) -> dict:
    return {"id": d.pk, "name": d.name, "icon": d.icon, "color": d.color, "description": d.description,
            "positions": d.positions.count()}


# ------------------------------------------------------------------ umumiy
@router.get("/meta", auth=auth)
def meta(request):
    _guard(request, "ops.view")
    from core.models import Role
    from modules.hr.models import Position
    return {
        "departments": [_dept_out(d) for d in Department.objects.all()],
        "positions": [{"id": p.pk, "name": p.name} for p in Position.objects.all()],
        "levels": [{"value": v.value, "label": v.label} for v in Level],
        "scopes": [{"value": v.value, "label": v.label} for v in Scope],
        "freqs": [{"value": v.value, "label": v.label} for v in Freq],
        "roles": [{"code": r.code, "name": r.name} for r in Role.objects.exclude(code="owner")],
        "has_structure": PositionProfile.objects.exclude(template_key="").exists() or Department.objects.exists(),
    }


@router.get("/tree", auth=auth)
def org_tree(request):
    _guard(request, "ops.view")
    return services.tree()


@router.post("/template", auth=auth)
def template(request):
    """Tayyor restoran tuzilmasini yaratish (mavjud lavozimlar saqlanadi va to'ldiriladi)."""
    _guard(request, "ops.edit")
    r = services.install_template()
    record(request, "create", model="ops.Template", after=r)
    return r


# ------------------------------------------------------------------ bo'limlar
@router.post("/departments", auth=auth)
def create_department(request, data: DepartmentIn):
    _guard(request, "ops.edit")
    if not data.name.strip():
        raise HttpError(400, "Bo'lim nomini kiriting.")
    d = Department.objects.create(**data.dict(), sort_order=Department.objects.count())
    record(request, "create", d)
    return _dept_out(d)


@router.put("/departments/{int:did}", auth=auth)
def update_department(request, did: int, data: DepartmentIn):
    _guard(request, "ops.edit")
    d = get_object_or_404(Department, pk=did)
    if not data.name.strip():
        raise HttpError(400, "Bo'lim nomini kiriting.")
    before = snapshot(d)
    for k, v in data.dict().items():
        setattr(d, k, v)
    d.save()
    for prof in d.positions.select_related("position"):
        services.sync_department_name(prof.position, d)
    record(request, "update", d, before=before)
    return _dept_out(d)


@router.delete("/departments/{int:did}", auth=auth)
def delete_department(request, did: int):
    _guard(request, "ops.edit")
    d = get_object_or_404(Department, pk=did)
    n = d.positions.count()
    if n:
        raise HttpError(400, f"Bu bo'limda {n} ta lavozim bor — avval ularni boshqa bo'limga o'tkazing.")
    record(request, "delete", d)
    d.delete()
    return {"ok": True}


# ------------------------------------------------------------------ lavozimlar
@router.get("/positions", auth=auth)
def list_positions(request, department_id: Optional[int] = None, q: Optional[str] = None):
    _guard(request, "ops.view")
    from modules.hr.models import Position
    qs = Position.objects.all().select_related("profile__department", "profile__reports_to")
    if q:
        qs = qs.filter(name__icontains=q)
    out = [services.position_out(p) for p in qs]
    if department_id:
        out = [p for p in out if p["department"] and p["department"]["id"] == department_id]
    elif department_id == 0:
        out = [p for p in out if not p["department"]]
    return sorted(out, key=lambda p: (p["level"], p["name"]))


@router.get("/positions/{int:pid}", auth=auth)
def get_position(request, pid: int):
    _guard(request, "ops.view")
    return services.position_detail(_position(pid), request.tenant)


def _apply(p, data: PositionIn):
    from modules.hr.models import Position
    if not data.name.strip():
        raise HttpError(400, "Lavozim nomini kiriting.")
    if Position.objects.filter(name__iexact=data.name.strip()).exclude(pk=p.pk).exists():
        raise HttpError(400, f"«{data.name.strip()}» nomli lavozim allaqachon bor.")
    if data.level not in Level.values or data.scope not in Scope.values:
        raise HttpError(400, "Daraja yoki doira noto'g'ri.")
    dept = get_object_or_404(Department, pk=data.department_id) if data.department_id else None
    parent = _position(data.reports_to_id) if data.reports_to_id else None
    p.name = data.name.strip()
    p.default_salary_type = data.default_salary_type
    p.default_rate = max(0, data.default_rate)
    p.department = dept.name if dept else ""
    p.save()
    prof = services.ensure_profile(p)
    try:
        services.move(p, parent)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    prof.refresh_from_db()
    prof.department = dept
    prof.code, prof.icon, prof.level, prof.scope = data.code.strip(), data.icon or "👤", data.level, data.scope
    prof.purpose = data.purpose.strip()
    prof.responsibilities = [{"text": r.text.strip(), "freq": r.freq if r.freq in Freq.values else Freq.DAILY}
                             for r in data.responsibilities if r.text.strip()]
    prof.role_code, prof.headcount = data.role_code, max(0, min(500, data.headcount))
    prof.save()


@router.post("/positions", auth=auth)
def create_position(request, data: PositionIn):
    _guard(request, "ops.edit")
    from modules.hr.models import Position
    p = Position(name=data.name.strip() or "—", sort_order=Position.objects.count())
    if Position.objects.filter(name__iexact=data.name.strip()).exists():
        raise HttpError(400, f"«{data.name.strip()}» nomli lavozim allaqachon bor.")
    if not data.name.strip():
        raise HttpError(400, "Lavozim nomini kiriting.")
    p.save()
    _apply(p, data)
    record(request, "create", p)
    return services.position_detail(_position(p.pk), request.tenant)


@router.put("/positions/{int:pid}", auth=auth)
def update_position(request, pid: int, data: PositionIn):
    _guard(request, "ops.edit")
    p = _position(pid)
    before = snapshot(p)
    _apply(p, data)
    record(request, "update", p, before=before)
    return services.position_detail(_position(pid), request.tenant)


@router.delete("/positions/{int:pid}", auth=auth)
def delete_position(request, pid: int):
    _guard(request, "ops.edit")
    p = _position(pid)
    n = p.employees.filter(is_active=True).count()
    if n:
        raise HttpError(400, f"Bu lavozimda {n} ta xodim ishlayapti — avval ularni boshqa lavozimga o'tkazing.")
    PositionProfile.objects.filter(reports_to=p).update(reports_to=p.profile.reports_to if hasattr(p, "profile") else None)
    record(request, "delete", p)
    p.delete()
    return {"ok": True}


@router.post("/positions/{int:pid}/move", auth=auth)
def move_position(request, pid: int, data: MoveIn):
    """Tuzilmada sudrab tashlash: lavozim kimga bo'ysunishini o'zgartirish."""
    _guard(request, "ops.edit")
    p = _position(pid)
    parent = _position(data.reports_to_id) if data.reports_to_id else None
    try:
        services.move(p, parent)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    record(request, "update", p, after={"reports_to": data.reports_to_id})
    return {"ok": True}


@router.put("/positions/{int:pid}/links", auth=auth)
def set_links(request, pid: int, data: LinksIn):
    """Lavozimga kurs va standartlarni biriktirish — shu lavozimdagi xodimlarga avtomatik beriladi."""
    _guard(request, "ops.edit")
    if not request.tenant.module_enabled("training"):
        raise HttpError(400, "«O'qitish» moduli yoqilmagan.")
    p = _position(pid)
    r = services.set_links(p, courses=data.courses, standards=data.standards, tenant=request.tenant, by=request.auth)
    record(request, "update", p, after={"links": data.dict()})
    return {**r, "position": services.position_detail(_position(pid), request.tenant)}
