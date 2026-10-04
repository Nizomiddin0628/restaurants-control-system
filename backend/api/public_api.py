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

from api.hq_api import router as hq_router  # noqa: E402

public_api.add_router("/hq", hq_router)


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
        from public.models import SiteOffer
        t = create_tenant(name=data.name.strip(), slug=slug, owner_phone=data.phone, preset=data.preset,
                          owner_name=data.owner_name, plan_code=data.plan, domain=f"{slug}.{host}",
                          trial_days=SiteOffer.get().trial_days or 30)
    except ValueError as e:
        raise HttpError(400, str(e)) from e
    except IntegrityError as e:
        raise HttpError(409, "Bu manzil yoki telefon band") from e
    domain = t.domains.first().domain
    sch = "https" if request.is_secure() else "http"
    return {"ok": True, "tenant": t.slug, "domain": domain, "admin_url": f"{sch}://{domain}/admin/",
            "site_url": f"{sch}://{domain}/", "modules": t.enabled_modules, "platform": settings.PLATFORM_NAME}


# ------------------------------------------------------------------ saytdagi AI maslahatchi (mehmonlar uchun, faqat o'qiydi)
class SalesIn(Schema):
    question: str = ""
    history: list[dict] = []
    image: str = ""            # data:image/jpeg;base64,... (brauzerda kichraytirilgan)


@public_api.post("/sales/ask-stream")
def sales_ask_stream(request, data: SalesIn):
    """Javob yozila boradi (NDJSON): {"t": bo'lak} | {"reset": true} | {"done": true, ok, answer, lead}."""
    import json
    import queue
    import threading

    from django.db import connection
    from django.http import StreamingHttpResponse
    from django_tenants.utils import schema_context

    from public.models import SiteOffer
    from website import sales_ai
    if not SiteOffer.get().ai_chat:
        raise HttpError(403, "AI maslahatchi hozir o'chirilgan")
    q = (data.question or "").strip()[:1500]
    if len(q) < 1 and not data.image:
        raise HttpError(400, "Savolni yozing")
    if len(data.image) > 9_000_000:
        raise HttpError(400, "Rasm juda katta")
    msg = sales_ai.allow(request)
    if msg:
        raise HttpError(429, msg)
    tenant, box, flag = request.tenant, queue.Queue(), {"stop": False}
    hist = [h for h in data.history if isinstance(h, dict)][-10:]

    def work():
        try:
            with schema_context(tenant.schema_name):
                res = sales_ai.ask(request, q, history=hist, image=data.image,
                                   on_text=lambda d: box.put(("t", d)), stop=lambda: flag["stop"])
                box.put(("done", res))
        except Exception as e:  # noqa: BLE001
            box.put(("done", {"ok": False, "error": f"Ichki xato: {type(e).__name__}"}))
        finally:
            connection.close()

    threading.Thread(target=work, daemon=True).start()

    def gen():
        try:
            yield json.dumps({"start": True}) + "\n"
            while True:
                try:
                    kind, val = box.get(timeout=120)
                except queue.Empty:
                    yield json.dumps({"done": True, "ok": False, "error": "Javob kechikdi — qayta urinib ko'ring"}) + "\n"
                    return
                if kind == "t":
                    yield json.dumps({"reset": True} if val is None else {"t": val}, ensure_ascii=False) + "\n"
                else:
                    yield json.dumps({"done": True, **val}, ensure_ascii=False) + "\n"
                    return
        finally:
            flag["stop"] = True

    resp = StreamingHttpResponse(gen(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


class LeadFormIn(Schema):
    name: str = ""
    phone: str
    business: str = ""
    note: str = ""


@public_api.post("/sales/lead")
def sales_lead(request, data: LeadFormIn):
    """Saytdagi «Qo'ng'iroq qiling» formasi."""
    from website import sales_ai
    r = sales_ai._save_lead(request, data.dict(), source="form")
    if not r.get("ok"):
        raise HttpError(400, r.get("error") or "Xato")
    return {"ok": True}
