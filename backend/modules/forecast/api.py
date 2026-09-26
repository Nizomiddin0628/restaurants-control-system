"""Bayram va ob-havo prognozi API — /api/v1/forecast/..."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm

from . import services, weather
from .models import Holiday, HolidayKind

router = Router(tags=["forecast"])


def _guard(request, perm: str):
    require_module(request, "forecast")
    require_perm(request, perm)


class I18n(Schema):
    uz: str = ""
    ru: str = ""
    en: str = ""


class HolidayIn(Schema):
    name: I18n
    date: date
    days: int = 1
    kind: str = HolidayKind.LOCAL
    uplift_percent: int = 20
    prep_days: int = 7
    is_approx: bool = False
    is_active: bool = True
    note: str = ""


def _validate(data: HolidayIn):
    if not data.name.uz.strip():
        raise HttpError(400, "Bayram nomini kiriting.")
    if not 1 <= data.days <= 40:
        raise HttpError(400, "Davomiylik 1 dan 40 kungacha bo'lishi kerak.")
    if not -90 <= data.uplift_percent <= 300:
        raise HttpError(400, "Savdo o'zgarishi −90% dan +300% gacha bo'lishi kerak.")
    if not 0 <= data.prep_days <= 60:
        raise HttpError(400, "Ogohlantirish 0–60 kun oldin bo'lishi mumkin.")
    if data.kind not in HolidayKind.values:
        raise HttpError(400, "Noma'lum bayram turi.")


def _weather(request) -> dict:
    t = request.tenant
    r = weather.refresh(t)
    days = [weather.day_out(w, t) for w in weather.forecast_days(t)]
    return {"location": weather.location(t), "days": days, "ok": r["ok"], "error": r.get("error"),
            "demo": bool(days) and all(d["source"] != "open-meteo" for d in days)}


# ------------------------------------------------------------------ umumiy ko'rinish
@router.get("/overview", auth=auth)
def overview(request):
    _guard(request, "forecast.view")
    services.ensure_holidays()
    t = request.tenant
    return {
        "alerts": services.alerts(t),
        "upcoming": [services.holiday_out(h, with_history=True) for h in services.upcoming(limit=6)],
        "weather": _weather(request),
        "kinds": [{"code": k.value, "label": k.label} for k in HolidayKind],
        "lead_days": int(weather.setting(t, "purchase_lead_days", 2)),
    }


# ------------------------------------------------------------------ bayramlar
@router.get("/holidays", auth=auth)
def list_holidays(request, year: Optional[int] = None):
    _guard(request, "forecast.view")
    services.ensure_holidays()
    y = year or timezone.localdate().year
    services.ensure_year(y)
    return [services.holiday_out(h, with_history=True) for h in Holiday.objects.filter(date__year=y)]


@router.post("/holidays", auth=auth)
def create_holiday(request, data: HolidayIn):
    _guard(request, "forecast.edit")
    _validate(data)
    d = data.dict()
    d["name"] = data.name.dict()
    h = Holiday.objects.create(**d)
    record(request, "create", h)
    return services.holiday_out(h, with_history=True)


@router.put("/holidays/{int:hid}", auth=auth)
def update_holiday(request, hid: int, data: HolidayIn):
    _guard(request, "forecast.edit")
    _validate(data)
    h = get_object_or_404(Holiday, pk=hid)
    before = snapshot(h)
    moved = h.date != data.date
    for k, v in data.dict().items():
        setattr(h, k, v.dict() if k == "name" else v)
    if moved:
        h.notified_at = None       # sana o'zgardi — ogohlantirish qaytadan
    h.save()
    record(request, "update", h, before=before)
    return services.holiday_out(h, with_history=True)


@router.delete("/holidays/{int:hid}", auth=auth)
def delete_holiday(request, hid: int):
    """Tizim bayrami o'chirilmaydi — o'chirib qo'yiladi (keyingi yil yana chiqadi); o'zimiznikisi o'chadi."""
    _guard(request, "forecast.edit")
    h = get_object_or_404(Holiday, pk=hid)
    record(request, "delete", h)
    if h.code:
        h.is_active = False
        h.save(update_fields=["is_active", "updated_at"])
        return {"ok": True, "disabled": True}
    h.delete()
    return {"ok": True, "disabled": False}


@router.post("/holidays/{int:hid}/learn", auth=auth)
def learn(request, hid: int):
    """O'tgan yilgi haqiqiy savdo o'sishini shu bayramga yozish."""
    _guard(request, "forecast.edit")
    h = get_object_or_404(Holiday, pk=hid)
    prev = services.previous_of(h)
    pct = services.history_uplift(prev) if prev else None
    if pct is None:
        raise HttpError(400, "O'tgan yilgi savdo ma'lumoti yo'q — foizni qo'lda kiriting.")
    h.uplift_percent = max(-90, min(300, pct))
    h.save(update_fields=["uplift_percent", "updated_at"])
    record(request, "update", h, after={"uplift_percent": h.uplift_percent})
    return services.holiday_out(h, with_history=True)


# ------------------------------------------------------------------ xarid rejasi
@router.get("/plan", auth=auth)
def purchase_plan(request, holiday_id: Optional[int] = None, days: int = 7):
    _guard(request, "forecast.view")
    services.ensure_holidays()
    weather.refresh(request.tenant)
    if holiday_id:
        h = get_object_or_404(Holiday, pk=holiday_id)
        if h.end < timezone.localdate():
            raise HttpError(400, "Bu bayram o'tib ketgan.")
        return services.plan(request.tenant, holiday=h)
    days = max(1, min(30, days))
    today = timezone.localdate()
    return services.plan(request.tenant, start=today, end=today + timedelta(days=days - 1))


# ------------------------------------------------------------------ ob-havo
@router.get("/weather", auth=auth)
def get_weather(request):
    _guard(request, "forecast.view")
    return _weather(request)


@router.post("/weather/refresh", auth=auth)
def refresh_weather(request):
    _guard(request, "forecast.edit")
    r = weather.refresh(request.tenant, force=True)
    if not r["ok"]:
        raise HttpError(503, r["error"])
    return _weather(request)
