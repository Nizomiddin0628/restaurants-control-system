"""
Profil rasmi: yuklangan rasm markazdan kvadrat qilib qirqiladi va 400×400 JPEG'ga kichraytiriladi.
Natija ~30–60 KB — telefondan 5 MB rasm yuklansa ham disk to'lmaydi.
"""
from __future__ import annotations

import io
import uuid

from django.core.files.base import ContentFile
from ninja.errors import HttpError

ALLOWED = {"jpg", "jpeg", "png", "webp", "heic", "gif"}
MAX_MB = 10
SIZE = 400


def process(upload) -> ContentFile:
    ext = (upload.name or "").lower().rsplit(".", 1)[-1]
    if ext not in ALLOWED:
        raise HttpError(400, "Rasm fayli tanlang (JPG, PNG yoki WEBP).")
    if upload.size and upload.size > MAX_MB * 1024 * 1024:
        raise HttpError(400, f"Rasm juda katta — {MAX_MB} MB dan oshmasin.")
    try:
        from PIL import Image, ImageOps
        img = Image.open(upload)
        img = ImageOps.exif_transpose(img)          # telefon rasmi yonboshlab qolmasin
        img = img.convert("RGB")
        w, h = img.size
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((SIZE, SIZE), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
    except Exception as e:  # buzilgan fayl yoki qo'llab-quvvatlanmagan format (masalan HEIC)
        raise HttpError(400, "Rasmni o'qib bo'lmadi — boshqa rasm tanlang (JPG yoki PNG).") from e
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4().hex[:12]}.jpg")


def set_avatar(user, upload) -> None:
    old = user.avatar.name if user.avatar else None
    content = process(upload)
    user.avatar.save(content.name, content, save=True)
    if old:
        user.avatar.storage.delete(old)


def clear_avatar(user) -> None:
    if user.avatar:
        user.avatar.storage.delete(user.avatar.name)
        user.avatar = ""
        user.save(update_fields=["avatar"])
