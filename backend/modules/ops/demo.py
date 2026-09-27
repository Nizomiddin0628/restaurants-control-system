"""Demo: tayyor tuzilma + ko'rgazma xodimlarini lavozim va filiallarga taqsimlash (daraxt «jonli» ko'rinsin)."""
from __future__ import annotations

from . import services

# ism → (shablon kaliti, filial tartib raqami yoki None = bosh ofis)
DEMO_MULTI = {
    "Rustam Karimov": ("ops_director", None), "Malika Yusupova": ("branch_manager", 0), "Kamron Saidov": ("branch_manager", 1),
    "Umar Bekzodov": ("branch_manager", 2), "Farhod Tursunov": ("cook", 1), "Ravshan Hakimov": ("cook", 2),
    "Nodira Ahmedova": ("cashier", 1), "Otabek Nurmatov": ("waiter", 1), "Shahzoda Umarova": ("waiter", 2),
    "Gulnoza Nazarova": ("hr_manager", None), "Aziza Rahimova": ("accountant", None), "Sardor Aliyev": ("marketing", None),
}
DEMO_SINGLE = {
    "Rustam Karimov": ("ops_director", None), "Malika Yusupova": ("branch_manager", 0), "Kamron Saidov": ("shift_manager", 0),
    "Umar Bekzodov": ("shift_manager", 0), "Gulnoza Nazarova": ("hr_manager", None), "Aziza Rahimova": ("accountant", None),
    "Sardor Aliyev": ("marketing", None),
}


def seed_demo_ops(tenant=None, demo: bool = False) -> dict:
    r = services.install_template()
    if demo:
        r["moved"] = _spread()
    return r


def _spread() -> int:
    from core.models import Branch
    from modules.hr.models import Employee

    from .models import PositionProfile
    branches = list(Branch.objects.filter(deleted_at__isnull=True, is_active=True))
    plan = DEMO_MULTI if len(branches) >= 3 else DEMO_SINGLE
    pos = {p.template_key: p.position for p in PositionProfile.objects.exclude(template_key="").select_related("position")}
    bm = pos.get("branch_manager")
    if bm is not None and bm.name == "Menejer":
        bm.name = "Filial menejeri"
        bm.save(update_fields=["name", "updated_at"])
    n = 0
    for e in Employee.objects.select_related("user"):
        spec = plan.get(e.user.full_name)
        if not spec or spec[0] not in pos:
            continue
        key, bi = spec
        e.position = pos[key]
        e.branch = branches[bi] if bi is not None and bi < len(branches) else None
        e.save(update_fields=["position", "branch", "updated_at"])
        n += 1
    return n
