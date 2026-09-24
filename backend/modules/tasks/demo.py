"""Demo ma'lumot: xodimlar, vazifalar va muammolar (panel bo'sh ko'rinmasin)."""
from __future__ import annotations

import random
from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone

from core.models import Branch, Membership, Role, User

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
)
from .services import ensure_setup, log

STAFF = [
    ("+998901110001", "Rustam Karimov", "manager"),
    ("+998901110002", "Malika Yusupova", "manager"),
    ("+998901110003", "Dilshod Ergashev", "cook"),
    ("+998901110004", "Jasur Toshmatov", "cashier"),
    ("+998901110005", "Nodira Ahmedova", "cashier"),
    ("+998901110006", "Kamron Saidov", "manager"),
    ("+998901110007", "Aziza Rahimova", "accountant"),
    ("+998901110008", "Gulnoza Nazarova", "marketer"),
    ("+998901110009", "Sardor Aliyev", "marketer"),
    ("+998901110010", "Umar Bekzodov", "manager"),
]


def _placeholder(text: str, color: tuple[int, int, int]) -> ContentFile:
    """Demo foto — tashqi tarmoqsiz, Pillow bilan chiziladi."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 420), color)
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, 616, 396], outline=(255, 255, 255), width=3)
    d.text((40, 190), text, fill=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return ContentFile(buf.getvalue(), name=f"{abs(hash(text)) % 10**8}.jpg")


def seed_demo_tasks() -> int:
    ensure_setup()
    if Task.objects.exists():
        return 0

    roles = {r.code: r for r in Role.objects.all()}
    users: dict[str, User] = {}
    for phone, name, role_code in STAFF:
        u, created = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        if created and roles.get(role_code):
            Membership.objects.create(user=u, role=roles[role_code])
        users[name.split()[0]] = u

    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    cats = {c.code: c for c in TaskCategory.objects.all()}
    deps = {d.code: d for d in TaskDepartment.objects.all()}
    cols = {c.code: c for c in TaskColumn.objects.all()}
    labels = {n: TaskLabel.objects.get_or_create(name=n, defaults={"color": c})[0]
              for n, c in [("Mebel", "#8A5A12"), ("Zal", "#0F6E63"), ("Oshxona", "#D9482B"),
                           ("Mijozga ko'rinadi", "#C2321F"), ("Byudjet", "#1F5FBF")]}
    now = timezone.now()

    # (sarlavha, ustun, tur, bajaruvchi, nazoratchi, ustuvorlik, muddat kuni, bajarilgan bosqich, teglar)
    rows = [
        ("Oshxona ventilyatsiyasini tozalash", "new", "sanitary", "Dilshod", "Umar", Priority.HIGH, 1, 0, ["Oshxona"]),
        ("Menyu narxlarini yangilash", "new", "marketing", "Malika", "Umar", Priority.NORMAL, 2, 0, []),
        ("Yangi xodimlar uchun forma buyurtma", "new", "staff", "Gulnoza", "Umar", Priority.LOW, 3, 0, ["Byudjet"]),
        ("Kamera tizimini tekshirish", "new", "safety", "Jasur", "Umar", Priority.HIGH, 1, 0, []),
        ("Zal chiroqlarini almashtirish", "new", "furniture", "Rustam", "Umar", Priority.LOW, 4, 0, ["Zal"]),
        ("Divanni remont qilish", "in_progress", "furniture", "Rustam", "Umar", Priority.HIGH, 1, 3, ["Mebel", "Zal"]),
        ("Sanitariya tekshiruviga tayyorgarlik", "in_progress", "sanitary", "Malika", "Umar", Priority.NORMAL, 1, 2, ["Mijozga ko'rinadi"]),
        ("Yangi menyu foto/video kontent", "in_progress", "marketing", "Sardor", "Gulnoza", Priority.NORMAL, 2, 1, []),
        ("Sovutgich servisi", "in_progress", "equipment", "Dilshod", "Umar", Priority.URGENT, 0, 2, ["Oshxona"]),
        ("Kassa dasturini yangilash", "in_progress", "it", "Kamron", "Umar", Priority.NORMAL, 2, 1, []),
        ("Ofitsiantlar uchun servis treningi", "in_progress", "staff", "Gulnoza", "Malika", Priority.NORMAL, 5, 1, []),
        ("Stol va stullarni tozalash", "review", "sanitary", "Nodira", "Malika", Priority.NORMAL, 0, 3, ["Zal"]),
        ("Wi-Fi tarmog'ini yangilash", "review", "it", "Jasur", "Kamron", Priority.LOW, 0, 3, []),
        ("Reklama stendini o'rnatish", "review", "marketing", "Dilshod", "Gulnoza", Priority.NORMAL, 0, 3, ["Mijozga ko'rinadi"]),
        ("Muzlatgich haroratini o'lchash", "review", "equipment", "Dilshod", "Umar", Priority.HIGH, 0, 4, ["Oshxona"]),
        ("Kassa dasturini sozlash", "done", "it", "Kamron", "Umar", Priority.LOW, -1, 3, []),
        ("Ombor inventarizatsiya", "done", "supply", "Aziza", "Umar", Priority.NORMAL, -1, 3, []),
        ("Xodimlar tibbiy ko'rik", "done", "staff", "Malika", "Umar", Priority.LOW, -2, 3, []),
        ("Yong'inga qarshi vositalarni tekshirish", "done", "safety", "Jasur", "Umar", Priority.NORMAL, -2, 3, []),
        ("Zal derazalarini yuvish", "done", "sanitary", "Nodira", "Malika", Priority.LOW, -3, 3, ["Zal"]),
        ("Yetkazib beruvchi bilan shartnoma", "done", "supply", "Aziza", "Umar", Priority.NORMAL, -4, 3, ["Byudjet"]),
    ]

    created = 0
    for title, col, cat, asg, sup, prio, due_days, steps_done, lbls in rows:
        c = cats.get(cat)
        column = cols[col]
        t = Task.objects.create(
            title=title, description="", column=column, branch=branch, category=c,
            department=c.department if c else deps.get("economy"), priority=prio,
            source=Source.ISSUE if col == "new" and cat in ("furniture", "equipment", "sanitary") else Source.MANUAL,
            reporter=users.get("Umar"), assignee=users.get(asg), supervisor=users.get(sup),
            location="Zal" if "Zal" in lbls else "", due_at=now + timedelta(days=due_days),
            estimated_cost=random.choice([0, 150_000, 450_000, 900_000]),
            requires_proof=c.requires_proof if c else True,
            requires_approval=c.requires_approval if c else True,
            sort_order=created,
            start_at=now - timedelta(days=1) if col != "new" else None,
            submitted_at=now - timedelta(hours=3) if col == "review" else None,
            done_at=now + timedelta(days=due_days) if col == "done" else None,
            approved_at=now + timedelta(days=due_days) if col == "done" else None,
            approved_by=users.get(sup) if col == "done" else None,
        )
        t.labels.set([labels[n] for n in lbls])
        for i, s in enumerate(list((c.default_steps if c else []) or ["Bajarish"])):
            t.steps.create(title=s, sort_order=i, is_done=i < steps_done,
                           done_by=users.get(asg) if i < steps_done else None,
                           done_at=now - timedelta(hours=6 - i) if i < steps_done else None)
        if col == "done":   # tarix real ko'rinsin: ochilgan sana bajarilgandan oldin
            Task.objects.filter(pk=t.pk).update(created_at=now - timedelta(days=abs(due_days) + 2))
        log(t, users.get("Umar"), "created", "Vazifa ochildi")
        created += 1

    # "Divanni remont qilish" — to'liq zanjir namunasi: muammo rasmlari + izohlar
    demo = Task.objects.filter(title="Divanni remont qilish").first()
    if demo:
        demo.description = ("Zaldagi katta divan o'ng tomoni singan, remont qilish kerak. "
                            "Mijozlar uchun noqulay, tezda hal qilish.")
        demo.estimated_cost = 450_000
        demo.save()
        for txt, color in [("Divan — umumiy ko'rinish", (122, 92, 70)),
                           ("Singan joyi (yaqindan)", (96, 74, 58)),
                           ("O'lchov", (140, 110, 86))]:
            TaskAttachment.objects.create(task=demo, kind=Attachment.PHOTO, caption=txt,
                                          uploaded_by=demo.reporter, file=_placeholder(txt, color))
        TaskComment.objects.create(task=demo, author=demo.supervisor, body="Usta topildi. Ertaga ertalab boshlaydi.")
        TaskComment.objects.create(task=demo, author=demo.assignee, body="Materiallar olindi. Remont ishlari boshlandi.")
        log(demo, demo.assignee, "photo", "3 ta rasm yuklandi")

    # tekshiruvdagi ishlarga dalil-foto (aks holda tasdiqlab bo'lmaydi)
    for t in Task.objects.filter(column__kind__in=[ColumnKind.REVIEW, ColumnKind.DONE]):
        TaskAttachment.objects.create(task=t, kind=Attachment.PROOF, caption="Bajarilgan ish",
                                      uploaded_by=t.assignee, file=_placeholder("Bajarildi", (30, 127, 79)))

    # takroriy ishlar
    TaskRecurrence.objects.get_or_create(
        title="Kunlik sanitariya checklisti",
        defaults={"category": cats.get("sanitary"), "department": deps.get("service"), "branch": branch,
                  "assignee": users.get("Nodira"), "supervisor": users.get("Malika"), "priority": Priority.HIGH,
                  "steps": ["Zalni tozalash", "Sanuzel", "Oshxona yuzalari", "Foto-hisobot"],
                  "freq": "daily", "due_in_hours": 6})
    TaskRecurrence.objects.get_or_create(
        title="Haftalik ombor inventarizatsiyasi",
        defaults={"category": cats.get("supply"), "department": deps.get("warehouse"), "branch": branch,
                  "assignee": users.get("Aziza"), "supervisor": users.get("Umar"), "priority": Priority.NORMAL,
                  "steps": ["Sanash", "Solishtirish", "Akt"], "freq": "weekly", "weekdays": [0], "due_in_hours": 10})
    return created
