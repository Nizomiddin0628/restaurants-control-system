"""Platforma sayti (public sxema): tariflar so'mda, 15 kun bepul, ro'yxatdan o'tish sehrgari."""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from core.presets import PRESETS
from public.models import Plan


def index(request):
    return render(request, "platform/index.html", {
        "plans": Plan.objects.filter(is_active=True).order_by("price_per_branch"),
        "presets": PRESETS, "platform": settings.PLATFORM_NAME, "domain": settings.PLATFORM_DOMAIN,
    })


def signup(request):
    return render(request, "platform/signup.html", {"presets": PRESETS, "platform": settings.PLATFORM_NAME, "domain": settings.PLATFORM_DOMAIN})


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})
