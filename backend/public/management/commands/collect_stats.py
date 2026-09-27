"""
HQ statistikasi va oylik hisoblar — har kecha (cron / Celery beat) ishga tushiriladi:
    python manage.py collect_stats
HQ sahifasi ochilganda ham 15 daqiqada bir o'zi yangilanadi; bu buyruq katta platformada tunda oldindan tayyorlaydi.
"""
from django.core.management.base import BaseCommand

from public import hq


class Command(BaseCommand):
    help = "Barcha restoranlar statistikasini yig'ish va oylik hisoblarni yaratish"

    def handle(self, *args, **opts):
        n = hq.ensure_stats(force=True)
        m = hq.ensure_invoices()
        self.stdout.write(self.style.SUCCESS(f"Statistika: {n} ta restoran · yangi hisob: {m}"))
