"""
Kirish huquqlari — oddiy tilda.

Har bir xodim: bir yoki bir nechta ROL (Kassir, Oshpaz, Filial menejeri…) + kerak bo'lsa SHAXSIY ruxsatlar
(masalan kassirga «Ombor — faqat ko'radi»). Filiallar: bo'sh — hammasi, aks holda faqat tanlanganlar.

Ierarxiya (Role.level):  Superadmin (egasi) 100 → Bosh menejer 80 → Filial menejeri 60 → xodim 10.
  • kirishni faqat o'zidan PASTdagilarga beradi (Superadmin — hammaga, boshqa Superadminga ham);
  • filial menejeri faqat o'z filiallari ichida;
  • o'zida yo'q ruxsatni boshqaga bera olmaydi.

Sahifalar matritsasi (AREAS): har bo'lim uchun daraja — Yo'q / Ko'radi / Ishlaydi / To'liq.
"""
from __future__ import annotations

from ninja.errors import HttpError

SECTIONS = [
    ("sales", "💳 Savdo va xizmat"), ("menu", "🍽️ Menyu"), ("clients", "❤️ Mijozlar va marketing"),
    ("stock", "📦 Ombor va xarid"), ("team", "👥 Xodimlar"), ("training", "🎓 O'qitish"),
    ("work", "✅ Vazifa va loyihalar"), ("finance", "📊 Moliya va hisobot"), ("settings", "⚙️ Sozlamalar"), ("ai", "🤖 AI Kotib"),
]

# (bo'lim, kod, nomi, modul, ko'radi, ishlaydi, to'liq)
_A = [
    ("sales", "pos", "Kassa", "pos", [], ["pos.sell", "pos.shift"], ["pos.*"]),
    ("sales", "kds", "Oshxona ekrani", "kds", ["kds.view"], ["kds.view", "kds.cook"], ["kds.*"]),
    ("sales", "tables", "Zal va stollar", "tables", ["tables.view"], ["tables.view", "tables.serve"], ["tables.*"]),
    ("sales", "reservations", "Bron", "reservations", ["reservations.view"], ["reservations.view", "reservations.manage"], ["reservations.*"]),
    ("menu", "catalog", "Menyu (taomlar, narxlar)", "catalog", ["catalog.view"], ["catalog.view", "catalog.edit"], ["catalog.*"]),
    ("clients", "crm", "Mijozlar va bonus", "crm", ["crm.view"], ["crm.view", "crm.manage", "crm.bonus"], ["crm.*"]),
    ("clients", "telegram", "Telegram bot", "telegram", ["telegram.view"], ["telegram.view", "telegram.broadcast"], ["telegram.*"]),
    ("clients", "cms", "Sayt", "cms", ["cms.view"], ["cms.view", "cms.edit"], ["cms.*"]),
    ("stock", "inventory", "Ombor", "inventory", ["inventory.view"], ["inventory.view", "inventory.edit", "inventory.purchase"], ["inventory.*"]),
    ("stock", "procurement", "Zakup va bozorlik", "procurement", ["procurement.view"], ["procurement.view", "procurement.buy", "procurement.edit"], ["procurement.*"]),
    ("stock", "forecast", "Bayram va ob-havo prognozi", "forecast", ["forecast.view"], ["forecast.view", "forecast.edit"], ["forecast.*"]),
    ("team", "hr", "Xodimlar, smena, davomat", "hr", ["hr.view"], ["hr.view", "hr.edit"], ["hr.*"]),
    ("team", "ops", "Tuzilma va lavozimlar", "ops", ["ops.view"], ["ops.view", "ops.edit"], ["ops.*"]),
    ("team", "users", "Xodimlar va kirish (boshqalarga kirish berish)", None, [], [], ["core.users.manage"]),
    ("training", "training", "O'qitish", "training", ["training.view"], ["training.view", "training.review"], ["training.*"]),
    ("work", "tasks", "Vazifalar", "tasks", ["tasks.view"], ["tasks.view", "tasks.create", "tasks.edit"], ["tasks.*"]),
    ("work", "projects", "Loyihalar", "projects", ["projects.view"], ["projects.view", "projects.edit"], ["projects.*"]),
    ("finance", "dashboard", "Boshqaruv paneli (savdo raqamlari)", None, ["core.dashboard.view"], [], []),
    ("finance", "finance", "Moliya va hisobotlar", "finance", ["finance.view"], ["finance.view", "finance.edit"], ["finance.*", "payments.*"]),
    ("settings", "branches", "Filiallar", None, [], [], ["core.branches.manage"]),
    ("settings", "settings", "Restoran sozlamalari", None, ["core.settings.view"], [], ["core.settings.view", "core.settings.edit", "core.modules.manage"]),
    ("ai", "ai", "AI Kotib", "ai", [], ["ai.use"], ["ai.*"]),
]
AREAS = [{"section": a[0], "code": a[1], "title": a[2], "module": a[3], "view": a[4], "edit": a[5], "full": a[6]} for a in _A]

PERM_LABELS = {
    "pos.sell": "Sotish (buyurtma olish)", "pos.shift": "Smena ochish/yopish", "pos.refund": "Qaytarish (vozvrat)", "pos.view_all": "Barcha cheklar",
    "kds.view": "Ekranni ko'rish", "kds.cook": "Taom tayyor deb belgilash", "kds.admin": "Ekran sozlamalari",
    "tables.view": "Zalni ko'rish", "tables.serve": "Stolga xizmat", "tables.admin": "Zal xaritasini tahrirlash",
    "reservations.view": "Bronlarni ko'rish", "reservations.manage": "Bron qilish/o'zgartirish",
    "catalog.view": "Ko'rish", "catalog.edit": "Taom/narx tahrirlash", "catalog.publish": "Menyuni e'lon qilish",
    "crm.view": "Ko'rish", "crm.manage": "Tahrirlash", "crm.bonus": "Bonus berish", "crm.message": "Xabar yuborish",
    "telegram.view": "Ko'rish", "telegram.manage": "Bot sozlamalari", "telegram.broadcast": "Xabar tarqatish",
    "cms.view": "Ko'rish", "cms.edit": "Saytni tahrirlash",
    "inventory.view": "Qoldiqni ko'rish", "inventory.edit": "Kirim/chiqim", "inventory.purchase": "Xarid", "inventory.recipe": "Tex-karta",
    "procurement.view": "Ko'rish", "procurement.edit": "Tahrirlash", "procurement.buy": "Bozorlik (xarid)", "procurement.pay": "To'lov",
    "forecast.view": "Ko'rish", "forecast.edit": "Sozlash",
    "hr.view": "Ko'rish", "hr.edit": "Tahrirlash", "hr.payroll": "Oylik", "hr.recruit": "Ishga olish", "hr.review": "Baholash/KPI",
    "ops.view": "Ko'rish", "ops.edit": "Tahrirlash",
    "training.view": "O'qish", "training.manage": "Kurs yaratish", "training.review": "Tekshirish",
    "tasks.view": "O'z vazifalari", "tasks.view_all": "Barcha vazifalar", "tasks.create": "Yaratish", "tasks.edit": "Tahrirlash",
    "tasks.assign": "Topshirish", "tasks.approve": "Tasdiqlash", "tasks.admin": "Doska sozlamalari", "tasks.delete": "O'chirish",
    "projects.view": "Ko'rish", "projects.edit": "Boshqarish",
    "finance.view": "Hisobotlarni ko'rish", "finance.edit": "Xarajat kiritish", "payments.view": "To'lovlar",
    "ai.use": "Foydalanish", "ai.manage": "Sozlash va taqsimlash",
    "core.dashboard.view": "Savdo raqamlarini ko'rish", "core.users.manage": "Kirish berish",
    "core.branches.manage": "Filiallarni boshqarish", "core.settings.view": "Ko'rish", "core.settings.edit": "O'zgartirish", "core.modules.manage": "Modullarni yoqish",
}
LEVEL_LABELS = {"none": "Yo'q", "view": "Ko'radi", "edit": "Ishlaydi", "full": "To'liq", "custom": "Tanlangan"}


def covers(perms: set[str] | list[str], code: str) -> bool:
    perms = set(perms)
    if "*" in perms or code in perms:
        return True
    parts = code.split(".")
    return any(".".join(parts[:i]) + ".*" in perms for i in range(1, len(parts)))


def area_perms(a: dict) -> list[str]:
    mod = a["module"]
    from core import modules as modreg
    extra = []
    if mod and (m := modreg.get(mod)):
        extra = [p for p in m.permissions if not p.endswith(".*")]
    return list(dict.fromkeys([*a["view"], *a["edit"], *[p for p in a["full"] if not p.endswith(".*")], *extra]))


def area_level(perms, a: dict) -> str:
    if a["full"] and all(covers(perms, p) for p in a["full"]):
        return "full"
    if a["edit"] and all(covers(perms, p) for p in a["edit"]):
        return "edit"
    if a["view"] and all(covers(perms, p) for p in a["view"]):
        return "view"
    return "custom" if any(covers(perms, p) for p in area_perms(a)) else "none"


def known_perms() -> set[str]:
    from core import modules as modreg
    return set(modreg.all_permissions()) | set(PERM_LABELS)


# ------------------------------------------------------------------ ierarxiya
def is_platform(user) -> bool:
    return user.is_superuser or user.memberships.filter(is_active=True, role__code="platform_support").exists()


def can_grant_role(actor, role) -> bool:
    lv = actor.access_level()
    return role.code != "platform_support" and (role.level < lv or lv >= 100)


def can_manage_user(actor, target) -> bool:
    if actor.pk == target.pk:
        return False
    lv = actor.access_level()
    if not actor.has_perm_code("core.users.manage"):
        return False
    tl = target.access_level()
    if not (tl < lv or lv >= 100):
        return False
    if target.memberships.filter(role__code="platform_support").exists() and lv < 1000:
        return False
    scope = actor.branch_scope()
    if scope is None:
        return True
    ts = target.branch_scope()
    if ts is None:                 # hamma filiallardagi odam — faqat hammani ko'radigan rahbar boshqaradi
        return not target.memberships.filter(is_active=True).exists()
    return bool(ts) and ts <= scope


def check_branches(actor, branch_ids: list[int]) -> list[int]:
    """Filial menejeri boshqaga faqat o'z filiallarini bera oladi (bo'sh ro'yxat → o'z filiallari)."""
    scope = actor.branch_scope()
    if scope is None:
        return list(branch_ids)
    if not branch_ids:
        return sorted(scope)
    bad = set(branch_ids) - scope
    if bad:
        raise HttpError(403, "Faqat o'z filialingiz xodimlariga kirish bera olasiz")
    return list(branch_ids)


def check_perms(actor, perms: list[str]) -> list[str]:
    known = known_perms()
    clean = []
    for p in dict.fromkeys(perms or []):
        if p == "*" or p not in known:
            continue
        if not actor.has_perm_code(p):
            raise HttpError(403, f"«{PERM_LABELS.get(p, p)}» ruxsati sizda yo'q — uni boshqaga bera olmaysiz")
        clean.append(p)
    return clean
