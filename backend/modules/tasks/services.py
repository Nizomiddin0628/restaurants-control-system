"""
Vazifa oqimi — barcha qoidalar shu yerda (API faqat chaqiradi, tekshiruvlar bir joyda).

Qoidalar:
  1. "Tekshiruvda" ustuniga o'tish = ishni topshirish. `requires_proof` bo'lsa, kamida bitta dalil-foto shart.
  2. "Bajarildi" ustuniga faqat tasdiqlash orqali o'tiladi (`requires_approval` bo'lsa) — `tasks.approve` ruxsati
     yoki nazoratchining o'zi. Bajaruvchi o'z ishini o'zi yopa olmaydi.
  3. Rad etish ishni "Jarayonda"ga qaytaradi, sababni izohga yozadi va `rework_count` ni oshiradi.
  4. Har harakat TaskActivity'ga tushadi va hodisa (event) chiqaradi — Telegram/push keyin shunga ulanadi.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from ninja.errors import HttpError

from core.events import emit

from .models import (
    Attachment,
    ColumnKind,
    Freq,
    Priority,
    Source,
    Task,
    TaskActivity,
    TaskCategory,
    TaskColumn,
    TaskComment,
    TaskRecurrence,
    TaskStep,
)

# ---------------------------------------------------------------- boshlang'ich konfiguratsiya

DEFAULT_COLUMNS = [
    ("new", {"uz": "Yangi", "ru": "Новые", "en": "New"}, ColumnKind.BACKLOG, "#6C5CA8", 0),
    ("in_progress", {"uz": "Jarayonda", "ru": "В работе", "en": "In progress"}, ColumnKind.ACTIVE, "#B7791F", 0),
    ("review", {"uz": "Tekshiruvda", "ru": "На проверке", "en": "In review"}, ColumnKind.REVIEW, "#1F5FBF", 0),
    ("done", {"uz": "Bajarildi", "ru": "Готово", "en": "Done"}, ColumnKind.DONE, "#1E7F4F", 0),
]

DEFAULT_DEPARTMENTS = [
    ("economy", {"uz": "Xo'jalik", "ru": "Хозяйственный", "en": "Facilities"}, "#8A5A12"),
    ("kitchen", {"uz": "Oshxona", "ru": "Кухня", "en": "Kitchen"}, "#D9482B"),
    ("service", {"uz": "Zal va xizmat", "ru": "Зал и сервис", "en": "Service"}, "#0F6E63"),
    ("it", {"uz": "IT", "ru": "IT", "en": "IT"}, "#1F5FBF"),
    ("marketing", {"uz": "Marketing", "ru": "Маркетинг", "en": "Marketing"}, "#7A3FB5"),
    ("hr", {"uz": "HR", "ru": "HR", "en": "HR"}, "#C2321F"),
    ("warehouse", {"uz": "Ombor", "ru": "Склад", "en": "Warehouse"}, "#1E7F4F"),
    ("safety", {"uz": "Xavfsizlik", "ru": "Безопасность", "en": "Safety"}, "#B7791F"),
]

DEFAULT_CATEGORIES = [
    # (kod, nom, bo'lim, ikonka, SLA soat, ustuvorlik, dalil, tasdiq, bosqichlar)
    ("furniture", {"uz": "Mebel / Jihoz", "ru": "Мебель / Оборудование", "en": "Furniture"}, "economy", "sofa", 48, Priority.NORMAL,
     ["Usta topish", "Materiallar olish", "Remont ishlari", "Sifatni tekshirish", "Oldin / keyin rasm yuklash"]),
    ("sanitary", {"uz": "Sanitariya va tozalik", "ru": "Санитария", "en": "Sanitation"}, "service", "sparkle", 8, Priority.HIGH,
     ["Hududni tozalash", "Dezinfeksiya", "Foto-hisobot"]),
    ("equipment", {"uz": "Texnik nosozlik", "ru": "Поломка оборудования", "en": "Equipment"}, "kitchen", "wrench", 12, Priority.URGENT,
     ["Nosozlikni aniqlash", "Xizmat chaqirish", "Ta'mirlash", "Sinov ishga tushirish"]),
    ("it", {"uz": "IT va tarmoq", "ru": "IT и сеть", "en": "IT"}, "it", "wifi", 24, Priority.NORMAL,
     ["Muammoni takrorlash", "Yechim", "Tekshirish"]),
    ("safety", {"uz": "Xavfsizlik va nazorat", "ru": "Безопасность", "en": "Safety"}, "safety", "shield", 24, Priority.HIGH,
     ["Tekshirish", "Kamchiliklarni bartaraf etish", "Akt"]),
    ("supply", {"uz": "Ta'minot / Ombor", "ru": "Снабжение", "en": "Supply"}, "warehouse", "box", 24, Priority.NORMAL,
     ["Zakaz berish", "Qabul qilish", "Omborga kirim"]),
    ("marketing", {"uz": "Marketing va kontent", "ru": "Маркетинг", "en": "Marketing"}, "marketing", "megaphone", 72, Priority.NORMAL,
     ["Kontent tayyorlash", "Kelishuv", "E'lon qilish"]),
    ("staff", {"uz": "Xodimlar (HR)", "ru": "Персонал", "en": "Staff"}, "hr", "users", 72, Priority.NORMAL,
     ["Hujjatlar", "Suhbat", "Natija"]),
]


def ensure_setup() -> None:
    """Ustunlar, bo'limlar va muammo turlari — restoran birinchi kirganda avtomatik yaratiladi."""
    from .models import TaskDepartment

    for i, (code, name, kind, color, wip) in enumerate(DEFAULT_COLUMNS):
        TaskColumn.objects.get_or_create(code=code, defaults={"name": name, "kind": kind, "color": color,
                                                              "wip_limit": wip, "sort_order": i})
    deps = {}
    for i, (code, name, color) in enumerate(DEFAULT_DEPARTMENTS):
        deps[code], _ = TaskDepartment.objects.get_or_create(code=code, defaults={"name": name, "color": color, "sort_order": i})
    for i, (code, name, dep, icon, sla, prio, steps) in enumerate(DEFAULT_CATEGORIES):
        TaskCategory.objects.get_or_create(code=code, defaults={
            "name": name, "department": deps.get(dep), "icon": icon, "sla_hours": sla,
            "default_priority": prio, "default_steps": steps, "sort_order": i,
        })


def column_by_kind(kind: str) -> TaskColumn | None:
    return TaskColumn.objects.filter(kind=kind, is_active=True).order_by("sort_order").first()


# ---------------------------------------------------------------- yordamchilar

def log(task: Task, actor, action: str, detail: str = "", **meta) -> TaskActivity:
    return TaskActivity.objects.create(task=task, actor=actor if getattr(actor, "pk", None) else None,
                                       action=action, detail=detail[:240], meta=meta)


def _emit(request, event: str, task: Task, **extra):
    emit(f"tasks.{event}", {
        "task_id": task.pk, "number": task.number, "title": task.title,
        "status": task.column.kind, "priority": task.priority,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "supervisor_id": str(task.supervisor_id) if task.supervisor_id else None,
        "branch_id": task.branch_id, "due_at": task.due_at.isoformat() if task.due_at else None,
        **extra,
    }, tenant=getattr(request, "tenant", None))


def _next_sort(column: TaskColumn) -> int:
    return (Task.objects.filter(column=column).aggregate(m=Max("sort_order"))["m"] or 0) + 1


# ---------------------------------------------------------------- yaratish

@transaction.atomic
def create_task(request, *, title: str, description: str = "", column: TaskColumn | None = None,
                category: TaskCategory | None = None, department=None, branch=None, location: str = "",
                priority: str | None = None, assignee=None, supervisor=None, reporter=None,
                due_at=None, start_at=None, estimated_cost: int = 0, source: str = Source.MANUAL,
                steps: list[str] | None = None, label_ids: list[int] | None = None,
                requires_proof: bool | None = None, requires_approval: bool | None = None,
                recurrence: TaskRecurrence | None = None) -> Task:
    column = column or column_by_kind(ColumnKind.BACKLOG) or TaskColumn.objects.first()
    if column is None:
        ensure_setup()
        column = column_by_kind(ColumnKind.BACKLOG)

    if category is not None:
        department = department or category.department
        priority = priority or category.default_priority
        if due_at is None and category.sla_hours:
            due_at = timezone.now() + timedelta(hours=category.sla_hours)
        if requires_proof is None:
            requires_proof = category.requires_proof
        if requires_approval is None:
            requires_approval = category.requires_approval
        if steps is None and category.default_steps:
            steps = list(category.default_steps)
        assignee = assignee or category.default_assignee
    if supervisor is None and department is not None:
        supervisor = department.head

    task = Task.objects.create(
        title=title.strip(), description=description, column=column, category=category, department=department,
        branch=branch, location=location, priority=priority or Priority.NORMAL, source=source,
        reporter=reporter, assignee=assignee, supervisor=supervisor, due_at=due_at, start_at=start_at,
        estimated_cost=estimated_cost, requires_proof=True if requires_proof is None else requires_proof,
        requires_approval=True if requires_approval is None else requires_approval,
        recurrence=recurrence, sort_order=_next_sort(column),
    )
    if label_ids:
        task.labels.set(label_ids)
    for i, s in enumerate(steps or []):
        TaskStep.objects.create(task=task, title=s, sort_order=i)

    log(task, reporter, "created", f"{'Muammo' if source == Source.ISSUE else 'Vazifa'} ochildi")
    if assignee:
        log(task, reporter, "assigned", f"Bajaruvchi: {assignee.full_name or assignee.phone}")
    _emit(request, "created", task, source=source)
    return task


# ---------------------------------------------------------------- oqim

def _can_approve(user, task: Task) -> bool:
    return bool(user and (user.has_perm_code("tasks.approve") or task.supervisor_id == getattr(user, "pk", None)))


@transaction.atomic
def move_task(request, task: Task, column: TaskColumn, position: int | None = None) -> Task:
    """Kanban'da ko'chirish — qoidalar bilan (dalil, tasdiq, WIP chegarasi)."""
    user = request.auth
    old = task.column
    if old.pk == column.pk:
        _reposition(task, column, position)
        return task

    if column.kind == ColumnKind.REVIEW and task.requires_proof and not task.has_proof:
        raise HttpError(400, "Dalil yo'q: tekshiruvga yuborishdan oldin bajarilgan ish rasmini yuklang.")
    if column.kind == ColumnKind.DONE and task.requires_approval and not _can_approve(user, task):
        raise HttpError(403, "Bajarildi deb faqat nazoratchi (yoki tasdiqlash huquqi bor xodim) belgilay oladi.")
    if column.wip_limit and column.tasks.filter(deleted_at__isnull=True).count() >= column.wip_limit:
        raise HttpError(400, f"«{column.name.get('uz')}» ustunida bir vaqtda {column.wip_limit} tadan ortiq vazifa bo'lmasin.")

    task.column = column
    now = timezone.now()
    if column.kind == ColumnKind.ACTIVE and not task.start_at:
        task.start_at = now
    if column.kind == ColumnKind.REVIEW:
        task.submitted_at = now
    if column.kind == ColumnKind.DONE:
        task.done_at = task.done_at or now
        task.approved_at = task.approved_at or now
        task.approved_by = task.approved_by or (user if getattr(user, "pk", None) else None)
    else:
        task.done_at = task.approved_at = None
        task.approved_by = None
    task.sort_order = position if position is not None else _next_sort(column)
    task.save()
    _reposition(task, column, position)

    log(task, user, "moved", f"{old.name.get('uz')} → {column.name.get('uz')}",
        **{"from": old.code, "to": column.code})
    _emit(request, "status_changed", task, from_column=old.code, to_column=column.code)
    if column.kind == ColumnKind.DONE:
        _emit(request, "completed", task)
    return task


def _reposition(task: Task, column: TaskColumn, position: int | None):
    if position is None:
        return
    others = list(Task.objects.filter(column=column, deleted_at__isnull=True).exclude(pk=task.pk).order_by("sort_order", "-created_at"))
    others.insert(max(0, min(position, len(others))), task)
    for i, t in enumerate(others):
        if t.sort_order != i:
            Task.objects.filter(pk=t.pk).update(sort_order=i)


@transaction.atomic
def submit_task(request, task: Task) -> Task:
    """Bajaruvchi: "tayyor" — dalil tekshiriladi va ish tekshiruvga o'tadi."""
    col = column_by_kind(ColumnKind.REVIEW) or column_by_kind(ColumnKind.DONE)
    if col is None:
        raise HttpError(400, "Tekshiruv ustuni topilmadi.")
    task = move_task(request, task, col)
    log(task, request.auth, "submitted", "Ish tekshiruvga topshirildi")
    _emit(request, "submitted", task)
    return task


@transaction.atomic
def approve_task(request, task: Task, note: str = "") -> Task:
    user = request.auth
    if task.requires_approval and not _can_approve(user, task):
        raise HttpError(403, "Tasdiqlash huquqi yo'q.")
    if task.requires_proof and not task.has_proof:
        raise HttpError(400, "Dalil (foto) yuklanmagan — tasdiqlab bo'lmaydi.")
    done = column_by_kind(ColumnKind.DONE)
    if done is None:
        raise HttpError(400, "«Bajarildi» ustuni topilmadi.")
    task.column = done
    task.done_at = task.done_at or timezone.now()
    task.approved_at = timezone.now()
    task.approved_by = user if getattr(user, "pk", None) else None
    task.sort_order = _next_sort(done)
    task.save()
    if note:
        TaskComment.objects.create(task=task, author=user if getattr(user, "pk", None) else None, body=note)
    log(task, user, "approved", note or "Ish tasdiqlandi")
    _emit(request, "approved", task)
    _emit(request, "completed", task)
    return task


@transaction.atomic
def reject_task(request, task: Task, reason: str) -> Task:
    user = request.auth
    if task.requires_approval and not _can_approve(user, task):
        raise HttpError(403, "Rad etish huquqi yo'q.")
    if not reason.strip():
        raise HttpError(400, "Rad etish sababini yozing — bajaruvchi nimani tuzatishni bilishi kerak.")
    back = column_by_kind(ColumnKind.ACTIVE) or column_by_kind(ColumnKind.BACKLOG)
    task.column = back
    task.submitted_at = None
    task.done_at = task.approved_at = None
    task.approved_by = None
    task.rework_count += 1
    task.sort_order = 0
    task.save()
    TaskComment.objects.create(task=task, author=user if getattr(user, "pk", None) else None,
                               body=f"Qaytarildi: {reason.strip()}", is_system=True)
    log(task, user, "rejected", reason.strip())
    _emit(request, "rejected", task, reason=reason.strip())
    return task


@transaction.atomic
def toggle_step(request, step: TaskStep, is_done: bool) -> TaskStep:
    user = request.auth
    if is_done and step.requires_photo and not step.photos.exists():
        raise HttpError(400, "Bu bosqich uchun foto talab qilinadi.")
    step.is_done = is_done
    step.done_by = user if (is_done and getattr(user, "pk", None)) else None
    step.done_at = timezone.now() if is_done else None
    step.save()
    log(step.task, user, "step", f"{'✓' if is_done else '✗'} {step.title}")
    return step


def add_comment(request, task: Task, body: str) -> TaskComment:
    c = TaskComment.objects.create(task=task, author=request.auth if getattr(request.auth, "pk", None) else None, body=body)
    log(task, request.auth, "commented", body)
    _emit(request, "commented", task, comment=body[:200])
    return c


def archive_task(request, task: Task, archived: bool = True) -> Task:
    task.is_archived = archived
    task.save(update_fields=["is_archived", "updated_at"])
    log(task, request.auth, "archived" if archived else "unarchived")
    return task


# ---------------------------------------------------------------- statistika

def board_stats(qs) -> dict:
    from django.db.models import Count

    now = timezone.now()
    by_col = list(qs.values("column__code", "column__name", "column__kind", "column__color").annotate(n=Count("id")))
    by_dep = list(qs.exclude(department__isnull=True).values("department__name", "department__color").annotate(n=Count("id")).order_by("-n")[:8])
    by_prio = list(qs.values("priority").annotate(n=Count("id")))
    total = qs.count()
    return {
        "total": total,
        "open": qs.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).count(),
        "in_progress": qs.filter(column__kind=ColumnKind.ACTIVE).count(),
        "review": qs.filter(column__kind=ColumnKind.REVIEW).count(),
        "done": qs.filter(column__kind=ColumnKind.DONE).count(),
        "overdue": qs.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).filter(due_at__lt=now).count(),
        "by_column": [{"code": r["column__code"], "name": r["column__name"], "kind": r["column__kind"],
                       "color": r["column__color"], "count": r["n"]} for r in by_col],
        "by_department": [{"name": r["department__name"], "color": r["department__color"], "count": r["n"]} for r in by_dep],
        "by_priority": {r["priority"]: r["n"] for r in by_prio},
        "avg_hours_to_done": _avg_hours_to_done(qs),
        "rework_rate": _rework_rate(qs),
    }


def _avg_hours_to_done(qs) -> float | None:
    done = qs.filter(done_at__isnull=False).values_list("created_at", "done_at")[:500]
    if not done:
        return None
    hours = [max(0.0, (d - c).total_seconds() / 3600) for c, d in done]
    return round(sum(hours) / len(hours), 1)


def _rework_rate(qs) -> float:
    total = qs.count()
    return round(100 * qs.filter(rework_count__gt=0).count() / total, 1) if total else 0.0


# ---------------------------------------------------------------- takroriy vazifalar

def run_recurrences(request=None, today=None) -> int:
    """Celery beat har kuni chaqiradi: bugun tegishli shablonlardan vazifa ochadi."""
    today = today or timezone.localdate()
    created = 0

    class _Req:  # hodisa uchun yengil so'rov o'rnini bosuvchi
        auth = None
        tenant = getattr(request, "tenant", None) if request else None

    req = request or _Req()
    for rec in TaskRecurrence.objects.filter(is_active=True).select_related("category", "department"):
        if not rec.is_due_today(today):
            continue
        create_task(
            req, title=rec.title, description=rec.description, category=rec.category, department=rec.department,
            branch=rec.branch, priority=rec.priority, assignee=rec.assignee, supervisor=rec.supervisor,
            due_at=timezone.now() + timedelta(hours=rec.due_in_hours), source=Source.RECURRING,
            steps=list(rec.steps or []), recurrence=rec,
        )
        rec.last_created_on = today
        rec.save(update_fields=["last_created_on", "updated_at"])
        created += 1
    return created


def escalate_overdue(request=None) -> int:
    """Muddati o'tgan ochiq vazifalar — nazoratchiga xabar (hodisa). Kuniga bir marta yoziladi."""
    now = timezone.now()
    n = 0
    for task in Task.objects.overdue(now).select_related("column")[:500]:
        already = task.activity.filter(action="overdue", at__gte=now - timedelta(hours=20)).exists()
        if already:
            continue
        log(task, None, "overdue", f"Muddat o'tdi: {task.due_at:%d.%m.%Y %H:%M}")
        emit("tasks.overdue", {"task_id": task.pk, "number": task.number, "title": task.title,
                               "supervisor_id": str(task.supervisor_id) if task.supervisor_id else None},
             tenant=getattr(request, "tenant", None) if request else None)
        n += 1
    return n


# freq eksporti (API sxemalari uchun)
FREQ_CHOICES = [f.value for f in Freq]
ATTACHMENT_KINDS = [a.value for a in Attachment]
