"""AI Kotib: ertalabki hisobot kimga va qachon yuboriladi."""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.utils import timezone

from core.models import User

from . import agent, gemini, tg
from .models import AiDaily

log = logging.getLogger("ai")
WINDOW = timedelta(hours=3)        # belgilangan vaqtdan 3 soat ichida yuboriladi (server kech yoqilsa ham), kechqurun emas


def morning_time(tenant) -> time:
    raw = str(gemini.conf(tenant).get("morning_time") or "08:30")
    try:
        h, m = raw.split(":")[:2]
        return time(int(h) % 24, int(m) % 60)
    except (ValueError, TypeError):
        return time(8, 30)


def morning_on(tenant) -> bool:
    return bool(gemini.conf(tenant).get("morning_enabled", True))


def recipients(tenant) -> list[User]:
    """Telegram'ga ulangan va «AI Kotib» ruxsati bor faol xodimlar (egasi, menejerlar)."""
    users = User.objects.filter(is_active=True, telegram_id__isnull=False, memberships__is_active=True).distinct()
    return [u for u in users if tg.eligible(tenant, u)]


def due_now(tenant, now: datetime | None = None) -> bool:
    now = now or timezone.localtime()
    start = timezone.make_aware(datetime.combine(now.date(), morning_time(tenant)), timezone.get_current_timezone())
    return start <= now < start + WINDOW


def send_morning(tenant, *, force: bool = False, now: datetime | None = None, users: list[User] | None = None) -> dict:
    """Ertalabki hisobotni yuborish. force=False — faqat vaqti kelgan va bugun hali olmaganlarga."""
    now = now or timezone.localtime()
    out = {"sent": 0, "failed": 0, "skipped": 0}
    if not force and not (morning_on(tenant) and due_now(tenant, now)):
        return out
    if not tg._tok(tenant):
        out["skipped"] = -1                                   # bot ulanmagan
        return out
    today = now.date()
    cache: dict[tuple, list[str]] = {}
    for u in (users if users is not None else recipients(tenant)):
        if not force and AiDaily.objects.filter(date=today, user=u).exists():
            out["skipped"] += 1
            continue
        from .report import scope_of
        key = tuple(scope_of(u) or [])
        try:
            if key not in cache:                               # bir xil filial doirasidagilarga — bitta hisobot (AI so'rovini tejash)
                cache[key], _ = agent.morning(tenant, u)
            ok = all(tg.send(tenant, u.telegram_id, p) is not None for p in cache[key])
        except Exception:
            log.exception("ertalabki hisobot: %s", u.pk)
            ok = False
        AiDaily.objects.update_or_create(date=today, user=u, defaults={"ok": ok, "sent_at": timezone.now()})
        out["sent" if ok else "failed"] += 1
    return out
