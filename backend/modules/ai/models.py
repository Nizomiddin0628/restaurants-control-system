"""
AI Kotib ma'lumotlari:
  AiChat  — Telegram suhbati holati (bitta so'rov qoidasi: javob kelmaguncha yangi buyruq qabul qilinmaydi);
  AiLog   — har AI so'rovi (kim, nima so'radi, javob, model, token, vaqt) — hisob va nazorat uchun;
  AiDaily — ertalabki hisobot kimga, qaysi kuni yuborilgani (qayta yuborilmasin).
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import TimeStamped, User


class ChatState(models.TextChoices):
    IDLE = "idle", "Bo'sh"
    WAIT = "wait", "Ovozli xabar kutilmoqda"
    CONFIRM = "confirm", "Tasdiq kutilmoqda"
    BUSY = "busy", "Bajarilmoqda"


class AiChat(models.Model):
    chat_id = models.BigIntegerField(unique=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    state = models.CharField(max_length=8, choices=ChatState.choices, default=ChatState.IDLE)
    pending = models.TextField(blank=True, help_text="tasdiq kutayotgan buyruq matni")
    confirm_msg_id = models.BigIntegerField(null=True, blank=True, help_text="«Tasdiqlaysizmi?» xabari — tugmalarni olib tashlash uchun")
    base_url = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.chat_id} · {self.state}"


class AiLog(TimeStamped):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    channel = models.CharField(max_length=10, default="telegram", help_text="telegram | panel | morning")
    kind = models.CharField(max_length=10, default="ask", help_text="ask | voice | report | test")
    question = models.TextField(blank=True)
    answer = models.TextField(blank=True)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=240, blank=True)
    model = models.CharField(max_length=60, blank=True)
    calls = models.PositiveSmallIntegerField(default=0, help_text="AI'ga nechta so'rov ketdi")
    tokens = models.PositiveIntegerField(default=0)
    ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]


class AiDaily(models.Model):
    date = models.DateField(db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    sent_at = models.DateTimeField(default=timezone.now)
    ok = models.BooleanField(default=True)

    class Meta:
        unique_together = [("date", "user")]
