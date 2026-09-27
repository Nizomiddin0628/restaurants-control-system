"""Parol bilan kirish: o'rnatish, kirish, xato urinishlar cheklovi, rahbar xodimga parol qo'yishi."""
import pytest
from django.core.cache import cache
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


def _login(client, phone, pw):
    return client.post("/api/v1/auth/login", {"phone": phone, "password": pw}, content_type="application/json", **H)


@pytest.mark.django_db
def test_password_flow(api, client):
    cache.clear()
    assert _login(client, "+998901234567", "sirli123").status_code == 400          # hali parol yo'q
    assert api.get("/api/v1/me").json()["has_password"] is False
    assert api.post("/api/v1/me/password", {"new_password": "123"}).status_code == 400
    assert api.post("/api/v1/me/password", {"new_password": "sirli123"}).status_code == 200
    r = _login(client, "998 90 123 45 67", "sirli123")
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True and r.json()["token"]
    assert api.post("/api/v1/me/password", {"old_password": "xato", "new_password": "yangi1234"}).status_code == 400
    assert api.post("/api/v1/me/password", {"old_password": "sirli123", "new_password": "yangi1234"}).status_code == 200
    assert _login(client, "+998901234567", "sirli123").status_code == 400
    assert _login(client, "+998901234567", "yangi1234").status_code == 200


@pytest.mark.django_db
def test_bruteforce_limit(api, client):
    cache.clear()
    api.post("/api/v1/me/password", {"new_password": "togri123"})
    for _ in range(8):
        assert _login(client, "+998901234567", "noto'g'ri").status_code == 400
    assert _login(client, "+998901234567", "togri123").status_code == 429
    cache.clear()


@pytest.mark.django_db
def test_manager_sets_staff_password(api, client):
    cache.clear()
    r = api.post("/api/v1/users", {"phone": "+998935550011", "full_name": "Kassir", "role_code": "cashier", "password": "kassa2026"})
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert _login(client, "+998935550011", "kassa2026").status_code == 200
    uid = r.json()["id"]
    assert api.post(f"/api/v1/users/{uid}/password", {"password": "boshqa999"}).status_code == 200
    assert _login(client, "+998935550011", "boshqa999").status_code == 200


@pytest.mark.django_db
def test_user_access_command(tenant):
    from django.core.management import call_command
    cache.clear()
    call_command("user_access", "--slug", "lazzat", "--phone", "+998888203830", "--password", "egasi123", "--role", "owner", "--name", "Nizomiddin")
    with schema_context("lazzat"):
        from core.models import User
        u = User.objects.get(phone="+998888203830")
        assert u.check_password("egasi123") and u.memberships.filter(role__code="owner").exists()


@pytest.mark.django_db
def test_generate_password_and_telegram(api, client, tenant, monkeypatch):
    """Rahbar «parol yaratish» bosadi → 6 xonali parol; xodim botga ulangan bo'lsa — Telegram'ga ham boradi. SMS kod ham Telegram'ga."""
    from public.services import set_modules
    sent = []
    monkeypatch.setattr("modules.telegram.services.send_message", lambda chat_id, text, **kw: sent.append((chat_id, text)) or True)
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "telegram"}))
        tenant.settings = {**(tenant.settings or {}), "modules": {**((tenant.settings or {}).get("modules") or {}), "telegram": {"bot_token": "123:abc"}}}
        tenant.save(update_fields=["settings"])
    cache.clear()
    r = api.post("/api/v1/users", {"phone": "+998935550022", "full_name": "Ofitsiant", "role_code": "cashier"})
    uid = r.json()["id"]
    g = api.post(f"/api/v1/users/{uid}/password", {"generate": True}).json()
    assert len(g["password"]) == 6 and g["password"].isdigit() and g["login_url"].endswith("/admin/login") and g["telegram_sent"] is False
    assert _login(client, "+998935550022", g["password"]).status_code == 200
    with schema_context("lazzat"):
        from core.models import User
        User.objects.filter(pk=uid).update(telegram_id=555)
    g2 = api.post(f"/api/v1/users/{uid}/password", {"generate": True}).json()
    assert g2["telegram_sent"] is True and sent[-1][0] == 555 and g2["password"] in sent[-1][1]
    o = client.post("/api/v1/auth/otp", {"phone": "+998935550022"}, content_type="application/json", **H).json()
    assert o["via"] == "telegram" and "kirish kodi" in sent[-1][1]
