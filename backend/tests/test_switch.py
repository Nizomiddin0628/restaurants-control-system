"""Restoran va filial almashtirgich: /me filiallari, /me/restaurants, bir martalik o'tish havolasi."""
import pytest
from django.core.cache import cache
from django_tenants.utils import schema_context


@pytest.fixture
def two_homes(other_tenant):
    """Lazzat egasi Chopar'da ham menejer bo'lsin."""
    from core.models import Membership, Role, User
    cache.clear()
    with schema_context(other_tenant.schema_name):
        u, _ = User.objects.get_or_create(phone="+998901234567", defaults={"full_name": "Egasi"})
        Membership.objects.get_or_create(user=u, role=Role.objects.get(code="manager"))
    yield
    cache.clear()


@pytest.mark.django_db
def test_me_has_branches(api):
    me = api.get("/api/v1/me").json()
    assert me["branches"] and {"id", "name", "address"} <= set(me["branches"][0])


@pytest.mark.django_db
def test_restaurants_and_switch(api, client, two_homes):
    rows = api.get("/api/v1/me/restaurants").json()
    slugs = {r["slug"]: r for r in rows}
    assert rows[0]["slug"] == "lazzat" and set(slugs) == {"lazzat", "chopar"} and slugs["lazzat"]["current"] and not slugs["chopar"]["current"]
    assert slugs["chopar"]["url"].startswith("http://chopar.testserver") and slugs["chopar"]["url"].endswith("/admin/")

    r = api.post("/api/v1/me/switch", {"slug": "chopar"})
    assert r.status_code == 200
    code = r.json()["url"].split("switch=")[1]
    # boshqa restoranda ishlamaydi
    assert client.post("/api/v1/auth/switch", {"code": code}, content_type="application/json", HTTP_HOST="lazzat.testserver").status_code == 400
    ok = client.post("/api/v1/auth/switch", {"code": code}, content_type="application/json", HTTP_HOST="chopar.testserver")
    assert ok.status_code == 200 and ok.json()["user"]["tenant"]["slug"] == "chopar"
    tok = ok.json()["token"]
    assert client.get("/api/v1/me", HTTP_HOST="chopar.testserver", HTTP_AUTHORIZATION=f"Bearer {tok}").status_code == 200
    # bir martalik
    assert client.post("/api/v1/auth/switch", {"code": code}, content_type="application/json", HTTP_HOST="chopar.testserver").status_code == 400
    assert client.post("/api/v1/auth/switch", {"code": "xato"}, content_type="application/json", HTTP_HOST="chopar.testserver").status_code == 400


@pytest.mark.django_db
def test_switch_denied_without_membership(api):
    cache.clear()
    assert api.post("/api/v1/me/switch", {"slug": "chopar"}).status_code == 404
    assert [r["slug"] for r in api.get("/api/v1/me/restaurants").json()] == ["lazzat"]


@pytest.mark.django_db
def test_set_platform_domain():
    from django.core.management import call_command

    from public.models import Domain
    call_command("set_platform_domain", "demo.example.uz")
    assert Domain.objects.get(domain="lazzat.demo.example.uz").is_primary
    assert Domain.objects.get(domain="demo.example.uz").tenant.schema_name == "public"
    assert not Domain.objects.get(domain="lazzat.testserver").is_primary
    call_command("set_platform_domain", "demo.example.uz")       # qayta ishga tushirsa ham xato yo'q
    assert Domain.objects.filter(domain="lazzat.demo.example.uz").count() == 1
