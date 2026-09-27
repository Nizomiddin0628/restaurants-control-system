from django.apps import AppConfig


class ProcurementConfig(AppConfig):
    name = "modules.procurement"
    label = "procurement"
    verbose_name = "Zakup (xarid)"

    def ready(self):
        from . import listeners  # noqa: F401
