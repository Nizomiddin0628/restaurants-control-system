"""Vazifalar va muammolar API — /api/v1/tasks/..."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.pagination import PageNumberPagination, paginate

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm
from core.models import Branch, User

from . import services
from .models import (
    Attachment,
    ColumnKind,
    Priority,
    Source,
    Task,
    TaskAttachment,
    TaskCategory,
    TaskColumn,
    TaskComment,
    TaskDepartment,
    TaskLabel,
    TaskRecurrence,
    TaskStep,
)

router = Router(tags=["tasks"])


def _guard(request, perm: str):
    require_module(request, "tasks")
    require_perm(request, perm)


def _visible(request):
    """`tasks.view_all` bo'lmasa — xodim faqat o'ziga tegishli vazifalarni ko'radi."""
    qs = Task.objects.live()
    user = request.auth
    if not (user.has_perm_code("tasks.view_all") or user.has_perm_code("tasks.admin")):
        qs = qs.for_user(user)
    return qs


def _plain_qs(request):
    """Statistika uchun: `annotate(Count(...))`siz — aks holda JOIN sonlarni ikkilantiradi."""
    return _visible(request).select_related("column", "department")


def _task_qs(request):
    return (_visible(request)
            .select_related("column", "branch", "department", "category", "assignee", "supervisor", "reporter")
            .prefetch_related("labels", "steps", Prefetch("attachments", queryset=TaskAttachment.objects.all()))
            .annotate(comments_count=Count("comments", distinct=True)))


# ------------------------------------------------------------------ sxemalar
class I18n(Schema):
    uz: str = ""
    ru: str = ""
    en: str = ""


class UserMini(Schema):
    id: str
    full_name: str = ""
    phone: str = ""
    avatar: Optional[str] = None

    @staticmethod
    def resolve_id(obj):
        return str(obj.pk)

    @staticmethod
    def resolve_avatar(obj):
        return obj.avatar.url if obj.avatar else None


class ColumnIn(Schema):
    name: I18n
    kind: str = ColumnKind.ACTIVE
    color: str = "#6B6A63"
    wip_limit: int = 0
    is_active: bool = True


class ColumnOut(Schema):
    id: int
    code: str
    name: dict
    kind: str
    color: str
    wip_limit: int
    sort_order: int
    is_active: bool
    count: int = 0


class DepartmentOut(Schema):
    id: int
    code: str
    name: dict
    color: str
    head: Optional[UserMini] = None
    is_active: bool


class CategoryOut(Schema):
    id: int
    code: str
    name: dict
    icon: str
    color: str
    sla_hours: int
    default_priority: str
    requires_proof: bool
    requires_approval: bool
    default_steps: list = []
    department_id: Optional[int] = None
    is_active: bool


class LabelOut(Schema):
    id: int
    name: str
    color: str


class LabelIn(Schema):
    name: str
    color: str = "#1F5FBF"


class CategoryIn(Schema):
    name: I18n
    icon: str = "wrench"
    color: str = "#B7791F"
    sla_hours: int = 24
    default_priority: str = "normal"
    requires_proof: bool = True
    requires_approval: bool = True
    default_steps: list[str] = []
    department_id: Optional[int] = None
    is_active: bool = True


class StepOut(Schema):
    id: int
    title: str
    is_done: bool
    requires_photo: bool
    done_at: Optional[datetime] = None
    done_by: Optional[UserMini] = None
    sort_order: int


class AttachmentOut(Schema):
    id: int
    url: str
    kind: str
    caption: str
    is_image: bool
    created_at: datetime
    uploaded_by: Optional[UserMini] = None

    @staticmethod
    def resolve_url(obj):
        return obj.file.url


class CommentOut(Schema):
    id: int
    body: str
    is_system: bool
    created_at: datetime
    author: Optional[UserMini] = None


class ActivityOut(Schema):
    id: int
    at: datetime
    action: str
    detail: str
    meta: dict = {}
    actor: Optional[UserMini] = None


class TaskCard(Schema):
    """Kanban kartasi — yengil."""

    id: int
    number: int
    title: str
    column_id: int
    priority: str
    source: str
    status: str
    progress: int
    is_overdue: bool
    due_at: Optional[datetime] = None
    branch_name: Optional[str] = None
    department: Optional[dict] = None
    assignee: Optional[UserMini] = None
    labels: list[LabelOut] = []
    comments_count: int = 0
    attachments_count: int = 0
    steps_total: int = 0
    steps_done: int = 0
    sort_order: int = 0

    @staticmethod
    def resolve_branch_name(obj):
        return obj.branch.name if obj.branch_id else None

    @staticmethod
    def resolve_department(obj):
        return {"id": obj.department_id, "name": obj.department.name, "color": obj.department.color} if obj.department_id else None

    @staticmethod
    def resolve_attachments_count(obj):
        return len(obj.attachments.all())

    @staticmethod
    def resolve_steps_total(obj):
        return len(obj.steps.all())

    @staticmethod
    def resolve_steps_done(obj):
        return sum(1 for s in obj.steps.all() if s.is_done)

    @staticmethod
    def resolve_comments_count(obj):
        return getattr(obj, "comments_count", 0)


class TaskOut(TaskCard):
    """To'liq karta — o'ng paneldagi ko'rinish."""

    description: str = ""
    location: str = ""
    branch_id: Optional[int] = None
    category_id: Optional[int] = None
    department_id: Optional[int] = None
    supervisor: Optional[UserMini] = None
    reporter: Optional[UserMini] = None
    start_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    done_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[UserMini] = None
    estimated_cost: int = 0
    actual_cost: int = 0
    requires_proof: bool = True
    requires_approval: bool = True
    rework_count: int = 0
    is_archived: bool = False
    created_at: datetime
    steps: list[StepOut] = []
    attachments: list[AttachmentOut] = []
    can_approve: bool = False

    @staticmethod
    def resolve_can_approve(obj, context):
        user = context["request"].auth
        return bool(user and (user.has_perm_code("tasks.approve") or obj.supervisor_id == user.pk))


class TaskIn(Schema):
    title: str
    description: str = ""
    column_id: Optional[int] = None
    branch_id: Optional[int] = None
    department_id: Optional[int] = None
    category_id: Optional[int] = None
    label_ids: list[int] = []
    location: str = ""
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    supervisor_id: Optional[str] = None
    due_at: Optional[datetime] = None
    start_at: Optional[datetime] = None
    estimated_cost: int = 0
    actual_cost: int = 0
    requires_proof: Optional[bool] = None
    requires_approval: Optional[bool] = None
    steps: Optional[list[str]] = None
    source: str = Source.MANUAL


class TaskPatch(Schema):
    title: Optional[str] = None
    description: Optional[str] = None
    branch_id: Optional[int] = None
    department_id: Optional[int] = None
    category_id: Optional[int] = None
    label_ids: Optional[list[int]] = None
    location: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    supervisor_id: Optional[str] = None
    due_at: Optional[datetime] = None
    start_at: Optional[datetime] = None
    estimated_cost: Optional[int] = None
    actual_cost: Optional[int] = None
    requires_proof: Optional[bool] = None
    requires_approval: Optional[bool] = None
    is_archived: Optional[bool] = None


class MoveIn(Schema):
    column_id: int
    position: Optional[int] = None


class NoteIn(Schema):
    note: str = ""


class ReasonIn(Schema):
    reason: str


class CommentIn(Schema):
    body: str


class StepIn(Schema):
    title: str
    requires_photo: bool = False


class StepPatch(Schema):
    is_done: Optional[bool] = None
    title: Optional[str] = None


class ReorderIn(Schema):
    ids: list[int]


class RecurrenceIn(Schema):
    title: str
    description: str = ""
    category_id: Optional[int] = None
    department_id: Optional[int] = None
    branch_id: Optional[int] = None
    assignee_id: Optional[str] = None
    supervisor_id: Optional[str] = None
    priority: str = Priority.NORMAL
    steps: list[str] = []
    freq: str = "daily"
    interval: int = 1
    weekdays: list[int] = []
    day_of_month: int = 1
    time_of_day: str = "09:00"
    due_in_hours: int = 8
    is_active: bool = True


class RecurrenceOut(Schema):
    id: int
    title: str
    description: str
    freq: str
    interval: int
    weekdays: list = []
    day_of_month: int
    time_of_day: str
    due_in_hours: int
    is_active: bool
    priority: str
    steps: list = []
    category_id: Optional[int] = None
    department_id: Optional[int] = None
    branch_id: Optional[int] = None
    assignee: Optional[UserMini] = None
    last_created_on: Optional[str] = None

    @staticmethod
    def resolve_time_of_day(obj):
        return obj.time_of_day.strftime("%H:%M")

    @staticmethod
    def resolve_last_created_on(obj):
        return obj.last_created_on.isoformat() if obj.last_created_on else None


# ------------------------------------------------------------------ ma'lumotnomalar (ustun, bo'lim, tur, teg)
@router.get("/meta", auth=auth)
def meta(request):
    """Panel uchun bir so'rovda: ustunlar, bo'limlar, turlar, teglar, xodimlar, filiallar, ruxsatlar."""
    _guard(request, "tasks.view")
    services.ensure_setup()
    user = request.auth
    cols = TaskColumn.objects.annotate(n=Count("tasks", filter=Q(tasks__deleted_at__isnull=True, tasks__is_archived=False)))
    return {
        "columns": [{"id": c.id, "code": c.code, "name": c.name, "kind": c.kind, "color": c.color,
                     "wip_limit": c.wip_limit, "sort_order": c.sort_order, "is_active": c.is_active, "count": c.n}
                    for c in cols],
        "departments": [{"id": d.id, "code": d.code, "name": d.name, "color": d.color, "is_active": d.is_active,
                         "head_id": str(d.head_id) if d.head_id else None} for d in TaskDepartment.objects.all()],
        "categories": [{"id": c.id, "code": c.code, "name": c.name, "icon": c.icon, "color": c.color,
                        "sla_hours": c.sla_hours, "default_priority": c.default_priority,
                        "requires_proof": c.requires_proof, "requires_approval": c.requires_approval,
                        "default_steps": c.default_steps, "department_id": c.department_id, "is_active": c.is_active}
                       for c in TaskCategory.objects.all()],
        "labels": [{"id": lbl.id, "name": lbl.name, "color": lbl.color} for lbl in TaskLabel.objects.all()],
        "branches": [{"id": b.id, "name": b.name} for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True)],
        "users": [{"id": str(u.pk), "full_name": u.full_name, "phone": u.phone,
                   "avatar": u.avatar.url if u.avatar else None} for u in User.objects.filter(is_active=True)[:300]],
        "priorities": [{"code": p.value, "label": p.label} for p in Priority],
        "can": {
            "create": user.has_perm_code("tasks.create"),
            "edit": user.has_perm_code("tasks.edit"),
            "assign": user.has_perm_code("tasks.assign"),
            "approve": user.has_perm_code("tasks.approve"),
            "admin": user.has_perm_code("tasks.admin"),
            "delete": user.has_perm_code("tasks.delete"),
            "view_all": user.has_perm_code("tasks.view_all") or user.has_perm_code("tasks.admin"),
        },
    }


@router.post("/columns", response=ColumnOut, auth=auth)
def create_column(request, data: ColumnIn):
    """Egasi yangi ustun qo'shadi — kod avtomatik, tartib oxiriga."""
    _guard(request, "tasks.admin")
    base = (data.name.uz or data.kind).lower().replace(" ", "_")[:30] or "column"
    code, i = base, 1
    while TaskColumn.objects.filter(code=code).exists():
        i += 1
        code = f"{base}_{i}"
    c = TaskColumn.objects.create(code=code, name=data.name.dict(), kind=data.kind, color=data.color,
                                  wip_limit=data.wip_limit, is_active=data.is_active,
                                  sort_order=TaskColumn.objects.count())
    record(request, "create", c)
    return c


@router.put("/columns/{cid}", response=ColumnOut, auth=auth)
def update_column(request, cid: int, data: ColumnIn):
    _guard(request, "tasks.admin")
    c = get_object_or_404(TaskColumn, pk=cid)
    before = snapshot(c)
    c.name, c.kind, c.color, c.wip_limit, c.is_active = data.name.dict(), data.kind, data.color, data.wip_limit, data.is_active
    c.save()
    record(request, "update", c, before=before)
    return c


@router.delete("/columns/{cid}", auth=auth)
def delete_column(request, cid: int):
    _guard(request, "tasks.admin")
    c = get_object_or_404(TaskColumn, pk=cid)
    if c.tasks.filter(deleted_at__isnull=True).exists():
        raise HttpError(400, "Ustunda vazifalar bor — avval ularni boshqa ustunga ko'chiring.")
    if TaskColumn.objects.count() <= 2:
        raise HttpError(400, "Kamida ikkita ustun qolishi kerak.")
    record(request, "delete", c)
    c.delete()
    return {"ok": True}


@router.post("/columns/reorder", auth=auth)
def reorder_columns(request, data: ReorderIn):
    _guard(request, "tasks.admin")
    for i, cid in enumerate(data.ids):
        TaskColumn.objects.filter(pk=cid).update(sort_order=i)
    record(request, "reorder", model="TaskColumn", after={"ids": data.ids})
    return {"ok": True}


@router.post("/labels", response=LabelOut, auth=auth)
def create_label(request, data: LabelIn):
    _guard(request, "tasks.edit")
    return TaskLabel.objects.create(name=data.name, color=data.color)


@router.put("/categories/{cid}", response=CategoryOut, auth=auth)
def update_category(request, cid: int, data: CategoryIn):
    """Muammo turi qoidalari: SLA, dalil/tasdiq majburiyligi, standart bosqichlar."""
    _guard(request, "tasks.admin")
    c = get_object_or_404(TaskCategory, pk=cid)
    before = snapshot(c)
    for f, v in data.dict().items():
        setattr(c, f, v.dict() if f == "name" else v)
    c.save()
    record(request, "update", c, before=before)
    return c


# ------------------------------------------------------------------ doska va ro'yxat
def _apply_filters(qs, request, branch_id, department_id, category_id, priority, assignee_id,
                   q, overdue, mine, archived, source):
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if department_id:
        qs = qs.filter(department_id=department_id)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if priority:
        qs = qs.filter(priority=priority)
    if assignee_id:
        qs = qs.filter(assignee_id=assignee_id)
    if source:
        qs = qs.filter(source=source)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
    if overdue:
        from django.utils import timezone
        qs = qs.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).filter(due_at__lt=timezone.now())
    if mine:
        qs = qs.for_user(request.auth)
    return qs.filter(is_archived=bool(archived))


@router.get("/board", auth=auth)
def board(request, branch_id: Optional[int] = None, department_id: Optional[int] = None,
          category_id: Optional[int] = None, priority: Optional[str] = None, assignee_id: Optional[str] = None,
          q: Optional[str] = None, overdue: bool = False, mine: bool = False, archived: bool = False,
          source: Optional[str] = None, limit_per_column: int = 60):
    """Kanban: ustunlar + har ustundagi kartalar + statistika (bitta so'rov)."""
    _guard(request, "tasks.view")
    services.ensure_setup()
    qs = _apply_filters(_task_qs(request), request, branch_id, department_id, category_id, priority,
                        assignee_id, q, overdue, mine, archived, source)
    plain = _apply_filters(_plain_qs(request), request, branch_id, department_id, category_id, priority,
                           assignee_id, q, overdue, mine, archived, source)
    cards: dict[int, list] = {}
    for t in qs.order_by("sort_order", "-created_at"):
        cards.setdefault(t.column_id, [])
        if len(cards[t.column_id]) < limit_per_column:
            cards[t.column_id].append(TaskCard.from_orm(t).dict())
    columns = []
    for c in TaskColumn.objects.filter(is_active=True):
        columns.append({"id": c.id, "code": c.code, "name": c.name, "kind": c.kind, "color": c.color,
                        "wip_limit": c.wip_limit, "sort_order": c.sort_order,
                        "count": plain.filter(column_id=c.id).count(), "tasks": cards.get(c.id, [])})
    return {"columns": columns, "stats": services.board_stats(plain)}


@router.get("/tasks", response=list[TaskCard], auth=auth)
@paginate(PageNumberPagination, page_size=50)
def list_tasks(request, branch_id: Optional[int] = None, department_id: Optional[int] = None,
               category_id: Optional[int] = None, priority: Optional[str] = None, assignee_id: Optional[str] = None,
               q: Optional[str] = None, overdue: bool = False, mine: bool = False, archived: bool = False,
               source: Optional[str] = None, column_id: Optional[int] = None, ordering: str = "-created_at"):
    _guard(request, "tasks.view")
    qs = _apply_filters(_task_qs(request), request, branch_id, department_id, category_id, priority,
                        assignee_id, q, overdue, mine, archived, source)
    if column_id:
        qs = qs.filter(column_id=column_id)
    allowed = {"-created_at", "created_at", "due_at", "-due_at", "priority", "number", "-number"}
    return qs.order_by(ordering if ordering in allowed else "-created_at")


@router.get("/stats", auth=auth)
def stats(request, branch_id: Optional[int] = None, department_id: Optional[int] = None):
    _guard(request, "tasks.view")
    qs = _plain_qs(request).filter(is_archived=False)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if department_id:
        qs = qs.filter(department_id=department_id)
    return services.board_stats(qs)


# ------------------------------------------------------------------ vazifa CRUD
@router.post("/tasks", response=TaskOut, auth=auth)
def create_task(request, data: TaskIn):
    _guard(request, "tasks.create")
    if data.source == Source.MANUAL and not request.auth.has_perm_code("tasks.edit"):
        data.source = Source.ISSUE      # oddiy xodim ochsa — bu "muammo"
    t = services.create_task(
        request, title=data.title, description=data.description,
        column=TaskColumn.objects.filter(pk=data.column_id).first() if data.column_id else None,
        category=TaskCategory.objects.filter(pk=data.category_id).first() if data.category_id else None,
        department=TaskDepartment.objects.filter(pk=data.department_id).first() if data.department_id else None,
        branch=Branch.objects.filter(pk=data.branch_id).first() if data.branch_id else None,
        location=data.location, priority=data.priority,
        assignee=User.objects.filter(pk=data.assignee_id).first() if data.assignee_id else None,
        supervisor=User.objects.filter(pk=data.supervisor_id).first() if data.supervisor_id else None,
        reporter=request.auth, due_at=data.due_at, start_at=data.start_at,
        estimated_cost=data.estimated_cost, source=data.source, steps=data.steps,
        label_ids=data.label_ids, requires_proof=data.requires_proof, requires_approval=data.requires_approval,
    )
    record(request, "create", t)
    return _task_qs(request).get(pk=t.pk)


@router.get("/tasks/{tid}", response=TaskOut, auth=auth)
def get_task(request, tid: int):
    _guard(request, "tasks.view")
    return get_object_or_404(_task_qs(request), pk=tid)


@router.patch("/tasks/{tid}", response=TaskOut, auth=auth)
def patch_task(request, tid: int, data: TaskPatch):
    _guard(request, "tasks.edit")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    before = snapshot(t)
    payload = data.dict(exclude_unset=True)
    label_ids = payload.pop("label_ids", None)
    for k, v in payload.items():
        setattr(t, k, v)
    t.save()
    if label_ids is not None:
        t.labels.set(label_ids)
    changed = ", ".join(k for k in payload)
    services.log(t, request.auth, "updated", f"O'zgardi: {changed}" if changed else "")
    if "assignee_id" in payload:
        services.log(t, request.auth, "assigned", f"Bajaruvchi: {t.assignee.full_name if t.assignee else '—'}")
    record(request, "update", t, before=before)
    return _task_qs(request).get(pk=t.pk)


@router.delete("/tasks/{tid}", auth=auth)
def delete_task(request, tid: int):
    _guard(request, "tasks.delete")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    t.soft_delete()
    record(request, "delete", t)
    return {"ok": True}


# ------------------------------------------------------------------ oqim: ko'chirish, topshirish, tasdiqlash
@router.post("/tasks/{tid}/move", response=TaskOut, auth=auth)
def move(request, tid: int, data: MoveIn):
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    col = get_object_or_404(TaskColumn, pk=data.column_id)
    services.move_task(request, t, col, data.position)
    return _task_qs(request).get(pk=t.pk)


@router.post("/tasks/{tid}/submit", response=TaskOut, auth=auth)
def submit(request, tid: int):
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    services.submit_task(request, t)
    return _task_qs(request).get(pk=t.pk)


@router.post("/tasks/{tid}/approve", response=TaskOut, auth=auth)
def approve(request, tid: int, data: NoteIn):
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    services.approve_task(request, t, data.note)
    return _task_qs(request).get(pk=t.pk)


@router.post("/tasks/{tid}/reject", response=TaskOut, auth=auth)
def reject(request, tid: int, data: ReasonIn):
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    services.reject_task(request, t, data.reason)
    return _task_qs(request).get(pk=t.pk)


@router.post("/tasks/{tid}/archive", response=TaskOut, auth=auth)
def archive(request, tid: int, archived: bool = True):
    _guard(request, "tasks.edit")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    services.archive_task(request, t, archived)
    return _task_qs(request).get(pk=t.pk)


# ------------------------------------------------------------------ bosqichlar
@router.post("/tasks/{tid}/steps", response=StepOut, auth=auth)
def add_step(request, tid: int, data: StepIn):
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    return TaskStep.objects.create(task=t, title=data.title, requires_photo=data.requires_photo,
                                   sort_order=t.steps.count())


@router.patch("/steps/{sid}", response=StepOut, auth=auth)
def patch_step(request, sid: int, data: StepPatch):
    _guard(request, "tasks.view")
    s = get_object_or_404(TaskStep, pk=sid)
    if data.title is not None:
        s.title = data.title
        s.save(update_fields=["title", "updated_at"])
    if data.is_done is not None:
        services.toggle_step(request, s, data.is_done)
    return s


@router.delete("/steps/{sid}", auth=auth)
def delete_step(request, sid: int):
    _guard(request, "tasks.edit")
    get_object_or_404(TaskStep, pk=sid).delete()
    return {"ok": True}


# ------------------------------------------------------------------ fayllar (muammo rasmi va dalil)
@router.post("/tasks/{tid}/attachments", response=AttachmentOut, auth=auth)
def upload_attachment(request, tid: int, kind: str = Attachment.PHOTO, caption: str = "",
                      step_id: Optional[int] = None, file: UploadedFile = File(...)):
    """Muammo rasmi (`photo`) yoki bajarilgan ish dalili (`proof`). Telefondan ham shu yo'l."""
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    if kind not in services.ATTACHMENT_KINDS:
        raise HttpError(400, "Noto'g'ri fayl turi.")
    a = TaskAttachment.objects.create(task=t, file=file, kind=kind, caption=caption,
                                      step_id=step_id, uploaded_by=request.auth)
    services.log(t, request.auth, "proof" if kind == Attachment.PROOF else "photo",
                 caption or ("Dalil yuklandi" if kind == Attachment.PROOF else "Rasm yuklandi"))
    return a


@router.delete("/attachments/{aid}", auth=auth)
def delete_attachment(request, aid: int):
    _guard(request, "tasks.edit")
    get_object_or_404(TaskAttachment, pk=aid).delete()
    return {"ok": True}


# ------------------------------------------------------------------ izoh va tarix
@router.get("/tasks/{tid}/comments", response=list[CommentOut], auth=auth)
def list_comments(request, tid: int):
    _guard(request, "tasks.view")
    return TaskComment.objects.filter(task_id=tid).select_related("author")


@router.post("/tasks/{tid}/comments", response=CommentOut, auth=auth)
def add_comment(request, tid: int, data: CommentIn):
    _guard(request, "tasks.view")
    t = get_object_or_404(Task.objects.live(), pk=tid)
    if not data.body.strip():
        raise HttpError(400, "Izoh bo'sh.")
    return services.add_comment(request, t, data.body.strip())


@router.get("/tasks/{tid}/activity", response=list[ActivityOut], auth=auth)
def activity(request, tid: int):
    _guard(request, "tasks.view")
    return get_object_or_404(Task.objects.live(), pk=tid).activity.select_related("actor")[:200]


# ------------------------------------------------------------------ takroriy vazifalar
@router.get("/recurrences", response=list[RecurrenceOut], auth=auth)
def list_recurrences(request):
    _guard(request, "tasks.view")
    return TaskRecurrence.objects.select_related("assignee").all()


@router.post("/recurrences", response=RecurrenceOut, auth=auth)
def create_recurrence(request, data: RecurrenceIn):
    _guard(request, "tasks.admin")
    r = TaskRecurrence.objects.create(**data.dict())
    record(request, "create", r)
    return r


@router.put("/recurrences/{rid}", response=RecurrenceOut, auth=auth)
def update_recurrence(request, rid: int, data: RecurrenceIn):
    _guard(request, "tasks.admin")
    r = get_object_or_404(TaskRecurrence, pk=rid)
    before = snapshot(r)
    for k, v in data.dict().items():
        setattr(r, k, v)
    r.save()
    record(request, "update", r, before=before)
    return r


@router.delete("/recurrences/{rid}", auth=auth)
def delete_recurrence(request, rid: int):
    _guard(request, "tasks.admin")
    get_object_or_404(TaskRecurrence, pk=rid).delete()
    return {"ok": True}


@router.post("/recurrences/run", auth=auth)
def run_recurrences_now(request):
    """Qo'lda ishga tushirish (odatda Celery beat har kuni bajaradi)."""
    _guard(request, "tasks.admin")
    return {"created": services.run_recurrences(request)}
