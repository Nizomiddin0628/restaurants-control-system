from django.apps import AppConfig


class TelegramBotConfig(AppConfig):
    name = "modules.telegram"
    label = "tgbot"          # "telegram" nomi integratsiya paketi bilan chalkashmasin
    verbose_name = "Telegram bot va Mini App"

    def ready(self):
        from . import listeners  # noqa: F401
