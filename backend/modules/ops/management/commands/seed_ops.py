"""
«Tuzilma va standartlar» modulini yoqish + tayyor tuzilma (bo'limlar va lavozimlar):
    python manage.py seed_ops                 (barcha restoranlar)
    python manage.py seed_ops --slug namuna
    python manage.py seed_ops --demo          (ko'rgazma: xodimlarni yangi lavozimlarga taqsimlaydi)
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import set_modules


class Command(BaseCommand):
    help = "Tuzilma va standartlar modulini yoqadi va tayyor tuzilmani yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--demo", action="store_true", help="ko'rgazma xodimlarini lavozim/filiallarga taqsimlash")

    def handle(self, *args, **opts):
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        if not qs.exists():
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        for t in qs:
            if "ops" not in t.enabled_modules:
                try:
                    set_modules(t, [*t.enabled_modules, "ops"])
                except PermissionError as e:
                    self.stderr.write(f"{t.slug}: {e}")
                    continue
            with schema_context(t.schema_name):
                from modules.ops.demo import seed_demo_ops
                r = seed_demo_ops(t, demo=opts["demo"])
            self.stdout.write(f"{t.slug}: modul yoqildi · yangi bo'lim: {r['departments']} · yangi lavozim: {r['positions']} · "
                              f"mavjudiga bog'landi: {r['linked']}" + (f" · xodim taqsimlandi: {r['moved']}" if "moved" in r else ""))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
