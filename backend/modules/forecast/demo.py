"""Demo: bayramlar (joriy va keyingi yil) + ob-havo. Internet bo'lmasa — namunaviy 7 kunlik prognoz."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import services, weather
from .models import WeatherDay


def seed_demo_forecast(tenant) -> dict:
    n = services.ensure_holidays()
    r = weather.refresh(tenant, force=True)
    demo = False
    if not r["ok"] and not WeatherDay.objects.filter(date__gte=timezone.localdate()).exists():
        today = timezone.localdate()
        # (kun, maks, min, yog'in %, yog'in mm, shamol, WMO kodi) — kuz boshi, Toshkent
        sample = [(0, 27, 14, 5, 0, 9, 0), (1, 29, 15, 0, 0, 7, 1), (2, 24, 13, 75, 6.2, 18, 63), (3, 21, 11, 40, 0.8, 24, 3),
                  (4, 25, 12, 10, 0, 11, 2), (5, 28, 14, 0, 0, 8, 0), (6, 30, 16, 0, 0, 12, 0)]
        weather.save_days([{"date": today + timedelta(days=d), "t_max": mx, "t_min": mn, "precip_prob": pp, "precip_mm": mm,
                            "wind": w, "code": c} for d, mx, mn, pp, mm, w, c in sample], source="demo")
        demo = True
    return {"holidays": n, "weather": "demo" if demo else ("ok" if r["ok"] else "eski")}
