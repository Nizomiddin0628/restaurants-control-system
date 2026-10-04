"""Platforma sayti (public sxema): taklif va narxlar (HQ → «Sayt va narxlar»), bepul sinov, ro'yxatdan o'tish, AI maslahatchi."""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from core.presets import PRESETS
from public.models import Plan, SiteOffer


def _ctx(**kw):
    return {"offer": SiteOffer.get(), "platform": settings.PLATFORM_NAME, "domain": settings.PLATFORM_DOMAIN, **kw}


def index(request):
    return render(request, "platform/index.html", _ctx(plans=Plan.objects.filter(is_active=True).order_by("price_per_branch"), presets=PRESETS))


def signup(request):
    return render(request, "platform/signup.html", _ctx(presets=PRESETS))


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})
