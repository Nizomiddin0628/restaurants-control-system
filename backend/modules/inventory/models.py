"""
Ombor va tannarx moduli.

  Ingredient (xomashyo: go'sht, un, pomidor…)  — bazaviy birlik: kg / l / dona; narx bazaviy birlik uchun (so'm/kg).
  Purchase (kirim / bozorlik) → PurchaseLine   — narxni yangilaydi (oxirgi yoki o'rtacha), qoldiqni oshiradi.
  Recipe (tex-karta) → RecipeLine              — taomga nechta gramm/ml/dona ketadi; chiqindi %; yield (porsiya).
  StockMovement                                — har harakat: kirim, savdo, chiqindi, inventarizatsiya.

Tannarx = Σ (miqdor_bazaviy × narx_bazaviy × (1 + chiqindi%)) / porsiya. Xomashyo narxi o'zgarsa —
shu xomashyo bor barcha tex-kartalar qayta hisoblanadi va Product.cost yangilanadi (listeners/signals).
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import Branch, SoftDelete, TimeStamped, User
from modules.catalog.models import Product


class Unit(models.TextChoices):
    KG = "kg", "kg"
    L = "l", "litr"
    PCS = "dona", "dona"


# tex-kartadagi mayda birlik → bazaviy birlikka koeffitsient
SUB_UNIT = {Unit.KG: ("g", Decimal("0.001")), Unit.L: ("ml", Decimal("0.001")), Unit.PCS: ("dona", Decimal("1"))}


def empty_i18n() -> dict:
    return {"uz": "", "ru": "", "en": ""}


class Supplier(TimeStamped):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Ingredient(TimeStamped, SoftDelete):
    name = models.JSONField(default=empty_i18n)
    category = models.CharField(max_length=60, blank=True, help_text="Go'sht, Sabzavot, Sut mahsulotlari, Quruq…")
    unit = models.CharField(max_length=5, choices=Unit.choices, default=Unit.KG)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="so'm / bazaviy birlik (kg, l, dona)")
    stock = models.DecimalField(max_digits=14, decimal_places=3, default=0, help_text="qoldiq, bazaviy birlikda")
    min_stock = models.DecimalField(max_digits=14, decimal_places=3, default=0, help_text="shu miqdordan kam bo'lsa — ogohlantirish")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="ingredients")
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["category", "id"]

    def __str__(self) -> str:
        return self.name.get("uz") or f"#{self.pk}"

    @property
    def sub_unit(self) -> str:
        return SUB_UNIT[Unit(self.unit)][0]

    @property
    def is_low(self) -> bool:
        return self.min_stock > 0 and self.stock <= self.min_stock

    @property
    def stock_value(self) -> Decimal:
        return (self.stock * self.price).quantize(Decimal("1"))


class Purchase(TimeStamped):
    """Kirim (bozorlik / yetkazib beruvchi)."""

    number = models.PositiveIntegerField(editable=False)
    date = models.DateField(default=timezone.localdate)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)
    total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_posted = models.BooleanField(default=True, help_text="omborga o'tkazilgan")

    class Meta:
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if not self.number:
            last = Purchase.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 0) + 1
        super().save(*args, **kwargs)


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="purchase_lines")
    qty = models.DecimalField(max_digits=14, decimal_places=3, help_text="bazaviy birlikda (kg/l/dona)")
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, help_text="so'm / bazaviy birlik")

    @property
    def total(self) -> Decimal:
        return (self.qty * self.unit_price).quantize(Decimal("0.01"))


class Recipe(TimeStamped):
    """Tex-karta: bitta taom uchun xomashyo ro'yxati."""

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="recipe")
    yield_qty = models.DecimalField(max_digits=8, decimal_places=2, default=1, help_text="necha porsiya chiqadi")
    note = models.TextField(blank=True, help_text="tayyorlash tartibi (oshpaz uchun)")
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="1 porsiya tannarxi, so'm (avtomatik)")
    computed_at = models.DateTimeField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self) -> str:
        return f"Tex-karta: {self.product}"

    def compute_cost(self) -> Decimal:
        total = Decimal("0")
        for line in self.lines.select_related("ingredient"):
            total += line.cost
        yield_qty = self.yield_qty or Decimal("1")
        return (total / yield_qty).quantize(Decimal("1"))


class RecipeLine(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="lines")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="recipe_lines")
    qty = models.DecimalField(max_digits=12, decimal_places=3, help_text="mayda birlikda: g / ml / dona")
    waste_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="tozalash/pishirish chiqindisi, %")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    @property
    def base_qty(self) -> Decimal:
        """gramm → kg, ml → l, dona → dona."""
        return self.qty * SUB_UNIT[Unit(self.ingredient.unit)][1]

    @property
    def cost(self) -> Decimal:
        return (self.base_qty * self.ingredient.price * (1 + self.waste_percent / 100)).quantize(Decimal("0.01"))


class MovementKind(models.TextChoices):
    PURCHASE = "purchase", "Kirim"
    SALE = "sale", "Savdo"
    WASTE = "waste", "Chiqindi / yaroqsiz"
    ADJUST = "adjust", "Inventarizatsiya"
    TRANSFER = "transfer", "Filialga o'tkazish"


class StockMovement(models.Model):
    at = models.DateTimeField(default=timezone.now, db_index=True)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name="movements")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=10, choices=MovementKind.choices)
    qty = models.DecimalField(max_digits=14, decimal_places=3, help_text="+ kirim, − chiqim (bazaviy birlik)")
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    ref = models.CharField(max_length=60, blank=True, help_text="Kirim #12, Buyurtma #345…")
    note = models.CharField(max_length=200, blank=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-at", "-id"]
