"""
Demo restoranlarni bugungi holatga keltirish (eskirgan ochiq buyurtmalar, stollar, bronlar, xomashyo sarfi).
    python manage.py refresh_demo                 (namuna, lazzat va settings["demo"] = True bo'lganlar)
    python manage.py refresh_demo --slug namuna
Haqiqiy restoranlarga tegmaydi. deploy/install.sh har yangilanishda chaqiradi. Batafsil: public/demo_refresh.py
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Demo restoranlar: eskirgan buyurtma/stol/bronni bugungi vaqtga surish, xomashyo sarfini to'ldirish"

    def add_arguments(self, parser):
        parser.add_argument("--slug", action="append", default=[], help="faqat shu restoran (bir necha marta berish mumkin)")

    def handle(self, *args, **o):
        from public.demo_refresh import demo_tenants, refresh
        ts = demo_tenants(o["slug"] or None)
        if not ts:
            self.stdout.write("Demo restoran topilmadi — hech narsa o'zgarmadi.")
            return
        for t in ts:
            with schema_context(t.schema_name):
                connection.set_tenant(t)
                try:
                    r = refresh(t)
                except Exception as e:   # bitta restorandagi xato boshqalarini to'xtatmasin
                    self.stdout.write(self.style.WARNING(f"{t.slug}: xato — {e}"))
                    continue
            self.stdout.write(f"{t.slug}: buyurtma {r['orders']}, stol {r['tables']}, bron {r['reservations']}, sarf yozuvi {r['usage']}")
        self.stdout.write(self.style.SUCCESS("Demo yangilandi."))
