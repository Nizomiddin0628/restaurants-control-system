"""
Bron (oldindan buyurtma) va navbat (waitlist).

Reservation: mehmon qachon, nechta odam bilan, qaysi stolga keladi.
    yangi -> tasdiqlandi -> o'tirdi -> tugadi;  bekor / kelmadi.
WaitlistEntry: joy yo'q bo'lganda navbatga yozish - stol bo'shasa chaqiriladi.
Bronga stol biriktirilsa, o'sha vaqtda stol «bron» rangida ko'rinadi (tables moduli).
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.models import Branch, TimeStamped, User
from modules.tables.models import Table, Zone


class ReservationStatus(models.TextChoices):
    NEW = "new", "Yangi"
    CONFIRMED = "confirmed", "Tasdiqlandi"
    SEATED = "seated", "O'tirdi"
    DONE = "done", "Tugadi"
    CANCELLED = "cancelled", "Bekor"
    NO_SHOW = "no_show", "Kelmadi"


ACTIVE_STATUSES = [ReservationStatus.NEW, ReservationStatus.CONFIRMED]


class Reservation(TimeStamped):
    guest_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    guests = models.PositiveSmallIntegerField(default=2)
    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations")
    zone = models.ForeignKey(Zone, null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="reservations")
    starts_at = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(default=90)
    status = models.CharField(max_length=10, choices=ReservationStatus.choices, default=ReservationStatus.NEW, db_index=True)
    source = models.CharField(max_length=12, default="phone", help_text="phone | hall | site | telegram")
    note = models.CharField(max_length=200, blank=True)
    occasion = models.CharField(max_length=40, blank=True, help_text="tug'ilgan kun, uchrashuv...")
    deposit = models.BigIntegerField(default=0, help_text="oldindan to'lov (so'm)")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations")
    seated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [models.Index(fields=["starts_at", "status"])]

    def __str__(self) -> str:
        return f"{self.guest_name} - {timezone.localtime(self.starts_at):%d.%m %H:%M}"

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def minutes_left(self) -> int:
        return int((self.starts_at - timezone.now()).total_seconds() // 60)

    @property
    def is_late(self) -> bool:
        return self.is_active and self.minutes_left < 0


class WaitStatus(models.TextChoices):
    WAITING = "waiting", "Navbatda"
    CALLED = "called", "Chaqirildi"
    SEATED = "seated", "O'tirdi"
    LEFT = "left", "Ketdi"


class WaitlistEntry(TimeStamped):
    """Navbat: zal to'la bo'lganda mehmon shu ro'yxatga yoziladi."""

    guest_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    guests = models.PositiveSmallIntegerField(default=2)
    status = models.CharField(max_length=8, choices=WaitStatus.choices, default=WaitStatus.WAITING, db_index=True)
    called_at = models.DateTimeField(null=True, blank=True)
    seated_at = models.DateTimeField(null=True, blank=True)
    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.SET_NULL, related_name="waitlist")
    quoted_minutes = models.PositiveSmallIntegerField(default=15, help_text="aytilgan kutish vaqti")
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "waitlist"

    def __str__(self) -> str:
        return f"{self.guest_name} ({self.guests})"

    @property
    def waiting_minutes(self) -> int:
        end = self.seated_at or timezone.now()
        return int((end - self.created_at).total_seconds() // 60)