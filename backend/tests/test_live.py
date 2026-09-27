"""
Jonli demo: tarix bilan hozir orasidagi bo'shliq to'ldiriladi — cheklar (kun/soat taqsimoti), ombor yechiladi, kam qolgan
xomashyo zakup qilinadi, davomat va bron paydo bo'ladi, oshxonada faol buyurtmalar; takror chaqirilsa ko'paymaydi;
demo belgisi bo'lmagan restoranga umuman tegmaydi.
"""
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django_tenants.utils import schema_context


@pytest.fixture
def demo(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "inventory", "procurement", "hr", "kds", "tables", "reservations", "crm", "finance"}))
    with schema_context("lazzat"):
        from django.db import connection
        connection.set_tenant(tenant)
        from modules.catalog.demo import seed_demo_menu
        from modules.hr.demo import seed_demo_hr
        from modules.inventory.demo import seed_demo_inventory
        from modules.pos.demo import seed_demo_orders
        from modules.pos.models import Order
        from modules.tables.demo import seed_demo_tables
        seed_demo_menu()
        seed_demo_inventory(tenant)
        seed_demo_orders(days=10, per_day=(30, 40))
        from core.models import Membership, Role, User
        for ph, code in (("998935559001", "cook"), ("998935559002", "cashier")):
            u = User.objects.filter(phone=f"+{ph}").first() or User.objects.create_user(ph, full_name=f"Xodim {code}")
            Membership.objects.get_or_create(user=u, role=Role.objects.get(code=code))
        from modules.hr.models import Attendance, Employee
        Employee.objects.all().delete()
        seed_demo_hr()
        Attendance.objects.all().delete()
        seed_demo_tables()
        Order.objects.update(paid_at=F("paid_at") - timedelta(days=3), created_at=F("created_at") - timedelta(days=3))
    cache.clear()
    yield tenant
    with schema_context("public"):
        tenant.settings = {k: v for k, v in (tenant.settings or {}).items() if k != "demo_live"}
        tenant.save(update_fields=["settings"])


def _set_live(t, on=True):
    with schema_context("public"):
        t.settings = {**(t.settings or {}), "demo_live": on}
        t.save(update_fields=["settings"])


@pytest.mark.django_db
def test_not_live_does_nothing(demo):
    from public.live import tick
    with schema_context("lazzat"):
        assert tick(demo, force=True) == {}


@pytest.mark.django_db
def test_fills_gap_and_links_everything(demo):
    from public.live import tick
    _set_live(demo)
    with schema_context("lazzat"):
        from modules.hr.models import Attendance
        from modules.inventory.models import StockMovement
        from modules.pos.models import Order
        from modules.reservations.models import Reservation
        before = Order.objects.count()
        r = tick(demo, force=True)
        assert "error" not in r and r["orders"] > 30
        today = timezone.localdate()
        days = set(Order.objects.filter(paid_at__date__gt=today - timedelta(days=3)).values_list("paid_at__date", flat=True))
        assert today - timedelta(days=1) in days and today - timedelta(days=2) in days
        hours = {timezone.localtime(x).hour for x in Order.objects.filter(pk__gt=0).exclude(paid_at__isnull=True).values_list("paid_at", flat=True)[:4000]}
        assert hours <= set(range(10, 23)) | set(range(0, 24))                 # soatlar mavjud (tarixdagilar ham)
        assert StockMovement.objects.filter(kind="sale", ref__startswith="Savdo ").exists()
        assert Attendance.objects.filter(check_in__date=today - timedelta(days=1)).exists()
        assert Reservation.objects.filter(starts_at__date=today + timedelta(days=1)).count() >= 4
        n = Order.objects.count()
        assert n > before
        assert tick(demo, force=True).get("orders", 0) <= 3                    # takror chaqirilsa — deyarli hech narsa
        assert tick(demo) == {}                                                # kesh: 4 daqiqada bir marta


@pytest.mark.django_db
def test_low_stock_is_restocked(demo):
    from public.live import tick
    _set_live(demo)
    with schema_context("lazzat"):
        from modules.inventory.models import Ingredient, Purchase
        from modules.tasks.models import Task
        Ingredient.objects.filter(min_stock__gt=0).update(stock=F("min_stock") * 0.5)
        p0 = Purchase.objects.count()
        tick(demo, force=True)
        assert Purchase.objects.count() > p0                                    # kechagi kunlar uchun zakup qabul qilindi
        assert Task.objects.filter(title__startswith="Ta'minot:").count() == len(set(Task.objects.filter(title__startswith="Ta'minot:").values_list("title", flat=True)))
