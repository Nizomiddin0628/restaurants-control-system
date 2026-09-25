"""
Marketing va bonuslar (CRM).

Customer   — telefon bo'yicha yagona mijoz kartasi (kassa, Telegram, sayt — hammasi bitta joyda).
BonusTxn   — bonus harakati (+ yig'ildi / − sarflandi). Balans = yig'indi; Customer.balance — tezkor nusxa.
Promo      — aksiya: foiz yoki summa, avtomatik yoki promokod bilan, vaqt/kun/minimal summa/kimga.
OrderLink  — kassa buyurtmasiga biriktirilgan mijoz, aksiya va bonus (to'langanda hisoblanadi).
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import TimeStamped, User


class Customer(TimeStamped):
    phone = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120, blank=True)
    birthday = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, blank=True, help_text="m | f")
    note = models.CharField(max_length=300, blank=True)
    tags = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=12, default="pos", help_text="pos | telegram | site | manual | import")
    balance = models.BigIntegerField(default=0)
    spent_total = models.BigIntegerField(default=0)
    orders_count = models.PositiveIntegerField(default=0)
    first_order_at = models.DateTimeField(null=True, blank=True)
    last_order_at = models.DateTimeField(null=True, blank=True, db_index=True)
    marketing_ok = models.BooleanField(default=True, help_text="aksiya xabarlarini olishga rozi")

    class Meta:
        ordering = ["-last_order_at", "-created_at"]

    def __str__(self) -> str:
        return self.name or self.phone


class TxnKind(models.TextChoices):
    EARN = "earn", "Xariddan keshbek"
    SPEND = "spend", "Xaridda ishlatildi"
    WELCOME = "welcome", "Xush kelibsiz sovg'asi"
    BIRTHDAY = "birthday", "Tug'ilgan kun sovg'asi"
    ADJUST = "adjust", "Qo'lda o'zgartirildi"
    REFUND = "refund", "Qaytarildi (chek bekor)"


class BonusTxn(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="txns")
    kind = models.CharField(max_length=10, choices=TxnKind.choices)
    amount = models.BigIntegerField(help_text="+ qo'shildi, − ayirildi")
    order_id = models.IntegerField(null=True, blank=True, db_index=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class PromoKind(models.TextChoices):
    PERCENT = "percent", "Foiz chegirma"
    FIXED = "fixed", "Summa chegirma"


class PromoAudience(models.TextChoices):
    ALL = "all", "Hamma"
    NEW = "new", "Yangi mijozlar (birinchi xarid)"
    BIRTHDAY = "birthday", "Tug'ilgan kuni yaqin"
    SILVER = "silver", "Kumush va Oltin"
    GOLD = "gold", "Faqat Oltin"


class Promo(TimeStamped):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    kind = models.CharField(max_length=8, choices=PromoKind.choices, default=PromoKind.PERCENT)
    value = models.PositiveIntegerField(help_text="foiz (1–100) yoki so'm")
    max_discount = models.PositiveIntegerField(default=0, help_text="foizda eng ko'p chegirma, 0 — cheksiz")
    code = models.CharField(max_length=30, blank=True, db_index=True, help_text="bo'sh — avtomatik qo'llanadi")
    audience = models.CharField(max_length=10, choices=PromoAudience.choices, default=PromoAudience.ALL)
    min_order = models.PositiveIntegerField(default=0)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    weekdays = models.JSONField(default=list, blank=True, help_text="[0..6], 0 — dushanba; bo'sh — har kuni")
    hour_from = models.PositiveSmallIntegerField(null=True, blank=True)
    hour_to = models.PositiveSmallIntegerField(null=True, blank=True)
    category_ids = models.JSONField(default=list, blank=True, help_text="bo'sh — butun menyu")
    product_ids = models.JSONField(default=list, blank=True)
    max_uses = models.PositiveIntegerField(default=0, help_text="0 — cheksiz")
    used_count = models.PositiveIntegerField(default=0)
    discount_total = models.BigIntegerField(default=0, help_text="shu aksiya bo'yicha berilgan jami chegirma")
    revenue_total = models.BigIntegerField(default=0, help_text="aksiya qo'llangan cheklar summasi")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "-created_at"]

    def __str__(self) -> str:
        return self.name


class OrderLink(models.Model):
    order_id = models.IntegerField(unique=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    promo = models.ForeignKey(Promo, null=True, blank=True, on_delete=models.SET_NULL)
    promo_discount = models.BigIntegerField(default=0)
    bonus_used = models.BigIntegerField(default=0)
    earned = models.BigIntegerField(default=0)
    settled = models.BooleanField(default=False, help_text="to'lov hisoblangan (bonus yechilgan / qo'shilgan)")
    created_at = models.DateTimeField(default=timezone.now)
