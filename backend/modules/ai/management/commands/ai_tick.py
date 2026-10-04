"""
AI Kotib navbatchisi — server har 5 daqiqada chaqiradi (systemd timer: restopos-ai.timer).
  • ertalabki hisobot vaqti kelgan bo'lsa — Telegram'ga yuboradi (har kishiga kuniga bir marta);
  • uzoq «band» qolgan suhbatlarni tiklaydi.
Qo'lda: python manage.py ai_tick            (vaqti kelganlarga)
        python manage.py ai_tick --force    (hozir hammaga, sinov uchun)
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "AI Kotib: ertalabki hisobotni vaqtida yuborish"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--slug", default="")

    def handle(self, *args, **o):
        try:                                      # platforma: kuniga bir marta to'lovlar va muddati o'tgan vazifalar xulosasi (HQ Telegram)
            from public.hq import daily_tick
            daily_tick()
        except Exception as e:
            self.stderr.write(f"hq daily: {e}")
        from public.models import Tenant
        qs = Tenant.objects.exclude(schema_name="public").filter(is_active=True)
        if o["slug"]:
            qs = qs.filter(slug=o["slug"])
        for t in qs:
            if not t.module_enabled("ai"):
                continue
            with schema_context(t.schema_name):
                connection.set_tenant(t)
                from django.utils import timezone

                from modules.ai.models import AiChat, ChatState
                from modules.ai.services import send_morning
                from modules.ai.tg import STALE
                AiChat.objects.filter(state=ChatState.BUSY, updated_at__lt=timezone.now() - STALE).update(state=ChatState.IDLE)
                try:
                    r = send_morning(t, force=o["force"])
                except Exception as e:
                    self.stderr.write(f"{t.slug}: xato — {e}")
                    continue
            if r["sent"] or r["failed"] or o["force"]:
                self.stdout.write(f"{t.slug}: yuborildi {r['sent']}, xato {r['failed']}" + (" (bot ulanmagan)" if r["skipped"] == -1 else ""))
