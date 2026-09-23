"""
Oshxona ekrani (KDS): kassadan tushgan buyurtma oshxona bo'limlariga (stansiyalarga) taqsimlanadi.

Stansiya = Grill, Salat, Ichimlik... Har stansiya o'z kategoriyalarini ko'radi.
Chek (Ticket) = bitta buyurtmaning bitta stansiyaga tegishli qismi. Holatlar:
    yangi → tayyorlanmoqda → tayyor → berildi.
Vaqt hisoblanadi: qancha kutayotgani rangda ko'rinadi (yashil / sariq / qizil).
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import Branch, TimeStamped, User
from modules.catalog.models import Category
from modules.pos.models import Order, OrderItem


def empty_i18n() -> dict:
    return {"uz": "", "ru": "", "en": ""}


class Station(TimeStamped):
    """Oshxona bo'limi. Kategoriyalar biriktiriladi — shu kategoriyadagi taomlar shu ekranga tushadi."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.JSONField(default=empty_i18n)
    categories = models.ManyToManyField(Category, blank=True, related_name="kds_stations")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="kds_stations")
    color = models.CharField(max_length=9, default="#0F6E63")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or self.code


class TicketStatus(models.TextChoices):
    NEW = "new", "Yangi"
    COOKING = "cooking", "Tayyorlanmoqda"
    READY = "ready", "Tayyor"
    SERVED = "served", "Berildi"
    CANCELLED = "cancelled", "Bekor"


class Ticket(TimeStamped):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="kds_tickets")
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    status = models.CharField(max_length=10, choices=TicketStatus.choices, default=TicketStatus.NEW, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)
    cook = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="kds_tickets")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        unique_together = [("order", "station")]

    def __str__(self) -> str:
        return f"KDS #{self.order.number}"

    @property
    def number(self) -> int:
        return self.order.number

    @property
    def waiting_minutes(self) -> int:
        end = self.ready_at or timezone.now()
        return int((end - self.created_at).total_seconds() // 60)

    @property
    def cook_minutes(self) -> int | None:
        if not self.started_at:
            return None
        end = self.ready_at or timezone.now()
        return int((end - self.started_at).total_seconds() // 60)


class TicketItem(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(OrderItem, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=160)
    qty = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=160, blank=True)
    modifiers = models.JSONField(default=list, blank=True)
    is_done = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]


DEFAULT_STATIONS = [
    ("hot", {"uz": "Issiq oshxona", "ru": "Горячий цех", "en": "Hot kitchen"}, "#D9482B"),
    ("cold", {"uz": "Sovuq / salat", "ru": "Холодный цех", "en": "Cold station"}, "#1E7F4F"),
    ("bar", {"uz": "Bar / ichimlik", "ru": "Бар", "en": "Bar"}, "#1F5FBF"),
]


def ensure_stations() -> None:
    """Birinchi kirishda 3 ta stansiya; kategoriyalarni egasi o'zi biriktiradi."""
    for i, (code, name, color) in enumerate(DEFAULT_STATIONS):
        Station.objects.get_or_create(code=code, defaults={"name": name, "color": color, "sort_order": i})