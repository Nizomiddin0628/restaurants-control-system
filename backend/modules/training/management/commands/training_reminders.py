"""
O'qitish eslatmalari (serverda kuniga bir marta cron bilan, masalan 09:00):
    python manage.py training_reminders            (barcha restoranlar)
    python manage.py training_reminders --slug lazzat
Cron bo'lmasa ham ishlaydi: xodim o'qitish sahifasini ochganda kunlik eslatma o'zi ketadi.
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant


class Command(BaseCommand):
    help = "Kechikayotgan kurs/topshiriq va standartlar bo'yicha Telegram eslatmalari (xodimlar + mas'ullar)"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")

    def handle(self, *args, **opts):
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        for t in qs:
            if not t.module_enabled("training"):
                continue
            with schema_context(t.schema_name):
                from django.db import connection

                from modules.training import services
                connection.set_tenant(t)
                r = services.remind(t, force=True)
            self.stdout.write(f"{t.name}: xodimlarga {r['users']}, mas'ullarga {r['responsibles']} ta eslatma")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
