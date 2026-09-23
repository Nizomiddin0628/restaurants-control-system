"""
To'lovlar moduli — Payme (Merchant API, JSON-RPC) va Click (SHOP API, Prepare/Complete).

Har restoran o'z merchant kalitlarini kiritadi (Tenant.settings["payments"]), callback'lar restoran domeniga keladi:
    POST https://<slug>.restopos.uz/api/v1/payments/payme
    POST https://<slug>.restopos.uz/api/v1/payments/click/prepare  va  /click/complete
To'lov muvaffaqiyatli bo'lsa — buyurtma "to'langan" bo'ladi va `pos.order_paid` hodisasi chiqadi
(ombor yechiladi, moliya ko'radi). Payment jadvali — provayder bilan solishtirish (GetStatement) uchun.
"""
from __future__ import annotations

from django.db import models

from core.models import TimeStamped
from modules.pos.models import Order


class Provider(models.TextChoices):
    PAYME = "payme", "Payme"
    CLICK = "click", "Click"


class PaymeState(models.IntegerChoices):
    CREATED = 1
    PERFORMED = 2
    CANCELLED = -1
    CANCELLED_AFTER_PERFORM = -2


class Payment(TimeStamped):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=8, choices=Provider.choices)
    external_id = models.CharField(max_length=64, db_index=True, help_text="Payme transaction id / Click click_trans_id")
    amount = models.BigIntegerField(help_text="so'm")
    state = models.SmallIntegerField(default=PaymeState.CREATED, help_text="Payme holati; Click: 1 prepare, 2 complete, -1 bekor")
    reason = models.SmallIntegerField(null=True, blank=True)
    create_time = models.BigIntegerField(default=0, help_text="ms (Payme)")
    perform_time = models.BigIntegerField(default=0)
    cancel_time = models.BigIntegerField(default=0)
    prepare_id = models.PositiveIntegerField(null=True, blank=True, help_text="Click merchant_prepare_id")
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("provider", "external_id")]
