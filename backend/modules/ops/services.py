"""Tuzilma xizmatlari: shablon, daraxt (org chart), lavozim kartasi, bog'lanishlar, ko'chirish."""
from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from core.events import emit

from . import templates
from .models import Department, Level, PositionProfile, Scope


def _enabled(tenant, code: str) -> bool:
    try:
        return tenant is None or tenant.module_enabled(code)
    except Exception:
        return False


def ensure_profile(position) -> PositionProfile:
    try:
        return position.profile
    except PositionProfile.DoesNotExist:
        return PositionProfile.objects.create(position=position)


def sync_department_name(position, dept: Department | None) -> None:
    """hr.Position.department (matn) eski modullar uchun bo'lim nomi bilan bir xil bo'lsin."""
    name = dept.name if dept else ""
    if position.department != name:
        position.department = name
        position.save(update_fields=["department", "updated_at"])


# ------------------------------------------------------------------ shablon
@transaction.atomic
def install_template() -> dict:
    """Tayyor tuzilma: 9 bo'lim, 17 lavozim. Takror bosilsa — yangi narsa qo'shilmaydi, bo'shlari to'ldiriladi."""
    from modules.hr.models import Position

    depts: dict[str, Department] = {}
    made_d = made_p = linked = 0
    for i, (key, name, icon, color, desc) in enumerate(templates.DEPARTMENTS):
        d = Department.objects.filter(name__iexact=name).first()
        if d is None:
            d = Department.objects.create(name=name, icon=icon, color=color, description=desc, sort_order=i)
            made_d += 1
        depts[key] = d

    existing = {p.name.strip().lower(): p for p in Position.objects.all()}
    by_key = {}
    for i, (key, name, dkey, level, scope, parent, role, icon, head, aliases, purpose, resp) in enumerate(templates.POSITIONS):
        pos = next((existing.get(n.strip().lower()) for n in [name, *aliases] if existing.get(n.strip().lower())), None)
        taken = PositionProfile.objects.filter(template_key=key).select_related("position").first()
        if taken:
            pos = taken.position
        if pos is None:
            pos = Position.objects.create(name=name, department=depts[dkey].name, sort_order=100 + i)
            made_p += 1
        else:
            linked += 1
        prof = ensure_profile(pos)
        if not prof.template_key:
            prof.template_key = key
            prof.department = prof.department or depts[dkey]
            prof.level = level
            prof.scope = scope
            prof.icon = icon if prof.icon in ("", "👤") else prof.icon
            prof.role_code = prof.role_code or role
            prof.headcount = prof.headcount or head
            prof.purpose = prof.purpose or purpose
            prof.responsibilities = prof.responsibilities or [{"text": t, "freq": f} for t, f in resp]
            prof.save()
        sync_department_name(pos, prof.department)
        by_key[key] = (pos, parent)
    for _key, (pos, parent) in by_key.items():
        prof = pos.profile
        if parent and prof.reports_to_id is None and parent in by_key:
            prof.reports_to = by_key[parent][0]
            prof.save(update_fields=["reports_to", "updated_at"])
    return {"departments": made_d, "positions": made_p, "linked": linked}


# ------------------------------------------------------------------ daraxt
def _people(emps) -> list[dict]:
    return [{"id": e.pk, "name": e.user.full_name or e.user.phone, "avatar": e.user.avatar.url if e.user.avatar else None}
            for e in emps[:4]]


def tree() -> dict:
    """Org chart: bosh ofis lavozimlari (kimga bo'ysunishi bo'yicha) + har filial uchun filial lavozimlari."""
    from core.models import Branch
    from modules.hr.models import Employee, Position

    branches = list(Branch.objects.filter(deleted_at__isnull=True, is_active=True))
    single = branches[0] if len(branches) == 1 else None
    positions = list(Position.objects.all().select_related("profile__department"))
    prof = {p.pk: getattr(p, "profile", None) for p in positions}
    emps_all = list(Employee.objects.filter(is_active=True).select_related("user"))
    by_pos: dict[int, list] = defaultdict(list)
    for e in emps_all:
        if e.position_id:
            by_pos[e.position_id].append(e)

    def scope(p):
        return prof[p.pk].scope if prof.get(p.pk) else Scope.BRANCH

    def parent(p):
        return prof[p.pk].reports_to_id if prof.get(p.pk) else None

    pmap = {p.pk: p for p in positions}
    kids: dict[int | None, list] = defaultdict(list)
    for p in positions:
        par = parent(p)
        kids[par if par in pmap else None].append(p)

    def node(p, branch=None) -> dict:
        pr = prof.get(p.pk)
        es = by_pos.get(p.pk, [])
        if branch is not None:
            es = [e for e in es if e.branch_id == branch.pk or (e.branch_id is None and single is not None)]
        d = pr.department if pr and pr.department_id else None
        out = {"type": "position", "id": p.pk, "name": p.name, "icon": pr.icon if pr else "👤",
               "level": pr.level if pr else Level.STAFF, "scope": scope(p),
               "department": {"id": d.pk, "name": d.name, "color": d.color, "icon": d.icon} if d else None,
               "count": len(es), "headcount": pr.headcount if pr else 0, "people": _people(es),
               "branch_id": branch.pk if branch else None, "children": []}
        for c in kids.get(p.pk, []):
            if scope(c) == scope(p) or (branch is not None and scope(c) == Scope.BRANCH):
                out["children"].append(node(c, branch))
        # filial lavozimlarining «ildizi» shu bosh ofis lavozimiga bo'ysunsa — har filial tuguni
        if branch is None and scope(p) == Scope.HQ:
            broots = [c for c in kids.get(p.pk, []) if scope(c) == Scope.BRANCH]
            if broots:
                out["children"].extend(_branch_nodes(broots))
        return out

    def _branch_nodes(roots) -> list[dict]:
        if not branches:
            return [node(r) for r in roots]
        return [{"type": "branch", "id": b.pk, "name": b.name, "address": b.address,
                 "count": sum(1 for e in emps_all if e.branch_id == b.pk or (e.branch_id is None and single is not None)),
                 "children": [node(r, b) for r in roots]} for b in branches]

    top = kids.get(None, [])
    roots = [node(p) for p in top if scope(p) == Scope.HQ]
    loose = [p for p in top if scope(p) == Scope.BRANCH]
    if loose:
        roots.extend(_branch_nodes(loose))
    return {"roots": roots, "stats": stats(positions, prof, emps_all, branches)}


def stats(positions, prof, emps, branches) -> dict:
    from modules.hr.models import Vacancy, VacancyStatus
    nb = max(1, len(branches))
    need = sum((pr.headcount * (nb if pr.scope == Scope.BRANCH else 1)) for pr in prof.values() if pr)
    return {"departments": Department.objects.count(), "positions": len(positions), "employees": len(emps),
            "branches": len(branches), "headcount": need, "short": max(0, need - len([e for e in emps if e.position_id])),
            "vacancies": Vacancy.objects.filter(status=VacancyStatus.OPEN).count(),
            "no_profile": sum(1 for v in prof.values() if v is None)}


# ------------------------------------------------------------------ lavozim kartasi
def position_out(p) -> dict:
    pr = ensure_profile(p)
    d = pr.department
    return {"id": p.pk, "name": p.name, "code": pr.code, "icon": pr.icon, "level": pr.level, "level_label": Level(pr.level).label,
            "scope": pr.scope, "scope_label": Scope(pr.scope).label, "purpose": pr.purpose, "responsibilities": pr.responsibilities or [],
            "role_code": pr.role_code, "headcount": pr.headcount,
            "department": {"id": d.pk, "name": d.name, "color": d.color, "icon": d.icon} if d else None,
            "reports_to": {"id": pr.reports_to_id, "name": pr.reports_to.name} if pr.reports_to_id else None,
            "default_salary_type": p.default_salary_type, "default_rate": p.default_rate,
            "employees_count": p.employees.filter(is_active=True).count()}


def position_detail(p, tenant=None) -> dict:
    from modules.hr.models import Employee, Vacancy, VacancyStatus
    out = position_out(p)
    out["subordinates"] = [{"id": s.position_id, "name": s.position.name, "icon": s.icon}
                           for s in PositionProfile.objects.filter(reports_to=p).select_related("position")]
    emps = list(Employee.objects.filter(position=p, is_active=True).select_related("user", "branch"))
    month = timezone.localdate().replace(day=1)
    kpi_rows = []
    try:
        from modules.hr.kpi import compute
        ctx: dict = {}
        for e in emps[:60]:
            k = compute(e, month, tenant, ctx)
            kpi_rows.append((e, k))
    except Exception:
        kpi_rows = [(e, {}) for e in emps]
    out["employees"] = [{"id": e.pk, "name": e.user.full_name or e.user.phone, "phone": e.user.phone,
                         "avatar": e.user.avatar.url if e.user.avatar else None, "branch": e.branch.name if e.branch_id else None,
                         "hire_date": e.hire_date.isoformat() if e.hire_date else None,
                         "kpi": k.get("score"), "grade": k.get("grade")} for e, k in kpi_rows]
    scored = [r["kpi"] for r in out["employees"] if r["kpi"] is not None]
    out["kpi"] = {"avg": round(sum(scored) / len(scored)) if scored else None, "month": month.isoformat(),
                  "grades": {g: sum(1 for r in out["employees"] if r["grade"] == g) for g in "ABCD"}}
    out["vacancies"] = [{"id": v.pk, "title": v.title, "branch": v.branch.name if v.branch_id else None}
                        for v in Vacancy.objects.filter(position=p, status=VacancyStatus.OPEN).select_related("branch")]
    out["training"] = _training_links(p) if _enabled(tenant, "training") else None
    out["tasks"] = _task_links(p) if _enabled(tenant, "tasks") else None
    out["counts"] = {"responsibilities": len(out["responsibilities"]), "employees": len(emps),
                     "courses": sum(1 for c in (out["training"] or {}).get("courses", []) if c["via"]),
                     "standards": sum(1 for s in (out["training"] or {}).get("standards", []) if s["via"]),
                     "tasks": len((out["tasks"] or [])), "vacancies": len(out["vacancies"])}
    return out


def _has(obj, pid: int) -> bool:
    return pid in [int(x) for x in (obj.positions or [])]


def _via(obj, p, role: str) -> str | None:
    """Kurs/standart shu lavozimga qanday yetadi: to'g'ridan-to'g'ri, rol orqali yoki hammaga."""
    if _has(obj, p.pk):
        return "position"
    if getattr(obj, "everyone", False):
        return "everyone"
    if role and role in (obj.roles or []):
        return "role"
    return None


def _training_links(p) -> dict:
    from modules.hr.models import Employee
    from modules.training.models import Course, Enrollment, Standard
    role = p.profile.role_code if hasattr(p, "profile") else ""
    users = list(Employee.objects.filter(position=p, is_active=True).values_list("user_id", flat=True))
    courses = []
    for c in Course.objects.filter(is_archived=False):
        via = _via(c, p, role)
        done = Enrollment.objects.filter(course=c, user_id__in=users, status="completed").count() if via else 0
        courses.append({"id": c.pk, "title": c.title, "category": c.category, "linked": via == "position", "via": via,
                        "published": c.is_published, "done": done, "total": len(users) if via else 0})
    standards = [{"id": s.pk, "title": s.title, "category": s.category, "linked": _has(s, p.pk), "via": _via(s, p, role),
                  "version": s.version} for s in Standard.objects.filter(is_active=True)]
    return {"courses": courses, "standards": standards}


def _task_links(p) -> list[dict]:
    from modules.tasks.models import TaskRecurrence
    return [{"id": r.pk, "title": r.title, "freq": r.get_freq_display(), "time": r.time_of_day.strftime("%H:%M"),
             "assignee": r.assignee.full_name if r.assignee_id else None}
            for r in TaskRecurrence.objects.filter(is_active=True, assignee__employee__position=p).select_related("assignee")]


@transaction.atomic
def set_links(p, *, courses: list[int] | None = None, standards: list[int] | None = None, tenant=None, by=None) -> dict:
    """Lavozimga kurs/standart biriktirish: tanlanganlarga lavozim qo'shiladi, olib tashlanganlardan — o'chiriladi.
    Yangi biriktirilgan kurs shu lavozimdagi hamma xodimga darhol beriladi."""
    from modules.training import services as tr
    from modules.training.models import Course, Standard
    added = 0
    for model, ids in ((Course, courses), (Standard, standards)):
        if ids is None:
            continue
        want = {int(x) for x in ids}
        for obj in model.objects.all():
            cur = [int(x) for x in (obj.positions or [])]
            if obj.pk in want and p.pk not in cur:
                obj.positions = [*cur, p.pk]
                obj.save(update_fields=["positions", "updated_at"])
                if model is Course:
                    added += tr.sync_course(obj, by, tenant)
            elif obj.pk not in want and p.pk in cur:
                obj.positions = [x for x in cur if x != p.pk]
                obj.save(update_fields=["positions", "updated_at"])
    return {"enrolled": added}


def move(p, new_parent) -> None:
    """Kimga bo'ysunishini o'zgartirish (daraxtda sudrab tashlash). Aylana hosil bo'lsa — xato."""
    if new_parent is not None:
        cur, seen = new_parent, set()
        while cur is not None and cur.pk not in seen:
            if cur.pk == p.pk:
                raise ValueError("Lavozim o'ziga yoki o'z qo'l ostidagisiga bo'ysuna olmaydi.")
            seen.add(cur.pk)
            nxt = getattr(cur, "profile", None)
            cur = nxt.reports_to if nxt and nxt.reports_to_id else None
    prof = ensure_profile(p)
    prof.reports_to = new_parent
    prof.save(update_fields=["reports_to", "updated_at"])
    emit("ops.structure_changed", {"position_id": p.pk, "reports_to": new_parent.pk if new_parent else None})

