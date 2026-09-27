"""
Tenant yaratish xizmati — "15 daqiqada ishga tushirish" ning backend qismi.

create_tenant(): sxema + migratsiyalar → owner foydalanuvchi → tizim rollari → preset modullar →
sayt temasi va bo'limlari → birinchi filial. Hammasi bitta funksiya, sehrgar va CLI shu funksiyani chaqiradi.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from core.models import Branch, Membership, Role, User
from core.modules import resolve_dependencies
from core.presets import DEFAULT_SETTINGS, PRESETS

from .models import Domain, Plan, Tenant

SYSTEM_ROLES = [
    ("owner", "Superadmin (egasi)", ["*"]),
    ("general_manager", "Bosh menejer", ["*"]),
    ("manager", "Filial menejeri (admin)", ["core.users.manage", "core.dashboard.view", "catalog.*", "cms.view", "core.branches.manage", "core.settings.view", "finance.*", "pos.*", "kds.*", "inventory.*", "hr.*", "tasks.*", "tables.*", "reservations.*", "payments.view", "training.*", "telegram.*", "crm.*", "forecast.*", "ops.*", "procurement.*", "projects.*"]),
    ("cashier", "Kassir", ["procurement.buy", "procurement.pay", "crm.view", "pos.sell", "pos.shift", "catalog.view", "tasks.view", "tasks.create", "hr.view", "tables.view", "tables.serve", "reservations.view", "reservations.manage"]),
    ("waiter", "Ofitsiant", ["crm.view", "tables.view", "tables.serve", "reservations.view", "reservations.manage", "pos.sell", "catalog.view", "kds.view", "tasks.view", "tasks.create", "hr.view"]),
    ("cook", "Oshpaz", ["kds.view", "kds.cook", "catalog.view", "inventory.view", "forecast.view", "tasks.view", "tasks.create", "hr.view"]),
    ("courier", "Kuryer", ["delivery.courier", "tasks.view", "tasks.create", "hr.view"]),
    ("accountant", "Buxgalter", ["core.dashboard.view", "finance.*", "inventory.*", "forecast.view", "ops.view", "procurement.*", "projects.view", "hr.payroll", "hr.view", "core.settings.view", "tasks.view", "tasks.create", "payments.view"]),
    ("buyer", "Bozorchi (zakupshik)", ["procurement.buy", "procurement.view", "inventory.view", "tasks.view", "tasks.create", "hr.view"]),
    ("marketer", "Marketolog", ["projects.view", "crm.*", "cms.*", "catalog.view", "tasks.view", "tasks.create", "tasks.edit", "telegram.view", "telegram.broadcast"]),
]
# Ierarxiya: kim kimga kirish bera oladi (faqat o'zidan pastga; Superadmin — hammaga)
ROLE_LEVELS = {"owner": 100, "general_manager": 80, "manager": 60}
ROLE_DESC = {
    "owner": "Restoran egasi — hamma narsa, barcha filiallar",
    "general_manager": "Barcha filiallar va bo'limlarni ko'radi va boshqaradi",
    "manager": "O'z filialining admini: xodimlar, smena, savdo, ombor",
}
# O'qitish: har bir xodim o'z kurslari, topshiriqlari va standartlarini ko'radi
for _code, _name, _perms in SYSTEM_ROLES:
    if _code not in ("owner", "general_manager", "manager"):
        _perms.append("training.view")
# Loyihalar: har bir xodim o'zi ishtirok etgan loyiha va vazifalarni ko'radi
for _code, _name, _perms in SYSTEM_ROLES:
    if "*" not in _perms and not any(p.startswith("projects.") for p in _perms):
        _perms.append("projects.view")


def slugify_schema(slug: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    if not re.match(r"^[a-z]", s):
        s = "t_" + s
    return s[:40]


@transaction.atomic
def create_tenant(*, name: str, slug: str, owner_phone: str, preset: str = "fast_food",
                  owner_name: str = "", plan_code: str | None = None, domain: str | None = None,
                  branch_name: str = "Asosiy filial", trial_days: int = 15) -> Tenant:
    if preset not in PRESETS:
        raise ValueError(f"Noma'lum preset: {preset}")
    cfg = PRESETS[preset]
    plan = Plan.objects.filter(code=plan_code).first() if plan_code else Plan.objects.filter(is_active=True).order_by("price_per_branch").first()

    tenant = Tenant(
        schema_name=slugify_schema(slug), name=name, slug=slug, preset=preset, plan=plan,
        enabled_modules=resolve_dependencies(list(cfg["modules"])),
        settings={**DEFAULT_SETTINGS},
        owner_phone=User.objects.normalize_phone(owner_phone),
        trial_ends_at=timezone.now() + timedelta(days=trial_days),
    )
    tenant.save()  # sxema yaratiladi + TENANT_APPS migratsiyalari qo'llanadi

    Domain.objects.create(tenant=tenant, domain=domain or f"{slug}.{settings.PLATFORM_DOMAIN}", is_primary=True)

    with schema_context(tenant.schema_name):
        roles = {}
        for code, rname, perms in SYSTEM_ROLES:
            roles[code], _ = Role.objects.get_or_create(code=code, defaults={"name": rname, "permissions": perms, "is_system": True,
                                                                             "level": ROLE_LEVELS.get(code, 10), "description": ROLE_DESC.get(code, "")})
        owner = User.objects.create_user(owner_phone, full_name=owner_name or "Egasi")
        Membership.objects.create(user=owner, role=roles["owner"])
        Branch.objects.create(name=branch_name, sort_order=0)

        # CMS moduli: tema + bo'limlar (modul o'zi `tenant.created` hodisasini tinglaydi)
        from core.events import emit
        emit("tenant.created", {"tenant_id": tenant.pk, "preset": preset, "name": name, "theme": cfg["theme"], "sections": cfg["sections"]}, tenant=tenant)

    return tenant


def set_modules(tenant: Tenant, codes: list[str]) -> list[str]:
    """Egasi modullarni yoqadi/o'chiradi. Tarif ruxsat bermasa — xato."""
    resolved = resolve_dependencies(codes)
    for c in resolved:
        if not tenant.can_enable(c):
            raise PermissionError(f"Tarif ushbu modulga ruxsat bermaydi: {c}")
    tenant.enabled_modules = resolved
    tenant.save(update_fields=["enabled_modules"])
    return resolved
