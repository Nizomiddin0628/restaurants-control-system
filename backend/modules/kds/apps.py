from django.apps import AppConfig


class KdsConfig(AppConfig):
    name = "modules.kds"
    label = "kds"
    verbose_name = "Oshxona ekrani"

    def ready(self):
        from . import listeners  # noqa: F401