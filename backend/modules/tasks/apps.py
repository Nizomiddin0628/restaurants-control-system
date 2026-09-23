from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "modules.tasks"
    label = "tasks"
    verbose_name = "Vazifalar va muammolar"

    def ready(self):
        from . import listeners  # noqa: F401
