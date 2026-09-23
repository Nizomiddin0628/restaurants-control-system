"""python manage.py create_tenant --name "Lazzat" --slug lazzat --phone 998901234567 --preset fast_food"""
from django.core.management.base import BaseCommand

from public.services import create_tenant


class Command(BaseCommand):
    help = "Yangi restoran (tenant) yaratadi: sxema, egasi, rollar, preset modullar, sayt"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--phone", required=True)
        parser.add_argument("--preset", default="fast_food")
        parser.add_argument("--owner-name", default="")
        parser.add_argument("--domain", default=None)

    def handle(self, *args, **o):
        t = create_tenant(name=o["name"], slug=o["slug"], owner_phone=o["phone"], preset=o["preset"],
                          owner_name=o["owner_name"], domain=o["domain"])
        self.stdout.write(self.style.SUCCESS(f"Tenant yaratildi: {t} → domen: {t.domains.first()} · modullar: {t.enabled_modules}"))
