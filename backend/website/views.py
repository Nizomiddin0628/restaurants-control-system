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
        "jobs_count": _jobs_count(request),
    }


def _jobs_count(request) -> int:
    if not request.tenant.module_enabled("hr"):
        return 0
    from modules.hr.models import Vacancy, VacancyStatus
    return Vacancy.objects.filter(status=VacancyStatus.OPEN).count()


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


def miniapp(request):
    """Telegram Mini App (/tg/) — bot ichida ochiladigan menyu va savat. Buyurtma /api/v1/bot/miniapp/order ga ketadi."""
    if not request.tenant.module_enabled("telegram"):
        return render(request, "site/offline.html", status=404)
    from modules.telegram.services import conf
    ctx = _ctx(request)
    cfg = conf(request.tenant)
    ctx["rules"] = {k: cfg[k] for k in ("allow_delivery", "allow_pickup", "allow_dine_in", "delivery_fee", "free_delivery_from", "min_order")}
    return render(request, "site/miniapp.html", ctx)


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


# ------------------------------------------------------------------ vakansiyalar (HR moduli)
def _bot_link(request, vid: int) -> str | None:
    if not request.tenant.module_enabled("telegram"):
        return None
    from modules.telegram.services import conf
    u = (conf(request.tenant).get("bot_username") or "").strip().lstrip("@")
    return f"https://t.me/{u}?start=job_{vid}" if u else None


def _media(v) -> dict:
    from modules.training.media import info
    return info(v.video_url) if v.video_url else {}


def vacancies(request):
    """/vacancies/ — ochiq vakansiyalar ro'yxati."""
    if not request.tenant.module_enabled("hr"):
        return render(request, "site/offline.html", status=404)
    from modules.hr import recruit
    from modules.hr.models import Vacancy, VacancyStatus
    ctx = _ctx(request)
    rows = [v for v in Vacancy.objects.filter(status=VacancyStatus.OPEN).select_related("branch") if recruit.is_open(v)]
    ctx["jobs"] = [{"v": v, "salary": recruit.salary_text(v), "employment": recruit.EMPLOYMENT.get(v.employment, "")} for v in rows]
    ctx["intro"] = (((request.tenant.settings or {}).get("modules") or {}).get("hr") or {}).get(
        "careers_intro", "Biz bilan ishlang: barqaror maosh, bepul ovqat, o'qitish va o'sish imkoniyati.")
    return render(request, "site/vacancies.html", ctx)


def vacancy(request, vid: int):
    """/vacancies/<id>/ — to'liq ma'lumot + ariza (Telegram bot yoki shu yerda forma)."""
    if not request.tenant.module_enabled("hr"):
        return render(request, "site/offline.html", status=404)
    from django.db.models import F

    from modules.hr import recruit
    from modules.hr.models import Vacancy
    v = Vacancy.objects.select_related("branch").filter(pk=vid).first()
    if v is None or not recruit.is_open(v):
        ctx = _ctx(request)
        ctx["closed"] = True
        return render(request, "site/vacancy.html", ctx, status=404 if v is None else 200)
    ctx = _ctx(request)
    ctx.update({"v": v, "salary": recruit.salary_text(v), "employment": recruit.EMPLOYMENT.get(v.employment, ""),
                "bot_link": _bot_link(request, v.pk), "media": _media(v), "questions": list(enumerate(v.questions or []))})
    if request.method == "POST":
        if request.POST.get("website"):                       # bot to'ldiradigan yashirin maydon (spam)
            ctx["sent"] = True
            return render(request, "site/vacancy.html", ctx)
        answers = [{"i": i, "a": request.POST.get(f"q{i}", "")} for i, _ in enumerate(v.questions or [])]
        by = request.POST.get("birth_year", "").strip()
        wh = [{"company": request.POST.get("prev_company", "").strip(), "position": request.POST.get("prev_position", "").strip(),
               "years": request.POST.get("prev_years", "").strip()}] if request.POST.get("prev_company", "").strip() else []
        photo = request.FILES.get("photo")
        if photo and (photo.size > 5 * 1024 * 1024 or not (photo.content_type or "").startswith("image/")):
            photo = None
        try:
            recruit.create_application(request.tenant, v, full_name=request.POST.get("full_name", ""), phone=request.POST.get("phone", ""),
                                       answers=answers, experience=request.POST.get("experience", ""), work_history=wh,
                                       birth_year=int(by) if by.isdigit() and 1950 < int(by) < 2012 else None,
                                       city=request.POST.get("city", ""), source="site", photo=photo)
            ctx["sent"] = True
        except ValueError as e:
            ctx["error"] = str(e)
            ctx["form"] = request.POST
    else:
        Vacancy.objects.filter(pk=v.pk).update(views=F("views") + 1)
    return render(request, "site/vacancy.html", ctx)
