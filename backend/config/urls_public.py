"""Public sxema (platforma domeni) uchun URL'lar: platforma sayti + ro'yxatdan o'tish API."""
from django.contrib import admin
from django.urls import path, re_path

from api.public_api import public_api
from website import platform_views
from website.views import admin_spa

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", public_api.urls),
    path("", platform_views.index, name="platform_index"),
    path("signup/", platform_views.signup, name="platform_signup"),
    path("ru/", platform_views.index, {"lang": "ru"}, name="platform_index_ru"),
    path("ru/signup/", platform_views.signup, {"lang": "ru"}, name="platform_signup_ru"),
    path("healthz/", platform_views.healthz, name="healthz"),
    re_path(r"^hq(?:/.*)?$", admin_spa, name="hq_spa"),   # RESTROOS HQ — o'sha SPA, /hq yo'li

]
