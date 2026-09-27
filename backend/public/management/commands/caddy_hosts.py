"""
Caddy uchun domenlar ro'yxati (vergul bilan): platforma + barcha restoranlar (<slug>.PLATFORM_DOMAIN).
Har domen uchun Caddy o'zi bepul SSL (https) sertifikat oladi.
    python manage.py caddy_hosts           → a.uz, x.a.uz, y.a.uz
    python manage.py caddy_hosts --http    → http://a.uz, http://x.a.uz, ...
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from public.models import Domain


class Command(BaseCommand):
    help = "Caddy sayt manzillari (platforma domeni ostidagi barcha domenlar)"

    def add_arguments(self, parser):
        parser.add_argument("--http", action="store_true")

    def handle(self, *args, **opts):
        base = settings.PLATFORM_DOMAIN.strip(".").lower()
        hosts = sorted({d for d in Domain.objects.values_list("domain", flat=True) if d == base or d.endswith("." + base)})
        if base not in hosts:
            hosts.insert(0, base)
        pre = "http://" if opts["http"] else ""
        self.stdout.write(", ".join(pre + h for h in hosts))
