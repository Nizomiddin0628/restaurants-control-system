"""
Dev muhitini bir buyruq bilan tayyorlash:
public sxema migratsiyasi → tariflar → 'localhost' public domeni → demo tenant 'lazzat' (lazzat.localhost).
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Domain, Plan, Tenant
from public.services import create_tenant


class Command(BaseCommand):
    help = "Dev: migratsiya + tariflar + platforma domeni + demo tenant"

    def handle(self, *args, **options):
        call_command("migrate_schemas", "--shared", verbosity=0)
        for code, name, price, mods in [
            ("start", "Start", 199_000, ["catalog", "cms", "pos", "fiscal", "payments", "telegram", "reports"]),
            ("pro", "Pro", 490_000, ["*"]),
            ("network", "Tarmoq", 990_000, ["*"]),
        ]:
            Plan.objects.update_or_create(code=code, defaults={"name": name, "price_per_branch": price, "allowed_modules": mods, "max_branches": 1 if code == "start" else 100})

        if not Tenant.objects.filter(schema_name="public").exists():
            public = Tenant(schema_name="public", name="Platforma", slug="public", enabled_modules=[])
            public.save()
            Domain.objects.get_or_create(tenant=public, domain="localhost", defaults={"is_primary": True})
            self.stdout.write("public tenant + localhost domeni yaratildi")

        if not Tenant.objects.filter(slug="lazzat").exists():
            t = create_tenant(name="Lazzat", slug="lazzat", owner_phone="998901234567", preset="fast_food",
                              owner_name="Akmal T.", plan_code="pro", domain="lazzat.localhost")
            with schema_context(t.schema_name):
                from modules.catalog.demo import seed_demo_menu
                from modules.finance.demo import seed_demo_expenses
                from modules.hr.demo import seed_demo_hr
                from modules.inventory.demo import seed_demo_inventory
                from modules.pos.demo import seed_demo_orders
                from modules.reservations.demo import seed_demo_reservations
                from modules.tables.demo import seed_demo_tables
                from modules.tasks.demo import seed_demo_tasks
                seed_demo_menu()
                seed_demo_tasks()
                seed_demo_inventory(t)      # tex-kartalar → taom tannarxi real
                seed_demo_orders()          # 14 kunlik savdo → hisobotlar
                seed_demo_hr()              # xodimlar, smena, davomat, oylik
                from core.models import Membership
                from modules.hr.demo import seed_demo_recruit_people
                seed_demo_recruit_people(Membership.objects.filter(role__code="owner").first().user)
                seed_demo_expenses()        # ijara, kommunal, marketing
                seed_demo_tables()          # zal xaritasi: 2 zal, 14 stol
                seed_demo_reservations()    # bugungi/ertangi bronlar + navbat
                from modules.training.demo import seed_demo_training
                seed_demo_training()        # kurslar, testlar, standartlar, topshiriqlar
                from modules.crm.demo import seed_demo_crm
                seed_demo_crm(t)            # mijozlar, bonus tarixi, aksiyalar
                from modules.forecast.demo import seed_demo_forecast
                seed_demo_forecast(t)       # bayramlar + ob-havo
                from modules.ops.demo import seed_demo_ops
                seed_demo_ops(t, demo=True)            # tashkiliy tuzilma
                from modules.procurement.demo import seed_demo_procurement
                seed_demo_procurement(t)    # zakup: ta'minotchi, narx, buyurtma, bozorlik
                from modules.projects.demo import seed_demo_projects
                seed_demo_projects(t)       # loyihalar: filial ochish, menyu, ta'mir, aksiya
            from public.services import set_modules
            set_modules(t, [*t.enabled_modules, "training", "crm", "forecast", "ops", "procurement", "projects"])
            t.settings = {**(t.settings or {}), "demo_live": True}      # jonli demo: savdo va boshqalar vaqt o'tgani sari davom etadi
            t.save(update_fields=["settings"])
            self.stdout.write(self.style.SUCCESS("Demo tenant: http://lazzat.localhost:8000  (egasi: +998901234567, OTP dev rejimida javobda qaytadi)"))
        call_command("seed_hq", "--demo", verbosity=0)   # RESTROOS HQ: http://localhost:8000/hq/ (+998901234567)
        self.stdout.write(self.style.SUCCESS("HQ: http://localhost:8000/hq/  (+998901234567)"))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
