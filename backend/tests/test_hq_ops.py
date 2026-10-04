"""
HQ operatsiyalari (v48): shartnoma bilan restoran ochish, shartnoma → billing (valyuta, to'lov kuni, bepul davr),
to'lov kalendari, hudud va chegaralar (filial limiti), restoranga xos funksiya bayrog'i, vazifalar doskasi (kanban).
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from tests.test_hq import hq  # noqa: F401  (fixture)


@pytest.mark.django_db
def test_create_tenant_with_contract_and_billing(hq, monkeypatch):  # noqa: F811
    sent = []
    import website.sales_ai as sa
    monkeypatch.setattr(sa, "notify", lambda text, target=None: sent.append(text) or True)
    refs = hq.get("/api/v1/hq/refs").json()
    assert any(r["name"] == "Toshkent shahri" and "Chilonzor" in r["districts"] for r in refs["regions"])
    bad = hq.post("/api/v1/hq/tenants", {"name": "X", "slug": "lazzat", "owner_phone": "901112233"})
    assert bad.status_code == 409
    assert hq.post("/api/v1/hq/tenants", {"name": "X", "slug": "xx-yy", "owner_phone": "12"}).status_code == 400
    r = hq.post("/api/v1/hq/tenants", {"name": "Somsa Markazi", "slug": "somsa-markazi", "preset": "cafe", "owner_name": "Sardor", "owner_phone": "90 777 66 55",
                                       "region": "Samarqand viloyati", "district": "Samarqand sh.", "branches": ["Markaz", "Siyob"], "free_days": 14,
                                       "contract": {"tariff": "ai", "price": 140, "currency": "USD", "billing_day": 7, "extra_branch_price": 40, "inn": "305123456"}})
    assert r.status_code == 200, r.content
    j = r.json()
    assert j["contract"]["number"].startswith("RP-") and j["branches"] == ["Markaz", "Siyob"] and sent and "Somsa Markazi" in sent[-1]
    from public import hq as H
    from public.models import Contract, Invoice, Tenant
    with schema_context("public"):
        t = Tenant.objects.get(slug="somsa-markazi")
        assert t.region == "Samarqand viloyati" and t.module_enabled("ai") and (t.plan is None or t.plan.allows("ai"))
    with schema_context(t.schema_name):
        from core.models import Branch, User
        assert Branch.objects.count() == 2 and User.objects.filter(phone="+998907776655").exists()
    d = hq.get(f"/api/v1/hq/tenants/{t.pk}").json()
    assert d["tariff_label"] == "Dastur + AI Kotib" and d["price"] == 180 and d["currency"] == "USD"           # 140 + 1 × 40
    assert d["next_payment"]["state"] == "trial" and d["next_payment"]["amount"] == 180 and d["next_payment"]["date"][8:10] == "07"
    with schema_context("public"):
        H.ensure_invoices()
        assert not Invoice.objects.filter(tenant=t).exists()                                                   # bepul davr
        Contract.objects.filter(tenant=t).update(paid_from=timezone.localdate() - timedelta(days=60))
        t = Tenant.objects.get(pk=t.pk)
        H.ensure_invoices()
        i = Invoice.objects.get(tenant=t, period=timezone.localdate().replace(day=1))
        assert (i.amount, i.currency, i.due_date.day) == (180, "USD", 7)
    # shartnomani o'zgartirish — to'lanmagan hisob yangilanadi, AI o'chadi
    r = hq.put(f"/api/v1/hq/tenants/{t.pk}/contract", {"tariff": "base", "price": 1_200_000, "currency": "UZS", "billing_day": 7,
                                                        "paid_from": (timezone.localdate() - timedelta(days=60)).isoformat()})
    assert r.status_code == 200 and r.json()["tariff"] == "base"
    with schema_context("public"):
        i.refresh_from_db()
        assert (i.amount, i.currency) == (1_200_000, "UZS") and not Tenant.objects.get(pk=t.pk).module_enabled("ai")
    assert hq.put(f"/api/v1/hq/tenants/{t.pk}/contract", {"billing_day": 31}).status_code == 400
    b = hq.get("/api/v1/hq/billing").json()
    assert b["summary"]["month_total"]["UZS"] >= 1_200_000 and b["summary"]["month_total"]["usd_eq"] > 0
    up = hq.get("/api/v1/hq/payments/upcoming").json()["items"]
    assert any(x["tenant_id"] == t.pk and x["currency"] == "UZS" for x in up)
    pay = hq.post(f"/api/v1/hq/invoices/{i.pk}/status", {"status": "paid", "method": "bank"}).json()
    assert pay["status"] == "paid" and pay["method"] == "bank"
    reg = hq.get("/api/v1/hq/regions").json()["items"]
    assert any(x["region"] == "Samarqand viloyati" and x["tenants"] == 1 for x in reg)
    assert any(x["slug"] == "somsa-markazi" for x in hq.get("/api/v1/hq/tenants", region="Samarqand viloyati").json()["items"])


@pytest.mark.django_db
def test_profile_limits_and_tenant_flags(hq, api, tenant):  # noqa: F811
    from core.features import flag_on, reset_cache
    from public.models import FeatureFlag, Tenant
    with schema_context("public"):
        FeatureFlag.objects.create(code="kds_v2", name="Yangi oshxona ekrani")
    reset_cache()
    r = hq.put(f"/api/v1/hq/tenants/{tenant.pk}/profile", {"region": "Toshkent shahri", "district": "Chilonzor", "max_branches": 1})
    assert r.status_code == 200 and r.json()["limits"] == {"branches": 1}
    res = api.post("/api/v1/branches", {"name": "Ikkinchi filial"})
    assert res.status_code == 403 and "Shartnoma" in res.json()["detail"]
    hq.put(f"/api/v1/hq/tenants/{tenant.pk}/profile", {"region": "Toshkent shahri", "max_branches": 0})
    flags = hq.put(f"/api/v1/hq/tenants/{tenant.pk}/flags", {"codes": ["kds_v2"]}).json()
    assert next(f for f in flags if f["code"] == "kds_v2")["on"] is True
    with schema_context("public"):
        assert flag_on(Tenant.objects.get(pk=tenant.pk), "kds_v2") and not flag_on(Tenant.objects.get(slug="chopar"), "kds_v2")
    hq.put(f"/api/v1/hq/tenants/{tenant.pk}/flags", {"codes": []})
    with schema_context("public"):
        assert not flag_on(Tenant.objects.get(pk=tenant.pk), "kds_v2")


@pytest.mark.django_db
def test_board_cards_move_and_sla(hq, api, tenant, monkeypatch):  # noqa: F811
    sent = []
    import website.sales_ai as sa
    monkeypatch.setattr(sa, "notify", lambda text, target=None: sent.append(text) or True)
    # restoran murojaati → HQ Telegram
    k = api.post("/api/v1/platform/tickets", {"subject": "Printer ishlamayapti", "priority": "critical"})
    assert k.status_code == 200 and sent and "🔴" in sent[-1] and "Printer" in sent[-1]
    # ichki vazifa (restoransiz)
    c = hq.post("/api/v1/hq/tickets", {"subject": "Zaxira nusxani tekshirish", "kind": "task", "priority": "low"}).json()
    assert c["tenant"] == "Ichki vazifa" and c["due_at"]
    assert hq.post("/api/v1/hq/tickets", {"subject": " "}).status_code == 400
    b = hq.get("/api/v1/hq/board").json()
    open_col = next(x for x in b["columns"] if x["code"] == "open")
    assert {x["subject"] for x in open_col["items"]} >= {"Printer ishlamayapti", "Zaxira nusxani tekshirish"}
    m = hq.post(f"/api/v1/hq/tickets/{c['id']}/move", {"status": "progress"}).json()
    assert m["status"] == "progress" and m["assigned"]                                                 # olgan odam mas'ul bo'ladi
    crit = next(x for x in open_col["items"] if x["subject"] == "Printer ishlamayapti")
    hq.post(f"/api/v1/hq/tickets/{crit['id']}/move", {"status": "progress", "before_id": c["id"]})
    prog = next(x for x in hq.get("/api/v1/hq/board").json()["columns"] if x["code"] == "progress")["items"]
    assert [x["id"] for x in prog].index(crit["id"]) < [x["id"] for x in prog].index(c["id"])         # ustiga qo'yildi
    late = (timezone.now() - timedelta(hours=1)).isoformat()
    u = hq.put(f"/api/v1/hq/tickets/{c['id']}", {"due_at": late, "kind": "bug"}).json()
    assert u["kind"] == "bug"
    card = next(x for col in hq.get("/api/v1/hq/board").json()["columns"] for x in col["items"] if x["id"] == c["id"])
    assert card["sla"] == "late" and hq.get("/api/v1/hq/board").json()["late"] >= 1
    assert hq.post(f"/api/v1/hq/tickets/{c['id']}/move", {"status": "closed"}).json()["status"] == "closed"
    from public.hq import daily_tick
    r = daily_tick(force=True)
    assert r is not None
