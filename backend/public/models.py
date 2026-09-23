"""
Public sxema modellari: tenantlar (restoranlar), domenlar, tariflar.

Har Tenant = alohida PostgreSQL sxemasi (django-tenants). Kod bitta, ma'lumot alohida.
"""
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin

from core.presets import PRESETS


class Plan(models.Model):
    """Tarif: qaysi modullar mavjud, limitlar, oylik narx (so'm)."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    price_per_branch = models.BigIntegerField(default=0, help_text="so'm / filial / oy")
    max_branches = models.PositiveIntegerField(default=1)
    max_devices = models.PositiveIntegerField(default=2)
    allowed_modules = models.JSONField(default=list, help_text="modul kodlari ro'yxati; ['*'] = hammasi")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name

    def allows(self, module_code: str) -> bool:
        return "*" in self.allowed_modules or module_code in self.allowed_modules


class Tenant(TenantMixin):
    """Bitta restoran / tarmoq. `schema_name` = PostgreSQL sxemasi."""

    PRESET_CHOICES = [(k, v["name"]) for k, v in PRESETS.items()]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, help_text="subdomen: <slug>.restopos.uz")
    preset = models.CharField(max_length=32, choices=PRESET_CHOICES, default="fast_food")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL)
    enabled_modules = models.JSONField(default=list, help_text="yoqilgan modul kodlari")
    settings = models.JSONField(default=dict, help_text="tenant darajasidagi sozlamalar (tillar, valyuta, soliq rejimi...)")
    owner_phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True   # save() da sxema + migratsiyalar avtomatik
    auto_drop_schema = False    # xavfsizlik: o'chirishda sxema saqlanadi

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.schema_name})"

    # ---- modullar
    def module_enabled(self, code: str) -> bool:
        return code in (self.enabled_modules or [])

    def can_enable(self, code: str) -> bool:
        return self.plan is None or self.plan.allows(code)


class Domain(DomainMixin):
    """Tenantga bog'langan domenlar: lazzat.restopos.uz, lazzat.uz ..."""

    def __str__(self) -> str:
        return self.domain
