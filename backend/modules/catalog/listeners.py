"""Hodisa tinglovchilari (bu modul yoqilgan tenantlarda ishlaydi)."""
from core.events import on


@on("tenant.created")
def _on_tenant_created(payload: dict):
    # Yangi tenant uchun bo'sh boshlang'ich kategoriyalar — egasi darhol taom qo'sha oladi
    from .models import Category

    if not Category.objects.exists():
        for i, name in enumerate([("Asosiy taomlar", "Основные блюда", "Mains"), ("Ichimliklar", "Напитки", "Drinks")]):
            Category.objects.create(name={"uz": name[0], "ru": name[1], "en": name[2]}, sort_order=i)
