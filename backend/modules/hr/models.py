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
