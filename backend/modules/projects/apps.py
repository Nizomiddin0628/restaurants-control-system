from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    name = "modules.projects"
    label = "projects"
    verbose_name = "Loyihalar"

    def ready(self):
        from . import listeners  # noqa: F401
