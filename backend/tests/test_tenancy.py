"""Eng muhim test: bir tenant boshqasining ma'lumotini ko'rmaydi; modul o'chirilsa API 404; token boshqa tenantda ishlamaydi."""
import json

import pytest
from django_tenants.utils import schema_context

pytestmark = pytest.mark.django_db


def test_schemas_are_isolated(tenant, other_tenant):
    from modules.catalog.models import Category
    with schema_context(tenant.schema_name):
        Category.objects.create(name={"uz": "Faqat Lazzat"})
        assert Category.objects.filter(name__uz="Faqat Lazzat").exists()
    with schema_context(other_tenant.schema_name):
        assert not Category.objects.filter(name__uz="Faqat Lazzat").exists()


def test_token_bound_to_tenant(client, owner_token):
    r = client.get("/api/v1/me", HTTP_HOST="chopar.testserver", HTTP_AUTHORIZATION=f"Bearer {owner_token}")
    assert r.status_code == 401


def test_owner_can_read_me_and_nav(api):
    r = api.get("/api/v1/me")
    assert r.status_code == 200
    body = r.json()
    assert body["tenant"]["slug"] == "lazzat"
    assert "*" in body["permissions"]
    assert any(n["module"] == "catalog" for n in body["nav"])


def test_disabled_module_returns_404(api, tenant):
    from public.services import set_modules
    set_modules(tenant, [m for m in tenant.enabled_modules if m not in ("cms",)])
    tenant.refresh_from_db()
    assert api.get("/api/v1/cms/settings").status_code == 404
    set_modules(tenant, tenant.enabled_modules + ["cms"])
    assert api.get("/api/v1/cms/settings").status_code == 200


def test_catalog_crud_and_publish(api):
    cats = api.get("/api/v1/catalog/categories").json()
    assert cats, "preset bo'sh kategoriya yaratishi kerak"
    r = api.post("/api/v1/catalog/products", json.dumps({"category_id": cats[0]["id"], "name": {"uz": "Lazzat Burger"}, "price": 36000, "cost": 15400}))
    assert r.status_code == 200, r.content
    pid = r.json()["id"]
    assert r.json()["margin_percent"] == 57.2
    r = api.patch(f"/api/v1/catalog/products/{pid}", json.dumps({"price": 38000}))
    assert r.json()["price"] == 38000
    r = api.post("/api/v1/catalog/publish")
    assert r.status_code == 200 and r.json()["version"] == 1
    pub = api.get("/api/v1/catalog/published").json()
    assert pub["version"] == 1 and pub["categories"][0]["products"][0]["price"] == 38000
    audit = api.get("/api/v1/audit").json()
    assert audit[0]["action"] == "publish"


def test_site_renders_on_all_devices(client, api):
    api.post("/api/v1/catalog/publish")
    for ua in ["Mozilla/5.0 (iPhone)", "Mozilla/5.0 (iPad)", "Mozilla/5.0 (Windows NT 10.0)", "Mozilla/5.0 (SMART-TV; Tizen)"]:
        r = client.get("/", HTTP_HOST="lazzat.testserver", HTTP_USER_AGENT=ua)
        assert r.status_code == 200 and b"Lazzat" in r.content
    assert client.get("/tv/menu-board/", HTTP_HOST="lazzat.testserver").status_code == 200
    assert client.get("/menu/", HTTP_HOST="lazzat.testserver", HTTP_HX_REQUEST="true").status_code == 200


def test_platform_signup(client):
    r = client.post("/api/v1/signup", data=json.dumps({"name": "Yangi Kafe", "slug": "yangi-kafe", "phone": "998911111111", "preset": "cafe"}),
                    content_type="application/json", HTTP_HOST="testserver")
    assert r.status_code == 200, r.content
    assert r.json()["domain"] == "yangi-kafe.testserver"
    assert client.get("/", HTTP_HOST="yangi-kafe.testserver").status_code == 200
