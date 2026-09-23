"""Public API — platforma domenida: ro'yxatdan o'tish (yangi restoran), tariflar, preset'lar."""
from __future__ import annotations

import re

from django.conf import settings
from django.db import IntegrityError
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from core.modules import all_modules
from core.presets import PRESETS
from public.models import Plan, Tenant
from public.services import create_tenant

public_api = NinjaAPI(title="RestoPOS Platform API", version="1.0", urls_namespace="public_api")


class SignupIn(Schema):
    name: str
    slug: str
    phone: str
    preset: str = "fast_food"
    owner_name: str = ""
    plan: str = "start"


@public_api.get("/plans")
def plans(request):
    return [{"code": p.code, "name": p.name, "price_per_branch": p.price_per_branch, "max_branches": p.max_branches,
             "allowed_modules": p.allowed_modules} for p in Plan.objects.filter(is_active=True).order_by("price_per_branch")]


@public_api.get("/presets")
def presets(request):
    return [{"code": k, "name": v["name"], "modules": v["modules"]} for k, v in PRESETS.items()]


@public_api.get("/modules")
def modules(request):
    return [m.to_dict() for m in all_modules()]


@public_api.post("/signup")
def signup(request, data: SignupIn):
    """Yangi restoran: sxema + egasi + preset. Prod'da Celery vazifasiga o'tkaziladi (5–15 soniya oladi)."""
    slug = data.slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,30}", slug):
        raise HttpError(400, "Manzil faqat lotin harf, raqam va '-' dan iborat bo'lsin (3–31 belgi)")
    if Tenant.objects.filter(slug=slug).exists():
        raise HttpError(409, "Bu manzil band")
    try:
        host = request.get_host().split(":")[0]   # localhost / restopos.uz — tenant subdomeni shu asosda
        t = create_tenant(name=data.name.strip(), slug=slug, owner_phone=data.phone, preset=data.preset,
                          owner_name=data.owner_name, plan_code=data.plan, domain=f"{slug}.{host}")
    except ValueError as e:
        raise HttpError(400, str(e)) from e
    except IntegrityError as e:
        raise HttpError(409, "Bu manzil yoki telefon band") from e
    domain = t.domains.first().domain
    return {"ok": True, "tenant": t.slug, "domain": domain, "admin_url": f"http://{domain}/admin/",
            "site_url": f"http://{domain}/", "modules": t.enabled_modules, "platform": settings.PLATFORM_NAME}
