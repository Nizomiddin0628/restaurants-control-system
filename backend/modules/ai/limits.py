"""
AI Kotib chegaralari — platforma (HQ) tarifga qarab beradi, restoran Superadmini xodimlarga taqsimlaydi.

tenant.settings["hq"]["ai"] = {"enabled": true, "daily_limit": 0, "seats": 0}
  enabled     — restoranda AI Kotib umuman ishlaydimi (platforma o'chirsa — hech kimda ishlamaydi)
  daily_limit — kuniga AI so'rovlar soni (0 — cheklovsiz)
  seats       — nechta xodim foydalana oladi (0 — cheklovsiz)
Restoranning o'z sozlamasi (modules.ai.daily_limit) faqat platforma chegarasidan kichik bo'lishi mumkin.
"""
from __future__ import annotations

DEFAULT = {"enabled": True, "daily_limit": 0, "seats": 0}


def platform(tenant) -> dict:
    c = (((getattr(tenant, "settings", None) or {}).get("hq") or {}).get("ai") or {})
    out = dict(DEFAULT)
    out.update({k: c[k] for k in DEFAULT if k in c})
    try:
        out["daily_limit"] = max(0, int(out["daily_limit"] or 0))
        out["seats"] = max(0, int(out["seats"] or 0))
    except (TypeError, ValueError):
        out["daily_limit"], out["seats"] = 0, 0
    out["enabled"] = bool(out["enabled"])
    return out


def set_platform(tenant, *, enabled: bool | None = None, daily_limit: int | None = None, seats: int | None = None) -> dict:
    s = dict(tenant.settings or {})
    hq = dict(s.get("hq") or {})
    c = platform(tenant)
    if enabled is not None:
        c["enabled"] = bool(enabled)
    if daily_limit is not None:
        c["daily_limit"] = max(0, min(int(daily_limit), 100000))
    if seats is not None:
        c["seats"] = max(0, min(int(seats), 1000))
    hq["ai"] = c
    s["hq"] = hq
    tenant.settings = s
    tenant.save(update_fields=["settings"])
    return c


def combine(own: int, cap: int) -> int:
    """Ikki chegaradan kichigi (0 — cheklovsiz)."""
    vals = [v for v in (own, cap) if v and v > 0]
    return min(vals) if vals else 0


def holders():
    """AI Kotibdan foydalana oladigan faol xodimlar (rol yoki shaxsiy ruxsat orqali)."""
    from core.models import User
    users = User.objects.filter(is_active=True, memberships__is_active=True).exclude(memberships__role__code="platform_support").distinct()
    return [u for u in users if u.has_perm_code("ai.use")]


def seats_info(tenant) -> dict:
    p = platform(tenant)
    used = len(holders())
    return {"enabled": p["enabled"], "seats": p["seats"], "used": used,
            "free": (None if p["seats"] == 0 else max(0, p["seats"] - used)), "daily_limit_cap": p["daily_limit"]}


def over_seats(tenant) -> bool:
    p = platform(tenant)
    return bool(p["seats"]) and len(holders()) > p["seats"]
