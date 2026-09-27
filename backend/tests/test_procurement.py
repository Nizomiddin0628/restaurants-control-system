"""
Zakup va bozor xarajatlari: bozorlar ro'yxati, «Nima kerak?» qidiruvi va narx taqqoslash, buyurtma → qisman qabul → omborga kirim,
qarzdorlik va to'lov, bozorlik hisobi (avans, xarajat tannarxga taqsimlanishi, kamomad), bozorchi huquqlari, Moliyaga yozish.
"""
from decimal import Decimal

import pytest
from django_tenants.utils import schema_context


@pytest.fixture
def proc(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "inventory", "procurement", "finance"}))
        tenant.settings = {**(tenant.settings or {}), "modules": {**(tenant.settings or {}).get("modules", {}), "procurement": {"overhead_to_cost": True}}}
        tenant.save(update_fields=["settings"])
    with schema_context("lazzat"):
        from modules.inventory.models import Ingredient, Supplier
        from modules.procurement.models import Order, SupplierPrice, Trip
        Trip.objects.all().delete()
        Order.objects.all().delete()
        SupplierPrice.objects.all().delete()
        s1, _ = Supplier.objects.get_or_create(name="Go'sht aka", defaults={"phone": "+998901112233"})
        s2, _ = Supplier.objects.get_or_create(name="Go'sht MChJ", defaults={"phone": "+998901112244"})
        beef, _ = Ingredient.objects.get_or_create(name={"uz": "Test mol go'shti"}, defaults={"category": "Go'sht", "unit": "kg", "price": 90000})
        onion, _ = Ingredient.objects.get_or_create(name={"uz": "Test piyoz"}, defaults={"category": "Sabzavot", "unit": "kg", "price": 5000})
        Ingredient.objects.filter(pk__in=[beef.pk, onion.pk]).update(stock=0, price=90000)
        Ingredient.objects.filter(pk=onion.pk).update(price=5000)
        yield {"s1": s1.pk, "s2": s2.pk, "beef": beef.pk, "onion": onion.pk}


def _client_for(client, phone, role):
    from core.auth import issue_token
    from core.models import Membership, Role, User
    with schema_context("lazzat"):
        u = User.objects.filter(phone=f"+{phone}").first() or User.objects.create_user(phone, full_name=f"Test {role}")
        Membership.objects.get_or_create(user=u, role=Role.objects.get(code=role))
        tok = issue_token(u, "lazzat")
    h = {"HTTP_HOST": "lazzat.testserver", "HTTP_AUTHORIZATION": f"Bearer {tok}"}

    class C:
        uid = str(u.pk)

        def get(self, url, **kw):
            return client.get(url, **h, **kw)

        def post(self, url, data=None):
            return client.post(url, data=data, content_type="application/json", **h)
    return C()


@pytest.mark.django_db
def test_markets_search_and_price_board(api, proc):
    m = api.get("/api/v1/procurement/markets").json()
    assert len(m) >= 8 and any(x["name"] == "Chorsu bozori" for x in m) and all(x["map_url"].startswith("https://yandex.uz/maps") for x in m)
    chorsu = next(x for x in m if x["name"] == "Chorsu bozori")
    assert api.delete(f"/api/v1/procurement/markets/{chorsu['id']}").json()["disabled"] is True       # tayyor bozor o'chmaydi, faolsizlanadi
    api.put(f"/api/v1/procurement/suppliers/{proc['s1']}", {"name": "Go'sht aka", "kind": "bazaar", "categories": ["meat", "xato"], "telegram": "@goshtaka"})
    s = api.get(f"/api/v1/procurement/suppliers/{proc['s1']}").json()
    assert [c["code"] for c in s["categories"]] == ["meat"] and s["telegram_url"] == "https://t.me/goshtaka"
    for sid, price in ((proc["s1"], 88000), (proc["s2"], 95000), (proc["s1"], 86000)):
        api.post("/api/v1/procurement/prices", {"ingredient_id": proc["beef"], "supplier_id": sid, "price": price})
    b = api.get(f"/api/v1/procurement/prices?ingredient_id={proc['beef']}").json()["board"]
    assert [r["price"] for r in b] == [86000, 95000] and b[0]["rank"] == 1 and b[0]["change"] == pytest.approx(-2.3)
    assert b[1]["vs_best"] == pytest.approx(10.5)
    r = api.get("/api/v1/procurement/search?q=Test+mol").json()
    assert r["offers"][0]["price"] == 86000 and any(x["id"] == proc["s1"] for x in r["suppliers"])
    assert api.post("/api/v1/procurement/prices", {"ingredient_id": proc["beef"], "price": 1000}).status_code == 400   # kimdan — ko'rsatilmagan


@pytest.mark.django_db
def test_order_receive_partial_debt_and_payment(api, proc):
    o = api.post("/api/v1/procurement/orders", {"supplier_id": proc["s1"], "lines": [
        {"ingredient_id": proc["beef"], "qty": 10, "price": 85000}, {"ingredient_id": proc["onion"], "qty": 20, "price": 4000}]}).json()
    assert o["total"] == 930000 and o["status"] == "draft" and "Test mol go'shti — 10 kg" in o["text"]
    assert api.post(f"/api/v1/procurement/orders/{o['id']}/status", {"status": "received"}).status_code == 400   # qabul faqat /receive orqali
    api.post(f"/api/v1/procurement/orders/{o['id']}/status", {"status": "sent"})
    api.post(f"/api/v1/procurement/orders/{o['id']}/status", {"status": "confirmed"})
    beef_line = next(ln for ln in o["lines"] if ln["ingredient_id"] == proc["beef"])
    r = api.post(f"/api/v1/procurement/orders/{o['id']}/receive", {"lines": {str(beef_line["id"]): 8}}).json()   # 2 kg kam keldi
    assert r["status"] == "received" and r["total"] == 8 * 85000 + 20 * 4000
    with schema_context("lazzat"):
        from modules.inventory.models import Ingredient
        assert Ingredient.objects.get(pk=proc["beef"]).stock == Decimal("8")
    assert api.put(f"/api/v1/procurement/orders/{o['id']}", {"supplier_id": proc["s1"], "lines": []}).status_code == 400
    d = api.get("/api/v1/procurement/debts").json()
    row = next(x for x in d["items"] if x["supplier_id"] == proc["s1"])
    assert row["debt"] == 760000 and d["total"] >= 760000
    assert api.post("/api/v1/procurement/payments", {"supplier_id": proc["s1"], "amount": 500000}).json()["debt"] == 260000
    api.post(f"/api/v1/procurement/orders/{o['id']}/rate", {"rating": 4})
    s = api.get("/api/v1/procurement/suppliers").json()["items"]
    assert next(x for x in s if x["id"] == proc["s1"])["rating"] == 4
    b = api.get(f"/api/v1/procurement/prices?ingredient_id={proc['beef']}").json()
    assert b["board"][0]["source"] == "order"                                                   # qabul narxi tarixga yozildi


@pytest.mark.django_db
def test_trip_overhead_to_cost_and_shortage(api, proc):
    t = api.post("/api/v1/procurement/trips", {"advance": 1_000_000, "plan": [{"ingredient_id": proc["beef"], "qty": 10}, {"name": "Shivit", "qty": 2, "unit": "bog'"}]}).json()
    assert t["status"] == "active" and t["planned"] == 2 and t["bought"] == 0
    t = api.post(f"/api/v1/procurement/trips/{t['id']}/items", {"ingredient_id": proc["beef"], "qty": 10, "price": 50000, "seller": "Ahmad aka"}).json()
    assert t["status"] == "active" and len(t["items"]) == 2                                     # rejadagi band to'ldirildi, yangisi qo'shilmadi
    t = api.post(f"/api/v1/procurement/trips/{t['id']}/items", {"ingredient_id": proc["onion"], "qty": 3, "total": 90000}).json()
    onion = next(i for i in t["items"] if i["ingredient_id"] == proc["onion"])
    assert onion["price"] == 30000
    t = api.post(f"/api/v1/procurement/trips/{t['id']}/expenses", {"kind": "taxi", "amount": 50000}).json()
    assert t["spent"] == 640000 and t["balance"] == 360000 and t["overhead_percent"] == pytest.approx(8.5)
    assert t["items_sum"] == 590000 and t["expenses_sum"] == 50000
    t = api.post(f"/api/v1/procurement/trips/{t['id']}/close", {"returned": 350000}).json()
    assert t["status"] == "closed" and t["diff"] == -10000
    assert api.post(f"/api/v1/procurement/trips/{t['id']}/expenses", {"kind": "taxi", "amount": 1}).status_code == 400
    with schema_context("lazzat"):
        from modules.inventory.models import PurchaseLine
        ln = PurchaseLine.objects.filter(ingredient_id=proc["beef"], purchase__note=f"Bozorlik #{t['number']}").get()
        assert ln.unit_price == Decimal("54237.29")                                            # 50 000 + 50 000·500/590/10
    st = api.get("/api/v1/procurement/trip-stats?days=7").json()
    assert st["expenses"] >= 50000 and st["by_kind"][0]["kind"] == "taxi"
    assert any(b["diff"] == -10000 for b in st["by_buyer"])


@pytest.mark.django_db
def test_trip_expense_to_finance_when_not_in_cost(api, proc, tenant):
    with schema_context("public"):
        tenant.settings["modules"]["procurement"]["overhead_to_cost"] = False
        tenant.save(update_fields=["settings"])
    t = api.post("/api/v1/procurement/trips", {"advance": 200000}).json()
    assert t["overhead_to_cost"] is False
    api.post(f"/api/v1/procurement/trips/{t['id']}/items", {"ingredient_id": proc["onion"], "qty": 10, "price": 5000})
    api.post(f"/api/v1/procurement/trips/{t['id']}/expenses", {"kind": "porter", "amount": 20000})
    api.post(f"/api/v1/procurement/trips/{t['id']}/close", {"returned": 130000})
    with schema_context("lazzat"):
        from modules.finance.models import Expense
        from modules.inventory.models import PurchaseLine
        assert Expense.objects.filter(category__code="market", amount=20000).exists()
        assert PurchaseLine.objects.filter(ingredient_id=proc["onion"], purchase__note=f"Bozorlik #{t['number']}").get().unit_price == Decimal("5000")


@pytest.mark.django_db
def test_buyer_permissions(client, api, proc):
    buyer = _client_for(client, "998935557788", "buyer")
    other = api.post("/api/v1/procurement/trips", {"advance": 100000}).json()                # egasining bozorligi
    assert buyer.post("/api/v1/procurement/orders", {"supplier_id": proc["s1"], "lines": [{"ingredient_id": proc["beef"], "qty": 1}]}).status_code == 403
    assert buyer.post("/api/v1/procurement/trips", {"advance": 1, "buyer_id": other["buyer_id"]}).status_code == 403
    mine = buyer.post("/api/v1/procurement/trips", {"advance": 300000}).json()
    assert mine["buyer_id"] == buyer.uid
    assert [t["id"] for t in buyer.get("/api/v1/procurement/trips").json()] == [mine["id"]]
    assert buyer.get(f"/api/v1/procurement/trips/{other['id']}").status_code == 403
    assert buyer.post(f"/api/v1/procurement/trips/{mine['id']}/items", {"ingredient_id": proc["onion"], "qty": 5, "price": 5000}).status_code == 200
    assert buyer.post(f"/api/v1/procurement/trips/{mine['id']}/close", {"returned": 275000}).status_code == 403   # kassir/menejer yopadi
    assert api.post(f"/api/v1/procurement/trips/{mine['id']}/close", {"returned": 275000}).json()["diff"] == 0
    meta = buyer.get("/api/v1/procurement/meta").json()
    assert meta["can_edit"] is False and [b["id"] for b in meta["buyers"]] == [buyer.uid]


@pytest.mark.django_db
def test_module_disabled(api, proc, tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "procurement"])
    assert api.get("/api/v1/procurement/overview").status_code in (403, 404)
