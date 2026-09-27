"""
Loyihalar (Project Management) — kunlik operatsiyadan tashqaridagi katta ishlar: yangi filial, yangi menyu, ta'mir,
marketing kampaniyasi, xodimlarni o'qitish, IT joriy etish.

  Project    — loyiha: toifa, holat, muhimlik, filial, mas'ul, boshlanish/tugash, byudjet.
  Member     — ishtirokchilar (rahbar / a'zo / kuzatuvchi).
  Milestone  — bosqichlar (masalan: «Joy va ijara» → «Ta'mir» → «Ruxsatnomalar» → «Ochilish»).
  PTask      — loyiha vazifasi: mas'ul, muddat, holat (Qilinadi → Jarayonda → Tekshiruvda → Bajarildi), mini-checklist.
  PFile      — hujjat/rasm yoki havola (shartnoma, smeta, dizayn).
  PExpense   — loyiha xarajati → byudjet nazorati.
  Activity   — tarix va izohlar (kim nima qildi) → bildirishnomalar.
"""
from __future__ import annotations

from django.db import models

from core.models import Branch, TimeStamped, User


class Category(models.TextChoices):
    BRANCH = "branch", "Filial ochish"
    MENU = "menu", "Menyu va taom"
    RENOVATION = "renovation", "Ta'mir va jihoz"
    MARKETING = "marketing", "Marketing"
    HR = "hr", "HR va o'qitish"
    IT = "it", "IT va tizim"
    OTHER = "other", "Boshqa"


CAT_META = {  # emoji, rang
    "branch": ("🏪", "#2563EB"), "menu": ("🍽️", "#EA580C"), "renovation": ("🛠️", "#7C3AED"), "marketing": ("📣", "#DB2777"),
    "hr": ("👥", "#059669"), "it": ("💻", "#0891B2"), "other": ("📌", "#64748B"),
}


class Status(models.TextChoices):
    PLAN = "plan", "Rejada"
    ACTIVE = "active", "Jarayonda"
    PAUSED = "paused", "To'xtatilgan"
    DONE = "done", "Yakunlangan"
    CANCELLED = "cancelled", "Bekor qilingan"


class Priority(models.TextChoices):
    LOW = "low", "Past"
    NORMAL = "normal", "O'rta"
    HIGH = "high", "Yuqori"
    CRITICAL = "critical", "Juda muhim"


class Project(TimeStamped):
    number = models.PositiveIntegerField(unique=True, editable=False)
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLAN, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_projects")
    start = models.DateField(null=True, blank=True)
    due = models.DateField(null=True, blank=True)
    budget = models.BigIntegerField(default=0)
    template_key = models.CharField(max_length=30, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-number"]

    def save(self, *args, **kwargs):
        if not self.number:
            last = Project.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 0) + 1
        super().save(*args, **kwargs)

    @property
    def code(self) -> str:
        return f"P-{self.number:03d}"

    def __str__(self):
        return f"{self.code} {self.title}"


class MemberRole(models.TextChoices):
    LEAD = "lead", "Rahbar"
    MEMBER = "member", "A'zo"
    WATCHER = "watcher", "Kuzatuvchi"


class Member(TimeStamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="project_memberships")
    role = models.CharField(max_length=8, choices=MemberRole.choices, default=MemberRole.MEMBER)

    class Meta:
        unique_together = [("project", "user")]


class Milestone(TimeStamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=160)
    due = models.DateField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]


class TaskStatus(models.TextChoices):
    TODO = "todo", "Qilinadi"
    DOING = "doing", "Jarayonda"
    REVIEW = "review", "Tekshiruvda"
    DONE = "done", "Bajarildi"


class PTask(TimeStamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    milestone = models.ForeignKey(Milestone, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="project_tasks")
    status = models.CharField(max_length=8, choices=TaskStatus.choices, default=TaskStatus.TODO, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    due = models.DateField(null=True, blank=True)
    checklist = models.JSONField(default=list, blank=True)       # [{"text": "...", "done": false}]
    sort_order = models.PositiveIntegerField(default=0)
    done_at = models.DateTimeField(null=True, blank=True)
    reminded_on = models.DateField(null=True, blank=True)        # muddat eslatmasi yuborilgan kun
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["sort_order", "id"]


class PFile(TimeStamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="files")
    task = models.ForeignKey(PTask, null=True, blank=True, on_delete=models.SET_NULL, related_name="files")
    file = models.FileField(upload_to="projects/%Y/%m/", blank=True)
    url = models.URLField(max_length=500, blank=True)
    title = models.CharField(max_length=200)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-id"]


class PExpense(TimeStamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField()
    amount = models.BigIntegerField()
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-date", "-id"]


class Activity(TimeStamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="activity")
    task = models.ForeignKey(PTask, null=True, blank=True, on_delete=models.SET_NULL, related_name="activity")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=12, default="info")      # created, status, task, done, comment, file, expense, member, milestone
    text = models.TextField()

    class Meta:
        ordering = ["-id"]
