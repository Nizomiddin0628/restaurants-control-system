from django.apps import AppConfig


class CmsConfig(AppConfig):
    name = "modules.cms"
    label = "cms"
    verbose_name = "Sayt va brend"

    def ready(self):
        from . import listeners  # noqa: F401
