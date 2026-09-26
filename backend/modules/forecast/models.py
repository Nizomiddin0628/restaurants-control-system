"""
Bayram va ob-havo prognozi.

  Holiday     — bayram / muhim kun: sana, necha kun davom etadi, kutilayotgan savdo o'sishi (%),
                necha kun oldin ogohlantirish. O'zbekiston bayramlari har yil uchun avtomatik qo'shiladi
                (services.ensure_holidays), egasi tahrirlaydi yoki o'zinikini qo'shadi.
  WeatherDay  — kunlik ob-havo prognozi (Open-Meteo, kalit shart emas), 3 soatda bir yangilanadi.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models

from core.models import TimeStamped


def empty_i18n() -> dict:
    return {"uz": "", "ru": "", "en": ""}


class HolidayKind(models.TextChoices):
    OFFICIAL = "official", "Davlat bayrami"
    RELIGIOUS = "religious", "Diniy bayram"
    COMMERCIAL = "commercial", "Tijoriy kun"
    SEASON = "season", "Mavsum"
    LOCAL = "local", "O'zimizniki"


class Holiday(TimeStamped):
    code = models.CharField(max_length=40, blank=True, db_index=True, help_text="tizim bayrami kodi (navruz, hayit…); qo'lda qo'shilganda bo'sh")
    name = models.JSONField(default=empty_i18n)
    date = models.DateField(db_index=True)
    days = models.PositiveSmallIntegerField(default=1, help_text="necha kun davom etadi")
    kind = models.CharField(max_length=12, choices=HolidayKind.choices, default=HolidayKind.OFFICIAL)
    uplift_percent = models.IntegerField(default=20, help_text="kutilayotgan savdo o'zgarishi, % (manfiy ham bo'lishi mumkin)")
    prep_days = models.PositiveSmallIntegerField(default=7, help_text="necha kun oldin ogohlantirish")
    is_approx = models.BooleanField(default=False, help_text="sana taxminiy (hayitlar — Diniy idora e'lonidan keyin aniqlanadi)")
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=240, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True, help_text="tayyorgarlik vazifasi ochilgan vaqt")

    class Meta:
        ordering = ["date", "id"]

    def __str__(self) -> str:
        return (self.name or {}).get("uz") or self.code or f"#{self.pk}"

    @property
    def end(self):
        return self.date + timedelta(days=max(1, self.days) - 1)

    def covers(self, d) -> bool:
        return self.date <= d <= self.end


class WeatherDay(models.Model):
    date = models.DateField(unique=True)
    t_max = models.FloatField(default=0)
    t_min = models.FloatField(default=0)
    precip_mm = models.FloatField(default=0)
    precip_prob = models.PositiveSmallIntegerField(default=0)
    wind = models.FloatField(default=0, help_text="km/soat")
    code = models.PositiveSmallIntegerField(default=0, help_text="WMO ob-havo kodi")
    source = models.CharField(max_length=20, default="open-meteo")
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]
