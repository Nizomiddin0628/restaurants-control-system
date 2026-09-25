"""
Mavjud restoranga HR demo: vakansiyalar (saytda ko'rinadi), nomzodlar, xodim profillari, ish tarixi, hujjatlar, baholar:
    python manage.py seed_hr                  (standart: lazzat)
    python manage.py seed_hr --slug namuna
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.utils import schema_context

from public.models import Tenant


class Command(BaseCommand):
    help = "HR demo: ishga olish, profil, KPI"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="lazzat")

    def handle(self, *args, **opts):
        t = Tenant.objects.filter(slug=opts["slug"]).first()
        if t is None:
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        with schema_context(t.schema_name):
            connection.set_tenant(t)
            from core.models import Membership
            from modules.hr.demo import seed_demo_hr, seed_demo_recruit_people
            seed_demo_hr()
            owner = Membership.objects.filter(role__code="owner").select_related("user").first()
            r = seed_demo_recruit_people(owner.user if owner else None)
        connection.set_schema_to_public()
        if not r.get("vacancies"):
            self.stdout.write("Vakansiyalar allaqachon bor — demo qo'shilmadi")
        else:
            self.stdout.write(f"Vakansiya: {r['vacancies']} · nomzod: {r['applications']} · profil: {r['profiles']}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
