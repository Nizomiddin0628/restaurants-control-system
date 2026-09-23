"""Public sxema (platforma domeni) uchun URL'lar: platforma sayti + ro'yxatdan o'tish API."""
from django.contrib import admin
from django.urls import path

from api.public_api import public_api
from website import platform_views

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", public_api.urls),
    path("", platform_views.index, name="platform_index"),
    path("signup/", platform_views.signup, name="platform_signup"),
    path("healthz/", platform_views.healthz, name="healthz"),
]
