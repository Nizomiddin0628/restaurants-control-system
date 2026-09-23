from django.urls import path, re_path

from . import views

urlpatterns = [
    path("", views.home, name="site_home"),
    path("menu/", views.menu, name="site_menu"),
    path("tv/menu-board/", views.menu_board, name="site_menu_board"),
    path("manifest.webmanifest", views.manifest, name="site_manifest"),
    re_path(r"^admin(?:/.*)?$", views.admin_spa, name="admin_spa"),
]
