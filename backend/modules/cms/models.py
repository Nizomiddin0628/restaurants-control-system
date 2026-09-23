"""
CMS moduli: restoran saytining temasi, sozlamalari, bo'limlari va media kutubxonasi.
Sayt = ma'lumot (tema + bo'limlar JSON), kod emas — egasi panelda o'zgartiradi, deploy kerak emas.
"""
from __future__ import annotations

from django.db import models
from simple_history.models import HistoricalRecords

from core.models import TimeStamped

SECTION_TYPES = [
    ("hero", "Bosh bo'lim (hero)"),
    ("menu", "Taomnoma"),
    ("bonus", "Bonus tizimi"),
    ("branches", "Filiallar"),
    ("delivery", "Yetkazib berish"),
    ("gallery", "Galereya"),
    ("text", "Matn / e'lon"),
    ("contact", "Aloqa"),
]


def default_theme() -> dict:
    return {"primary": "#D9482B", "accent": "#0F6E63", "bg": "#FFF6EA", "ink": "#1C1512", "font": "Manrope",
            "radius": 16, "dark_default": False}


class SiteSettings(TimeStamped):
    """Bitta yozuv (singleton) — sayt sarlavhasi, aloqa, tillar, tema."""

    title = models.CharField(max_length=120, default="")
    tagline = models.JSONField(default=dict, blank=True)          # {"uz": "...", "ru": "..."}
    logo = models.ImageField(upload_to="site/", blank=True)
    favicon = models.ImageField(upload_to="site/", blank=True)
    phone = models.CharField(max_length=20, blank=True)
    telegram = models.CharField(max_length=64, blank=True, help_text="@bot yoki t.me havola")
    instagram = models.CharField(max_length=64, blank=True)
    address = models.CharField(max_length=255, blank=True)
    languages = models.JSONField(default=list)                   # ["uz", "ru"]
    default_language = models.CharField(max_length=5, default="uz")
    theme = models.JSONField(default=default_theme)
    seo = models.JSONField(default=dict, blank=True)              # {"title": ..., "description": ...}
    delivery = models.JSONField(default=dict, blank=True)        # {"free_from": 80000, "fee": 9000, "eta_min": 25, "eta_max": 35}
    custom_css = models.TextField(blank=True)
    is_published = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Sayt sozlamalari"

    @classmethod
    def get(cls) -> "SiteSettings":
        obj = cls.objects.first()
        return obj or cls.objects.create(title="")

    def __str__(self) -> str:
        return self.title or "Sayt"


class SiteSection(TimeStamped):
    """Sayt bo'limi: turi, tartibi, yoqilgan/o'chirilgan, props (matn, rasm, ranglar)."""

    type = models.CharField(max_length=20, choices=SECTION_TYPES)
    title = models.JSONField(default=dict, blank=True)
    props = models.JSONField(default=dict, blank=True)
    is_enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    history = HistoricalRecords()

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.get_type_display()} #{self.sort_order}"


class MediaAsset(TimeStamped):
    """Media kutubxonasi: rasm/video/PDF; papka bo'yicha; keyin S3/MinIO."""

    KIND = [("image", "Rasm"), ("video", "Video"), ("file", "Fayl")]
    file = models.FileField(upload_to="media/%Y/%m/")
    kind = models.CharField(max_length=10, choices=KIND, default="image")
    folder = models.CharField(max_length=60, default="umumiy", db_index=True)
    title = models.CharField(max_length=120, blank=True)
    alt = models.CharField(max_length=160, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title or self.file.name
