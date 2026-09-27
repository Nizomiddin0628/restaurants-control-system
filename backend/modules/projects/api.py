"""Loyihalar API — /api/v1/projects/..."""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.audit import record
from core.auth import auth, require_module, require_perm

from . import services as S
from .models import (
    CAT_META,
    Category,
    Member,
    MemberRole,
    Milestone,
    PExpense,
    PFile,
    Priority,
    Project,
    PTask,
    Status,
    TaskStatus,
)
from .templates import template_list

router = Router(tags=["projects"])


def _guard(request, perm: str = "projects.view"):
    require_module(request, "projects")
    require_perm(request, perm)


def _project(request, pid: int, *, lead: bool = False) -> Project:
    p = get_object_or_404(Project.objects.select_related("branch", "owner"), pk=pid)
    if not S.is_participant(p, request.auth):
        raise HttpError(403, "Bu loyiha sizga ochiq emas.")
    if lead and not S.is_lead(p, request.auth):
        raise HttpError(403, "Buni loyiha rahbari yoki menejer qila oladi.")
    return p


def _task(request, tid: int, *, lead: bool = False) -> PTask:
    t = get_object_or_404(PTask.objects.select_related("project", "assignee"), pk=tid)
    if not S.is_participant(t.project, request.auth):
        raise HttpError(403, "Bu loyiha sizga ochiq emas.")
    if lead and not S.is_lead(t.project, request.auth):
        raise HttpError(403, "Buni loyiha rahbari yoki menejer qila oladi.")
    if not lead and not S.can_touch_task(t, request.auth):
        raise HttpError(403, "Faqat o'zingizga berilgan vazifani o'zgartira olasiz.")
    return t


def _user(uid: Optional[str]):
    from core.models import User
    if not uid:
        return None
    return get_object_or_404(User, pk=uid)


def _full(request, p: Project) -> dict:
    return S.project_out(Project.objects.select_related("branch", "owner").get(pk=p.pk), tenant=request.tenant, full=True, user=request.auth)


# ------------------------------------------------------------------ umumiy
@router.get("/meta", auth=auth)
def meta(request):
    _guard(request)
    from core.models import Branch, User
    return {
        "categories": [S.cat_out(c) for c in Category.values],
        "statuses": [{"code": s.value, "label": s.label} for s in Status],
        "task_statuses": [{"code": s.value, "label": s.label} for s in TaskStatus],
        "priorities": [{"code": s.value, "label": s.label} for s in Priority],
        "member_roles": [{"code": s.value, "label": s.label} for s in MemberRole],
        "templates": template_list(),
        "users": [S.user_mini(u) for u in User.objects.filter(is_active=True, memberships__is_active=True).distinct().order_by("full_name")],
        "branches": [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True)],
        "me": str(request.auth.pk), "can_create": S.can_edit_all(request.auth),
    }


@router.get("/overview", auth=auth)
def overview(request):
    _guard(request)
    return S.overview(request.auth, request.tenant)


@router.get("/list", auth=auth)
def projects(request, status: str = "", category: str = "", branch_id: Optional[int] = None, q: str = "", mine: bool = False):
    _guard(request)
    qs = S.visible_projects(request.auth).select_related("branch", "owner").prefetch_related("tasks", "members__user", "milestones", "expenses")
    if status == "live":
        qs = qs.filter(status__in=[Status.PLAN, Status.ACTIVE, Status.PAUSED])
    elif status:
        qs = qs.filter(status=status)
    if category:
        qs = qs.filter(category=category)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if mine:
        u = request.auth
        qs = qs.filter(Q(owner=u) | Q(members__user=u) | Q(tasks__assignee=u)).distinct()
    return [S.project_out(p, tenant=request.tenant) for p in qs]


class ProjectIn(Schema):
    title: str = ""
    category: str = ""
    template_key: str = ""
    description: str = ""
    priority: str = Priority.NORMAL
    status: Optional[str] = None
    branch_id: Optional[int] = None
    owner_id: Optional[str] = None
    start: Optional[date] = None
    due: Optional[date] = None
    budget: int = 0
    member_ids: list[str] = []


def _check_dates(start, due):
    if start and due and due < start:
        raise HttpError(400, "Tugash sanasi boshlanishdan oldin bo'lishi mumkin emas.")


@router.post("/", auth=auth)
def create(request, data: ProjectIn):
    _guard(request, "projects.edit")
    if data.category and data.category not in Category.values:
        raise HttpError(400, "Toifa noto'g'ri.")
    if not data.title.strip() and not data.template_key:
        raise HttpError(400, "Loyiha nomini kiriting.")
    _check_dates(data.start, data.due)
    p = S.create_project(title=data.title, category=data.category, template_key=data.template_key, actor=request.auth, start=data.start, due=data.due,
                         owner=_user(data.owner_id), branch_id=data.branch_id, budget=data.budget, description=data.description,
                         priority=data.priority, members=[_user(i) for i in data.member_ids if i], tenant=request.tenant)
    record(request, "create", p)
    return _full(request, p)


@router.get("/{int:pid}", auth=auth)
def detail(request, pid: int):
    _guard(request)
    return _full(request, _project(request, pid))


@router.put("/{int:pid}", auth=auth)
def update(request, pid: int, data: ProjectIn):
    _guard(request)
    p = _project(request, pid, lead=True)
    if not data.title.strip():
        raise HttpError(400, "Loyiha nomini kiriting.")
    _check_dates(data.start, data.due)
    changes = []
    if data.due != p.due:
        changes.append(f"muddat: {p.due:%d.%m.%Y} → {data.due:%d.%m.%Y}" if p.due and data.due else "muddat o'zgardi")
    if data.budget != p.budget:
        changes.append(f"byudjet: {p.budget:,} → {data.budget:,}".replace(",", " "))
    p.title, p.description = data.title.strip(), data.description
    if data.category in Category.values:
        p.category = data.category
    if data.priority in Priority.values:
        p.priority = data.priority
    p.branch_id, p.start, p.due, p.budget = data.branch_id, data.start, data.due, max(0, data.budget)
    if data.owner_id and data.owner_id != str(p.owner_id):
        p.owner = _user(data.owner_id)
        Member.objects.update_or_create(project=p, user=p.owner, defaults={"role": MemberRole.LEAD})
        changes.append(f"rahbar: {p.owner.full_name or p.owner.phone}")
    p.save()
    if changes:
        S.log(p, request.auth, "info", "O'zgartirildi — " + "; ".join(changes))
    record(request, "update", p)
    return _full(request, p)


class StatusIn(Schema):
    status: str


@router.post("/{int:pid}/status", auth=auth)
def set_status(request, pid: int, data: StatusIn):
    _guard(request)
    p = _project(request, pid, lead=True)
    if data.status not in Status.values:
        raise HttpError(400, "Holat noto'g'ri.")
    old = p.status
    p.status = data.status
    p.done_at = timezone.now() if data.status == Status.DONE else None
    p.save()
    S.log(p, request.auth, "status", f"Loyiha holati: {Status(old).label} → {Status(data.status).label}")
    return _full(request, p)


@router.delete("/{int:pid}", auth=auth)
def delete(request, pid: int):
    _guard(request, "projects.edit")
    p = get_object_or_404(Project, pk=pid)
    record(request, "delete", p)
    p.delete()
    return {"ok": True}


class MembersIn(Schema):
    members: list[dict]    # [{"user_id": "...", "role": "member"}]


@router.put("/{int:pid}/members", auth=auth)
def members(request, pid: int, data: MembersIn):
    _guard(request)
    p = _project(request, pid, lead=True)
    keep = set()
    for m in data.members:
        u = _user(m.get("user_id"))
        role = m.get("role") if m.get("role") in MemberRole.values else MemberRole.MEMBER
        if u.pk == p.owner_id:
            role = MemberRole.LEAD
        obj, created = Member.objects.update_or_create(project=p, user=u, defaults={"role": role})
        keep.add(u.pk)
        if created:
            S.log(p, request.auth, "member", f"Jamoaga qo'shildi: {u.full_name or u.phone}")
    p.members.exclude(user_id__in=keep).exclude(user_id=p.owner_id).delete()
    return _full(request, p)


# ------------------------------------------------------------------ bosqichlar
class MilestoneIn(Schema):
    title: str
    due: Optional[date] = None
    sort_order: Optional[int] = None


@router.post("/{int:pid}/milestones", auth=auth)
def add_milestone(request, pid: int, data: MilestoneIn):
    _guard(request)
    p = _project(request, pid, lead=True)
    if not data.title.strip():
        raise HttpError(400, "Bosqich nomini kiriting.")
    Milestone.objects.create(project=p, title=data.title.strip(), due=data.due,
                             sort_order=data.sort_order if data.sort_order is not None else p.milestones.count())
    S.log(p, request.auth, "milestone", f"Yangi bosqich: {data.title.strip()}")
    return _full(request, p)


@router.put("/milestones/{int:mid}", auth=auth)
def edit_milestone(request, mid: int, data: MilestoneIn):
    _guard(request)
    m = get_object_or_404(Milestone, pk=mid)
    _project(request, m.project_id, lead=True)
    m.title, m.due = data.title.strip() or m.title, data.due
    if data.sort_order is not None:
        m.sort_order = data.sort_order
    m.save()
    return _full(request, m.project)


@router.delete("/milestones/{int:mid}", auth=auth)
def del_milestone(request, mid: int):
    _guard(request)
    m = get_object_or_404(Milestone, pk=mid)
    p = _project(request, m.project_id, lead=True)
    m.delete()      # vazifalar bosqichsiz qoladi
    return _full(request, p)


# ------------------------------------------------------------------ vazifalar
class TaskIn(Schema):
    title: str
    description: str = ""
    milestone_id: Optional[int] = None
    assignee_id: Optional[str] = None
    status: str = TaskStatus.TODO
    priority: str = Priority.NORMAL
    due: Optional[date] = None
    checklist: list[dict] = []


def _clean_cl(cl: list[dict]) -> list[dict]:
    return [{"text": str(c.get("text", "")).strip()[:200], "done": bool(c.get("done"))} for c in cl if str(c.get("text", "")).strip()][:30]


@router.post("/{int:pid}/tasks", auth=auth)
def add_task(request, pid: int, data: TaskIn):
    _guard(request)
    p = _project(request, pid, lead=True)
    if not data.title.strip():
        raise HttpError(400, "Vazifa nomini kiriting.")
    ms = get_object_or_404(Milestone, pk=data.milestone_id, project=p) if data.milestone_id else None
    t = PTask.objects.create(project=p, milestone=ms, title=data.title.strip(), description=data.description, due=data.due,
                             priority=data.priority if data.priority in Priority.values else Priority.NORMAL,
                             checklist=_clean_cl(data.checklist), sort_order=(p.tasks.count() + 1) * 10, created_by=request.auth)
    S.log(p, request.auth, "task", f"Yangi vazifa: {t.title}", task=t)
    if data.assignee_id:
        S.assign(t, _user(data.assignee_id), request.auth, request.tenant)
    if data.status != TaskStatus.TODO:
        S.set_task_status(t, data.status, request.auth, request.tenant)
    S.sync_milestone(ms)
    return S.task_out(PTask.objects.get(pk=t.pk))


@router.put("/tasks/{int:tid}", auth=auth)
def edit_task(request, tid: int, data: TaskIn):
    _guard(request)
    t = _task(request, tid)
    lead = S.is_lead(t.project, request.auth)
    if lead:     # rahbar hammasini o'zgartiradi; mas'ul — faqat holat, izoh va checklist
        if not data.title.strip():
            raise HttpError(400, "Vazifa nomini kiriting.")
        old_ms = t.milestone
        t.title, t.description, t.due = data.title.strip(), data.description, data.due
        t.priority = data.priority if data.priority in Priority.values else t.priority
        t.milestone = get_object_or_404(Milestone, pk=data.milestone_id, project=t.project) if data.milestone_id else None
        if old_ms != t.milestone:
            t.save()
            S.sync_milestone(old_ms)
    t.checklist = _clean_cl(data.checklist)
    t.save()
    if lead and (data.assignee_id or None) != (str(t.assignee_id) if t.assignee_id else None):
        S.assign(t, _user(data.assignee_id), request.auth, request.tenant)
    S.set_task_status(t, data.status, request.auth, request.tenant)
    S.sync_milestone(t.milestone)
    return S.task_out(PTask.objects.select_related("assignee").get(pk=t.pk))


class MoveIn(Schema):
    status: str
    order: list[int] = []     # shu ustundagi vazifalar tartibi


@router.post("/tasks/{int:tid}/move", auth=auth)
def move_task(request, tid: int, data: MoveIn):
    """Kanban: ustunga sudrab tashlash."""
    _guard(request)
    t = _task(request, tid)
    if data.status not in TaskStatus.values:
        raise HttpError(400, "Holat noto'g'ri.")
    S.set_task_status(t, data.status, request.auth, request.tenant)
    for i, x in enumerate(data.order):
        PTask.objects.filter(pk=x, project=t.project).update(sort_order=(i + 1) * 10)
    return S.task_out(PTask.objects.select_related("assignee").get(pk=t.pk))


@router.delete("/tasks/{int:tid}", auth=auth)
def del_task(request, tid: int):
    _guard(request)
    t = _task(request, tid, lead=True)
    p, ms = t.project, t.milestone
    S.log(p, request.auth, "task", f"Vazifa o'chirildi: {t.title}")
    t.delete()
    S.sync_milestone(ms)
    return {"ok": True}


@router.get("/tasks", auth=auth)
def all_tasks(request, project_id: Optional[int] = None, mine: bool = False, assignee_id: Optional[str] = None):
    """Kanban uchun: barcha (yoki bitta loyiha / o'zimning) vazifalar."""
    _guard(request)
    qs = PTask.objects.filter(project__in=S.visible_projects(request.auth).exclude(status__in=[Status.CANCELLED, Status.DONE]).values("pk"))
    if project_id:
        qs = qs.filter(project_id=project_id)
    if mine:
        qs = qs.filter(assignee=request.auth)
    elif assignee_id:
        qs = qs.filter(assignee_id=assignee_id)
    today = timezone.localdate()
    out = []
    for t in qs.select_related("project", "assignee").order_by("sort_order", "id")[:500]:
        out.append({**S.task_out(t, today), "project": t.project.title, "project_code": t.project.code,
                    "color": CAT_META[t.project.category][1], "can_move": S.can_touch_task(t, request.auth)})
    return out


# ------------------------------------------------------------------ kalendar va bildirishnomalar
@router.get("/calendar", auth=auth)
def calendar(request, month: str = ""):
    _guard(request)
    today = timezone.localdate()
    try:
        y, m = (int(x) for x in month.split("-")) if month else (today.year, today.month)
        date(y, m, 1)
    except ValueError:
        raise HttpError(400, "Oy formati: YYYY-MM") from None
    return S.calendar_events(request.auth, y, m)


@router.get("/feed", auth=auth)
def feed(request):
    _guard(request)
    return S.feed(request.auth, 40)


# ------------------------------------------------------------------ hujjatlar
@router.post("/{int:pid}/files", auth=auth)
def upload(request, pid: int, task_id: Optional[int] = None, title: str = "", file: UploadedFile = File(...)):
    _guard(request)
    p = _project(request, pid)
    if file.size > 20 * 1024 * 1024:
        raise HttpError(400, "Fayl 20 MB dan oshmasin.")
    f = PFile(project=p, task_id=task_id if task_id and p.tasks.filter(pk=task_id).exists() else None, title=(title or file.name)[:200],
              size=file.size, uploaded_by=request.auth)
    f.file.save(file.name, file, save=True)
    S.log(p, request.auth, "file", f"📎 Hujjat qo'shildi: {f.title}")
    return S.file_out(f)


class LinkIn(Schema):
    title: str
    url: str


@router.post("/{int:pid}/links", auth=auth)
def add_link(request, pid: int, data: LinkIn):
    _guard(request)
    p = _project(request, pid)
    if not data.url.startswith(("http://", "https://")):
        raise HttpError(400, "Havola http:// yoki https:// bilan boshlansin.")
    f = PFile.objects.create(project=p, url=data.url[:500], title=(data.title or data.url)[:200], uploaded_by=request.auth)
    S.log(p, request.auth, "file", f"🔗 Havola qo'shildi: {f.title}")
    return S.file_out(f)


@router.delete("/files/{int:fid}", auth=auth)
def del_file(request, fid: int):
    _guard(request)
    f = get_object_or_404(PFile, pk=fid)
    p = _project(request, f.project_id)
    if f.uploaded_by_id != request.auth.pk and not S.is_lead(p, request.auth):
        raise HttpError(403, "Faqat o'zingiz yuklagan faylni o'chira olasiz.")
    f.file.delete(save=False) if f.file else None
    f.delete()
    return {"ok": True}


# ------------------------------------------------------------------ byudjet
class ExpenseIn(Schema):
    amount: int
    note: str = ""
    date: Optional[date] = None


@router.post("/{int:pid}/expenses", auth=auth)
def add_expense(request, pid: int, data: ExpenseIn):
    _guard(request)
    p = _project(request, pid, lead=True)
    if data.amount <= 0:
        raise HttpError(400, "Summani kiriting.")
    PExpense.objects.create(project=p, amount=data.amount, note=data.note.strip()[:200], date=data.date or timezone.localdate(), created_by=request.auth)
    b = S.budget_line(p)
    S.log(p, request.auth, "expense", f"Xarajat: {data.amount:,} so'm — {data.note}".replace(",", " ").rstrip(" —"))
    if p.budget and b["spent"] > p.budget:
        S.log(p, None, "info", f"⚠️ Byudjetdan oshdi: {b['spent']:,} / {p.budget:,} so'm".replace(",", " "))
    return _full(request, p)


@router.delete("/expenses/{int:eid}", auth=auth)
def del_expense(request, eid: int):
    _guard(request)
    e = get_object_or_404(PExpense, pk=eid)
    p = _project(request, e.project_id, lead=True)
    e.delete()
    return _full(request, p)


# ------------------------------------------------------------------ izohlar
class CommentIn(Schema):
    text: str
    task_id: Optional[int] = None


@router.post("/{int:pid}/comments", auth=auth)
def comment(request, pid: int, data: CommentIn):
    _guard(request)
    p = _project(request, pid)
    if not data.text.strip():
        raise HttpError(400, "Izoh yozing.")
    t = p.tasks.filter(pk=data.task_id).first() if data.task_id else None
    a = S.log(p, request.auth, "comment", data.text.strip()[:2000], task=t)
    return S.activity_out(a)
