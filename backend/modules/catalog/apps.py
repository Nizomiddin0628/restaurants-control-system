from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "modules.catalog"
    label = "catalog"
    verbose_name = "Taomnoma"

    def ready(self):
        from . import listeners  # noqa: F401  hodisa tinglovchilarini ro'yxatga oladi
