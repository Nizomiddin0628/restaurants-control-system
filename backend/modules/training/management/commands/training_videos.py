"""
Demo darslarga haqiqiy YouTube videolarni qo'yadi (bo'sh yoki eskirgan havolalar):
    python manage.py training_videos --all
    python manage.py training_videos --slug namuna
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant


class Command(BaseCommand):
    help = "O'qitish darslariga haqiqiy videolarni qo'yadi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        from modules.training.videos import apply_videos
        qs = Tenant.objects.exclude(schema_name="public")
        if not opts["all"]:
            qs = qs.filter(slug=opts["slug"] or "lazzat")
        for t in qs:
            if "training" not in (t.enabled_modules or []):
                continue
            with schema_context(t.schema_name):
                n = apply_videos()
            self.stdout.write(f"{t.slug}: {n} ta darsga video qo'yildi")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
