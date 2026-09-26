"""
Ob-havo — Open-Meteo (bepul, kalit shart emas). 7 kunlik prognoz bazaga yoziladi va 3 soatda bir yangilanadi
(«lazy»: sahifa ochilganda). Internet bo'lmasa — oxirgi saqlangan prognoz ko'rsatiladi, xato chiqmaydi.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, timedelta

from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from .models import WeatherDay

log = logging.getLogger("forecast.weather")

CITIES = {
    "Toshkent": (41.3111, 69.2797), "Samarqand": (39.6542, 66.9597), "Buxoro": (39.7747, 64.4286),
    "Andijon": (40.7821, 72.3442), "Farg'ona": (40.3864, 71.7864), "Namangan": (40.9983, 71.6726),
    "Qarshi": (38.8606, 65.7891), "Nukus": (42.4600, 59.6166), "Urganch": (41.5500, 60.6333),
    "Jizzax": (40.1158, 67.8422), "Navoiy": (40.0844, 65.3792), "Termiz": (37.2242, 67.2783),
    "Guliston": (40.4897, 68.7842),
}
API_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
           "precipitation_probability_max,wind_speed_10m_max&timezone=Asia%2FTashkent&forecast_days=7")
REFRESH_HOURS = 3
FAIL_TEXT = "Ob-havo serveriga ulanib bo'lmadi — oxirgi saqlangan prognoz ko'rsatilmoqda."


def setting(tenant, key, default):
    try:
        return (tenant.settings.get("modules", {}).get("forecast", {}) or {}).get(key, default)
    except Exception:
        return default


def location(tenant) -> dict:
    """Filial koordinatasi bo'lsa — o'sha, bo'lmasa sozlamadagi shahar (standart: Toshkent)."""
    from core.models import Branch
    b = Branch.objects.filter(deleted_at__isnull=True, is_active=True, lat__isnull=False, lng__isnull=False).first()
    if b:
        return {"name": b.name, "lat": float(b.lat), "lng": float(b.lng)}
    city = setting(tenant, "city", "Toshkent")
    lat, lng = CITIES.get(city, CITIES["Toshkent"])
    return {"name": city if city in CITIES else "Toshkent", "lat": lat, "lng": lng}


def _http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=6) as r:
        return json.loads(r.read().decode())


def fetch(lat: float, lng: float) -> list[dict]:
    data = _http_get(API_URL.format(lat=lat, lng=lng))["daily"]
    out = []
    for i, d in enumerate(data["time"]):
        def v(key, _i=i):
            arr = data.get(key) or []
            return arr[_i] if _i < len(arr) and arr[_i] is not None else 0
        out.append({"date": date.fromisoformat(d), "t_max": float(v("temperature_2m_max")), "t_min": float(v("temperature_2m_min")),
                    "precip_mm": float(v("precipitation_sum")), "precip_prob": int(v("precipitation_probability_max")),
                    "wind": float(v("wind_speed_10m_max")), "code": int(v("weather_code"))})
    return out


def save_days(rows: list[dict], source: str = "open-meteo") -> int:
    for r in rows:
        WeatherDay.objects.update_or_create(date=r["date"], defaults={**{k: v for k, v in r.items() if k != "date"}, "source": source})
    return len(rows)


def refresh(tenant, force: bool = False) -> dict:
    """Prognoz eskirgan bo'lsa (3 soat) — yangilaydi. Natija: {"ok", "updated", "error"}."""
    today = timezone.localdate()
    last = WeatherDay.objects.filter(date__gte=today, source="open-meteo").order_by("-fetched_at").first()
    fresh = last and last.fetched_at > timezone.now() - timedelta(hours=REFRESH_HOURS)
    if fresh and not force:
        return {"ok": True, "updated": False}
    fail_key = f"forecast_wx_fail:{connection.schema_name}"
    if not force and cache.get(fail_key):          # yaqinda ulanib bo'lmagan — sahifani 6 soniya kutdirmaymiz
        return {"ok": False, "updated": False, "error": FAIL_TEXT}
    loc = location(tenant)
    try:
        n = save_days(fetch(loc["lat"], loc["lng"]))
        WeatherDay.objects.filter(date__lt=today - timedelta(days=30)).delete()
        cache.delete(fail_key)
        return {"ok": True, "updated": bool(n)}
    except Exception as e:  # tarmoq yo'q — eski prognoz qoladi
        log.warning("Ob-havoni olib bo'lmadi: %s", e)
        cache.set(fail_key, 1, 30 * 60)
        return {"ok": False, "updated": False, "error": FAIL_TEXT}


# ------------------------------------------------------------------ talqin
WMO = [
    ((0,), "☀️", "Ochiq"), ((1, 2), "🌤️", "Qisman bulutli"), ((3,), "☁️", "Bulutli"), ((45, 48), "🌫️", "Tuman"),
    ((51, 53, 55, 56, 57), "🌦️", "Mayda yomg'ir"), ((61, 63, 65, 66, 67), "🌧️", "Yomg'ir"), ((71, 73, 75, 77), "❄️", "Qor"),
    ((80, 81, 82), "🌧️", "Jala"), ((85, 86), "🌨️", "Qor yog'adi"), ((95, 96, 99), "⛈️", "Momaqaldiroq"),
]


def describe(code: int) -> tuple[str, str]:
    for codes, icon, label in WMO:
        if code in codes:
            return icon, label
    return "🌡️", "—"


def is_rainy(w: WeatherDay, tenant) -> bool:
    return w.precip_prob >= int(setting(tenant, "rain_probability", 60)) or w.precip_mm >= 5 or w.code in (61, 63, 65, 80, 81, 82, 95, 96, 99)


def is_snowy(w: WeatherDay) -> bool:
    return w.code in (71, 73, 75, 77, 85, 86)


def factor(w: WeatherDay | None, tenant) -> float:
    """Ob-havoning savdoga ta'siri (ko'paytuvchi). Sozlamada egasi foizlarni o'zgartiradi."""
    if w is None:
        return 1.0
    pct = 0
    if is_rainy(w, tenant) or is_snowy(w):
        pct += int(setting(tenant, "rain_effect", -10))
    if w.t_max >= int(setting(tenant, "hot_threshold", 35)):
        pct += int(setting(tenant, "hot_effect", -5))
    if w.t_max <= int(setting(tenant, "cold_threshold", 0)):
        pct += int(setting(tenant, "cold_effect", 0))
    return max(0.3, 1 + pct / 100)


def hints(w: WeatherDay, tenant) -> list[dict]:
    """Oddiy tilda maslahat: nima ko'proq/kamroq sotiladi, nimaga tayyorlanish kerak."""
    out = []
    hot, cold = int(setting(tenant, "hot_threshold", 35)), int(setting(tenant, "cold_threshold", 0))
    if w.t_max >= hot:
        out.append({"tone": "warn", "text": f"Issiq {round(w.t_max)}° — sovuq ichimlik, muz, salat va muzqaymoq zaxirasini oshiring. Issiq taomlar kamroq ketadi."})
    if w.t_max <= cold:
        out.append({"tone": "info", "text": f"Sovuq {round(w.t_max)}° — sho'rva, choy va issiq taomlar ko'proq ketadi."})
    if is_snowy(w):
        out.append({"tone": "warn", "text": "Qor — yo'llar sirpanchiq, ta'minotchi kechikishi mumkin. Xaridni bir kun oldin qiling."})
    elif is_rainy(w, tenant):
        out.append({"tone": "info", "text": f"Yomg'ir ({w.precip_prob}%) — zalga kamroq odam keladi, yetkazib berish va olib ketish ko'payadi."})
    if w.wind >= 40:
        out.append({"tone": "warn", "text": f"Kuchli shamol ({round(w.wind)} km/soat) — ochiq ayvon va terrasani yoping."})
    return out


def day_out(w: WeatherDay, tenant) -> dict:
    icon, label = describe(w.code)
    f = factor(w, tenant)
    return {"date": w.date.isoformat(), "t_max": round(w.t_max), "t_min": round(w.t_min), "precip_prob": w.precip_prob,
            "precip_mm": round(w.precip_mm, 1), "wind": round(w.wind), "code": w.code, "icon": icon, "label": label,
            "effect": round((f - 1) * 100), "hints": hints(w, tenant), "source": w.source}


def forecast_days(tenant, days: int = 7) -> list[WeatherDay]:
    today = timezone.localdate()
    return list(WeatherDay.objects.filter(date__gte=today, date__lt=today + timedelta(days=days)))
