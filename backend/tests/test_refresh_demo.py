"""refresh_demo: eskirgan ochiq buyurtma/stol/bron «hozir»ga suriladi, faqat demo restoranlarda; takror ishga tushirish xavfsiz."""
from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context


@pytest.mark.django_db
def test_refresh_demo_moves_stale_things(tenant, other_tenant):
    from public.demo_refresh import demo_tenants, refresh
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "pos", "tables", "reservations", "inventory", "kds"}))
    # demo ro'yxati: lazzat bor, chopar (haqiqiy) yo'q
    slugs = {t.slug for t in demo_tenants()}
    assert "lazzat" in slugs and "chopar" not in slugs

    now = timezone.now()
    with schema_context(tenant.schema_name):
        from modules.pos.models import Order
        from modules.reservations.models import Reservation
        from modules.tables.models import Table, TableSession
        o = Order.objects.create(type="dine_in", table_no="1")
        Order.objects.filter(pk=o.pk).update(created_at=now - timedelta(hours=5))
        fresh = Order.objects.create(type="takeaway")
        tb = Table.objects.create(number="T1")
        s = TableSession.objects.create(table=tb, opened_at=now - timedelta(hours=6))
        r = Reservation.objects.create(guest_name="Ali", starts_at=now - timedelta(days=2, hours=-1), status="new")

        res = refresh(tenant, now=now)
        assert res["orders"] == 1 and res["tables"] == 1 and res["reservations"] == 1
        o.refresh_from_db(); s.refresh_from_db(); r.refresh_from_db(); fresh.refresh_from_db()
        assert now - timedelta(minutes=30) <= o.created_at <= now
        assert now - timedelta(minutes=75) <= s.opened_at <= now
        assert r.starts_at >= now - timedelta(hours=1)
        assert (r.starts_at - (now - timedelta(days=2, hours=-1))).total_seconds() % 86400 == 0   # soati saqlanadi
        # ikkinchi marta — hech narsa o'zgarmaydi
        again = refresh(tenant, now=now)
        assert again == {"orders": 0, "tables": 0, "reservations": 0, "usage": 0, "categories": 0}
