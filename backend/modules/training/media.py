"""
Havola orqali material: faylni serverga yuklamasdan internetdagi manzilni qo'yish (baza va disk tejaladi).

info(url) havola turini aniqlaydi va brauzer ko'rsata oladigan manzilni qaytaradi:
  youtube → embed + id (ko'rish foizi aniq o'lchanadi)
  video   → to'g'ridan .mp4/.webm (aniq o'lchanadi)
  image   → .jpg/.png
  drive   → Google Drive (rasm, video, PDF — hammasi "preview" oynasida)
  vimeo   → Vimeo pleer
  pdf / link → oddiy havola
"""
from __future__ import annotations

import re

VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "ogg"}
IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}

_YT = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})")
_DRIVE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=\w+&)?id=)([\w-]{20,})")
_VIMEO = re.compile(r"vimeo\.com/(?:video/)?(\d{6,})")


def _ext(url: str) -> str:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return path.lower().rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""


def info(url: str) -> dict:
    u = (url or "").strip()
    if not u:
        return {"kind": "none", "src": "", "embed": ""}
    if m := _YT.search(u):
        return {"kind": "youtube", "src": u, "embed": f"https://www.youtube.com/embed/{m.group(1)}", "id": m.group(1)}
    if m := _DRIVE.search(u):
        fid = m.group(1)
        return {"kind": "drive", "src": u, "embed": f"https://drive.google.com/file/d/{fid}/preview",
                "thumb": f"https://drive.google.com/thumbnail?id={fid}&sz=w1600"}
    if m := _VIMEO.search(u):
        return {"kind": "vimeo", "src": u, "embed": f"https://player.vimeo.com/video/{m.group(1)}"}
    ext = _ext(u)
    if ext in VIDEO_EXT:
        return {"kind": "video", "src": u, "embed": ""}
    if ext in IMAGE_EXT:
        return {"kind": "image", "src": u, "embed": ""}
    if ext == "pdf":
        return {"kind": "pdf", "src": u, "embed": ""}
    return {"kind": "link", "src": u, "embed": ""}


def of(file=None, url: str = "") -> dict | None:
    """Yuklangan fayl yoki havola — qaysi biri bo'lsa, bir xil ko'rinishda (frontend MediaView uchun)."""
    if file:
        e = file.name.lower().rsplit(".", 1)[-1]
        kind = "image" if e in IMAGE_EXT else "video" if e in VIDEO_EXT else "pdf" if e == "pdf" else "link"
        return {"kind": kind, "src": file.url, "embed": ""}
    if url:
        return info(url)
    return None


def image_src(file=None, url: str = "") -> str | None:
    """Rasm sifatida ko'rsatish uchun manzil (Drive havolasi → rasm ko'rinishi)."""
    if file:
        return file.url
    if not url:
        return None
    i = info(url)
    return i.get("thumb") or i["src"]
