"""
Hodisa tinglovchilari (modul o'chirilgan bo'lsa chaqirilmaydi).

training.course_completed — xodim kursni tugatdi (boshqa modullar tinglashi mumkin: hr — sertifikat kartaga).
"""
from __future__ import annotations

import logging

from core.events import on

log = logging.getLogger("training")


@on("training.course_completed")
def log_completion(payload: dict) -> None:
    log.info("Kurs tugatildi: %s", payload)
