"""
Foydalanuvchiga kirish berish: telefon + parol (+ rol). Serverda birinchi egani qo'shish uchun qulay.
    python manage.py user_access --slug namuna --phone +998888203830 --password "Maxfiy123" --role owner --name "Nizomiddin"
    python manage.py user_access --all --phone +998888203830 --password "Maxfiy123" --role owner
Rol berilmasa — faqat parol o'rnatiladi (foydalanuvchi mavjud bo'lishi kerak).
"""
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from public.models import Tenant


class Command(BaseCommand):
    help = "Foydalanuvchi yaratadi/yangilaydi: parol va rol"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--phone", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--role", default="")
        parser.add_argument("--name", default="")

    def handle(self, *args, **o):
        if len(o["password"]) < 6:
            raise CommandError("Parol kamida 6 ta belgi bo'lsin")
        qs = Tenant.objects.exclude(schema_name="public")
        qs = qs if o["all"] else qs.filter(slug=o["slug"])
        if not qs.exists():
            raise CommandError("Restoran topilmadi (--slug yoki --all bering)")
        for t in qs:
            with schema_context(t.schema_name):
                from core.models import Membership, Role, User
                phone = User.objects.normalize_phone(o["phone"])
                u = User.objects.filter(phone=phone).first()
                if u is None:
                    if not o["role"]:
                        self.stderr.write(f"  {t.slug}: foydalanuvchi yo'q — --role bering")
                        continue
                    u = User.objects.create_user(phone=phone, full_name=o["name"])
                if o["name"]:
                    u.full_name = o["name"]
                u.is_active = True
                u.set_password(o["password"])
                u.save()
                if o["role"]:
                    role = Role.objects.filter(code=o["role"]).first()
                    if role is None:
                        raise CommandError(f"Rol topilmadi: {o['role']}")
                    m, _ = Membership.objects.get_or_create(user=u, role=role)
                    if not m.is_active:
                        m.is_active = True
                        m.save(update_fields=["is_active"])
                self.stdout.write(f"  {t.name}: {phone} — parol o'rnatildi" + (f", rol: {o['role']}" if o["role"] else ""))
        self.stdout.write(self.style.SUCCESS("Tayyor. Endi telefon + parol bilan kiring."))
