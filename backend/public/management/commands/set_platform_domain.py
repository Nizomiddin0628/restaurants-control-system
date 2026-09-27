"""
Serverda domenlarni sozlash: platforma (HQ) va har restoran uchun <slug>.<domen>.
    python manage.py set_platform_domain 185-196-215-179.nip.io
    python manage.py set_platform_domain restopos.uz
Yangi domen asosiy (primary) bo'ladi, eskilari (masalan *.localhost) ham ishlashda qoladi.
"""
from django.core.management.base import BaseCommand

from public.models import Domain, Tenant


class Command(BaseCommand):
    help = "Platforma va restoranlar uchun asosiy domenni o'rnatadi"

    def add_arguments(self, parser):
        parser.add_argument("base")

    def handle(self, *args, **opts):
        base = opts["base"].strip().lower().strip(".")
        for t in Tenant.objects.all().order_by("pk"):
            host = base if t.schema_name == "public" else f"{t.slug}.{base}"
            Domain.objects.filter(tenant=t).exclude(domain=host).update(is_primary=False)
            d = Domain.objects.filter(domain=host).first()
            if d and d.tenant_id != t.pk:
                self.stderr.write(f"  ! {host} boshqa restoranga bog'langan — o'tkazib yuborildi")
                continue
            if d is None:
                Domain.objects.create(tenant=t, domain=host, is_primary=True)
            elif not d.is_primary:
                d.is_primary = True
                d.save(update_fields=["is_primary"])
            self.stdout.write(f"  {t.name}: http://{host}/" + ("hq/" if t.schema_name == "public" else "admin/"))
        self.stdout.write(self.style.SUCCESS("Domenlar tayyor."))
