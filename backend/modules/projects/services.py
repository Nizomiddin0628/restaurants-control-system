"""Loyihalar xizmatlari: progress va «sog'lomlik», shablondan yaratish, kirish huquqi, kalendar, bildirishnomalar, eslatmalar."""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.events import emit

from .models import (
    CAT_META,
    Activity,
    Category,
    Member,
    MemberRole,
    Milestone,
    PExpense,
    Priority,
    Project,
    PTask,
    Status,
    TaskStatus,
)
from .templates import TEMPLATES

HEALTH = {"ok": "O'z vaqtida", "risk": "Xavf ostida", "late": "Kechikmoqda", "done": "Yakunlangan", "idle": "To'xtagan"}


def setting(tenant, key, default):
    try:
        return (tenant.settings.get("modules", {}).get("projects", {}) or {}).get(key, default)
    except Exception:
        return default


def user_mini(u) -> dict | None:
    if not u:
        return None
    name = u.full_name or u.phone
    return {"id": str(u.pk), "name": name, "initials": "".join(w[0] for w in name.split()[:2]).upper() if name else "?",
            "avatar": u.avatar.url if getattr(u, "avatar", None) else None}


def cat_out(code: str) -> dict:
    e, c = CAT_META.get(code, CAT_META["other"])
    return {"code": code, "label": Category(code).label, "emoji": e, "color": c}


# ------------------------------------------------------------------ kirish huquqi
def can_edit_all(user) -> bool:
    return user.has_perm_code("projects.edit")


def visible_projects(user):
    qs = Project.objects.all()
    if can_edit_all(user):
        return qs
    return qs.filter(Q(owner=user) | Q(members__user=user) | Q(tasks__assignee=user)).distinct()


def is_lead(p: Project, user) -> bool:
    return can_edit_all(user) or p.owner_id == user.pk or p.members.filter(user=user, role=MemberRole.LEAD).exists()


def is_participant(p: Project, user) -> bool:
    return is_lead(p, user) or p.members.filter(user=user).exists() or p.tasks.filter(assignee=user).exists()


def can_touch_task(t: PTask, user) -> bool:
    """Vazifani o'zgartirish: loyiha rahbari yoki vazifa mas'uli."""
    return is_lead(t.project, user) or t.assignee_id == user.pk


# ------------------------------------------------------------------ hisob-kitob
def progress(tasks: list[PTask], status: str) -> int:
    if status == Status.DONE:
        return 100
    if not tasks:
        return 0
    return round(100 * sum(1 for t in tasks if t.status == TaskStatus.DONE) / len(tasks))


def planned_progress(p: Project, tasks: list[PTask]) -> int | None:
    """Reja bo'yicha bugungacha necha foiz bajarilgan bo'lishi kerak edi: muddati o'tgan vazifalar ulushi
    (vazifalarda muddat bo'lmasa — o'tgan vaqt ulushi)."""
    today = timezone.localdate()
    dated = [t for t in tasks if t.due]
    if dated:
        return round(100 * sum(1 for t in dated if t.due < today) / len(dated))
    if p.start and p.due and p.due > p.start:
        return max(0, min(100, round(100 * (today - p.start).days / (p.due - p.start).days)))
    return None


def health(p: Project, prog: int, overdue: int, gap: int = 25, planned: int | None = None) -> str:
    today = timezone.localdate()
    if p.status == Status.DONE:
        return "done"
    if p.status in (Status.PAUSED, Status.CANCELLED):
        return "idle"
    if p.due and today > p.due:
        return "late"
    if planned is not None and planned - prog > gap:
        return "risk"
    if overdue >= 3:
        return "risk"
    return "ok"


def task_out(t: PTask, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    cl = t.checklist or []
    return {"id": t.pk, "project_id": t.project_id, "title": t.title, "description": t.description,
            "status": t.status, "status_label": TaskStatus(t.status).label, "priority": t.priority, "priority_label": Priority(t.priority).label,
            "milestone_id": t.milestone_id, "assignee": user_mini(t.assignee), "due": t.due.isoformat() if t.due else None,
            "overdue": bool(t.due and t.due < today and t.status != TaskStatus.DONE),
            "days_left": (t.due - today).days if t.due else None,
            "checklist": cl, "check_done": sum(1 for c in cl if c.get("done")), "check_total": len(cl),
            "sort_order": t.sort_order, "done_at": t.done_at.isoformat() if t.done_at else None,
            "files": t.files.count() if hasattr(t, "files") else 0}


def project_out(p: Project, *, tenant=None, full: bool = False, user=None) -> dict:
    today = timezone.localdate()
    tasks = list(p.tasks.select_related("assignee").all())
    prog = progress(tasks, p.status)
    overdue = sum(1 for t in tasks if t.due and t.due < today and t.status != TaskStatus.DONE)
    spent = int(p.expenses.aggregate(s=Sum("amount"))["s"] or 0)
    planned = planned_progress(p, tasks)
    h = health(p, prog, overdue, int(setting(tenant, "risk_gap", 25) or 25) if tenant else 25, planned)
    ms = list(p.milestones.all())
    nxt = next((m for m in ms if not m.done_at), None)
    order = {MemberRole.LEAD: 0, MemberRole.MEMBER: 1, MemberRole.WATCHER: 2}
    members = [{"user": user_mini(m.user), "role": m.role, "role_label": MemberRole(m.role).label}
               for m in sorted(p.members.select_related("user"), key=lambda m: (order.get(m.role, 3), m.user.full_name))]
    out = {"id": p.pk, "code": p.code, "title": p.title, "description": p.description, "category": cat_out(p.category),
           "status": p.status, "status_label": Status(p.status).label, "priority": p.priority, "priority_label": Priority(p.priority).label,
           "branch": {"id": p.branch_id, "name": p.branch.name} if p.branch_id else None, "owner": user_mini(p.owner),
           "start": p.start.isoformat() if p.start else None, "due": p.due.isoformat() if p.due else None,
           "days_left": (p.due - today).days if p.due else None, "budget": p.budget, "spent": spent,
           "budget_percent": round(100 * spent / p.budget) if p.budget else None,
           "progress": prog, "planned_progress": planned, "tasks_total": len(tasks), "tasks_done": sum(1 for t in tasks if t.status == TaskStatus.DONE),
           "overdue": overdue, "health": h, "health_label": HEALTH[h], "members": members,
           "milestones_total": len(ms), "milestones_done": sum(1 for m in ms if m.done_at),
           "next_milestone": {"title": nxt.title, "due": nxt.due.isoformat() if nxt.due else None} if nxt else None,
           "template_key": p.template_key, "created_at": p.created_at.isoformat()}
    if full:
        by_ms: dict = {}
        for t in tasks:
            by_ms.setdefault(t.milestone_id, []).append(t)
        out["milestones"] = [{"id": m.pk, "title": m.title, "due": m.due.isoformat() if m.due else None, "done": bool(m.done_at),
                              "sort_order": m.sort_order, "progress": progress(by_ms.get(m.pk, []), ""),
                              "tasks_total": len(by_ms.get(m.pk, [])),
                              "overdue": bool(m.due and m.due < today and not m.done_at)} for m in ms]
        out["tasks"] = [task_out(t, today) for t in tasks]
        out["files"] = [file_out(f) for f in p.files.select_related("uploaded_by")]
        out["expenses"] = [{"id": e.pk, "date": e.date.isoformat(), "amount": e.amount, "note": e.note, "by": user_mini(e.created_by)}
                           for e in p.expenses.select_related("created_by")]
        out["activity"] = [activity_out(a) for a in p.activity.select_related("actor", "task")[:60]]
        if user is not None:
            out["can_edit"] = is_lead(p, user)
            out["can_delete"] = can_edit_all(user)
    return out


def file_out(f) -> dict:
    return {"id": f.pk, "title": f.title, "url": f.file.url if f.file else f.url, "is_link": not f.file, "size": f.size,
            "is_image": bool(f.file) and f.file.name.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp", "gif"),
            "ext": (f.file.name.rsplit(".", 1)[-1].lower() if f.file and "." in f.file.name else "link"),
            "task_id": f.task_id, "by": user_mini(f.uploaded_by), "created_at": f.created_at.isoformat()}


def activity_out(a: Activity) -> dict:
    return {"id": a.pk, "kind": a.kind, "text": a.text, "actor": user_mini(a.actor), "task_id": a.task_id,
            "task": a.task.title if a.task_id else None, "project_id": a.project_id, "at": a.created_at.isoformat()}


def log(p: Project, actor, kind: str, text: str, task: PTask | None = None) -> Activity:
    return Activity.objects.create(project=p, actor=actor if getattr(actor, "pk", None) else None, kind=kind, text=text, task=task)


# ------------------------------------------------------------------ yaratish
@transaction.atomic
def create_project(*, title: str, category: str, actor=None, template_key: str = "", start: date | None = None, due: date | None = None,
                   owner=None, branch_id=None, budget: int = 0, description: str = "", priority: str = Priority.NORMAL,
                   members: list | None = None, tenant=None) -> Project:
    tpl = TEMPLATES.get(template_key) if template_key else None
    start = start or timezone.localdate()
    if tpl:
        category = category or tpl["category"]
        description = description or tpl["description"]
        due = due or start + timedelta(days=tpl["days"])
    p = Project.objects.create(title=title.strip() or (tpl["title"] if tpl else "Yangi loyiha"), category=category or Category.OTHER,
                               description=description, start=start, due=due, owner=owner or actor, branch_id=branch_id, budget=max(0, budget),
                               priority=priority if priority in Priority.values else Priority.NORMAL,
                               status=Status.ACTIVE if tpl else Status.PLAN, template_key=template_key if tpl else "", created_by=actor)
    lead = owner or actor
    if lead:
        Member.objects.get_or_create(project=p, user=lead, defaults={"role": MemberRole.LEAD})
    for u in members or []:
        Member.objects.get_or_create(project=p, user=u, defaults={"role": MemberRole.MEMBER})
    if tpl:
        # shablon muddatlarini loyiha davomiyligiga moslaymiz (masalan 75 kunlik shablon 60 kunga siqiladi)
        span = (due - start).days if due and due > start else tpl["days"]
        k = span / tpl["days"]
        n = 0
        for i, (mt, moff, tasks) in enumerate(tpl["milestones"]):
            m = Milestone.objects.create(project=p, title=mt, due=start + timedelta(days=round(moff * k)), sort_order=i)
            for title_, off, cl in tasks:
                n += 1
                PTask.objects.create(project=p, milestone=m, title=title_, due=start + timedelta(days=round(off * k)), sort_order=n,
                                     checklist=[{"text": c, "done": False} for c in cl], created_by=actor)
    log(p, actor, "created", f"Loyiha yaratildi{' («' + tpl['title'] + '» shablonidan)' if tpl else ''}")
    emit("projects.created", {"project_id": p.pk, "code": p.code, "title": p.title}, tenant=tenant)
    return p


def set_task_status(t: PTask, status: str, actor=None, tenant=None) -> PTask:
    if status not in TaskStatus.values or status == t.status:
        return t
    old = t.status
    t.status = status
    t.done_at = timezone.now() if status == TaskStatus.DONE else None
    if status == TaskStatus.DONE and t.checklist:
        t.checklist = [{**c, "done": True} for c in t.checklist]
    t.save()
    log(t.project, actor, "done" if status == TaskStatus.DONE else "status",
        f"«{t.title}»: {TaskStatus(old).label} → {TaskStatus(status).label}", task=t)
    sync_milestone(t.milestone)
    p = t.project
    if p.status == Status.PLAN and status != TaskStatus.TODO:
        p.status = Status.ACTIVE
        p.save(update_fields=["status", "updated_at"])
    if status == TaskStatus.REVIEW and p.owner_id and p.owner_id != getattr(actor, "pk", None):
        emit("projects.task_review", {"task_id": t.pk, "title": t.title, "project": p.title, "owner_id": str(p.owner_id)}, tenant=tenant)
    return t


def sync_milestone(m: Milestone | None) -> None:
    if not m:
        return
    ts = list(m.tasks.values_list("status", flat=True))
    done = bool(ts) and all(s == TaskStatus.DONE for s in ts)
    if done and not m.done_at:
        m.done_at = timezone.now()
        m.save(update_fields=["done_at", "updated_at"])
        log(m.project, None, "milestone", f"🏁 Bosqich yakunlandi: {m.title}")
    elif not done and m.done_at and ts:
        m.done_at = None
        m.save(update_fields=["done_at", "updated_at"])


def assign(t: PTask, user, actor=None, tenant=None) -> None:
    if (t.assignee_id and str(t.assignee_id)) == (str(user.pk) if user else None):
        return
    t.assignee = user
    t.save(update_fields=["assignee", "updated_at"])
    if user:
        Member.objects.get_or_create(project=t.project, user=user, defaults={"role": MemberRole.MEMBER})
        log(t.project, actor, "task", f"«{t.title}» → {user.full_name or user.phone}", task=t)
        if user.pk != getattr(actor, "pk", None):
            emit("projects.task_assigned", {"task_id": t.pk, "title": t.title, "project": t.project.title, "assignee_id": str(user.pk),
                                            "due": t.due.isoformat() if t.due else None}, tenant=tenant)


# ------------------------------------------------------------------ ko'rinishlar
def overview(user, tenant=None) -> dict:
    today = timezone.localdate()
    remind_due(tenant)
    qs = visible_projects(user).select_related("branch", "owner").prefetch_related("tasks", "members__user", "milestones", "expenses")
    items = [project_out(p, tenant=tenant) for p in qs]
    live = [x for x in items if x["status"] in (Status.PLAN, Status.ACTIVE, Status.PAUSED)]
    month_start = today.replace(day=1)
    done_month = Project.objects.filter(pk__in=[x["id"] for x in items], status=Status.DONE, done_at__date__gte=month_start).count()
    task_qs = PTask.objects.filter(project__in=qs.values("pk"), project__status__in=[Status.PLAN, Status.ACTIVE]).select_related("project", "assignee")
    open_tasks = task_qs.exclude(status=TaskStatus.DONE)
    upcoming = []
    for t in open_tasks.filter(due__isnull=False, due__lte=today + timedelta(days=14)).order_by("due")[:12]:
        upcoming.append({**task_out(t, today), "type": "task", "project": t.project.title, "project_code": t.project.code})
    for m in Milestone.objects.filter(project__in=qs.values("pk"), done_at__isnull=True, due__isnull=False, due__lte=today + timedelta(days=14),
                                      project__status__in=[Status.PLAN, Status.ACTIVE]).select_related("project"):
        upcoming.append({"type": "milestone", "id": m.pk, "project_id": m.project_id, "title": m.title, "project": m.project.title,
                         "project_code": m.project.code, "due": m.due.isoformat(), "days_left": (m.due - today).days, "overdue": m.due < today})
    upcoming.sort(key=lambda x: x["due"])
    mine = [{**task_out(t, today), "project": t.project.title, "project_code": t.project.code}
            for t in open_tasks.filter(assignee=user).order_by("due", "sort_order")[:15]]
    by_cat = {}
    for x in live:
        by_cat[x["category"]["code"]] = by_cat.get(x["category"]["code"], 0) + 1
    budget = sum(x["budget"] for x in live)
    spent = sum(x["spent"] for x in live)
    return {
        "kpis": {"active": sum(1 for x in live if x["status"] == Status.ACTIVE), "total": len(items), "plan": sum(1 for x in live if x["status"] == Status.PLAN),
                 "done_month": done_month, "risk": sum(1 for x in live if x["health"] in ("risk", "late")),
                 "late": sum(1 for x in live if x["health"] == "late"),
                 "open_tasks": open_tasks.count(), "overdue_tasks": open_tasks.filter(due__lt=today).count(),
                 "my_tasks": open_tasks.filter(assignee=user).count(), "budget": budget, "spent": spent,
                 "avg_progress": round(sum(x["progress"] for x in live) / len(live)) if live else 0},
        "health": [{"key": k, "label": HEALTH[k], "value": sum(1 for x in live if x["health"] == k)} for k in ("ok", "risk", "late", "idle")],
        "by_category": [{**cat_out(c), "count": n} for c, n in sorted(by_cat.items(), key=lambda x: -x[1])],
        "projects": items, "upcoming": upcoming[:8], "my_tasks": mine, "feed": feed(user, 10),
    }


def feed(user, limit: int = 30) -> list[dict]:
    """Bildirishnomalar: men ishtirok etgan loyihalardagi boshqalar qilgan ishlar."""
    pids = visible_projects(user).values("pk")
    qs = Activity.objects.filter(project__in=pids).exclude(actor=user).select_related("actor", "task", "project")
    if not can_edit_all(user):
        qs = qs.filter(Q(task__assignee=user) | Q(project__owner=user) | Q(kind__in=["comment", "milestone", "created", "file"]))
    return [{**activity_out(a), "project": a.project.title, "project_code": a.project.code} for a in qs[:limit]]


def calendar_events(user, year: int, month: int) -> dict:
    first = date(year, month, 1)
    last = date(year, month, _cal.monthrange(year, month)[1])
    pids = visible_projects(user).exclude(status=Status.CANCELLED).values("pk")
    ev = []
    for t in PTask.objects.filter(project__in=pids, due__gte=first, due__lte=last).select_related("project", "assignee"):
        ev.append({"type": "task", "id": t.pk, "date": t.due.isoformat(), "title": t.title, "project_id": t.project_id, "project": t.project.title,
                   "color": CAT_META[t.project.category][1], "done": t.status == TaskStatus.DONE,
                   "overdue": t.status != TaskStatus.DONE and t.due < timezone.localdate(), "assignee": user_mini(t.assignee)})
    for m in Milestone.objects.filter(project__in=pids, due__gte=first, due__lte=last).select_related("project"):
        ev.append({"type": "milestone", "id": m.pk, "date": m.due.isoformat(), "title": m.title, "project_id": m.project_id, "project": m.project.title,
                   "color": CAT_META[m.project.category][1], "done": bool(m.done_at), "overdue": False, "assignee": None})
    for p in Project.objects.filter(pk__in=pids).filter(Q(start__gte=first, start__lte=last) | Q(due__gte=first, due__lte=last)):
        if p.start and first <= p.start <= last:
            ev.append({"type": "start", "id": p.pk, "date": p.start.isoformat(), "title": f"Boshlanish: {p.title}", "project_id": p.pk,
                       "project": p.title, "color": CAT_META[p.category][1], "done": False, "overdue": False, "assignee": None})
        if p.due and first <= p.due <= last:
            ev.append({"type": "due", "id": p.pk, "date": p.due.isoformat(), "title": f"Tugash: {p.title}", "project_id": p.pk,
                       "project": p.title, "color": CAT_META[p.category][1], "done": p.status == Status.DONE, "overdue": False, "assignee": None})
    ev.sort(key=lambda e: (e["date"], e["type"] != "due", e["type"] != "milestone"))
    return {"year": year, "month": month, "first_weekday": first.weekday(), "days": last.day, "events": ev}


# ------------------------------------------------------------------ eslatmalar (lazy, soatiga bir marta)
def remind_due(tenant) -> int:
    """Ertaga yoki bugun muddati tugaydigan ochiq vazifalar — mas'ulga bir marta Telegram eslatma."""
    if tenant is None or not cache.add(f"projects:remind:{tenant.schema_name}", 1, 3600):
        return 0
    today = timezone.localdate()
    n = 0
    for t in (PTask.objects.filter(due__in=[today, today + timedelta(days=1)], assignee__isnull=False, project__status=Status.ACTIVE)
              .exclude(status=TaskStatus.DONE).exclude(reminded_on=today).select_related("project")):
        emit("projects.task_due", {"task_id": t.pk, "title": t.title, "project": t.project.title, "assignee_id": str(t.assignee_id),
                                   "due": t.due.isoformat(), "today": t.due == today}, tenant=tenant)
        t.reminded_on = today
        t.save(update_fields=["reminded_on"])
        n += 1
    return n


def budget_line(p: Project) -> dict:
    spent = int(PExpense.objects.filter(project=p).aggregate(s=Sum("amount"))["s"] or 0)
    return {"budget": p.budget, "spent": spent, "left": p.budget - spent, "percent": round(100 * spent / p.budget) if p.budget else None}
