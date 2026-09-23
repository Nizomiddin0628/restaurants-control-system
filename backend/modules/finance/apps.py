from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = "modules.finance"
    label = "finance"
    verbose_name = "Moliya"

    def ready(self):
        from . import listeners  # noqa: F401
