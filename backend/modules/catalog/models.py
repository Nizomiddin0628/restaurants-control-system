"""
Taomnoma moduli: kategoriya, taom, modifikatorlar, filial narxlari, e'lon qilingan versiya (snapshot).
Pul — so'm (butun son). Matnlar 3 tilda (uz/ru/en) JSON maydonda.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Branch, SoftDelete, TimeStamped


def empty_i18n() -> dict:
    return {"uz": "", "ru": "", "en": ""}


class Category(TimeStamped, SoftDelete):
    name = models.JSONField(default=empty_i18n)
    image = models.ImageField(upload_to="catalog/categories/", blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    custom_data = models.JSONField(default=dict, blank=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or self.name.get("ru") or f"#{self.pk}"


class ModifierGroup(TimeStamped):
    """Masalan: "Sous" (0–2 ta), "Achchiqlik" (1 ta majburiy)."""

    name = models.JSONField(default=empty_i18n)
    min_select = models.PositiveSmallIntegerField(default=0)
    max_select = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or f"#{self.pk}"


class Modifier(TimeStamped):
    group = models.ForeignKey(ModifierGroup, on_delete=models.CASCADE, related_name="options")
    name = models.JSONField(default=empty_i18n)
    price = models.BigIntegerField(default=0, help_text="qo'shimcha narx, so'm")
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class Product(TimeStamped, SoftDelete):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.JSONField(default=empty_i18n)
    description = models.JSONField(default=empty_i18n, blank=True)
    sku = models.CharField(max_length=40, blank=True)
    price = models.BigIntegerField(default=0, help_text="asosiy sotuv narxi, so'm")
    cost = models.BigIntegerField(default=0, help_text="tannarx, so'm (ombor moduli avtomatik yangilaydi)")
    image = models.ImageField(upload_to="catalog/products/", blank=True)
    weight_g = models.PositiveIntegerField(null=True, blank=True)
    kcal = models.PositiveIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list, blank=True, help_text='["hit", "new", "spicy"]')
    modifier_groups = models.ManyToManyField(ModifierGroup, blank=True, related_name="products")
    is_active = models.BooleanField(default=True)
    in_stop_list = models.BooleanField(default=False, help_text="vaqtincha yo'q (kassa/saytda ko'rinmaydi)")
    sort_order = models.PositiveIntegerField(default=0)
    ikpu_code = models.CharField(max_length=17, blank=True, help_text="fiskal chek uchun IKPU (4-bosqich)")
    custom_data = models.JSONField(default=dict, blank=True, help_text="egasi qo'shgan maydonlar")
    history = HistoricalRecords(m2m_fields=[modifier_groups])

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or self.name.get("ru") or f"#{self.pk}"

    @property
    def margin_percent(self) -> float | None:
        if self.price and self.cost:
            return round((self.price - self.cost) / self.price * 100, 1)
        return None


class BranchPrice(models.Model):
    """Filial bo'yicha boshqa narx (bo'lmasa Product.price)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="branch_prices")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="prices")
    price = models.BigIntegerField()

    class Meta:
        unique_together = [("product", "branch")]


class MenuVersion(models.Model):
    """E'lon qilingan taomnoma snapshoti — sayt, Mini App va kassa shuni o'qiydi (qoralama → e'lon)."""

    version = models.PositiveIntegerField()
    published_at = models.DateTimeField(default=timezone.now)
    published_by = models.CharField(max_length=120, blank=True)
    snapshot = models.JSONField()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-version"]
        get_latest_by = "version"

    def __str__(self) -> str:
        return f"v{self.version} · {self.published_at:%d.%m.%Y %H:%M}"
