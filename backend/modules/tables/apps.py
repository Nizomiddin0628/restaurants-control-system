from django.apps import AppConfig


class TablesConfig(AppConfig):
    name = "modules.tables"
    label = "tables"
    verbose_name = "Stollar va zal"

    def ready(self):
        from . import listeners  # noqa: F401