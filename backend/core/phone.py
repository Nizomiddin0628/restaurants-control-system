"""O'zbekiston telefon raqamini tekshirish: +998 va 9 raqam, operator/hudud kodi to'g'ri bo'lishi kerak."""
from __future__ import annotations

import re

# mobil operatorlar (Beeline, Ucell, Mobiuz, Uzmobile, Humans, Perfectum) va shahar/hudud kodlari
CODES = {"20", "33", "50", "55", "77", "88", "90", "91", "93", "94", "95", "97", "98", "99",
         "61", "62", "65", "66", "67", "69", "70", "71", "72", "73", "74", "75", "76", "78", "79"}


def normalize_uz(raw: str) -> str:
    """'+998 90 123-45-67', '901234567', '8 90 123 45 67' → '+998901234567'. Noto'g'ri bo'lsa — ValueError (o'zbekcha matn)."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("998"):
        d = d[3:]
    elif len(d) == 10 and d.startswith("8"):
        d = d[1:]
    if len(d) != 9:
        raise ValueError("Telefon raqam noto'g'ri: +998 dan keyin 9 ta raqam bo'lishi kerak (masalan +998 90 123 45 67)")
    if d[:2] not in CODES:
        raise ValueError(f"«{d[:2]}» — O'zbekiston operator kodi emas. Raqamni tekshiring (masalan 90, 91, 93, 94, 97, 99, 33, 88, 77, 50)")
    return "+998" + d
