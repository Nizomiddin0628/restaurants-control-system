"""
Modul registri — har modul `modules/<code>/module.json` bilan o'zini e'lon qiladi.

module.json:
{
  "code": "catalog", "name": {"uz": "...", "ru": "...", "en": "..."},
  "version": "1.0.0", "phase": 1, "implemented": true,
  "depends": [], "permissions": ["catalog.view", ...],
  "nav": [{"route": "/catalog", "label": {...}, "icon": "book", "order": 30}],
  "settings_schema": {...}   # JSON Schema — egasi paneldagi "Sozlamalar" formasi shu sxemadan quriladi
}

Registr ilova ishga tushganda bir marta o'qiladi. Yangi modul = yangi papka + module.json (yadroga tegilmaydi).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"

# Hali yozilmagan, lekin egasi panelda ko'radigan modullar (reja bo'yicha). Kod paydo bo'lganda
# papkaga module.json qo'shiladi va bu ro'yxatdan olib tashlanadi.
PLANNED_MODULES = [
    {"code": "fiscal", "name": {"uz": "Fiskal (onlayn-kassa)", "ru": "Фискализация", "en": "Fiscal"}, "phase": 4, "order": 21},
    {"code": "telegram", "name": {"uz": "Telegram bot va Mini App", "ru": "Telegram-бот", "en": "Telegram"}, "phase": 6, "order": 50},
    {"code": "crm", "name": {"uz": "Marketing va bonuslar", "ru": "Маркетинг и бонусы", "en": "Marketing & loyalty"}, "phase": 8, "order": 80},
    {"code": "delivery", "name": {"uz": "Yetkazib berish", "ru": "Доставка", "en": "Delivery"}, "phase": 8, "order": 85},
    {"code": "market", "name": {"uz": "Bozor tahlili", "ru": "Анализ рынка", "en": "Market insights"}, "phase": 10, "order": 95},
]


@dataclass
class ModuleInfo:
    code: str
    name: dict
    version: str = "0.0.0"
    phase: int = 0
    implemented: bool = False
    depends: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    nav: list[dict] = field(default_factory=list)
    settings_schema: dict = field(default_factory=dict)
    order: int = 100

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "version": self.version, "phase": self.phase,
            "implemented": self.implemented, "depends": self.depends, "permissions": self.permissions,
            "nav": self.nav, "settings_schema": self.settings_schema, "order": self.order,
        }


@lru_cache(maxsize=1)
def registry() -> dict[str, ModuleInfo]:
    mods: dict[str, ModuleInfo] = {}
    for manifest in sorted(MODULES_DIR.glob("*/module.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        info = ModuleInfo(**{k: v for k, v in data.items() if k in ModuleInfo.__dataclass_fields__})
        mods[info.code] = info
    for planned in PLANNED_MODULES:
        if planned["code"] not in mods:
            mods[planned["code"]] = ModuleInfo(code=planned["code"], name=planned["name"], phase=planned["phase"], order=planned["order"])
    return mods


def get(code: str) -> ModuleInfo | None:
    return registry().get(code)


def all_modules() -> list[ModuleInfo]:
    return sorted(registry().values(), key=lambda m: (m.order, m.code))


def nav_for(enabled: list[str]) -> list[dict]:
    """Yon menyu — faqat yoqilgan va yozilgan modullar bandlari, tartib bilan."""
    items: list[dict] = []
    for m in all_modules():
        if m.implemented and m.code in enabled:
            for item in m.nav:
                items.append({**item, "module": m.code})
    return sorted(items, key=lambda i: i.get("order", 100))


def all_permissions(enabled: list[str] | None = None) -> list[str]:
    perms = ["core.*", "core.settings.view", "core.settings.edit", "core.branches.manage", "core.users.manage", "core.modules.manage"]
    for m in all_modules():
        if enabled is None or m.code in enabled:
            perms.extend(m.permissions)
    return sorted(set(perms))


def resolve_dependencies(codes: list[str]) -> list[str]:
    """Yoqilayotgan modullar bog'liqliklarini avtomatik qo'shadi."""
    out: list[str] = []

    def add(c: str):
        if c in out:
            return
        m = get(c)
        if m:
            for d in m.depends:
                add(d)
        out.append(c)

    for c in codes:
        add(c)
    return out
