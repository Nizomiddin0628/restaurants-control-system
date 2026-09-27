"""Demo loyihalar: filial ochish (o'rtasida), yangi menyu, kechikkan ta'mir, rejadagi aksiya, yakunlangan o'qitish."""
from __future__ import annotations

import random
from datetime import timedelta

from django.utils import timezone

from . import services as S
from .models import Activity, Member, PExpense, PFile, Project, PTask, Status, TaskStatus

PLAN = [  # shablon, nomi, boshlanish (bugundan kun), davomiylik, byudjet, bajarilganlik chegarasi
    ("branch_open", "Chilonzor filialini ochish", -40, 75, 450_000_000, "branch"),
    ("new_menu", "Kuzgi menyu: 5 ta yangi taom", -12, 30, 8_000_000, "menu"),
    ("renovation", "Oshxona ventilyatsiyasini almashtirish", -25, 21, 35_000_000, "late"),
    ("marketing", "Kuzgi aksiya: «2+1 somsa»", 3, 30, 12_000_000, "plan"),
    ("training", "Yangi kassirlarni o'qitish", -45, 21, 2_000_000, "done"),
]
COMMENTS = {
    "branch_open": ["Ijara shartnomasini yurist ko'rdi — 2 ta tuzatish bor", "Ta'mir rasmlarini guruhga tashladim, devorlar tayyor"],
    "new_menu": ["Degustatsiyada tandir somsa eng yaxshi baho oldi", "Qovoq shorva tannarxi 28% chiqdi — narx to'g'ri"],
    "renovation": ["Pudratchi ertaga 9:00 da keladi", "Motor kechikdi, yetkazib beruvchi juma deyapti"],
    "marketing": ["Bloger bilan 2 ta stories kelishildi", "Afisha dizayni tayyor, ko'rib chiqing"],
    "training": ["Hamma test topshirdi, o'rtacha 87 ball", "Kassa bo'yicha amaliy mashg'ulot yaxshi o'tdi"],
}


def seed_demo_projects(tenant=None) -> dict:
    from core.models import User
    if Project.objects.exists():
        return {"skipped": True}
    rnd = random.Random(16)
    today = timezone.localdate()
    staff = list(User.objects.filter(is_active=True, memberships__is_active=True).exclude(phone__startswith="+998000").distinct()[:12])
    owner = next((u for u in staff if u.memberships.filter(role__code="owner").exists()), staff[0] if staff else None)
    made = 0
    for key, title, start_off, days, budget, mode in PLAN:
        start = today + timedelta(days=start_off)
        p = S.create_project(title=title, category="", template_key=key, actor=owner, start=start, due=start + timedelta(days=days),
                             owner=rnd.choice(staff) if staff and mode != "branch" else owner, budget=budget, tenant=None,
                             members=rnd.sample(staff, min(3, len(staff))))
        tasks = list(p.tasks.order_by("due", "sort_order"))
        past = [t for t in tasks if t.due and t.due < today]
        keep_open = set(t.pk for t in (past[-2:] if mode == "late" else past[-1:] if mode in ("branch", "menu") else []))
        for i, t in enumerate(tasks):
            if staff:
                t.assignee = staff[(i + made) % len(staff)]
            if mode == "done" or (mode != "plan" and t in past and t.pk not in keep_open):
                t.status, t.done_at = TaskStatus.DONE, timezone.now() - timedelta(days=max(0, (today - t.due).days))
                t.checklist = [{**c, "done": True} for c in t.checklist]
            elif mode != "plan" and t.due and (t.pk in keep_open or t.due <= today + timedelta(days=6)):
                t.status = rnd.choice([TaskStatus.DOING, TaskStatus.DOING, TaskStatus.REVIEW])
                if t.checklist:
                    t.checklist[0]["done"] = True
            t.save()
            if t.assignee_id:
                Member.objects.get_or_create(project=p, user_id=t.assignee_id, defaults={"role": "member"})
        for m in p.milestones.all():
            S.sync_milestone(m)
        if mode == "plan":
            p.status = Status.PLAN
        elif mode == "done":
            p.status, p.done_at = Status.DONE, timezone.now() - timedelta(days=20)
        p.save()
        if budget and mode != "plan":
            share = {"branch": 0.55, "late": 1.08, "done": 0.9}.get(mode, 0.4)
            for k, (note, part) in enumerate([("Avans pudratchiga", 0.5), ("Materiallar", 0.3), ("Jihoz va boshqa", 0.2)]):
                PExpense.objects.create(project=p, amount=int(budget * share * part) // 1000 * 1000, note=note,
                                        date=start + timedelta(days=5 + 7 * k), created_by=owner)
        PFile.objects.create(project=p, title="Smeta va reja (Google Sheets)", url="https://docs.google.com/spreadsheets/", uploaded_by=owner)
        for c in COMMENTS.get(key, []):
            a = Activity.objects.create(project=p, actor=rnd.choice(staff) if staff else None, kind="comment", text=c,
                                        task=rnd.choice(tasks) if tasks else None)
            Activity.objects.filter(pk=a.pk).update(created_at=timezone.now() - timedelta(hours=rnd.randint(2, 90)))
        # tarixni real vaqtga yoyamiz (hammasi «hozir» bo'lib qolmasin)
        born = timezone.make_aware(timezone.datetime.combine(start, timezone.datetime.min.time()) + timedelta(hours=10))
        Activity.objects.filter(project=p, kind="created").update(created_at=born)
        for a in Activity.objects.filter(project=p).exclude(kind__in=["created", "comment"]):
            when = a.task.done_at if a.task_id and a.task and a.task.done_at else born + timedelta(days=rnd.randint(1, max(1, (today - start).days)))
            Activity.objects.filter(pk=a.pk).update(created_at=min(when, timezone.now() - timedelta(hours=rnd.randint(1, 30))))
        made += 1
    return {"projects": made, "tasks": PTask.objects.count()}
