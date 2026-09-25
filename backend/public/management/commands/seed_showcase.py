"""
Namuna restoran «Navro'z milliy taomlar» — barcha bo'limlar to'la, boshqalarga ko'rsatish va sinash uchun:
    python manage.py seed_showcase           → yaratadi (bir marta)
    python manage.py seed_showcase --reset   → o'chirib, qaytadan yaratadi (sinovda buzilgan narsa tozalanadi)
Ochish: http://namuna.localhost:8000/admin · kirish: +998901234567 (kod ekranda chiqadi)
Boshqa restoranlarga (masalan Lazzat) tegmaydi.
"""
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Namuna restoran (to'liq soxta ma'lumot) — hamma imkoniyatlarni ko'rsatish uchun"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="bor bo'lsa o'chirib, qaytadan yaratish")
        parser.add_argument("--domain", default="namuna.localhost")

    def handle(self, *args, **opts):
        from public import showcase
        t0 = time.time()
        if opts["reset"] and showcase.drop():
            self.stdout.write("Eski namuna o'chirildi")
        if showcase._tenant_exists():
            self.stdout.write(self.style.WARNING("Namuna restoran allaqachon bor. Qaytadan: python manage.py seed_showcase --reset"))
            return
        self.stdout.write("Yaratilmoqda (1–3 daqiqa)…")
        showcase.build(domain=opts["domain"], log=lambda m: self.stdout.write("  • " + m))
        self.stdout.write(self.style.SUCCESS(f"Tayyor ({int(time.time() - t0)} s)."))
        self.stdout.write(f"  Admin panel: http://{opts['domain']}:8000/admin   (egasi: +998901234567)")
        self.stdout.write(f"  Sayt:        http://{opts['domain']}:8000/")
        self.stdout.write(f"  Mini App:    http://{opts['domain']}:8000/tg/")
