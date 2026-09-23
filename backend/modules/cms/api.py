"""CMS API — sayt sozlamalari, bo'limlar, media. /api/v1/cms/..."""
from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.files import UploadedFile

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm

from .models import SECTION_TYPES, MediaAsset, SiteSection, SiteSettings

router = Router(tags=["cms"])


def _guard(request, perm: str):
    require_module(request, "cms")
    require_perm(request, perm)


class SettingsIn(Schema):
    title: str = ""
    tagline: dict = {}
    phone: str = ""
    telegram: str = ""
    instagram: str = ""
    address: str = ""
    languages: list[str] = ["uz", "ru"]
    default_language: str = "uz"
    theme: dict = {}
    seo: dict = {}
    delivery: dict = {}
    custom_css: str = ""
    is_published: bool = True


class SettingsOut(SettingsIn):
    id: int
    logo: Optional[str] = None
    favicon: Optional[str] = None
    updated_at: str

    @staticmethod
    def resolve_logo(obj):
        return obj.logo.url if obj.logo else None

    @staticmethod
    def resolve_favicon(obj):
        return obj.favicon.url if obj.favicon else None

    @staticmethod
    def resolve_updated_at(obj):
        return obj.updated_at.isoformat()


class SectionIn(Schema):
    type: str
    title: dict = {}
    props: dict = {}
    is_enabled: bool = True


class SectionOut(SectionIn):
    id: int
    sort_order: int


class ReorderIn(Schema):
    ids: list[int]


class MediaOut(Schema):
    id: int
    url: str
    kind: str
    folder: str
    title: str
    alt: str
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: int
    created_at: str

    @staticmethod
    def resolve_url(obj):
        return obj.file.url

    @staticmethod
    def resolve_created_at(obj):
        return obj.created_at.isoformat()


# ------------------------------------------------------------------ sozlamalar / tema
@router.get("/settings", response=SettingsOut, auth=auth)
def get_settings(request):
    _guard(request, "cms.view")
    return SiteSettings.get()


@router.put("/settings", response=SettingsOut, auth=auth)
def update_settings(request, data: SettingsIn):
    _guard(request, "cms.edit")
    s = SiteSettings.get()
    before = snapshot(s)
    for k, v in data.dict().items():
        setattr(s, k, v)
    s.save()
    record(request, "update", s, before=before)
    return s


@router.post("/settings/logo", response=SettingsOut, auth=auth)
def upload_logo(request, file: UploadedFile = File(...), kind: str = "logo"):
    _guard(request, "cms.edit")
    s = SiteSettings.get()
    field = s.favicon if kind == "favicon" else s.logo
    field.save(file.name, file, save=True)
    return s


@router.get("/section-types")
def section_types(request):
    return [{"code": code, "label": label} for code, label in SECTION_TYPES]


# ------------------------------------------------------------------ bo'limlar
@router.get("/sections", response=list[SectionOut], auth=auth)
def list_sections(request):
    _guard(request, "cms.view")
    return SiteSection.objects.all()


@router.post("/sections", response=SectionOut, auth=auth)
def create_section(request, data: SectionIn):
    _guard(request, "cms.edit")
    s = SiteSection.objects.create(**data.dict(), sort_order=SiteSection.objects.count())
    record(request, "create", s)
    return s


@router.put("/sections/{sid}", response=SectionOut, auth=auth)
def update_section(request, sid: int, data: SectionIn):
    _guard(request, "cms.edit")
    s = get_object_or_404(SiteSection, pk=sid)
    before = snapshot(s)
    for k, v in data.dict().items():
        setattr(s, k, v)
    s.save()
    record(request, "update", s, before=before)
    return s


@router.delete("/sections/{sid}", auth=auth)
def delete_section(request, sid: int):
    _guard(request, "cms.edit")
    s = get_object_or_404(SiteSection, pk=sid)
    record(request, "delete", s)
    s.delete()
    return {"ok": True}


@router.post("/sections/reorder", auth=auth)
def reorder_sections(request, data: ReorderIn):
    _guard(request, "cms.edit")
    for i, pk in enumerate(data.ids):
        SiteSection.objects.filter(pk=pk).update(sort_order=i)
    record(request, "reorder", model="SiteSection", after={"ids": data.ids})
    return {"ok": True}


# ------------------------------------------------------------------ media
@router.get("/media", response=list[MediaOut], auth=auth)
def list_media(request, folder: Optional[str] = None, kind: Optional[str] = None):
    _guard(request, "cms.view")
    qs = MediaAsset.objects.all()
    if folder:
        qs = qs.filter(folder=folder)
    if kind:
        qs = qs.filter(kind=kind)
    return qs[:200]


@router.post("/media", response=MediaOut, auth=auth)
def upload_media(request, file: UploadedFile = File(...), folder: str = "umumiy", title: str = "", alt: str = ""):
    """Drag-and-drop yuklash. Rasm bo'lsa o'lchamlari o'qiladi (Pillow)."""
    _guard(request, "cms.edit")
    ctype = (file.content_type or "").lower()
    kind = "image" if ctype.startswith("image/") else "video" if ctype.startswith("video/") else "file"
    m = MediaAsset(kind=kind, folder=folder, title=title or file.name, alt=alt, size_bytes=file.size, uploaded_by=str(request.auth))
    m.file.save(file.name, file, save=False)
    if kind == "image":
        try:
            from PIL import Image
            with Image.open(m.file) as im:
                m.width, m.height = im.size
        except Exception:
            pass
    m.save()
    record(request, "upload", m, after={"file": m.file.name, "folder": folder})
    return m


@router.delete("/media/{mid}", auth=auth)
def delete_media(request, mid: int):
    _guard(request, "cms.edit")
    m = get_object_or_404(MediaAsset, pk=mid)
    record(request, "delete", m)
    m.file.delete(save=False)
    m.delete()
    return {"ok": True}


# ------------------------------------------------------------------ ochiq: sayt konfiguratsiyasi (Mini App / mobil ilova ham shuni o'qiydi)
@router.get("/public")
def public_site(request):
    require_module(request, "cms")
    s = SiteSettings.get()
    return {
        "title": s.title, "tagline": s.tagline, "logo": s.logo.url if s.logo else None, "phone": s.phone,
        "telegram": s.telegram, "instagram": s.instagram, "address": s.address, "languages": s.languages,
        "default_language": s.default_language, "theme": s.theme, "delivery": s.delivery,
        "sections": [{"type": x.type, "title": x.title, "props": x.props} for x in SiteSection.objects.filter(is_enabled=True)],
    }
