from django.apps import AppConfig


class TrainingConfig(AppConfig):
    name = "modules.training"
    label = "training"
    verbose_name = "O'qitish va komplayens"

    def ready(self):
        from . import listeners  # noqa: F401
