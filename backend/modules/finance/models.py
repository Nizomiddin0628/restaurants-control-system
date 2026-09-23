"""
Moliya moduli: chiqimlar + P&L (foyda-zarar) hisoboti.

Daromad — kassa (pos.Order, to'langan). Tannarx (COGS) — buyurtma qatorlaridagi tannarx snapshoti
(tex-karta → Product.cost). Mehnat — HR oyliklari (Payslip). Boshqa chiqimlar — shu yerdagi Expense.
Sof foyda = Daromad − COGS − Mehnat − Chiqimlar. Hammasi davr va filial kesimida.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import Branch, TimeStamped, User


class ExpenseCategory(TimeStamped):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, default="opex", help_text="opex | capex | tax")
    is_fixed = models.BooleanField(default=False, help_text="doimiy (ijara) yoki o'zgaruvchan")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "expense categories"

    def __str__(self) -> str:
        return self.name


class Expense(TimeStamped):
    date = models.DateField(default=timezone.localdate, db_index=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="expenses")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = models.BigIntegerField()
    note = models.CharField(max_length=200, blank=True)
    receipt = models.FileField(upload_to="finance/receipts/%Y/%m/", blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=12, default="manual", help_text="manual | purchase | payroll")
    ref = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["-date", "-id"]


DEFAULT_CATEGORIES = [
    ("rent", "Ijara", True), ("utilities", "Kommunal (svet, gaz, suv)", True), ("marketing", "Marketing va reklama", False),
    ("repair", "Ta'mirlash va texnik xizmat", False), ("packaging", "Qadoq va sarf materiallari", False),
    ("delivery", "Yetkazib berish xarajati", False), ("tax", "Soliq va to'lovlar", True), ("bank", "Bank va ekvayring komissiyasi", False),
    ("software", "Dasturiy ta'minot", True), ("other", "Boshqa", False),
]


def ensure_categories() -> None:
    for i, (code, name, fixed) in enumerate(DEFAULT_CATEGORIES):
        ExpenseCategory.objects.get_or_create(code=code, defaults={"name": name, "is_fixed": fixed, "sort_order": i,
                                                                   "kind": "tax" if code == "tax" else "opex"})
