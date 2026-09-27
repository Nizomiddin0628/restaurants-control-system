"""
RESTROOS HQ: faqat jamoa kiradi (restoran tokeni o'tmaydi), umumiy ko'rsatkichlar, rozilik bo'lmasa daromad yashirin,
panelga kirish faqat egasi ruxsati bilan (+ jurnal, egasi ko'radi), murojaatlar ikki tomonlama, billing va muddat o'tishi.
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

PUB = {"HTTP_HOST": "testserver"}


@pytest.fixture
def hq(client, tenant):
    from core.models import User
    from public.models import PlatformStaff
    with schema_context("public"):
        u, _ = User.objects.get_or_create(phone="+998900001122", defaults={"full_name": "HQ Admin"})
        PlatformStaff.objects.update_or_create(user=u, defaults={"role": "superadmin", "is_active": True})
    code = client.post("/api/v1/hq/auth/otp", {"phone": "900001122"}, content_type="application/json", **PUB).json()["dev_code"]
    tok = client.post("/api/v1/hq/auth/verify", {"phone": "900001122", "code": code}, content_type="application/json", **PUB).json()["token"]

    class H:
        h = {**PUB, "HTTP_AUTHORIZATION": f"Bearer {tok}"}

        def get(self, url, **kw):
            return client.get(url, **self.h, **kw)

        def post(self, url, data=None):
            return client.post(url, data=data or {}, content_type="application/json", **self.h)

        def put(self, url, data=None):
            return client.put(url, data=data or {}, content_type="application/json", **self.h)
    return H()


@pytest.mark.django_db
def test_only_staff_and_no_tenant_tokens(client, hq, owner_token):
    assert client.post("/api/v1/hq/auth/otp", {"phone": "901234567"}, content_type="application/json", **PUB).status_code == 404
    assert client.get("/api/v1/hq/overview", HTTP_AUTHORIZATION=f"Bearer {owner_token}", **PUB).status_code == 401
    me = hq.get("/api/v1/hq/me").json()
    assert me["role"] == "superadmin"


@pytest.mark.django_db
def test_overview_tenants_and_consent(hq, api, tenant):
    o = hq.get("/api/v1/hq/overview").json()
    assert o["kpis"]["clients"] >= 2 and {"healthy", "warning", "critical"} <= set(o["health"])
    items = hq.get("/api/v1/hq/tenants").json()["items"]
    lz = next(x for x in items if x["slug"] == "lazzat")
    assert lz["shares_finance"] is True and lz["branches"] >= 1
    assert api.put("/api/v1/platform/consent", {"share_finance": False, "showcase": False}).status_code == 200
    lz = next(x for x in hq.get("/api/v1/hq/tenants").json()["items"] if x["slug"] == "lazzat")
    assert lz["revenue_30d"] is None and lz["shares_finance"] is False
    d = hq.get(f"/api/v1/hq/tenants/{tenant.pk}").json()
    assert d["series"] == [] and all(b["revenue_30d"] is None for b in d["branches_list"])


@pytest.mark.django_db
def test_support_access_flow(client, hq, api, tenant):
    r = hq.post(f"/api/v1/hq/tenants/{tenant.pk}/impersonate", {"reason": "murojaat #1"})
    assert r.status_code == 403
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/access-request", {"reason": "kassa xatosi"}).status_code == 200
    st = api.get("/api/v1/platform/status").json()
    assert st["access_request"]["reason"] == "kassa xatosi" and st["access"] is None
    assert api.post("/api/v1/platform/access", {"hours": 100}).status_code == 400
    assert api.post("/api/v1/platform/access", {"hours": 2}).status_code == 200
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/impersonate", {"reason": " "}).status_code == 400
    r = hq.post(f"/api/v1/hq/tenants/{tenant.pk}/impersonate", {"reason": "murojaat #1"}).json()
    me = client.get("/api/v1/me", HTTP_HOST="lazzat.testserver", HTTP_AUTHORIZATION=f"Bearer {r['token']}").json()
    assert "platform_support" in me["roles"]
    sup = {"HTTP_HOST": "lazzat.testserver", "HTTP_AUTHORIZATION": f"Bearer {r['token']}"}
    assert client.post("/api/v1/platform/access", {"hours": 72}, content_type="application/json", **sup).status_code == 403   # o'ziga ruxsat uzaytira olmaydi
    st = api.get("/api/v1/platform/status").json()
    assert st["sessions"][0]["reason"] == "murojaat #1" and st["access_request"] is None
    with schema_context("lazzat"):
        from core.models import AuditLog
        assert AuditLog.objects.filter(action="support_login").exists()
    assert api.delete("/api/v1/platform/access").status_code == 200
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/impersonate", {"reason": "yana"}).status_code == 403


@pytest.mark.django_db
def test_tickets_both_sides(hq, api):
    assert api.post("/api/v1/platform/tickets", {"subject": " "}).status_code == 400
    t = api.post("/api/v1/platform/tickets", {"subject": "Chek chiqmayapti", "priority": "critical"}).json()
    lst = hq.get("/api/v1/hq/tickets", status="open").json()
    assert any(x["number"] == t["number"] for x in lst["items"]) and lst["counts"]["open"] >= 1
    r = hq.post(f"/api/v1/hq/tickets/{t['id']}/messages", {"body": "Printerni qayta ulang"}).json()
    assert r["status"] == "progress" and r["assigned"] == "HQ Admin"
    mine = api.get(f"/api/v1/platform/tickets/{t['id']}").json()
    assert mine["messages"][-1]["from_staff"] and "Printerni" in mine["messages"][-1]["body"]
    assert api.post(f"/api/v1/platform/tickets/{t['id']}/messages", {"body": "Rahmat!", "close": True}).json()["status"] == "closed"


@pytest.mark.django_db
def test_billing_plan_trial_modules(client, hq, tenant, owner_token):
    from public import hq as H
    from public.models import Invoice, InvoiceStatus, Plan, Tenant
    with schema_context("public"):
        plan, _ = Plan.objects.get_or_create(code="pro_t", defaults={"name": "Pro", "price_per_branch": 490_000, "allowed_modules": ["*"]})
        Tenant.objects.filter(pk=tenant.pk).update(trial_ends_at=timezone.now() - timedelta(days=1), plan=plan)
        H.ensure_invoices()
        i = Invoice.objects.get(tenant_id=tenant.pk, period=timezone.localdate().replace(day=1))
        assert i.amount > 0 and i.status == InvoiceStatus.PENDING
        i.due_date = timezone.localdate() - timedelta(days=20)
        i.save()
        H.ensure_invoices()
        i.refresh_from_db()
        assert i.status == InvoiceStatus.OVERDUE
    d = hq.get(f"/api/v1/hq/tenants/{tenant.pk}").json()
    assert d["health"] == "critical" and any("15 kun" in r for r in d["reasons"])
    assert hq.post(f"/api/v1/hq/invoices/{i.pk}/status", {"status": "paid"}).json()["status"] == "paid"
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/plan", {"plan_code": "nope"}).status_code == 404
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/trial", {"days": 500}).status_code == 400
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/trial", {"days": 7}).status_code == 200
    mods = [m["code"] for m in d["modules"] if m["enabled"] and m["code"] != "crm"]
    assert "crm" not in hq.put(f"/api/v1/hq/tenants/{tenant.pk}/modules", {"codes": mods}).json()["enabled"]
    assert hq.get("/api/v1/hq/health").json()["percent"] > 0
    assert hq.post(f"/api/v1/hq/tenants/{tenant.pk}/status", {"is_active": False}).status_code == 200
    r = client.get("/api/v1/me", HTTP_HOST="lazzat.testserver", HTTP_AUTHORIZATION=f"Bearer {owner_token}")
    assert r.status_code == 403 and "to'xtatilgan" in r.json()["detail"]
    hq.post(f"/api/v1/hq/tenants/{tenant.pk}/status", {"is_active": True})
    assert client.get("/api/v1/me", HTTP_HOST="lazzat.testserver", HTTP_AUTHORIZATION=f"Bearer {owner_token}").status_code == 200
    assert any(a["action"] == "trial" for a in hq.get("/api/v1/hq/audit").json())
