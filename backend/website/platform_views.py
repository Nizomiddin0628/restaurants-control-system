"""Platforma sayti (public sxema): taklif va narxlar (HQ → «Sayt va narxlar»), bepul sinov, ro'yxatdan o'tish, AI maslahatchi."""
import json

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from core.presets import PRESETS
from public.models import Plan, SiteOffer

from . import i18n


def _ctx(lang: str = "uz", **kw):
    lang = i18n.norm(lang)
    offer = SiteOffer.get()
    o = offer.localized(lang)
    t = i18n.strings(lang, days=offer.trial_days, platform=settings.PLATFORM_NAME, cur=offer.currency, base=offer.base_price, ai=offer.ai_price,
                     setup_lower=(o["setup_note"][:1].lower() + o["setup_note"][1:]) if o["setup_note"] else "")
    return {"offer": offer, "o": o, "t": t, "lang": lang, "other_lang": "uz" if lang == "ru" else "ru", "lang_prefix": "/ru" if lang == "ru" else "",
            "js_i18n": json.dumps({"lang": lang, "s": i18n.js_strings(lang)}, ensure_ascii=False),
            "platform": settings.PLATFORM_NAME, "domain": settings.PLATFORM_DOMAIN, **kw}


def index(request, lang: str = "uz"):
    return render(request, "platform/index.html", _ctx(lang, plans=Plan.objects.filter(is_active=True).order_by("price_per_branch"), presets=PRESETS))


def signup(request, lang: str = "uz"):
    return render(request, "platform/signup.html", _ctx(lang, presets=PRESETS))


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})
