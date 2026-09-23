from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "modules.inventory"
    label = "inventory"
    verbose_name = "Ombor va tannarx"

    def ready(self):
        from . import listeners  # noqa: F401
