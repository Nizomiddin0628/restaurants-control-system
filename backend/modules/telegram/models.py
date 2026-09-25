"""
Telegram bot mijozlari va ommaviy xabarlar.

BotUser — botga yozgan har bir odam (mijoz). Telefon ulashsa — buyurtmalari telefon orqali bog'lanadi.
Xodim ham botga yozishi mumkin: telefoni xodimlar ro'yxatida bo'lsa — `staff` bog'lanadi.
"""
from __future__ import annotations

from django.db import models

from core.models import TimeStamped, User


class BotUser(TimeStamped):
    chat_id = models.BigIntegerField(unique=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    full_name = models.CharField(max_length=160, blank=True)
    username = models.CharField(max_length=64, blank=True)
    language = models.CharField(max_length=5, default="uz")
    state = models.JSONField(default=dict, blank=True, help_text="suhbat qadami: {'step': 'book_guests', ...}")
    orders_count = models.PositiveIntegerField(default=0)
    spent_total = models.BigIntegerField(default=0)
    is_blocked = models.BooleanField(default=False, help_text="botni bloklagan — xabar yuborilmaydi")
    last_seen_at = models.DateTimeField(null=True, blank=True)
    staff = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="bot_profiles")

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return self.full_name or self.username or str(self.chat_id)


class Audience(models.TextChoices):
    ALL = "all", "Hamma obunachilar"
    WITH_PHONE = "with_phone", "Telefon ulaganlar"
    BUYERS = "buyers", "Xarid qilganlar"


class BroadcastStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    SENT = "sent", "Yuborildi"


class Broadcast(TimeStamped):
    text = models.TextField()
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.ALL)
    button_text = models.CharField(max_length=40, blank=True)
    button_url = models.URLField(blank=True)
    status = models.CharField(max_length=6, choices=BroadcastStatus.choices, default=BroadcastStatus.DRAFT)
    total = models.PositiveIntegerField(default=0)
    sent = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
