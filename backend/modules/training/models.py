"""
O'qitish va komplayens moduli.

Kurs → darslar (video / matn / rasm / fayl) → testlar → sertifikat.
Topshiriq: admin video/rasm bilan vazifa beradi → xodim dalil yuklaydi → mas'ul tasdiqlaydi.
Standart (qoida): xodim o'qiydi va "Tanishdim" deb imzolaydi; yangi versiya chiqsa — qaytadan.

Kim ko'rishi (auditoriya): rollar (cook, waiter...) + lavozimlar (hr moduli) + aniq xodimlar.
Xodim o'z sahifasini ochganda unga mos kurslar avtomatik biriktiriladi (services.sync_user).
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import TimeStamped, User


class Audience(models.Model):
    """Auditoriya maydonlari — kurs, topshiriq va standartda bir xil."""

    roles = models.JSONField(default=list, blank=True, help_text="['cook', 'waiter'] — bo'sh bo'lsa hamma")
    positions = models.JSONField(default=list, blank=True, help_text="hr.Position id'lari")
    user_ids = models.JSONField(default=list, blank=True, help_text="aniq xodimlar (User.id satr)")
    everyone = models.BooleanField(default=False, help_text="barcha xodimlar")

    class Meta:
        abstract = True


# ------------------------------------------------------------------ kurslar
class Course(TimeStamped, Audience):
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=60, blank=True, help_text="Oshxona, Zal, Gigiyena…")
    cover = models.ImageField(upload_to="training/covers/", blank=True)
    cover_url = models.URLField(max_length=500, blank=True, help_text="yoki internetdagi rasm havolasi")
    is_mandatory = models.BooleanField(default=True)
    due_days = models.PositiveIntegerField(default=7, help_text="biriktirilgandan keyin necha kunda tugatish kerak (0 — muddatsiz)")
    pass_score = models.PositiveSmallIntegerField(default=80)
    responsible = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_courses")
    is_published = models.BooleanField(default=False)
    certificate = models.BooleanField(default=True, help_text="tugatganda sertifikat beriladi")
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "-created_at"]

    def __str__(self) -> str:
        return self.title


class Lesson(TimeStamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True, help_text="Tavsif / dars matni")
    checklist = models.JSONField(default=list, blank=True, help_text="Dars mazmuni bandlari: ['Kerakli mahsulotlar', ...]")
    video = models.FileField(upload_to="training/videos/", blank=True)
    video_url = models.URLField(blank=True, help_text="YouTube yoki boshqa havola")
    image = models.ImageField(upload_to="training/images/", blank=True)
    image_url = models.URLField(max_length=500, blank=True, help_text="yoki internetdagi rasm havolasi")
    duration_seconds = models.PositiveIntegerField(default=0, help_text="video davomiyligi (fayl/YouTube — brauzer aniqlaydi; Drive/Vimeo — admin yozadi)")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.title

    @property
    def has_video(self) -> bool:
        return bool(self.video) or bool(self.video_url)

    @property
    def video_mode(self) -> str:
        """exact — ko'rilgan soniyalar aniq o'lchanadi (fayl, .mp4 havola, YouTube);
        time — faqat sahifada o'tkazilgan vaqt o'lchanadi (Google Drive, Vimeo, boshqa havola)."""
        from .media import info
        if self.video or not self.video_url:
            return "exact"
        return "exact" if info(self.video_url)["kind"] in ("video", "youtube") else "time"


class LessonFile(TimeStamped):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="training/files/", blank=True)
    url = models.URLField(max_length=500, blank=True, help_text="fayl o'rniga internetdagi havola (Google Drive va h.k.)")
    title = models.CharField(max_length=160, blank=True)
    size_bytes = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["id"]

    @property
    def is_image(self) -> bool:
        name = self.file.name if self.file else self.url.split("?")[0]
        return name.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "webp", "gif"}


# ------------------------------------------------------------------ testlar
class Quiz(TimeStamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="quizzes")
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name="quizzes",
                               help_text="bo'sh — kurs yakuniy testi")
    title = models.CharField(max_length=160)
    time_limit_seconds = models.PositiveIntegerField(default=0, help_text="0 — cheklovsiz")
    pass_score = models.PositiveSmallIntegerField(default=0, help_text="0 — kurs bali ishlatiladi")
    max_attempts = models.PositiveSmallIntegerField(default=0, help_text="0 — cheksiz")
    shuffle = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.title

    @property
    def effective_pass_score(self) -> int:
        return self.pass_score or self.course.pass_score


class Question(TimeStamped):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    image = models.ImageField(upload_to="training/questions/", blank=True)
    options = models.JSONField(default=list, help_text='[{"id": "a", "text": "55°C"}, ...]')
    correct = models.JSONField(default=list, help_text='["c"] — bittadan ko\'p bo\'lsa ko\'p tanlovli')
    explanation = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


# ------------------------------------------------------------------ xodim natijalari
class EnrollmentStatus(models.TextChoices):
    ASSIGNED = "assigned", "Biriktirilgan"
    IN_PROGRESS = "in_progress", "O'qiyapti"
    COMPLETED = "completed", "Tugatgan"


class Enrollment(TimeStamped):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="training_enrollments")
    assigned_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ASSIGNED)
    progress = models.PositiveSmallIntegerField(default=0, help_text="0–100")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    certificate_no = models.CharField(max_length=24, blank=True)
    last_lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        unique_together = [("course", "user")]
        ordering = ["-assigned_at"]

    @property
    def is_overdue(self) -> bool:
        return self.status != EnrollmentStatus.COMPLETED and self.due_at is not None and self.due_at < timezone.now()


class LessonProgress(TimeStamped):
    """Har dars bo'yicha: ochgan vaqti, videoni necha soniya ko'rgani, qayerda to'xtagani, tugatgani."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    watched_seconds = models.FloatField(default=0, help_text="haqiqatda ko'rilgan soniyalar (o'tkazib yuborilganlar hisobga kirmaydi)")
    max_position = models.FloatField(default=0, help_text="videoda yetib borgan eng uzoq nuqta")
    last_position = models.FloatField(default=0)
    duration = models.FloatField(default=0)
    percent = models.PositiveSmallIntegerField(default=0)
    views = models.PositiveIntegerField(default=0)
    first_opened_at = models.DateTimeField(default=timezone.now)
    last_beat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("user", "lesson")]


class QuizAttempt(TimeStamped):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quiz_attempts")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    question_ids = models.JSONField(default=list)
    answers = models.JSONField(default=dict, help_text='{"<qid>": ["c"]}')
    correct_count = models.PositiveSmallIntegerField(default=0)
    total = models.PositiveSmallIntegerField(default=0)
    score = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at"]


# ------------------------------------------------------------------ topshiriqlar
class Assignment(TimeStamped, Audience):
    """Amaliy topshiriq: 'Burger kotletini standart bo'yicha tayyorlab, rasmini yuboring'."""

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    media = models.FileField(upload_to="training/assignments/", blank=True, help_text="namuna video yoki rasm")
    media_url = models.URLField(max_length=500, blank=True, help_text="yoki internetdagi video/rasm havolasi")
    course = models.ForeignKey(Course, null=True, blank=True, on_delete=models.SET_NULL, related_name="assignments")
    due_at = models.DateTimeField(null=True, blank=True)
    requires_proof = models.BooleanField(default=True)
    responsible = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_assignments",
                                    help_text="tekshiradigan mas'ul")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]


class SubmissionStatus(models.TextChoices):
    TODO = "todo", "Bajarilmagan"
    SUBMITTED = "submitted", "Tekshiruvda"
    APPROVED = "approved", "Qabul qilindi"
    REJECTED = "rejected", "Qaytarildi"


class Submission(TimeStamped):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="training_submissions")
    status = models.CharField(max_length=10, choices=SubmissionStatus.choices, default=SubmissionStatus.TODO)
    text = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [("assignment", "user")]
        ordering = ["-updated_at"]


class SubmissionFile(TimeStamped):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="training/proofs/%Y/%m/")

    class Meta:
        ordering = ["id"]


# ------------------------------------------------------------------ standartlar (komplayens)
class Standard(TimeStamped, Audience):
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=60, blank=True)
    body = models.TextField(blank=True)
    file = models.FileField(upload_to="training/standards/", blank=True, help_text="rasm, video yoki PDF")
    file_url = models.URLField(max_length=500, blank=True, help_text="yoki internetdagi havola")
    version = models.PositiveIntegerField(default=1)
    responsible = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_standards")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "title"]


class StandardAck(models.Model):
    standard = models.ForeignKey(Standard, on_delete=models.CASCADE, related_name="acks")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="standard_acks")
    version = models.PositiveIntegerField()
    acked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("standard", "user", "version")]


class Reminder(models.Model):
    """Kunlik eslatma jurnali — bir kishiga kuniga bitta eslatma (spam bo'lmasin)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="training_reminders")
    day = models.DateField()
    kind = models.CharField(max_length=10, default="user", help_text="user — xodimga, digest — mas'ulga")
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("user", "day", "kind")]
        ordering = ["-created_at"]
