"""
Kassa (POS) moduli — buyurtma, to'lov, kassa smenasi.

Order: ochiq → to'langan / bekor. Har qatorda narx va tannarx SNAPSHOT (keyin narx o'zgarsa hisobot buzilmaydi).
To'langanda `pos.order_paid` hodisasi: ombor xomashyoni yechadi, moliya savdoni ko'radi, CRM bonus yozadi (keyin).
Fiskal chek (Soliq) — alohida `fiscal` moduli (keyingi bosqich): u ham shu hodisani tinglaydi.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import Branch, TimeStamped, User
from modules.catalog.models import Product


class OrderType(models.TextChoices):
    DINE_IN = "dine_in", "Zalda"
    TAKEAWAY = "takeaway", "Olib ketish"
    DELIVERY = "delivery", "Yetkazib berish"


class OrderStatus(models.TextChoices):
    OPEN = "open", "Ochiq"
    PAID = "paid", "To'langan"
    CANCELLED = "cancelled", "Bekor qilingan"


class PayMethod(models.TextChoices):
    CASH = "cash", "Naqd"
    CARD = "card", "Karta (terminal)"
    CLICK = "click", "Click"
    PAYME = "payme", "Payme"
    UZUM = "uzum", "Uzum"
    TRANSFER = "transfer", "O'tkazma"


class CashShift(TimeStamped):
    """Kassa smenasi: ochildi (boshlang'ich naqd) → yopildi (haqiqiy naqd, farq)."""

    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="cash_shifts")
    opened_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="opened_shifts")
    closed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="closed_shifts")
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    cash_start = models.BigIntegerField(default=0)
    cash_end = models.BigIntegerField(null=True, blank=True, help_text="hisoblangan haqiqiy naqd")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-opened_at"]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def totals(self) -> dict:
        qs = self.orders.filter(status=OrderStatus.PAID)
        by = {m.value: 0 for m in PayMethod}
        for o in qs.values("payment_method").annotate(s=models.Sum("total")):
            by[o["payment_method"]] = int(o["s"] or 0)
        total = sum(by.values())
        expected_cash = self.cash_start + by.get("cash", 0)
        return {"orders": qs.count(), "total": total, "by_method": by, "expected_cash": expected_cash,
                "cash_diff": (self.cash_end - expected_cash) if self.cash_end is not None else None}


class Order(TimeStamped):
    number = models.PositiveIntegerField(editable=False, db_index=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    shift = models.ForeignKey(CashShift, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    type = models.CharField(max_length=10, choices=OrderType.choices, default=OrderType.TAKEAWAY)
    status = models.CharField(max_length=10, choices=OrderStatus.choices, default=OrderStatus.OPEN, db_index=True)
    table_no = models.CharField(max_length=12, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=200, blank=True)

    subtotal = models.BigIntegerField(default=0)
    discount = models.BigIntegerField(default=0)
    total = models.BigIntegerField(default=0)
    cost_total = models.BigIntegerField(default=0, help_text="tannarx yig'indisi (snapshot)")

    payment_method = models.CharField(max_length=10, choices=PayMethod.choices, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    cashier = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    source = models.CharField(max_length=12, default="pos", help_text="pos | site | telegram | app")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Buyurtma #{self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            last = Order.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 1000) + 1
        super().save(*args, **kwargs)

    def recalc(self) -> None:
        items = list(self.items.all())
        self.subtotal = sum(i.line_total for i in items)
        self.cost_total = sum(i.cost * i.qty for i in items)
        self.total = max(0, self.subtotal - self.discount)

    @property
    def gross_profit(self) -> int:
        return self.total - self.cost_total


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=160)
    qty = models.PositiveIntegerField(default=1)
    price = models.BigIntegerField(help_text="sotuv narxi (snapshot)")
    cost = models.BigIntegerField(default=0, help_text="tannarx (snapshot)")
    modifiers = models.JSONField(default=list, blank=True, help_text='[{"name": "...", "price": 0}]')
    note = models.CharField(max_length=120, blank=True)

    @property
    def line_total(self) -> int:
        extra = sum(int(m.get("price", 0)) for m in self.modifiers or [])
        return (self.price + extra) * self.qty
