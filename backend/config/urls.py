"""Tenant (restoran) sxemasi uchun URL'lar: restoran sayti + API + admin."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from api.api import api

urlpatterns = [
    path("django-admin/", admin.site.urls),   # faqat platforma jamoasi uchun
    path("api/v1/", api.urls),
    path("", include("website.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
