from django.apps import AppConfig


class OpsConfig(AppConfig):
    name = "modules.ops"
    label = "ops"
    verbose_name = "Tuzilma va standartlar"

    def ready(self):
        from . import listeners  # noqa: F401
