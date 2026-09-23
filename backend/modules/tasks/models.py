"""
Vazifalar va muammolar moduli — restoranning "boshqaruv markazi".

Zanjir (xalqaro amaliyot: Andon + Kanban + CAPA):
    muammo (foto bilan) → vazifa → bajaruvchi → ish jarayoni → dalil (foto) → nazoratchi tasdig'i → arxiv

Asosiy g'oyalar:
  * ustunlar (TaskColumn) egasining o'zi tomonidan tahrirlanadi — "qora oyna" yo'q;
  * har vazifa kim aniqlagani (reporter), kim bajarishi (assignee), kim tasdiqlashi (supervisor) bilan yuradi;
  * `requires_proof` — dalilsiz "Tekshiruv"ga o'tkazib bo'lmaydi; `requires_approval` — tasdiqsiz "Bajarildi" bo'lmaydi;
  * har harakat TaskActivity'ga yoziladi (kim, qachon, nimadan nimaga) — bahslashishga o'rin qolmaydi;
  * takroriy ishlar (sanitariya, inventarizatsiya) TaskRecurrence'dan avtomatik tug'iladi.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Branch, SoftDelete, TimeStamped, User


def empty_i18n() -> dict:
    return {"uz": "", "ru": "", "en": ""}


class ColumnKind(models.TextChoices):
    BACKLOG = "backlog", "Yangi"          # endi tushgan, hali boshlanmagan
    ACTIVE = "active", "Jarayonda"        # ish ketyapti
    REVIEW = "review", "Tekshiruvda"      # dalil yuklandi, nazoratchi tekshirmoqda
    DONE = "done", "Bajarildi"            # tasdiqlangan
    CANCELLED = "cancelled", "Bekor qilindi"


class Priority(models.TextChoices):
    LOW = "low", "Past"
    NORMAL = "normal", "O'rta"
    HIGH = "high", "Muhim"
    URGENT = "urgent", "Shoshilinch"


PRIORITY_WEIGHT = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


class Source(models.TextChoices):
    MANUAL = "manual", "Qo'lda"
    ISSUE = "issue", "Muammo (xodim aniqladi)"
    RECURRING = "recurring", "Takroriy"
    CHECKLIST = "checklist", "Checklist"
    SYSTEM = "system", "Tizim"


class TaskColumn(TimeStamped):
    """Kanban ustuni. Egasi qo'shadi/nomlaydi/ko'chiradi; `kind` — tizim mantig'i uchun."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.JSONField(default=empty_i18n)
    kind = models.CharField(max_length=12, choices=ColumnKind.choices, default=ColumnKind.ACTIVE)
    color = models.CharField(max_length=9, default="#6B6A63")
    wip_limit = models.PositiveSmallIntegerField(default=0, help_text="0 = cheksiz; Kanban WIP chegarasi")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or self.code


class TaskDepartment(TimeStamped):
    """Bo'lim: Xo'jalik, Oshxona, IT, Marketing, HR, Ombor, Xavfsizlik, Sifat..."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.JSONField(default=empty_i18n)
    color = models.CharField(max_length=9, default="#0F6E63")
    head = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="headed_departments",
                             help_text="bo'lim boshlig'i — nazoratchi sifatida standart tanlanadi")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or self.code


class TaskCategory(TimeStamped):
    """Muammo turi: Mebel/Jihoz, Sanitariya, Ta'mirlash, Xavfsizlik... — qoidalari bilan."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.JSONField(default=empty_i18n)
    department = models.ForeignKey(TaskDepartment, null=True, blank=True, on_delete=models.SET_NULL, related_name="categories")
    icon = models.CharField(max_length=24, default="wrench")
    color = models.CharField(max_length=9, default="#B7791F")
    sla_hours = models.PositiveIntegerField(default=24, help_text="muddat: ochilgandan keyin necha soat")
    default_priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    requires_proof = models.BooleanField(default=True, help_text="tekshiruvga o'tishda foto-dalil majburiy")
    requires_approval = models.BooleanField(default=True, help_text="bajarildi deyish uchun nazoratchi tasdig'i")
    default_steps = models.JSONField(default=list, blank=True, help_text='["Usta topish", "Materiallar olish", ...]')
    default_assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="default_task_categories")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name_plural = "task categories"

    def __str__(self) -> str:
        return self.name.get("uz") or self.code


class TaskLabel(TimeStamped):
    """Erkin teg: Mebel, Zal, Mijozga ko'rinadi, Byudjet..."""

    name = models.CharField(max_length=40)
    color = models.CharField(max_length=9, default="#1F5FBF")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TaskQuerySet(models.QuerySet):
    def live(self):
        return self.filter(deleted_at__isnull=True)

    def open(self):
        return self.live().exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED])

    def overdue(self, now=None):
        now = now or timezone.now()
        return self.open().filter(due_at__lt=now)

    def for_user(self, user: User):
        """O'z vazifalari: bajaruvchi, nazoratchi, muallif yoki kuzatuvchi."""
        return self.live().filter(
            models.Q(assignee=user) | models.Q(supervisor=user) | models.Q(reporter=user) | models.Q(watchers=user)
        ).distinct()


class Task(TimeStamped, SoftDelete):
    number = models.PositiveIntegerField(unique=True, editable=False, help_text="#1238 — restoran ichida ketma-ket")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)

    column = models.ForeignKey(TaskColumn, on_delete=models.PROTECT, related_name="tasks")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    department = models.ForeignKey(TaskDepartment, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    category = models.ForeignKey(TaskCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    labels = models.ManyToManyField(TaskLabel, blank=True, related_name="tasks")
    location = models.CharField(max_length=120, blank=True, help_text="Zal, 3-stol / Oshxona / Ombor")

    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)

    reporter = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reported_tasks")
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tasks")
    supervisor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="supervised_tasks")
    watchers = models.ManyToManyField(User, blank=True, related_name="watched_tasks")

    start_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True, help_text="tekshiruvga topshirilgan vaqt")
    done_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_tasks")

    estimated_cost = models.BigIntegerField(default=0, help_text="taxminiy xarajat, so'm")
    actual_cost = models.BigIntegerField(default=0, help_text="haqiqiy xarajat, so'm")

    requires_proof = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=True)
    rework_count = models.PositiveSmallIntegerField(default=0, help_text="necha marta qaytarilgan")

    recurrence = models.ForeignKey("TaskRecurrence", null=True, blank=True, on_delete=models.SET_NULL, related_name="instances")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="subtasks")

    sort_order = models.PositiveIntegerField(default=0, help_text="ustun ichidagi tartib")
    is_archived = models.BooleanField(default=False, db_index=True)
    custom_data = models.JSONField(default=dict, blank=True, help_text="restoran o'zi qo'shgan maydonlar")

    objects = TaskQuerySet.as_manager()
    history = HistoricalRecords(excluded_fields=["sort_order"])

    class Meta:
        ordering = ["sort_order", "-created_at"]
        indexes = [
            models.Index(fields=["column", "sort_order"]),
            models.Index(fields=["branch", "priority"]),
        ]

    def __str__(self) -> str:
        return f"#{self.number} {self.title}"

    def save(self, *args, **kwargs):
        if not self.number:
            last = Task.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 1200) + 1   # #1201 dan boshlanadi — chek raqamiga o'xshamasin
        super().save(*args, **kwargs)

    # ---------------------------------------------------------------- holat
    @property
    def status(self) -> str:
        return self.column.kind

    @property
    def is_open(self) -> bool:
        return self.column.kind not in (ColumnKind.DONE, ColumnKind.CANCELLED)

    @property
    def is_overdue(self) -> bool:
        return bool(self.due_at and self.is_open and self.due_at < timezone.now())

    @property
    def progress(self) -> int:
        """Bosqichlar bo'yicha foiz; bosqich bo'lmasa — ustun turiga qarab."""
        steps = list(self.steps.all())
        if steps:
            return round(100 * sum(1 for s in steps if s.is_done) / len(steps))
        return {ColumnKind.BACKLOG: 0, ColumnKind.ACTIVE: 50, ColumnKind.REVIEW: 90,
                ColumnKind.DONE: 100, ColumnKind.CANCELLED: 0}.get(self.column.kind, 0)

    @property
    def has_proof(self) -> bool:
        return self.attachments.filter(kind=Attachment.PROOF).exists()


class TaskStep(TimeStamped):
    """Bajarilish bosqichi (checklist). Ba'zilari foto talab qilishi mumkin."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="steps")
    title = models.CharField(max_length=160)
    is_done = models.BooleanField(default=False)
    requires_photo = models.BooleanField(default=False)
    done_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    done_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.title


class Attachment(models.TextChoices):
    PHOTO = "photo", "Muammo rasmi"
    PROOF = "proof", "Bajarilgan ish dalili"
    DOC = "doc", "Hujjat"


class TaskAttachment(TimeStamped):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="tasks/%Y/%m/")
    kind = models.CharField(max_length=6, choices=Attachment.choices, default=Attachment.PHOTO)
    caption = models.CharField(max_length=160, blank=True)
    step = models.ForeignKey(TaskStep, null=True, blank=True, on_delete=models.SET_NULL, related_name="photos")
    uploaded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["id"]

    @property
    def is_image(self) -> bool:
        return self.file.name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"))


class TaskComment(TimeStamped):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    body = models.TextField()
    is_system = models.BooleanField(default=False, help_text="tizim izohi (rad etish sababi va h.k.)")

    class Meta:
        ordering = ["created_at", "id"]


class TaskActivity(models.Model):
    """O'zgarishlar tarixi — kim, qachon, nimadan nimaga."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=32)   # created | moved | assigned | step | proof | submitted | approved | rejected | commented | due | archived
    detail = models.CharField(max_length=240, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name_plural = "task activity"


class Freq(models.TextChoices):
    DAILY = "daily", "Har kuni"
    WEEKLY = "weekly", "Haftalik"
    MONTHLY = "monthly", "Oylik"


class TaskRecurrence(TimeStamped):
    """Takroriy ish shabloni: har kuni sanitariya, har dushanba inventarizatsiya, oyning 1-sanasida hisobot."""

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.ForeignKey(TaskCategory, null=True, blank=True, on_delete=models.SET_NULL)
    department = models.ForeignKey(TaskDepartment, null=True, blank=True, on_delete=models.SET_NULL)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE)
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="recurring_tasks")
    supervisor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="recurring_supervised")
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    steps = models.JSONField(default=list, blank=True)

    freq = models.CharField(max_length=8, choices=Freq.choices, default=Freq.DAILY)
    interval = models.PositiveSmallIntegerField(default=1, help_text="har N kun/hafta/oy")
    weekdays = models.JSONField(default=list, blank=True, help_text="[0..6] — 0 dushanba (weekly uchun)")
    day_of_month = models.PositiveSmallIntegerField(default=1)
    time_of_day = models.TimeField(default="09:00")
    due_in_hours = models.PositiveIntegerField(default=8)

    is_active = models.BooleanField(default=True)
    last_created_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title

    def is_due_today(self, today=None) -> bool:
        today = today or timezone.localdate()
        if not self.is_active or self.last_created_on == today:
            return False
        if self.freq == Freq.DAILY:
            return True
        if self.freq == Freq.WEEKLY:
            return today.weekday() in (self.weekdays or [0])
        return today.day == self.day_of_month
