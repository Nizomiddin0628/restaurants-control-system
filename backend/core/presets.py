"""
Preset'lar — yangi restoran 15 daqiqada ishga tushishi uchun tayyor konfiguratsiyalar.
Preset = yoqilgan modullar + sayt bo'limlari + tema + boshlang'ich sozlamalar. Kod emas, ma'lumot.
"""

DEFAULT_SETTINGS = {
    "languages": ["uz", "ru"],
    "default_language": "uz",
    "currency": "UZS",
    "timezone": "Asia/Tashkent",
    "tax_mode": "turnover",   # turnover | vat6 | vat12
    "receipt_footer": "Rahmat! Yana kutamiz.",
}

BASE_SECTIONS = [
    {"type": "hero", "props": {"title": "Issiq, tez va har buyurtmadan bonus", "subtitle": "Buyurtma bering — 25–35 daqiqada yetkazamiz", "cta": "Buyurtma berish"}},
    {"type": "menu", "props": {"title": "Taomnoma", "show_categories": True}},
    {"type": "bonus", "props": {"title": "Bonus tizimi", "percent": 5, "gift_visit": 4}},
    {"type": "branches", "props": {"title": "Filiallar"}},
    {"type": "delivery", "props": {"title": "Buyurtma qanday keladi"}},
    {"type": "contact", "props": {"title": "Aloqa"}},
]

PRESETS = {
    "fast_food": {
        "name": "Fast-food",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "telegram", "crm"],
        "sections": BASE_SECTIONS,
        "theme": {"primary": "#D9482B", "accent": "#0F6E63", "bg": "#FFF6EA", "ink": "#1C1512", "font": "Manrope", "dark_default": False},
    },
    "cafe": {
        "name": "Kafe",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "tables", "reservations", "telegram", "crm"],
        "sections": BASE_SECTIONS,
        "theme": {"primary": "#8A5A12", "accent": "#0F6E63", "bg": "#FAF6EF", "ink": "#1C1512", "font": "Manrope", "dark_default": False},
    },
    "restaurant": {
        "name": "Restoran",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "tables", "reservations", "telegram", "crm"],
        "sections": BASE_SECTIONS,
        "theme": {"primary": "#1C1512", "accent": "#B8321B", "bg": "#FFFFFF", "ink": "#1C1512", "font": "Manrope", "dark_default": False},
    },
    "cloud_kitchen": {
        "name": "Cloud kitchen",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "delivery", "telegram", "crm"],
        "sections": [s for s in BASE_SECTIONS if s["type"] != "branches"],
        "theme": {"primary": "#0F6E63", "accent": "#D9482B", "bg": "#F4F3EE", "ink": "#17171A", "font": "Manrope", "dark_default": True},
    },
}
