"""
«AI Kotib» modulini yoqish va menejer rollariga ruxsat berish:
    python manage.py seed_ai                 (barcha restoranlar)
    python manage.py seed_ai --slug namuna
Egasi ('*') ruxsatiga ega. Filial menejeri va operatsion rahbar rollariga «ai.use» qo'shiladi.
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import set_modules

ROLES = ("manager", "ops_director", "director")


class Command(BaseCommand):
    help = "AI Kotib modulini yoqadi va menejerlarga ruxsat beradi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")

    def handle(self, *args, **opts):
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        for t in qs:
            if "ai" not in (t.enabled_modules or []):
                try:
                    set_modules(t, [*t.enabled_modules, "ai"])
                except PermissionError as e:
                    self.stderr.write(f"{t.slug}: {e}")
                    continue
            with schema_context(t.schema_name):
                from core.models import Role
                n = 0
                for r in Role.objects.filter(code__in=ROLES):
                    if "ai.use" not in (r.permissions or []) and "*" not in (r.permissions or []):
                        r.permissions = [*(r.permissions or []), "ai.use"]
                        r.save(update_fields=["permissions"])
                        n += 1
            self.stdout.write(f"{t.slug}: AI Kotib yoqildi · ruxsat qo'shilgan rollar: {n}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
