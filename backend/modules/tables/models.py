"""
Zal va stollar.

Zone (zal/bo'lim) -> Table (stol). Stolning holati hisoblab chiqariladi:
    bo'sh -> band (ochiq seans) -> hisob so'raldi -> tozalash kerak -> bo'sh.
TableSession = stolda o'tirgan mehmonlar: qachon o'tirdi, nechta odam, ofitsiant kim, qaysi buyurtma.
Kassada zal buyurtmasi ochilsa - seans o'zi ochiladi (listeners.py), to'lansa - yopiladi.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from core.models import Branch, TimeStamped, User
from modules.pos.models import Order


class Zone(TimeStamped):
    """Zal, ikkinchi qavat, terrassa, VIP..."""

    name = models.CharField(max_length=80)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="zones")
    color = models.CharField(max_length=9, default="#0F6E63")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name


class TableShape(models.TextChoices):
    SQUARE = "square", "To'rtburchak"
    ROUND = "round", "Dumaloq"
    LONG = "long", "Uzun"


class TableStatus(models.TextChoices):
    FREE = "free", "Bo'sh"
    OCCUPIED = "occupied", "Band"
    BILL = "bill", "Hisob so'raldi"
    DIRTY = "dirty", "Tozalash kerak"
    RESERVED = "reserved", "Bron"
    OFF = "off", "Ishlatilmaydi"


class Table(TimeStamped):
    number = models.CharField(max_length=12, help_text="stol raqami yoki nomi: 12, A3, VIP-1")
    zone = models.ForeignKey(Zone, null=True, blank=True, on_delete=models.SET_NULL, related_name="tables")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="tables")
    seats = models.PositiveSmallIntegerField(default=4)
    shape = models.CharField(max_length=8, choices=TableShape.choices, default=TableShape.SQUARE)
    x = models.FloatField(default=10, help_text="zal xaritasidagi joyi, % (0-100)")
    y = models.FloatField(default=10)
    size = models.PositiveSmallIntegerField(default=1, help_text="1 kichik, 2 o'rta, 3 katta")
    needs_cleaning = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    qr_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["zone__sort_order", "number"]
        unique_together = [("branch", "number")]

    def __str__(self) -> str:
        return f"Stol {self.number}"

    @property
    def session(self):
        return self.sessions.filter(closed_at__isnull=True).order_by("-opened_at").first()

    def status(self, reserved_ids: set[int] | None = None) -> str:
        if not self.is_active:
            return TableStatus.OFF
        s = self.session
        if s:
            return TableStatus.BILL if s.bill_asked_at else TableStatus.OCCUPIED
        if self.needs_cleaning:
            return TableStatus.DIRTY
        if reserved_ids and self.pk in reserved_ids:
            return TableStatus.RESERVED
        return TableStatus.FREE


class TableSession(TimeStamped):
    """Stolda bir marta o'tirish: ochilishdan hisob to'langunicha."""

    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="sessions")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="table_sessions")
    waiter = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="table_sessions")
    guests = models.PositiveSmallIntegerField(default=2)
    opened_at = models.DateTimeField(default=timezone.now, db_index=True)
    bill_asked_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    total = models.BigIntegerField(default=0, help_text="yopilgandagi chek summasi (snapshot)")
    source = models.CharField(max_length=12, default="hall", help_text="hall | pos | reservation")
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["-opened_at"]

    def __str__(self) -> str:
        return f"{self.table} - {self.opened_at:%H:%M}"

    @property
    def minutes(self) -> int:
        end = self.closed_at or timezone.now()
        return int((end - self.opened_at).total_seconds() // 60)


DEFAULT_ZONES = [("Asosiy zal", "#0F6E63"), ("Terrassa", "#1F5FBF")]


def ensure_zones(branch=None) -> Zone:
    """Birinchi kirishda ikkita zal; stollarni egasi o'zi qo'shadi."""
    for i, (name, color) in enumerate(DEFAULT_ZONES):
        Zone.objects.get_or_create(name=name, defaults={"color": color, "sort_order": i, "branch": branch})
    return Zone.objects.first()