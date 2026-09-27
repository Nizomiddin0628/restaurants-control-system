"""
«Zakup (xarid)» modulini yoqish + bozorlar ro'yxati + (ixtiyoriy) ko'rgazma ma'lumotlari:
    python manage.py seed_procurement            (barcha restoranlar, faqat modul va bozorlar)
    python manage.py seed_procurement --demo     (ta'minotchilar, narxlar, buyurtmalar, bozorliklar)
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import SYSTEM_ROLES, set_modules


class Command(BaseCommand):
    help = "Zakup modulini yoqadi, bozorchi rolini va bozorlar ro'yxatini yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--demo", action="store_true")

    def handle(self, *args, **opts):
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        for t in qs:
            if "procurement" not in t.enabled_modules:
                try:
                    set_modules(t, [*t.enabled_modules, "procurement"])
                except PermissionError as e:
                    self.stderr.write(f"{t.slug}: {e}")
                    continue
            with schema_context(t.schema_name):
                from core.models import Role
                from modules.procurement import services
                for code, name, perms in SYSTEM_ROLES:          # yangi rol (bozorchi) va yangi ruxsatlar
                    r, created = Role.objects.get_or_create(code=code, defaults={"name": name, "permissions": perms, "is_system": True})
                    if not created and r.is_system and set(perms) - set(r.permissions):
                        r.permissions = sorted(set(r.permissions) | set(perms))
                        r.save(update_fields=["permissions"])
                services.ensure_markets()
                msg = ""
                if opts["demo"]:
                    from modules.procurement.demo import seed_demo_procurement
                    r = seed_demo_procurement(t)
                    msg = " · demo: allaqachon bor" if r.get("skipped") else f" · demo: {r['suppliers']} ta'minotchi, {r['orders']} buyurtma, {r['trips']} bozorlik"
            self.stdout.write(f"{t.slug}: modul yoqildi{msg}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
