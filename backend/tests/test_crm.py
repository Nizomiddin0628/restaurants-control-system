"""
CRM: to'lovda mijoz kartasi + sovg'a + keshbek, kassada bonus va aksiya (server qayta hisoblaydi),
bonus limiti, chek bekor → hammasi orqaga, aksiya qoidalari, darajalar, tug'ilgan kun (yiliga bir marta),
qo'lda bonus (sabab majburiy), Telegram: bonus tugmasi va tug'ilgan kun so'rovi, modul o'chsa 404.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}
PHONE = "+998935550011"


@pytest.fixture
def crm(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "crm", "pos", "catalog", "telegram"}))
        mods = dict(tenant.settings.get("modules") or {})
        mods["crm"] = {"cashback_percent": 3, "welcome_bonus": 5000, "max_pay_percent": 50, "birthday_bonus": 30000,
                       "silver_from": 1_000_000, "silver_percent": 5, "gold_from": 3_000_000, "gold_percent": 8}
        tenant.settings = {**tenant.settings, "modules": mods}
        tenant.save()
    with schema_context("lazzat"):
        from modules.catalog.models import Category, Product
        from modules.crm.models import BonusTxn, Customer, OrderLink, Promo
        for m in (BonusTxn, OrderLink, Promo, Customer):
            m.objects.all().delete()
        cat, _ = Category.objects.get_or_create(name={"uz": "CRM test", "ru": "", "en": ""})
        drink, _ = Category.objects.get_or_create(name={"uz": "CRM ichimlik", "ru": "", "en": ""})
        p, _ = Product.objects.get_or_create(name={"uz": "CRM burger", "ru": "", "en": ""}, defaults={"category": cat, "price": 50000, "cost": 15000})
        d, _ = Product.objects.get_or_create(name={"uz": "CRM cola", "ru": "", "en": ""}, defaults={"category": drink, "price": 10000, "cost": 3000})
        yield {"burger": p, "cola": d, "drink_cat": drink}


def _sell(api, items, phone="", **attach):
    api.post("/api/v1/pos/shift/open", {"cash_start": 0})
    o = api.post("/api/v1/pos/orders", {"items": items, "customer_phone": phone}).json()
    if attach:
        r = api.post(f"/api/v1/crm/orders/{o['id']}/attach", {"phone": phone, **attach})
        assert r.status_code == 200, r.content
    r = api.post(f"/api/v1/pos/orders/{o['id']}/pay", {"payment_method": "cash"})
    assert r.status_code == 200, r.content
    return r.json()


def _cust():
    with schema_context("lazzat"):
        from modules.crm.models import Customer
        return Customer.objects.get(phone=PHONE)


@pytest.mark.django_db
def test_paid_order_creates_card_welcome_and_cashback(api, crm):
    o = _sell(api, [{"product_id": crm["burger"].pk, "qty": 2}], "93 555 00 11")      # 9 xonali raqam ham tushunadi
    c = _cust()
    assert o["total"] == 100000
    assert c.orders_count == 1 and c.spent_total == 100000
    assert c.balance == 5000 + 3000                                                    # sovg'a + 3% keshbek
    s = api.get("/api/v1/crm/stats").json()
    assert s["customers"] == 1 and s["bonus_liability"] == 8000


@pytest.mark.django_db
def test_quote_bonus_cap_and_attach_recalculated_by_server(api, crm):
    with schema_context("lazzat"):
        from modules.crm.models import Customer
        Customer.objects.create(phone=PHONE, name="Aziz", balance=80000)
    q = api.post("/api/v1/crm/quote", {"phone": PHONE, "items": [{"product_id": crm["burger"].pk, "qty": 2}]}).json()
    assert q["customer"]["name"] == "Aziz" and q["max_bonus"] == 50000 and q["total"] == 50000   # 50% gacha
    # kassir 999 999 so'rasa ham — server limitgacha kesadi
    o = _sell(api, [{"product_id": crm["burger"].pk, "qty": 2}], PHONE, use_bonus=999999)
    assert o["discount"] == 50000 and o["total"] == 50000
    c = _cust()
    assert c.balance == 80000 - 50000 + 1500                                           # keshbek faqat to'langan puldan


@pytest.mark.django_db
def test_promo_code_and_category_scope(api, crm):
    api.post("/api/v1/crm/promos", {"name": "Ichimlik −50%", "value": 50, "code": "cola50", "category_ids": [crm["drink_cat"].pk]})
    items = [{"product_id": crm["burger"].pk, "qty": 1}, {"product_id": crm["cola"].pk, "qty": 2}]
    q = api.post("/api/v1/crm/quote", {"items": items, "promo_code": "COLA50"}).json()
    assert q["promo"]["discount"] == 10000 and q["total"] == 60000                    # faqat ichimlikka
    bad = api.post("/api/v1/crm/quote", {"items": items, "promo_code": "YOQ"}).json()
    assert bad["promo"] is None and "yo'q" in bad["promo_error"]
    o = _sell(api, items, PHONE, promo_code="cola50")
    assert o["total"] == 60000
    p = api.get("/api/v1/crm/promos").json()[0]
    assert p["used_count"] == 1 and p["discount_total"] == 10000
    assert api.post("/api/v1/crm/promos", {"name": "x", "value": 5, "code": "COLA50"}).status_code == 400   # takror kod


@pytest.mark.django_db
def test_promo_rules_time_weekday_min_audience(crm):
    with schema_context("lazzat"):
        from modules.crm import services
        from modules.crm.models import Customer, Promo
        cfg = services._DEFAULTS
        lines = [{"product_id": 1, "category_id": 1, "amount": 40000}]
        tz = timezone.get_current_timezone()
        at16 = datetime(2026, 9, 21, 16, 0, tzinfo=tz)                                    # dushanba
        hh = Promo(name="HH", value=15, hour_from=15, hour_to=17)
        assert services.promo_check(hh, lines, None, cfg, at16)[0] == 6000
        assert services.promo_check(hh, lines, None, cfg, at16.replace(hour=19))[0] == 0
        assert services.promo_check(Promo(name="W", value=10, weekdays=[5, 6]), lines, None, cfg, at16)[0] == 0
        assert "Eng kam" in services.promo_check(Promo(name="M", value=10, min_order=50000), lines, None, cfg, at16)[1]
        new = Promo(name="N", kind="fixed", value=10000, audience="new")
        assert services.promo_check(new, lines, Customer(orders_count=0), cfg, at16)[0] == 10000
        assert services.promo_check(new, lines, Customer(orders_count=3), cfg, at16)[0] == 0
        assert services.promo_check(Promo(name="C", value=50, max_discount=5000), lines, None, cfg, at16)[0] == 5000


@pytest.mark.django_db
def test_cancel_paid_order_reverses_everything(api, crm):
    with schema_context("lazzat"):
        from modules.crm.models import Customer
        Customer.objects.create(phone=PHONE, balance=20000)
    o = _sell(api, [{"product_id": crm["burger"].pk, "qty": 1}], PHONE, use_bonus=20000)
    assert _cust().balance == 0 + (o["total"] * 3 // 100)
    assert api.post(f"/api/v1/pos/orders/{o['id']}/cancel", {"reason": "xato"}).status_code == 200
    c = _cust()
    assert c.balance == 20000 and c.orders_count == 0 and c.spent_total == 0


@pytest.mark.django_db
def test_levels_raise_cashback(api, crm):
    with schema_context("lazzat"):
        from modules.crm.models import Customer
        Customer.objects.create(phone=PHONE, spent_total=3_200_000, orders_count=40)
    _sell(api, [{"product_id": crm["burger"].pk, "qty": 2}], PHONE)
    c = _cust()
    assert c.balance == 8000                                                          # Oltin: 8%
    card = api.get(f"/api/v1/crm/customers/{c.pk}").json()
    assert card["level"]["name"] == "Oltin" and card["txns"][0]["kind"] == "earn"


@pytest.mark.django_db
def test_birthday_bonus_once_a_year(tenant, crm):
    with schema_context("lazzat"):
        from modules.crm import services
        from modules.crm.models import Customer
        today = timezone.localdate()
        c = Customer.objects.create(phone=PHONE, name="Malika", birthday=date(1996, today.month, today.day))
        assert services.daily(tenant, force=True) == 1
        assert services.daily(tenant, force=True) == 0
        c.refresh_from_db()
        assert c.balance == 30000


@pytest.mark.django_db
def test_manual_bonus_needs_reason_and_balance(api, crm):
    c = api.post("/api/v1/crm/customers", {"phone": "+998935550011", "name": "Test"}).json()
    assert c["balance"] == 5000
    assert api.post(f"/api/v1/crm/customers/{c['id']}/bonus", {"amount": 10000}).status_code == 400
    assert api.post(f"/api/v1/crm/customers/{c['id']}/bonus", {"amount": -9000, "note": "x"}).status_code == 400
    r = api.post(f"/api/v1/crm/customers/{c['id']}/bonus", {"amount": 10000, "note": "Uzr so'raymiz"})
    assert r.status_code == 200 and r.json()["balance"] == 15000
    assert api.post("/api/v1/crm/customers", {"phone": "+998935550011"}).status_code == 400
    assert api.put("/api/v1/crm/settings", {"gold_from": 100, "silver_from": 500}).status_code == 400


@pytest.mark.django_db
def test_segments_and_search(api, crm):
    with schema_context("lazzat"):
        from modules.crm.models import Customer
        old = timezone.now() - timedelta(days=90)
        Customer.objects.create(phone="+998935550001", name="Uxlagan", orders_count=5, last_order_at=old)
        Customer.objects.create(phone="+998935550002", name="Yangi")
    s = api.get("/api/v1/crm/stats").json()["segments"]
    assert s["sleeping"] == 1 and s["never"] == 1 and s["regular"] == 1
    assert api.get("/api/v1/crm/customers?q=550002").json()["items"][0]["name"] == "Yangi"
    assert api.get("/api/v1/crm/customers?segment=sleeping").json()["total"] == 1


@pytest.mark.django_db
def test_telegram_bonus_button_and_birthday(client, crm):
    def hook(text=None, contact=None):
        m = {"message_id": 1, "chat": {"id": 6100, "type": "private"}, "from": {"id": 6100, "first_name": "Bek"}}
        if text is not None:
            m["text"] = text
        if contact:
            m["contact"] = contact
        import os
        return client.post("/api/v1/telegram/webhook", data=json.dumps({"update_id": 1, "message": m}), content_type="application/json",
                           HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    hook(contact={"phone_number": "998935550011", "user_id": 6100})
    c = _cust()
    assert c.source == "telegram" and c.balance == 5000                                # sovg'a bonus
    hook("25.09.1995")
    c.refresh_from_db()
    assert c.birthday == date(1995, 9, 25)
    assert hook("🎁 Bonuslarim").status_code == 200


@pytest.mark.django_db
def test_module_disabled_404(api, tenant, crm):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "crm"])
    assert api.get("/api/v1/crm/stats").status_code == 404
    with schema_context("public"):
        set_modules(tenant, [*tenant.enabled_modules, "crm"])


@pytest.mark.django_db
def test_dashboard_overview_all_periods(api, crm):
    """Boshqaruv paneli: har bir davr uchun barcha bloklar keladi, bugungi to'lov KPI'ga tushadi."""
    _sell(api, [{"product_id": crm["burger"].pk, "qty": 2}], PHONE)
    for p in ("today", "yesterday", "week", "month", "year"):
        r = api.get(f"/api/v1/dashboard/overview?period={p}")
        assert r.status_code == 200, r.content
        d = r.json()
        assert {k["key"] for k in d["kpis"]} >= {"revenue", "orders", "avg_check", "food_cost", "labor", "net"}
        assert d["series"]["points"] and isinstance(d["activity"], list)
        if p != "yesterday":
            assert d["status"]["total"] >= 1
    d = api.get("/api/v1/dashboard/overview?period=today").json()
    assert next(k for k in d["kpis"] if k["key"] == "revenue")["value"] >= 100000
    assert d["top"][0]["name"] == "CRM burger" and d["recent"][0]["status"] in ("done", "delivered")
