"""
Operatsion modullar: ombor→tannarx, kassa→ombor→P&L zanjiri, oylik, Payme/Click protokollari.
"""
import base64
import hashlib
import json
from decimal import Decimal

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


@pytest.fixture
def ops(tenant):
    """Barcha operatsion modullarni yoqadi va bitta taom + tex-karta tayyorlaydi."""
    from public.services import set_modules

    set_modules(tenant, ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance"])
    with schema_context("lazzat"):
        from modules.catalog.models import Category, Product
        from modules.inventory.models import Ingredient, Recipe, RecipeLine

        cat, _ = Category.objects.get_or_create(name={"uz": "Test", "ru": "", "en": ""})
        p, _ = Product.objects.get_or_create(name={"uz": "Test burger", "ru": "", "en": ""}, defaults={"category": cat, "price": 30_000})
        meat, _ = Ingredient.objects.get_or_create(name={"uz": "Go'sht", "ru": "", "en": ""}, defaults={"unit": "kg", "price": 100_000, "stock": 10, "min_stock": 1})
        bun, _ = Ingredient.objects.get_or_create(name={"uz": "Non", "ru": "", "en": ""}, defaults={"unit": "dona", "price": 2_000, "stock": 50})
        r, _ = Recipe.objects.get_or_create(product=p)
        r.lines.all().delete()
        RecipeLine.objects.create(recipe=r, ingredient=meat, qty=Decimal(100), waste_percent=Decimal(0))   # 100 g → 10 000
        RecipeLine.objects.create(recipe=r, ingredient=bun, qty=Decimal(1))                                 # 1 dona → 2 000
        yield {"product": p, "meat": meat, "bun": bun, "recipe": r}


@pytest.mark.django_db
def test_recipe_cost_and_price_change(api, ops):
    """Tex-karta: 100 g go'sht (100 000/kg) + non (2 000) = 12 000. Go'sht qimmatlashsa — tannarx o'zi yangilanadi."""
    r = api.put(f"/api/v1/inventory/recipes/{ops['product'].pk}", {"yield_qty": 1, "note": "", "lines": [
        {"ingredient_id": ops["meat"].pk, "qty": 100, "waste_percent": 0}, {"ingredient_id": ops["bun"].pk, "qty": 1, "waste_percent": 0}]})
    assert r.status_code == 200, r.content
    assert r.json()["cost"] == 12000 and r.json()["food_cost_percent"] == 40.0
    with schema_context("lazzat"):
        ops["product"].refresh_from_db()
        assert ops["product"].cost == 12000
    # bozorlik: go'sht 120 000 bo'ldi (oxirgi narx/o'rtacha — 10 kg eski 100k + 10 kg yangi 120k → 110k)
    r = api.post("/api/v1/inventory/purchases", {"lines": [{"ingredient_id": ops["meat"].pk, "qty": 10, "unit_price": 120_000}]})
    assert r.status_code == 200, r.content
    with schema_context("lazzat"):
        ops["product"].refresh_from_db()
        assert ops["product"].cost == 13000        # 100 g × 110 000 + 2 000


@pytest.mark.django_db
def test_pos_sale_deducts_stock_and_feeds_pnl(api, ops):
    """Kassa: buyurtma → to'lov → ombor kamayadi → P&L daromad va tannarxni ko'radi."""
    api.put(f"/api/v1/inventory/recipes/{ops['product'].pk}", {"yield_qty": 1, "note": "", "lines": [
        {"ingredient_id": ops["meat"].pk, "qty": 100, "waste_percent": 0}, {"ingredient_id": ops["bun"].pk, "qty": 1, "waste_percent": 0}]})
    r = api.post("/api/v1/pos/orders", {"items": [{"product_id": ops["product"].pk, "qty": 2}], "type": "takeaway"})
    assert r.status_code == 200, r.content
    o = r.json()
    assert o["total"] == 60_000 and o["cost_total"] == 24_000 and o["status"] == "open"
    r = api.post(f"/api/v1/pos/orders/{o['id']}/pay", {"payment_method": "cash"})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    with schema_context("lazzat"):
        ops["meat"].refresh_from_db(); ops["bun"].refresh_from_db()
        assert ops["meat"].stock == Decimal("9.800") and ops["bun"].stock == 48
    today = timezone.localdate().isoformat()
    p = api.get(f"/api/v1/finance/pnl?start={today}&end={today}").json()
    assert p["revenue"] >= 60_000 and p["cogs"] >= 24_000 and p["food_cost_percent"] > 0
    d = api.get(f"/api/v1/finance/dashboard?start={today}&end={today}").json()
    assert any(t["name"] == "Test burger" for t in d["top_products"])


@pytest.mark.django_db
def test_shift_close_requires_no_open_orders(api, ops):
    s = api.post("/api/v1/pos/shift/open", {"cash_start": 100_000}).json()
    o = api.post("/api/v1/pos/orders", {"items": [{"product_id": ops["product"].pk, "qty": 1}]}).json()
    r = api.post(f"/api/v1/pos/shift/{s['id']}/close", {"cash_end": 100_000})
    assert r.status_code == 400
    api.post(f"/api/v1/pos/orders/{o['id']}/pay", {"payment_method": "cash"})
    r = api.post(f"/api/v1/pos/shift/{s['id']}/close", {"cash_end": 125_000})
    assert r.status_code == 200
    assert r.json()["totals"]["expected_cash"] == 130_000 and r.json()["totals"]["cash_diff"] == -5_000


@pytest.mark.django_db
def test_payroll_compute_by_salary_type(api, ops):
    r = api.post("/api/v1/hr/employees", {"full_name": "Test Kassir", "phone": "+998900000001", "role_code": "cashier",
                                          "salary_type": "shift", "rate": 150_000})
    assert r.status_code == 200, r.content
    e = r.json()
    api.post(f"/api/v1/hr/attendance/check-in?employee_id={e['id']}")
    api.post(f"/api/v1/hr/attendance/check-out?employee_id={e['id']}")
    slips = api.post("/api/v1/hr/payroll/compute").json()
    mine = [s for s in slips if s["employee_id"] == e["id"]][0]
    assert mine["salary_type"] == "shift" and mine["shifts"] == 1 and mine["base"] == 150_000
    r = api.patch(f"/api/v1/hr/payroll/{mine['id']}", {"bonus": 50_000, "advance": 20_000})
    assert r.json()["total"] == 180_000
    r = api.post(f"/api/v1/hr/payroll/{mine['id']}/status?status=paid")
    assert r.json()["status"] == "paid"
    r = api.patch(f"/api/v1/hr/payroll/{mine['id']}", {"bonus": 1})
    assert r.status_code == 400     # to'langanni o'zgartirib bo'lmaydi


def _payme(client, method, params, key="testkey", rid=1):
    auth = "Basic " + base64.b64encode(f"Paycom:{key}".encode()).decode()
    return client.post("/api/v1/payments/payme", data=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}),
                       content_type="application/json", HTTP_AUTHORIZATION=auth, **H).json()


@pytest.mark.django_db
def test_payme_merchant_flow(api, client, tenant, ops):
    """Payme: Check → Create → Perform → buyurtma to'langan; noto'g'ri parol → -32504; noto'g'ri summa → -31001."""
    tenant.settings = {**(tenant.settings or {}), "payments": {"payme_merchant_id": "m1", "payme_key": "testkey", "payme_test": True}}
    tenant.save()
    o = api.post("/api/v1/pos/orders", {"items": [{"product_id": ops["product"].pk, "qty": 1}]}).json()
    acc = {"order_id": str(o["number"])}
    assert _payme(client, "CheckPerformTransaction", {"amount": 1, "account": acc})["error"]["code"] == -31001
    assert _payme(client, "CheckPerformTransaction", {"amount": 30_000 * 100, "account": acc}, key="wrong")["error"]["code"] == -32504
    assert _payme(client, "CheckPerformTransaction", {"amount": 30_000 * 100, "account": acc})["result"]["allow"] is True
    cr = _payme(client, "CreateTransaction", {"id": "tx1", "time": 1700000000000, "amount": 30_000 * 100, "account": acc})["result"]
    assert cr["state"] == 1
    # takroriy Create — o'sha tranzaksiya qaytadi (idempotent)
    assert _payme(client, "CreateTransaction", {"id": "tx1", "time": 1700000000000, "amount": 30_000 * 100, "account": acc})["result"]["transaction"] == cr["transaction"]
    pf = _payme(client, "PerformTransaction", {"id": "tx1"})["result"]
    assert pf["state"] == 2 and pf["perform_time"] > 0
    assert api.get(f"/api/v1/pos/orders/{o['id']}").json()["status"] == "paid"
    ck = _payme(client, "CheckTransaction", {"id": "tx1"})["result"]
    assert ck["state"] == 2
    st = _payme(client, "GetStatement", {"from": 0, "to": 9999999999999})["result"]["transactions"]
    assert any(t["id"] == "tx1" for t in st)
    assert _payme(client, "CheckTransaction", {"id": "nope"})["error"]["code"] == -31003


@pytest.mark.django_db
def test_click_prepare_complete(api, client, tenant, ops):
    """Click: imzo tekshiruvi, Prepare → Complete → buyurtma to'langan."""
    tenant.settings = {**(tenant.settings or {}), "payments": {"click_service_id": "123", "click_merchant_id": "9", "click_secret_key": "sec"}}
    tenant.save()
    o = api.post("/api/v1/pos/orders", {"items": [{"product_id": ops["product"].pk, "qty": 1}]}).json()
    d = {"click_trans_id": "555", "service_id": "123", "click_paydoc_id": "1", "merchant_trans_id": str(o["number"]),
         "amount": "30000.00", "action": "0", "error": "0", "error_note": "", "sign_time": "2026-09-20 12:00:00"}
    d["sign_string"] = "bad"
    assert client.post("/api/v1/payments/click/prepare", d, **H).json()["error"] == -1
    d["sign_string"] = hashlib.md5("".join([d["click_trans_id"], d["service_id"], "sec", d["merchant_trans_id"], d["amount"], d["action"], d["sign_time"]]).encode()).hexdigest()
    r = client.post("/api/v1/payments/click/prepare", d, **H).json()
    assert r["error"] == 0 and r["merchant_prepare_id"]
    c = {**d, "action": "1", "merchant_prepare_id": str(r["merchant_prepare_id"])}
    c["sign_string"] = hashlib.md5("".join([c["click_trans_id"], c["service_id"], "sec", c["merchant_trans_id"], c["merchant_prepare_id"], c["amount"], c["action"], c["sign_time"]]).encode()).hexdigest()
    r2 = client.post("/api/v1/payments/click/complete", c, **H).json()
    assert r2["error"] == 0
    assert api.get(f"/api/v1/pos/orders/{o['id']}").json()["status"] == "paid"
    assert client.post("/api/v1/payments/click/complete", c, **H).json()["error"] == -4   # ikkinchi marta — allaqachon to'langan


@pytest.mark.django_db
def test_telegram_webhook_links_user_by_contact(client, tenant, ops):
    import os

    os.environ["TELEGRAM_WEBHOOK_SECRET"] = "s3"
    upd = {"message": {"chat": {"id": 777}, "contact": {"phone_number": "+998901234567"}}}
    r = client.post("/api/v1/telegram/webhook", data=json.dumps(upd), content_type="application/json",
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3", **H)
    assert r.status_code == 200
    with schema_context("lazzat"):
        from core.models import User
        assert User.objects.get(phone="+998901234567").telegram_id == 777
    bad = client.post("/api/v1/telegram/webhook", data="{}", content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="x", **H)
    assert bad.status_code == 403
