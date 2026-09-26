"""
«Bayram va ob-havo prognozi» modulini yoqish + bayramlar va ob-havo:
    python manage.py seed_forecast                 (barcha restoranlar)
    python manage.py seed_forecast --slug namuna
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import set_modules


class Command(BaseCommand):
    help = "Bayram va ob-havo prognozi modulini yoqadi, bayramlar va ob-havoni yuklaydi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")

    def handle(self, *args, **opts):
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        if not qs.exists():
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        for t in qs:
            if "forecast" not in t.enabled_modules:
                try:
                    set_modules(t, [*t.enabled_modules, "forecast"])
                except PermissionError as e:
                    self.stderr.write(f"{t.slug}: {e}")
                    continue
            with schema_context(t.schema_name):
                from modules.forecast.demo import seed_demo_forecast
                r = seed_demo_forecast(t)
            w = {"ok": "yangilandi", "demo": "namunaviy (internet yo'q)", "eski": "oxirgi saqlangan"}[r["weather"]]
            self.stdout.write(f"{t.slug}: modul yoqildi · yangi bayramlar: {r['holidays']} · ob-havo: {w}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
