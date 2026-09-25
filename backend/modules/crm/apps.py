from django.apps import AppConfig


class CrmConfig(AppConfig):
    name = "modules.crm"
    label = "crm"
    verbose_name = "Marketing va bonuslar"

    def ready(self):
        from . import listeners  # noqa: F401
