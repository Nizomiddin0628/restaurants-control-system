"""
Botni https'siz (o'z kompyuteringizda) ishga tushirish — Telegram'dan xabarlarni o'zi so'rab oladi:
    python manage.py telegram_polling              (standart: lazzat)
    python manage.py telegram_polling --slug chopar
To'xtatish: Ctrl+C. Serverga joylaganda buning o'rniga «Webhook o'rnatish» tugmasi ishlatiladi.
"""
import time

import requests
from django.core.management.base import BaseCommand
from django.db import connection

from public.models import Tenant

API = "https://api.telegram.org/bot{token}/{method}"


class Command(BaseCommand):
    help = "Telegram botni polling rejimida ishga tushiradi (lokal sinov uchun, https kerak emas)"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="lazzat")
        parser.add_argument("--base-url", default="", help="Mini App uchun sayt manzili (https bo'lsa)")

    def handle(self, *args, **opts):
        t = Tenant.objects.filter(slug=opts["slug"]).first()
        if t is None:
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        from integrations.telegram.api import process_update
        from modules.telegram import services
        tok = services.token(t)
        if not tok:
            self.stderr.write("Bot tokeni yo'q. Admin panel → Telegram bot → tokenni qo'ying va Saqlang.")
            return
        me = requests.get(API.format(token=tok, method="getMe"), timeout=15).json()
        if not me.get("ok"):
            self.stderr.write(f"Token noto'g'ri: {me.get('description')}")
            return
        requests.post(API.format(token=tok, method="deleteWebhook"), json={"drop_pending_updates": False}, timeout=15)
        self.stdout.write(self.style.SUCCESS(f"Bot ishlayapti: @{me['result']['username']}  ({t.name})"))
        self.stdout.write("Telegram'da botni oching va /start bosing. To'xtatish: Ctrl+C")
        offset = None
        while True:
            try:
                r = requests.get(API.format(token=tok, method="getUpdates"),
                                 params={"timeout": 25, "offset": offset, "allowed_updates": '["message","callback_query"]'}, timeout=40).json()
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.stderr.write(f"Tarmoq xatosi: {e} — 5 soniyadan keyin qayta urinaman")
                time.sleep(5)
                continue
            if not r.get("ok"):
                self.stderr.write(f"Telegram xato: {r.get('description')}")
                time.sleep(5)
                continue
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                t.refresh_from_db()
                connection.set_tenant(t)
                frm = ((upd.get("message") or {}).get("from") or {})
                self.stdout.write(f"← {frm.get('first_name', '')} (@{frm.get('username', '')}): {(upd.get('message') or {}).get('text', '[kontakt/boshqa]')}")
                try:
                    process_update(t, upd, opts["base_url"] or None)
                except Exception as e:
                    self.stderr.write(f"Xato: {e}")
                finally:
                    connection.set_schema_to_public()
