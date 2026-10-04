"""Restoranga xos funksiyalar — bitta kod, har restoran uchun alohida yoqiladi (alohida «application» ochilmaydi).

Qatlamlar (pastdan yuqoriga):
  1. Tarif (Plan.allowed_modules)        — qaysi modullar ruxsat etilgan
  2. Modullar (Tenant.enabled_modules)   — restoranda nima yoqilgan
  3. Sozlamalar (Tenant.settings)        — restoranning o'z sozlamalari (til, valyuta, soliq, bot…)
  4. Chegaralar (Tenant.limits)          — shartnoma bo'yicha filial/foydalanuvchi soni
  5. Funksiya bayroqlari (FeatureFlag)   — yangi yoki maxsus imkoniyat faqat tanlangan restoranlarda

Kodda ishlatish:
    from core.features import flag_on
    if flag_on(request.tenant, "kds_v2"):
        ...yangi xatti-harakat...
"""
from __future__ import annotations

from django.core.cache import cache


def _flags() -> list[tuple[str, bool, list]]:
    data = cache.get("hq:flags")
    if data is None:
        from public.models import FeatureFlag
        data = [(f.code, f.enabled_all, list(f.tenants or [])) for f in FeatureFlag.objects.all()]
        cache.set("hq:flags", data, 60)
    return data


def flag_on(tenant, code: str) -> bool:
    """Bayroq shu restoran uchun yoqilganmi (hammaga yoki faqat unga)."""
    if tenant is None:
        return False
    for c, all_, ids in _flags():
        if c == code:
            return all_ or tenant.pk in ids
    return False


def flags_for(tenant) -> list[str]:
    return [c for c, all_, ids in _flags() if all_ or (tenant is not None and tenant.pk in ids)]


def reset_cache() -> None:
    cache.delete("hq:flags")
