"""
Hodisa tinglovchilari (modul o'chirilgan bo'lsa chaqirilmaydi).

training.course_completed — xodim kursni tugatdi (boshqa modullar tinglashi mumkin: hr — sertifikat kartaga).
"""
from __future__ import annotations

import logging

from core.events import on

log = logging.getLogger("training")


@on("training.course_completed")
def completed(payload: dict) -> None:
    """Kurs tugatildi → mas'ulga xabar (natija bilan)."""
    from django.db import connection

    from core.models import User

    from . import services
    from .models import Course, QuizAttempt
    log.info("Kurs tugatildi: %s", payload)
    c = Course.objects.select_related("responsible").filter(pk=payload.get("course_id")).first()
    u = User.objects.filter(pk=payload.get("user_id")).first()
    if c is None or u is None or not c.responsible_id or c.responsible_id == u.pk:
        return
    best = QuizAttempt.objects.filter(quiz__course=c, user=u, finished_at__isnull=False).order_by("-score").first()
    services.notify(getattr(connection, "tenant", None), c.responsible,
                    f"🎓 <b>{u.full_name or u.phone}</b> kursni tugatdi: <b>{c.title}</b>" + (f" · test {best.score}%" if best else ""))


@on("hr.employee_created")
@on("hr.position_changed")
def assign_by_position(payload: dict) -> None:
    """Xodim lavozimga qo'yildi → shu lavozimga biriktirilgan kurs va topshiriqlar unga o'zi beriladi."""
    from django.db import connection

    from core.models import User

    from . import services
    u = User.objects.filter(pk=payload.get("user_id")).first()
    if u is not None:
        services.sync_user(u, getattr(connection, "tenant", None))
