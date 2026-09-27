"""
Tuzilma va standartlar (ops) — restoranning «operatsion tizimi».

Asosiy g'oya: **lavozim hamma narsani bog'laydi**. Lavozim bir marta sozlanadi (maqsad, vazifalar, kimga bo'ysunadi,
qaysi kurs/standart/checklist/KPI) — xodim shu lavozimga qo'yilishi bilan hammasi unga o'zi ulanadi.

  Department        — bo'lim (Boshqaruv, Oshxona, Zal va servis…): rang va ikonka bilan.
  PositionProfile   — hr.Position ga qo'shimcha: bo'lim, kimga bo'ysunadi, daraja, bosh ofis/filial, maqsad,
                      asosiy vazifalar (takrorlanishi bilan), shtat soni, ishga olishdagi standart rol.
"""
from __future__ import annotations

from django.db import models

from core.models import TimeStamped


class Department(TimeStamped):
    name = models.CharField(max_length=80)
    icon = models.CharField(max_length=8, default="🏢")
    color = models.CharField(max_length=9, default="#2F80ED")
    description = models.CharField(max_length=240, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Level(models.IntegerChoices):
    TOP = 1, "Rahbariyat"
    DIRECTOR = 2, "Direktor / bo'lim boshlig'i"
    BRANCH = 3, "Filial rahbari"
    SHIFT = 4, "Smena rahbari"
    STAFF = 5, "Xodim"


class Scope(models.TextChoices):
    HQ = "hq", "Bosh ofis"
    BRANCH = "branch", "Har bir filialda"


class Freq(models.TextChoices):
    DAILY = "daily", "Har kuni"
    WEEKLY = "weekly", "Har hafta"
    MONTHLY = "monthly", "Har oy"
    SHIFT = "shift", "Har smenada"
    NEEDED = "needed", "Kerak bo'lganda"


class PositionProfile(TimeStamped):
    position = models.OneToOneField("hr.Position", on_delete=models.CASCADE, related_name="profile")
    code = models.CharField(max_length=20, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="positions")
    reports_to = models.ForeignKey("hr.Position", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    level = models.PositiveSmallIntegerField(choices=Level.choices, default=Level.STAFF)
    scope = models.CharField(max_length=6, choices=Scope.choices, default=Scope.BRANCH)
    icon = models.CharField(max_length=8, default="👤")
    purpose = models.TextField(blank=True, help_text="lavozim nima uchun bor — bir-ikki gap")
    responsibilities = models.JSONField(default=list, blank=True, help_text='[{"text": "...", "freq": "daily"}]')
    role_code = models.CharField(max_length=40, blank=True, help_text="ishga olishda beriladigan tizim roli")
    headcount = models.PositiveSmallIntegerField(default=0, help_text="rejadagi shtat (filial lavozimi — har filialda)")
    template_key = models.CharField(max_length=30, blank=True, help_text="shablondan yaratilgan bo'lsa — kalit")

    class Meta:
        ordering = ["level", "position__sort_order"]

    def __str__(self) -> str:
        return f"Profil: {self.position}"
