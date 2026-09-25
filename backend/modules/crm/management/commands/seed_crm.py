"""
Mavjud restoran uchun «Mijozlar va bonus» modulini yoqish + demo mijozlar:
    python manage.py seed_crm                 (standart: lazzat)
    python manage.py seed_crm --slug chopar --no-demo
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import set_modules


class Command(BaseCommand):
    help = "CRM (mijozlar, bonus, aksiyalar) modulini yoqadi va demo ma'lumot qo'shadi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="lazzat")
        parser.add_argument("--no-demo", action="store_true")

    def handle(self, *args, **opts):
        t = Tenant.objects.filter(slug=opts["slug"]).first()
        if t is None:
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        if "crm" not in t.enabled_modules:
            set_modules(t, [*t.enabled_modules, "crm"])
            self.stdout.write("«Mijozlar va bonus» moduli yoqildi")
        if not opts["no_demo"]:
            with schema_context(t.schema_name):
                from modules.crm.demo import seed_demo_crm
                n = seed_demo_crm(t)
            self.stdout.write(f"Demo mijozlar: {n}" if n else "Mijozlar allaqachon bor — demo qo'shilmadi")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
