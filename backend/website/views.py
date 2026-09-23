"""
Restoran sayti (tenant domenida): bo'limlar CMS'dan, taomnoma e'lon qilingan snapshotdan.
Sahifalar: / (landing), /menu (to'liq taomnoma, HTMX filtr), /tv/menu-board (TV rejimi), /admin (SPA).
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_page

from core.models import Branch
from modules.catalog.services import current_snapshot
from modules.cms.models import SiteSection, SiteSettings


def _lang(request, site: SiteSettings) -> str:
    lang = request.GET.get("lang") or request.COOKIES.get("lang") or site.default_language or "uz"
    return lang if lang in (site.languages or ["uz"]) else (site.default_language or "uz")


def _ctx(request):
    site = SiteSettings.get()
    lang = _lang(request, site)
    menu = current_snapshot() or {"categories": []} if request.tenant.module_enabled("catalog") else {"categories": []}
    return {
        "site": site, "lang": lang, "theme": site.theme, "tenant": request.tenant,
        "sections": SiteSection.objects.filter(is_enabled=True),
        "menu": menu, "branches": Branch.objects.filter(is_active=True, deleted_at__isnull=True),
        "languages": site.languages or ["uz"], "platform": settings.PLATFORM_NAME,
    }


def home(request):
    if not request.tenant.module_enabled("cms"):
        return render(request, "site/offline.html", status=404)
    resp = render(request, "site/home.html", _ctx(request))
    if request.GET.get("lang"):
        resp.set_cookie("lang", request.GET["lang"], max_age=365 * 86400)
    return resp


def menu(request):
    """To'liq taomnoma. `?cat=<id>` + HX-Request → faqat taomlar bo'lagi (HTMX)."""
    ctx = _ctx(request)
    cat_id = request.GET.get("cat")
    cats = ctx["menu"]["categories"]
    ctx["active_cat"] = int(cat_id) if cat_id and cat_id.isdigit() else (cats[0]["id"] if cats else None)
    template = "site/_menu_items.html" if request.headers.get("HX-Request") else "site/menu.html"
    return render(request, template, ctx)


@cache_page(30)
def menu_board(request):
    """TV rejimi: 10-fut interfeys, kategoriyalar avtomatik aylanadi (pult shart emas)."""
    ctx = _ctx(request)
    ctx["rotate"] = int(request.tenant.settings.get("menu_board_rotate_seconds", 12))
    return render(request, "site/menu_board.html", ctx)


def admin_spa(request, path: str = ""):
    """Boshqaruv paneli (Vue SPA). VITE_DEV=1 bo'lsa Vite dev-serverga ulanadi, aks holda build'ni beradi."""
    if settings.VITE_DEV:
        return render(request, "site/admin_dev.html", {"vite": settings.VITE_URL})
    built = settings.BASE_DIR / "website" / "static" / "admin" / "index.html"
    if built.exists():
        return HttpResponse(built.read_text(encoding="utf-8"))
    return HttpResponse("Admin build topilmadi: frontend'da `pnpm build` ni bajaring (yoki VITE_DEV=1).", status=503)


def manifest(request):
    """PWA manifest — sayt/Mini App telefonga o'rnatiladi; keyin Capacitor ilova shu konfiguratsiyani oladi."""
    site = SiteSettings.get()
    return JsonResponse({
        "name": site.title or request.tenant.name, "short_name": (site.title or request.tenant.name)[:12],
        "start_url": "/", "display": "standalone", "background_color": site.theme.get("bg", "#ffffff"),
        "theme_color": site.theme.get("primary", "#D9482B"),
        "icons": [{"src": site.logo.url, "sizes": "512x512", "type": "image/png"}] if site.logo else [],
    })
