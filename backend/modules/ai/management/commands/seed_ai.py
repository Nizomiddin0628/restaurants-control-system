"""
«AI Kotib» modulini yoqish va menejer rollariga ruxsat berish:
    python manage.py seed_ai                 (barcha restoranlar)
    python manage.py seed_ai --slug namuna
Superadmin ('*') ruxsatiga ega. Menejerlarga «ai.use» shaxsiy ruxsat sifatida beriladi (keyin Superadmin o'zi taqsimlaydi).
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
                from core.models import User
                n = 0
                for u in User.objects.filter(is_active=True, memberships__is_active=True, memberships__role__code__in=ROLES).distinct():
                    if "ai.use" not in (u.extra_permissions or []):
                        u.extra_permissions = [*(u.extra_permissions or []), "ai.use"]
                        u.save(update_fields=["extra_permissions"])
                        n += 1
            self.stdout.write(f"{t.slug}: AI Kotib yoqildi · AI Kotib berilgan menejerlar: {n}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
