"""
Loyihalar modulini yoqish va demo:
    python manage.py seed_projects            (modul yoqiladi, rollarga ruxsat)
    python manage.py seed_projects --demo     (5 ta demo loyiha: filial ochish, menyu, ta'mir, aksiya, o'qitish)
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Loyihalar moduli: yoqish, rollar, demo"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--demo", action="store_true")

    def handle(self, *args, **opts):
        from public.models import Tenant
        from public.services import SYSTEM_ROLES, set_modules
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        for t in qs:
            if "projects" not in t.enabled_modules:
                try:
                    set_modules(t, [*t.enabled_modules, "projects"])
                except PermissionError as e:
                    self.stderr.write(f"{t.slug}: {e}")
                    continue
            with schema_context(t.schema_name):
                from core.models import Role
                for code, name, perms in SYSTEM_ROLES:          # yangi ruxsatlar (projects.*)
                    r, created = Role.objects.get_or_create(code=code, defaults={"name": name, "permissions": perms, "is_system": True})
                    if not created and r.is_system and set(perms) - set(r.permissions):
                        r.permissions = sorted(set(r.permissions) | set(perms))
                        r.save(update_fields=["permissions"])
                msg = ""
                if opts["demo"]:
                    from modules.projects.demo import seed_demo_projects
                    r = seed_demo_projects(t)
                    msg = " · demo: allaqachon bor" if r.get("skipped") else f" · demo: {r['projects']} loyiha, {r['tasks']} vazifa"
            self.stdout.write(f"{t.slug}: modul yoqildi{msg}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
