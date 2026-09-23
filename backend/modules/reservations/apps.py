from django.apps import AppConfig


class ReservationsConfig(AppConfig):
    name = "modules.reservations"
    label = "reservations"
    verbose_name = "Bron va navbat"

    def ready(self):
        from . import listeners  # noqa: F401