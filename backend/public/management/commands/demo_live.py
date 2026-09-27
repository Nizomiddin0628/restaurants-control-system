"""
Demo restoranlarni «bugungacha» to'ldirish (taqdimotdan oldin qo'lda, bir martalik) — savdo, ombor, zakup, davomat, bron.
Panel ochilganda avtomatik davom etmaydi (v20 dan); kerak bo'lsa shu buyruqni qayta ishga tushiring.
    python manage.py demo_live --all --on             (lazzat, namuna — oxirgi chekdan hozirgacha)
    python manage.py demo_live --slug namuna --on     (yoqish + hozirgacha to'ldirish)
    python manage.py demo_live --slug namuna          (faqat hozirgacha to'ldirish)
    python manage.py demo_live --slug namuna --off    (o'chirish)
    python manage.py demo_live --all --on             (hamma demo restoranlar: lazzat, namuna)
Haqiqiy mijoz restoranida YOQMANG — u yerga soxta cheklar qo'shiladi.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import schema_context

DEMO_SLUGS = ("lazzat", "namuna")


class Command(BaseCommand):
    help = "Jonli demo: yoqish/o'chirish va bo'shliqni to'ldirish"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--all", action="store_true", help="lazzat va namuna")
        parser.add_argument("--on", action="store_true")
        parser.add_argument("--off", action="store_true")

    def handle(self, *args, **o):
        from public.live import KEY, tick
        from public.models import Tenant
        slugs = list(DEMO_SLUGS) if o["all"] else [o["slug"]] if o["slug"] else []
        if not slugs:
            raise CommandError("--slug NOM yoki --all kerak")
        for t in Tenant.objects.filter(slug__in=slugs):
            if o["on"] or o["off"]:
                t.settings = {**(t.settings or {}), KEY: bool(o["on"])}
                t.save(update_fields=["settings"])
            with schema_context(t.schema_name):
                connection.set_tenant(t)
                r = tick(t, force=True) if not o["off"] else {}
            state = "yoqilgan" if (t.settings or {}).get(KEY) else "o'chiq"
            self.stdout.write(f"{t.slug}: jonli demo {state}" + (f" · yangi cheklar: {r.get('orders', 0)}, zakup: {r.get('restock', 0)}" if r else ""))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
