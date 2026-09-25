"""
Xodimlar (HR) moduli: lavozim, xodim kartasi (maosh sharti), smena jadvali, davomat, oylik hisob-kitobi.

Maosh turlari: monthly (oylik stavka) · hourly (soatbay) · shift (smenabay) · percent (savdodan %).
Oylik = baza (turga qarab) + bonus − jarima − avans. Natija moliya modulida "Labor cost" sifatida P&L'ga tushadi.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Branch, TimeStamped, User


class SalaryType(models.TextChoices):
    MONTHLY = "monthly", "Oylik stavka"
    HOURLY = "hourly", "Soatbay"
    SHIFT = "shift", "Smenabay"
    PERCENT = "percent", "Savdodan %"


class Position(TimeStamped):
    name = models.CharField(max_length=80)
    department = models.CharField(max_length=60, blank=True, help_text="Oshxona, Zal, Kassa, Boshqaruv…")
    default_salary_type = models.CharField(max_length=8, choices=SalaryType.choices, default=SalaryType.MONTHLY)
    default_rate = models.BigIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Employee(TimeStamped):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employee")
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    hire_date = models.DateField(default=timezone.localdate)
    fire_date = models.DateField(null=True, blank=True)
    salary_type = models.CharField(max_length=8, choices=SalaryType.choices, default=SalaryType.MONTHLY)
    rate = models.BigIntegerField(default=0, help_text="so'm: oylik / soat / smena; percent uchun — foiz×100 (2.5% = 250)")
    pinfl = models.CharField(max_length=14, blank=True)
    passport = models.CharField(max_length=12, blank=True)
    card_number = models.CharField(max_length=20, blank=True, help_text="oylik tushadigan karta")
    emergency_phone = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    # --- shaxsiy profil (HR kartasi)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, blank=True, help_text="m | f")
    address = models.CharField(max_length=255, blank=True)
    emergency_name = models.CharField(max_length=120, blank=True, help_text="favqulodda aloqa: kim (ona, turmush o'rtog'i…)")
    education = models.CharField(max_length=255, blank=True, help_text="masalan: Toshkent oshpazlik kolleji, 2019")
    languages = models.JSONField(default=list, blank=True, help_text='["o\'zbek", "rus"]')
    skills = models.JSONField(default=list, blank=True, help_text='["tandir", "kassa", "Excel"]')
    about = models.TextField(blank=True)
    medical_book_until = models.DateField(null=True, blank=True, help_text="tibbiy daftarcha amal qilish muddati")
    source = models.CharField(max_length=20, blank=True, help_text="qayerdan kelgan: vakansiya, tavsiya…")
    fire_reason = models.CharField(max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["user__full_name"]

    def __str__(self) -> str:
        return self.user.full_name or self.user.phone


class ShiftPlan(TimeStamped):
    """Smena jadvali (rejalashtirilgan)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="shifts")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateField(db_index=True)
    start = models.TimeField(default="09:00")
    end = models.TimeField(default="18:00")
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["date", "start"]
        unique_together = [("employee", "date", "start")]

    @property
    def hours(self) -> float:
        s = datetime.combine(self.date, self.start)
        e = datetime.combine(self.date, self.end)
        if e <= s:
            e += timedelta(days=1)
        return round((e - s).total_seconds() / 3600, 2)


class Attendance(TimeStamped):
    """Davomat: keldi / ketdi. Manba: panel, kassa PIN, Telegram, QR (keyin)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    check_in = models.DateTimeField(default=timezone.now, db_index=True)
    check_out = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=12, default="panel")
    late_minutes = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-check_in"]

    @property
    def hours(self) -> float:
        end = self.check_out or timezone.now()
        return round((end - self.check_in).total_seconds() / 3600, 2)

    @property
    def is_open(self) -> bool:
        return self.check_out is None


class PayrollStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    APPROVED = "approved", "Tasdiqlangan"
    PAID = "paid", "To'langan"


class Payslip(TimeStamped):
    """Bir xodimning bir oylik hisob-kitobi."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payslips")
    period = models.DateField(help_text="oyning 1-sanasi", db_index=True)
    salary_type = models.CharField(max_length=8, choices=SalaryType.choices)
    rate = models.BigIntegerField(default=0)
    hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    shifts = models.PositiveIntegerField(default=0)
    sales_base = models.BigIntegerField(default=0, help_text="percent turi uchun savdo bazasi")
    base = models.BigIntegerField(default=0)
    bonus = models.BigIntegerField(default=0)
    penalty = models.BigIntegerField(default=0)
    advance = models.BigIntegerField(default=0)
    total = models.BigIntegerField(default=0)
    status = models.CharField(max_length=8, choices=PayrollStatus.choices, default=PayrollStatus.DRAFT)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-period", "employee__user__full_name"]
        unique_together = [("employee", "period")]

    def compute(self) -> None:
        r = Decimal(self.rate)
        if self.salary_type == SalaryType.MONTHLY:
            self.base = int(r)
        elif self.salary_type == SalaryType.HOURLY:
            self.base = int(r * Decimal(self.hours))
        elif self.salary_type == SalaryType.SHIFT:
            self.base = int(r * self.shifts)
        else:  # percent: rate = foiz × 100
            self.base = int(Decimal(self.sales_base) * r / 10000)
        self.total = self.base + self.bonus - self.penalty - self.advance


def month_start(d: date) -> date:
    return d.replace(day=1)



# ================================================================== XODIM PROFILI
class WorkHistory(TimeStamped):
    """Oldingi ish joylari (qabul qilishda nomzod anketasidan ko'chadi)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="work_history")
    company = models.CharField(max_length=160)
    position = models.CharField(max_length=120, blank=True)
    start = models.CharField(max_length=20, blank=True, help_text="2019-03 yoki 2019")
    end = models.CharField(max_length=20, blank=True, help_text="bo'sh — hozirgacha")
    reason_left = models.CharField(max_length=200, blank=True)
    reference_phone = models.CharField(max_length=20, blank=True, help_text="tavsiya beruvchi telefon")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-start", "-id"]


class DocKind(models.TextChoices):
    CONTRACT = "contract", "Mehnat shartnomasi"
    MEDBOOK = "medbook", "Tibbiy daftarcha"
    PASSPORT = "passport", "Pasport nusxasi"
    DIPLOMA = "diploma", "Diplom / sertifikat"
    OTHER = "other", "Boshqa"


class EmployeeDocument(TimeStamped):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=10, choices=DocKind.choices, default=DocKind.OTHER)
    title = models.CharField(max_length=160)
    file = models.FileField(upload_to="hr/docs/%Y/", blank=True)
    url = models.URLField(max_length=500, blank=True, help_text="fayl o'rniga havola (Google Drive va h.k.)")
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["kind", "-created_at"]


# ================================================================== BAHOLASH
REVIEW_CRITERIA = [
    ("discipline", "Intizom va o'z vaqtida kelish"),
    ("quality", "Ish sifati va standartlarga rioya"),
    ("speed", "Tezlik"),
    ("service", "Mehmon bilan muomala"),
    ("hygiene", "Gigiyena va tozalik"),
    ("teamwork", "Jamoada ishlash"),
]


class Review(TimeStamped):
    """Menejer bahosi (odatda oyiga bir marta): mezonlar 1–5, izoh, keyingi oy maqsadi."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    period = models.DateField(help_text="oyning 1-sanasi", db_index=True)
    scores = models.JSONField(default=dict, help_text='{"discipline": 4, ...}')
    strengths = models.CharField(max_length=300, blank=True)
    improve = models.CharField(max_length=300, blank=True)
    goals = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-period", "-created_at"]

    @property
    def average(self) -> float | None:
        vals = [int(v) for v in (self.scores or {}).values() if v]
        return round(sum(vals) / len(vals), 2) if vals else None


class ShiftFeedback(models.Model):
    """Smenadan keyin xodim bahosi (Telegram: 😀 🙂 😐 🙁) — kayfiyat va ketib qolish xavfini erta ko'rish uchun."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="feedback")
    attendance = models.OneToOneField(Attendance, null=True, blank=True, on_delete=models.SET_NULL, related_name="feedback")
    date = models.DateField(default=timezone.localdate, db_index=True)
    mood = models.PositiveSmallIntegerField(help_text="1 — yomon … 4 — a'lo")
    comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date", "-id"]


# ================================================================== ISHGA OLISH
class VacancyStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    OPEN = "open", "Ochiq"
    PAUSED = "paused", "To'xtatilgan"
    CLOSED = "closed", "Yopilgan"


class Vacancy(TimeStamped):
    title = models.CharField(max_length=140)
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.SET_NULL, related_name="vacancies")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="vacancies")
    role_code = models.CharField(max_length=40, default="waiter", help_text="qabul qilinganda beriladigan rol")
    employment = models.CharField(max_length=20, default="full", help_text="full | part | shift | intern")
    salary_from = models.BigIntegerField(default=0)
    salary_to = models.BigIntegerField(default=0)
    salary_note = models.CharField(max_length=120, blank=True, help_text="masalan: + choychaqa, bonus")
    schedule = models.CharField(max_length=120, blank=True, help_text="2/2, 10:00–22:00")
    summary = models.CharField(max_length=300, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    duties = models.JSONField(default=list, blank=True)
    benefits = models.JSONField(default=list, blank=True)
    image = models.ImageField(upload_to="hr/vacancies/", blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    video_url = models.URLField(max_length=500, blank=True, help_text="YouTube / Instagram / Drive")
    link_url = models.URLField(max_length=500, blank=True, help_text="qo'shimcha havola (masalan, jamoa haqida)")
    questions = models.JSONField(default=list, blank=True,
                                 help_text='[{"text": "Kechki smenada ishlay olasizmi?", "type": "yesno", "must": "ha"}]')
    status = models.CharField(max_length=8, choices=VacancyStatus.choices, default=VacancyStatus.DRAFT, db_index=True)
    responsible = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    closes_on = models.DateField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def image_src(self) -> str | None:
        return self.image.url if self.image else (self.image_url or None)


class Stage(models.TextChoices):
    NEW = "new", "Yangi ariza"
    SCREEN = "screen", "Ko'rib chiqilmoqda"
    INTERVIEW = "interview", "Suhbat"
    TRIAL = "trial", "Sinov kuni"
    OFFER = "offer", "Taklif"
    HIRED = "hired", "Qabul qilindi"
    REJECTED = "rejected", "Rad etildi"


class Application(TimeStamped):
    vacancy = models.ForeignKey(Vacancy, null=True, blank=True, on_delete=models.SET_NULL, related_name="applications")
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, db_index=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    city = models.CharField(max_length=80, blank=True)
    experience = models.TextField(blank=True, help_text="o'zi haqida / tajriba (erkin matn)")
    work_history = models.JSONField(default=list, blank=True, help_text='[{"company": "", "position": "", "years": ""}]')
    answers = models.JSONField(default=list, blank=True, help_text='[{"q": "...", "a": "...", "ok": true}]')
    photo = models.ImageField(upload_to="hr/candidates/", blank=True)
    resume = models.FileField(upload_to="hr/resumes/", blank=True)
    source = models.CharField(max_length=12, default="site", help_text="site | telegram | manual | referral")
    tg_chat_id = models.BigIntegerField(null=True, blank=True)
    tg_username = models.CharField(max_length=64, blank=True)
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.NEW, db_index=True)
    knocked_out = models.BooleanField(default=False, help_text="majburiy savolga mos javob bermagan")
    rating = models.PositiveSmallIntegerField(default=0, help_text="0–5 yulduz")
    notes = models.TextField(blank=True)
    interview_at = models.DateTimeField(null=True, blank=True)
    interview_place = models.CharField(max_length=160, blank=True)
    reject_reason = models.CharField(max_length=200, blank=True)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    stage_changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class ApplicationEvent(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=16, default="note", help_text="created | stage | note | message | interview")
    text = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
