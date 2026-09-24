"""
Mavjud restoran uchun O'qitish modulini yoqish + demo kurslar:
    python manage.py seed_training            (standart: lazzat)
    python manage.py seed_training --slug chopar --no-demo
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import set_modules


class Command(BaseCommand):
    help = "O'qitish modulini yoqadi va demo kurslar, testlar, standartlar qo'shadi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="lazzat")
        parser.add_argument("--no-demo", action="store_true")

    def handle(self, *args, **opts):
        t = Tenant.objects.filter(slug=opts["slug"]).first()
        if t is None:
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        if "training" not in t.enabled_modules:
            set_modules(t, [*t.enabled_modules, "training"])
            self.stdout.write("O'qitish moduli yoqildi")
        if not opts["no_demo"]:
            with schema_context(t.schema_name):
                from modules.training.demo import seed_demo_training
                n = seed_demo_training()
            self.stdout.write(f"Demo kurslar: {n}" if n else "Kurslar allaqachon bor — demo qo'shilmadi")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
