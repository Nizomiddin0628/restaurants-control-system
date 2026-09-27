"""
RESTROOS HQ: platforma jamoasi a'zosi + (ixtiyoriy) ko'rgazma ma'lumotlari.
    python manage.py seed_hq --phone +998901234567 --name "Bahodir" --role superadmin
    python manage.py seed_hq --demo           (o'tgan oylar hisoblari, murojaatlar, bayroqlar, relizlar)
Keyin: http://localhost:8000/hq/  (telefon + kod; dev rejimda kod ekranda chiqadi)
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import User
from public import hq
from public.models import (
    FeatureFlag,
    Invoice,
    InvoiceStatus,
    PlatformStaff,
    Release,
    StaffRole,
    Ticket,
    TicketMessage,
)


class Command(BaseCommand):
    help = "HQ: platforma administratori va demo ma'lumotlar"

    def add_arguments(self, parser):
        parser.add_argument("--phone", default="+998901234567")
        parser.add_argument("--name", default="Platforma admini")
        parser.add_argument("--role", default=StaffRole.SUPERADMIN, choices=StaffRole.values)
        parser.add_argument("--demo", action="store_true")

    def handle(self, *args, **o):
        phone = User.objects.normalize_phone(o["phone"])
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": o["name"]})
        s, created = PlatformStaff.objects.update_or_create(user=u, defaults={"role": o["role"], "is_active": True})
        self.stdout.write(f"HQ a'zosi: {phone} · {StaffRole(s.role).label}" + (" (yangi)" if created else ""))
        n = hq.ensure_stats(force=True)
        if o["demo"]:
            self._demo(s)
        hq.ensure_invoices()
        self.stdout.write(f"Statistika yig'ildi: {n} ta restoran")
        self.stdout.write(self.style.SUCCESS("Tayyor. Kirish: http://localhost:8000/hq/"))

    def _demo(self, staff):
        today = timezone.localdate().replace(day=1)
        for n, t in enumerate(hq.tenants_qs()):
            if t.trial_ends_at and t.trial_ends_at > timezone.now():   # ko'rgazma: «to'layotgan» mijozlar
                t.trial_ends_at = timezone.now() - timedelta(days=1)
                t.save(update_fields=["trial_ends_at"])
            branches = max(1, hq.stats_by_tenant(7).get(t.pk, {}).get("branches", 1) or 1)
            price = t.plan.price_per_branch if t.plan else 490_000
            for k in range(0, 7):
                y, m = today.year, today.month - k
                while m <= 0:
                    m += 12
                    y -= 1
                p = date(y, m, 1)
                paid = bool(k) or n % 2 == 0
                Invoice.objects.update_or_create(tenant=t, period=p, defaults={
                    "plan_name": t.plan.name if t.plan else "Pro", "branches": branches, "amount": price * branches,
                    "status": InvoiceStatus.PAID if paid else InvoiceStatus.PENDING,
                    "due_date": p + timedelta(days=10) if k else timezone.localdate() + timedelta(days=5),
                    "paid_at": timezone.now() - timedelta(days=30 * k) if paid else None})
        samples = [("Checklist ishlamayapti", "high", "open"), ("Trening videosi ochilmayapti", "normal", "progress"),
                   ("Kassada chek chiqmayapti", "critical", "open"), ("Yangi filial qo'shish", "low", "closed")]
        if not Ticket.objects.exists():
            for i, t in enumerate(hq.tenants_qs()):
                for j, (subj, pr, st) in enumerate(samples[i * 2:(i * 2) + 2] or samples[:1]):
                    x = Ticket.objects.create(tenant=t, subject=subj, body=f"{subj}. Iltimos, tezroq yordam bering.", priority=pr, status=st,
                                              author_name="Filial menejeri", branch_name="Asosiy filial")
                    TicketMessage.objects.create(ticket=x, from_staff=False, author_name="Filial menejeri", body=x.body)
                    if st != "open":
                        TicketMessage.objects.create(ticket=x, from_staff=True, author_name="Yordam", body="Salom! Ko'rib chiqyapmiz, 15 daqiqada javob beramiz.")
        for code, name, desc, allon in [("ai_assistant", "AI yordamchi (beta)", "Egasi uchun savol-javob yordamchisi", False),
                                        ("sop_video", "SOP video darslar", "SOP bosqichlarida video", True),
                                        ("new_pos", "Yangi kassa interfeysi", "Planshet uchun yangi kassa", False)]:
            FeatureFlag.objects.get_or_create(code=code, defaults={"name": name, "description": desc, "enabled_all": allon})
        if not Release.objects.exists():
            for v, title in [("v12", "Bayram va ob-havo prognozi"), ("v13", "Tashkiliy tuzilma va lavozimlar"), ("v14", "RESTROOS HQ platforma paneli")]:
                Release.objects.create(version=v, title=title, is_published=True, published_at=timezone.now())
        self.stdout.write("Demo: hisoblar (6 oy), murojaatlar, bayroqlar, relizlar")
