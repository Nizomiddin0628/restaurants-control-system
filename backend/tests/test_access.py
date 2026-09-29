"""
v33 — kirish tizimi: ierarxiya (Superadmin → Bosh menejer → Filial menejeri → xodim), bir nechta rol,
shaxsiy ruxsatlar, filial doirasi, AI Kotib o'rinlari, Telegram orqali kirish, founder/developer to'g'ridan-to'g'ri kirishi,
webhook doim 200.
"""
import json

import pytest
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


def _as(client, phone):
    from core.auth import issue_token
    from core.models import User
    with schema_context("lazzat"):
        tok = issue_token(User.objects.get(phone=phone), "lazzat")

    class C:
        h = {**H, "HTTP_AUTHORIZATION": f"Bearer {tok}"}

        def get(self, url, **kw):
            return client.get(url, **self.h, **kw)

        def post(self, url, data=None):
            return client.post(url, data=data or {}, content_type="application/json", **self.h)

        def put(self, url, data=None):
            return client.put(url, data=data or {}, content_type="application/json", **self.h)
    return C()


@pytest.fixture
def branches(tenant):
    with schema_context("lazzat"):
        from core.models import Branch
        b1 = Branch.objects.filter(deleted_at__isnull=True).order_by("id").first()
        b2, _ = Branch.objects.get_or_create(name="Chilonzor filiali")
        return b1.pk, b2.pk


@pytest.mark.django_db
def test_meta_roles_and_levels(api):
    m = api.get("/api/v1/access/meta").json()
    codes = {r["code"]: r for r in m["roles"]}
    assert codes["owner"]["level"] == 100 and codes["general_manager"]["level"] == 80 and codes["manager"]["level"] == 60
    assert "platform_support" not in codes and m["me"]["level"] == 100 and m["me"]["all_branches"]
    assert any(a["code"] == "pos" for a in m["areas"]) and all(a["levels"][0]["key"] == "none" for a in m["areas"])


@pytest.mark.django_db
def test_branch_manager_scope_and_hierarchy(client, api, branches):
    b1, b2 = branches
    r = api.post("/api/v1/access/users", {"phone": "+998 90 700 00 01", "full_name": "Filial Menejer", "role_codes": ["manager"], "branch_ids": [b1]})
    assert r.status_code == 200, r.content
    assert r.json()["branch_ids"] == [b1] and r.json()["roles"][0]["code"] == "manager"
    mgr = _as(client, "+998907000001")
    me = mgr.get("/api/v1/me").json()
    assert me["branch_all"] is False and [b["id"] for b in me["branches"]] == [b1] and me["level"] == 60
    # o'z filialiga kassir + oshpaz (bir nechta rol)
    r = mgr.post("/api/v1/access/users", {"phone": "+998907000002", "full_name": "Kassir Oshpaz", "role_codes": ["cashier", "cook"], "branch_ids": []})
    assert r.status_code == 200, r.content
    u = r.json()
    assert u["branch_ids"] == [b1] and {x["code"] for x in u["roles"]} == {"cashier", "cook"}
    assert u["areas"]["pos"] == "edit" and u["areas"]["kds"] == "edit"
    # boshqa filialga — yo'q; yuqori rolni bera olmaydi; o'zida yo'q ruxsatni bera olmaydi
    assert mgr.post("/api/v1/access/users", {"phone": "+998907000003", "role_codes": ["cashier"], "branch_ids": [b2]}).status_code == 403
    assert mgr.post("/api/v1/access/users", {"phone": "+998907000004", "role_codes": ["general_manager"]}).status_code == 403
    assert mgr.put(f"/api/v1/access/users/{u['id']}", {"role_codes": ["cashier"], "extra_permissions": ["core.settings.edit"]}).status_code == 403
    # shaxsiy ruxsat: omborni ko'rish
    r = mgr.put(f"/api/v1/access/users/{u['id']}", {"role_codes": ["cashier"], "extra_permissions": ["inventory.view"]}).json()
    assert r["areas"]["inventory"] == "view" and r["areas"]["kds"] == "none"
    # egasini tahrirlay olmaydi, ro'yxatda faqat o'z filiali
    with schema_context("lazzat"):
        from core.models import User
        owner_id = str(User.objects.get(phone="+998901234567").pk)
    assert mgr.put(f"/api/v1/access/users/{owner_id}", {"role_codes": ["owner"]}).status_code == 403
    ids = {x["id"] for x in mgr.get("/api/v1/access/users").json()}
    assert u["id"] in ids and owner_id not in ids
    # boshqaruv paneli filial bo'yicha
    assert mgr.get("/api/v1/dashboard/overview", branch_id=b2).status_code == 200


@pytest.mark.django_db
def test_staff_home_and_dashboard_forbidden(client, api):
    api.post("/api/v1/access/users", {"phone": "+998907000011", "full_name": "Ofitsiant", "role_codes": ["waiter"]})
    w = _as(client, "+998907000011")
    me = w.get("/api/v1/me").json()
    assert me["home"] == "/my" and "core.dashboard.view" not in me["permissions"]
    assert w.get("/api/v1/dashboard/overview").status_code == 403
    assert all(n["route"] != "/reports" for n in me["nav"])


@pytest.mark.django_db
def test_last_owner_protected_and_roles(api):
    with schema_context("lazzat"):
        from core.models import User
        owner_id = str(User.objects.get(phone="+998901234567").pk)
    assert api.put(f"/api/v1/access/users/{owner_id}", {"role_codes": ["manager"]}).status_code == 400   # o'zini
    r = api.post("/api/v1/access/roles", {"name": "Katta kassir", "permissions": ["pos.*", "catalog.view"]}).json()
    assert r["code"] == "katta_kassir" and r["level"] == 10
    assert api.put(f"/api/v1/access/roles/{r['id']}", {"name": "Katta kassir", "permissions": ["pos.*"]}).json()["permissions"] == ["pos.*"]


@pytest.mark.django_db
def test_ai_seats_from_platform(client, api, tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "ai"}))
        from modules.ai import limits
        limits.set_platform(tenant, seats=1, daily_limit=20)
    api.post("/api/v1/access/users", {"phone": "+998907000021", "full_name": "Menejer AI", "role_codes": ["cashier"]})
    s = api.get("/api/v1/ai/seats").json()
    assert s["seats"] == 1 and s["used"] == 1           # egasi ('*')
    uid = next(x["id"] for x in s["users"] if x["phone"] == "+998907000021")
    r = api.post("/api/v1/ai/seats", {"user_id": uid, "on": True})
    assert r.status_code == 400 and "O'rinlar" in r.json()["detail"]
    with schema_context("public"):
        limits.set_platform(tenant, seats=0)
    r = api.post("/api/v1/ai/seats", {"user_id": uid, "on": True}).json()
    assert r["user"]["on"] is True
    st = api.get("/api/v1/ai/status").json()
    assert st["daily_limit"] == 20                          # platforma chegarasi
    # restoran platforma chegarasini o'zi o'zgartira olmaydi
    api.put("/api/v1/tenant", {"settings": {"hq": {"ai": {"seats": 99, "daily_limit": 0}}}})
    with schema_context("public"):
        tenant.refresh_from_db()
        assert limits.platform(tenant)["daily_limit"] == 20


@pytest.mark.django_db
def test_telegram_login_flow(client, api, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    sent = []
    monkeypatch.setattr("core.tglogin.call", lambda m, p, t=None: sent.append((m, p)) or {"ok": True})
    api.post("/api/v1/access/users", {"phone": "+998907000031", "full_name": "Tg Xodim", "role_codes": ["cashier"]})
    r0 = client.post("/api/v1/auth/tg-login", {"phone": "+998907000031"}, content_type="application/json", **H).json()
    assert r0["ok"] is True and r0["linked"] is False                 # ulanmagan: havola orqali davom etadi
    # havola: botda /start login_<id> → «📱 Telefonni ulashish» → raqam mos → sayt o'zi kiradi
    from integrations.telegram.api import process_update as pu
    with schema_context("lazzat"):
        from public.models import Tenant as T0
        t0 = T0.objects.get(slug="lazzat")
        pu(t0, {"update_id": 5, "message": {"message_id": 1, "chat": {"id": 777002, "type": "private"}, "from": {"id": 777002},
                                            "text": "/start login_" + r0["id"].replace("-", "")}})
        assert "Telefonni ulashish" in sent[-1][1]["text"]
        from core.models import User as U0
        from core.tglogin import after_contact
        stranger = U0.objects.get(phone="+998901234567")
        assert after_contact(t0, 777002, stranger) is True                # boshqa raqam — rad
    assert client.get(f"/api/v1/auth/tg-login/{r0['id']}", {"secret": r0["secret"]}, **H).json()["status"] == "pending"
    with schema_context("lazzat"):
        pu(t0, {"update_id": 6, "message": {"message_id": 2, "chat": {"id": 777002, "type": "private"}, "from": {"id": 777002},
                                            "text": "/start login_" + r0["id"].replace("-", "")}})
        after_contact(t0, 777002, U0.objects.get(phone="+998907000031"))
    ok0 = client.get(f"/api/v1/auth/tg-login/{r0['id']}", {"secret": r0["secret"]}, **H).json()
    assert ok0["status"] == "ok" and ok0["reset_token"]
    with schema_context("lazzat"):
        from core.models import User
        User.objects.filter(phone="+998907000031").update(telegram_id=777001)
    r = client.post("/api/v1/auth/tg-login", {"phone": "907000031"}, content_type="application/json", **H).json()
    assert r["ok"] and sent[-1][0] == "sendMessage"
    kb = sent[-1][1]["reply_markup"]["inline_keyboard"][0]
    assert client.get(f"/api/v1/auth/tg-login/{r['id']}", {"secret": r["secret"]}, **H).json()["status"] == "pending"
    assert client.get(f"/api/v1/auth/tg-login/{r['id']}", {"secret": "x"}, **H).json()["status"] == "no"
    # boshqa odam bossa — o'tmaydi; egasi bossa — tasdiqlanadi
    from integrations.telegram.api import process_update
    with schema_context("lazzat"):
        from public.models import Tenant
        t = Tenant.objects.get(slug="lazzat")
        process_update(t, {"update_id": 9, "callback_query": {"id": "q1", "data": kb[0]["callback_data"], "from": {"id": 5},
                                                              "message": {"message_id": 3, "chat": {"id": 5}}}})
    assert client.get(f"/api/v1/auth/tg-login/{r['id']}", {"secret": r["secret"]}, **H).json()["status"] == "pending"
    with schema_context("lazzat"):
        process_update(t, {"update_id": 10, "callback_query": {"id": "q2", "data": kb[0]["callback_data"], "from": {"id": 777001},
                                                               "message": {"message_id": 3, "chat": {"id": 777001}}}})
    ok = client.get(f"/api/v1/auth/tg-login/{r['id']}", {"secret": r["secret"]}, **H).json()
    assert ok["status"] == "ok" and ok["token"] and ok["user"]["phone"] == "+998907000031"
    assert client.get(f"/api/v1/auth/tg-login/{r['id']}", {"secret": r["secret"]}, **H).json()["status"] != "ok"   # bir marta


@pytest.mark.django_db
def test_founder_enters_without_consent_and_sets_ai(client, tenant):
    from core.models import User
    from public.models import PlatformStaff
    pub = {"HTTP_HOST": "testserver"}
    with schema_context("public"):
        u, _ = User.objects.get_or_create(phone="+998900009988", defaults={"full_name": "Founder"})
        PlatformStaff.objects.update_or_create(user=u, defaults={"role": "founder", "is_active": True})
    code = client.post("/api/v1/hq/auth/otp", {"phone": "900009988"}, content_type="application/json", **pub).json()["dev_code"]
    tok = client.post("/api/v1/hq/auth/verify", {"phone": "900009988", "code": code}, content_type="application/json", **pub).json()["token"]
    h = {**pub, "HTTP_AUTHORIZATION": f"Bearer {tok}"}
    d = client.get(f"/api/v1/hq/tenants/{tenant.pk}", **h).json()
    assert d["direct_entry"] is True and "ai" in d
    r = client.post(f"/api/v1/hq/tenants/{tenant.pk}/impersonate", {"reason": ""}, content_type="application/json", **h)
    assert r.status_code == 200 and r.json()["token"]
    a = client.put(f"/api/v1/hq/tenants/{tenant.pk}/ai", {"enabled": True, "daily_limit": 30, "seats": 3}, content_type="application/json", **h).json()
    assert a["seats"] == 3 and a["daily_limit"] == 30


@pytest.mark.django_db
def test_webhook_always_200(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr("integrations.telegram.api.process_update", boom)
    r = client.post("/api/v1/telegram/webhook", data=json.dumps({"update_id": 1}), content_type="application/json",
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="restopos", **H)
    assert r.status_code == 200


@pytest.mark.django_db
def test_telegram_check_fix(monkeypatch, tenant):
    from io import StringIO

    from django.core.management import call_command
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_TENANT", "lazzat")
    monkeypatch.setenv("HTTPS", "1")
    calls = []

    def fake(tok, method, payload=None):
        calls.append((method, payload))
        if method == "getMe":
            return {"ok": True, "result": {"username": "lazzat_bot"}}
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": "", "pending_update_count": 4}}
        return {"ok": True}
    monkeypatch.setattr("modules.telegram.management.commands.telegram_check.tg", fake)
    out = StringIO()
    with schema_context("public"):
        call_command("telegram_check", "--fix", stdout=out)
        tenant.refresh_from_db()
    hook = next(p for m, p in calls if m == "setWebhook")
    assert hook["url"] == "https://lazzat.testserver/api/v1/telegram/webhook" and hook["drop_pending_updates"] is True
    assert hook["secret_token"] == tenant.settings["modules"]["telegram"]["webhook_secret"]
    assert tenant.settings["modules"]["telegram"]["bot_username"] == "lazzat_bot"
    assert ("setChatMenuButton", {"menu_button": {"type": "commands"}}) in calls
    assert "webhook o'rnatildi" in out.getvalue()


@pytest.mark.django_db
def test_manager_cannot_revive_owner(client, api, branches):
    b1, _ = branches
    api.post("/api/v1/access/users", {"phone": "+998907000041", "full_name": "Ikkinchi egasi", "role_codes": ["owner"]})
    api.post("/api/v1/access/users", {"phone": "+998907000042", "full_name": "Menejer", "role_codes": ["manager"], "branch_ids": [b1]})
    with schema_context("lazzat"):
        from core.models import User
        own2 = User.objects.get(phone="+998907000041")
        own2.is_active = False
        own2.save()
    mgr = _as(client, "+998907000042")
    assert mgr.put(f"/api/v1/access/users/{own2.pk}", {"role_codes": ["owner"], "is_active": True}).status_code == 403
    assert mgr.post("/api/v1/access/users", {"phone": "+998907000041", "role_codes": ["owner"]}).status_code == 403


@pytest.mark.django_db
def test_bot_contact_welcome_card(api, tenant, monkeypatch):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "telegram", "ai"}))
    api.post("/api/v1/access/users", {"phone": "+998907000051", "full_name": "Aziz Karimov", "role_codes": ["cashier"]})
    said = []
    from modules.telegram import services
    monkeypatch.setattr(services, "say", lambda t, chat, text, markup=None: said.append(text) or True)
    with schema_context("lazzat"):
        from public.models import Tenant
        t = Tenant.objects.get(slug="lazzat")
        msg = {"message_id": 1, "chat": {"id": 880001, "type": "private"}, "from": {"id": 880001, "first_name": "Aziz"},
               "contact": {"phone_number": "998907000051", "user_id": 880001}}
        services.handle_update(t, {"update_id": 1, "message": msg})
        assert "Xush kelibsiz, Aziz" in said[-1] and "Kassir" in said[-1] and "AI Kotib: ruxsat yo'q" in said[-1]
        # ro'yxatda yo'q raqam — tasdiqlanmaydi
        msg2 = {**msg, "chat": {"id": 880002, "type": "private"}, "from": {"id": 880002}, "contact": {"phone_number": "998900000000", "user_id": 880002}}
        services.handle_update(t, {"update_id": 2, "message": msg2})
        assert "topilmadi" in said[-1]


@pytest.mark.django_db
def test_security_invite_logout_history(client, api, tenant, monkeypatch):
    """Taklif havolasi → botda bir bosishda ulanish; parol bilan kirish → tarix + Telegram ogohlantirish; hamma qurilmalardan chiqarish."""
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "telegram"}))
        tenant.settings = {**tenant.settings, "modules": {**(tenant.settings.get("modules") or {}),
                                                          "telegram": {**((tenant.settings.get("modules") or {}).get("telegram") or {}), "bot_username": "lazzat_bot"}}}
        tenant.save()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    sent = []
    monkeypatch.setattr("integrations.telegram.call", lambda m, p, t=None: sent.append((m, p)) or {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr("modules.telegram.services.say", lambda t, chat, text, markup=None: sent.append(("say", {"text": text, "markup": markup})) or True)
    uid = api.post("/api/v1/access/users", {"phone": "+998907000061", "full_name": "Sardor Aliyev", "role_codes": ["cashier"]}).json()["id"]
    inv = api.post(f"/api/v1/access/users/{uid}/invite").json()
    assert inv["link"].startswith("https://t.me/lazzat_bot?start=inv_")
    code = inv["link"].split("inv_", 1)[1]
    from integrations.telegram.api import process_update
    with schema_context("lazzat"):
        from public.models import Tenant
        t = Tenant.objects.get(slug="lazzat")
        process_update(t, {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 990001, "type": "private"}, "from": {"id": 990001}, "text": f"/start inv_{code}"}})
        from core.models import User
        u = User.objects.get(pk=uid)
        assert u.telegram_id == 990001 and not u.tg_invite
    assert "Xush kelibsiz, Sardor" in sent[-1][1]["text"]
    # parol berib, parol bilan kirish → tarix + ogohlantirish
    pw = api.post(f"/api/v1/users/{uid}/password", {"generate": True, "send_telegram": False}).json()["password"]
    r = client.post("/api/v1/auth/login", {"phone": "+998907000061", "password": pw}, content_type="application/json", HTTP_USER_AGENT="Mozilla Chrome/1 Windows", **H)
    tok = r.json()["token"]
    assert any(m == "sendMessage" and "yangi kirish" in p.get("text", "") for m, p in sent)
    p = api.get(f"/api/v1/access/users/{uid}").json()
    assert p["login"]["history"][0]["method"] == "password" and "Chrome" in p["login"]["history"][0]["device"]
    me = {**H, "HTTP_AUTHORIZATION": f"Bearer {tok}"}
    assert client.get("/api/v1/me", **me).status_code == 200
    # rahbar hamma qurilmalardan chiqaradi → eski token ishlamaydi
    assert api.post(f"/api/v1/access/users/{uid}/logout-all").status_code == 200
    assert client.get("/api/v1/me", **me).status_code == 401
    # botdagi «🚪 Hamma qurilmalardan chiqish» va «🔑 Yangi parol»
    with schema_context("lazzat"):
        process_update(t, {"update_id": 2, "callback_query": {"id": "c", "data": "sec:pw", "message": {"message_id": 5, "chat": {"id": 990001}}}})
    assert any("Yangi parolingiz" in p.get("text", "") for m, p in sent if m == "sendMessage")
    # o'zim: boshqa qurilmalardan chiqish — yangi token beriladi
    r = api.post("/api/v1/me/logout-all").json()
    assert client.get("/api/v1/me", **{**H, "HTTP_AUTHORIZATION": f"Bearer {r['token']}"}).status_code == 200


@pytest.mark.django_db
def test_login_check_register_and_reset(client, api):
    """Kirish sahifasi: raqam tekshiruvi; parolsiz xodim kod bilan tasdiqlab parol qo'yadi; unutgan — eski parolsiz yangisini qo'yadi."""
    api.post("/api/v1/access/users", {"phone": "+998907000071", "full_name": "Yangi", "role_codes": ["cashier"]})
    j = lambda url, d, **h: client.post(url, d, content_type="application/json", **H, **h)    # noqa: E731
    assert j("/api/v1/auth/check", {"phone": "+998900000009"}).json()["exists"] is False
    c = j("/api/v1/auth/check", {"phone": "90 700 00 71"}).json()
    assert c["has_password"] is False
    code = j("/api/v1/auth/otp", {"phone": "+998907000071"}).json()["dev_code"]
    v = j("/api/v1/auth/verify", {"phone": "+998907000071", "code": code}).json()
    auth_h = {"HTTP_AUTHORIZATION": f"Bearer {v['token']}"}
    assert j("/api/v1/me/password", {"new_password": "salom123", "reset_token": v["reset_token"]}, **auth_h).status_code == 200
    assert j("/api/v1/auth/check", {"phone": "+998907000071"}).json()["has_password"] is True
    # unutdi: kod bilan tasdiq → eski parolsiz yangisi
    code = j("/api/v1/auth/otp", {"phone": "+998907000071"}).json()["dev_code"]
    v = j("/api/v1/auth/verify", {"phone": "+998907000071", "code": code}).json()
    auth_h = {"HTTP_AUTHORIZATION": f"Bearer {v['token']}"}
    assert j("/api/v1/me/password", {"new_password": "yangi456"}, **auth_h).status_code == 400         # reset_token'siz — eski parol kerak
    assert j("/api/v1/me/password", {"new_password": "yangi456", "reset_token": "buzuq"}, **auth_h).status_code == 400
    assert j("/api/v1/me/password", {"new_password": "yangi456", "reset_token": v["reset_token"]}, **auth_h).status_code == 200
    assert j("/api/v1/auth/login", {"phone": "+998907000071", "password": "yangi456"}).status_code == 200



@pytest.mark.django_db
def test_join_request_needs_approval(client, api, monkeypatch, tenant):
    """Ro'yxatda yo'q odam so'rov yuboradi → kira olmaydi → rahbar tasdiqlaydi (lavozim bilan) → endi kiradi; rad etish ham."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    sent = []
    monkeypatch.setattr("integrations.telegram.call", lambda m, p, t=None: sent.append((m, p)) or {"ok": True})
    with schema_context("lazzat"):
        from core.models import User
        boss = User.objects.get(phone="+998901234567")
        boss.telegram_id = 880100
        boss.save()
    j = lambda url, d: client.post(url, d, content_type="application/json", **H)    # noqa: E731
    r = j("/api/v1/auth/join", {"phone": "+998 90 555 44 33", "full_name": "Yangi Ofitsiant", "note": "ofitsiant"}).json()
    assert r["ok"] and r["status"] == "pending"
    assert any(p.get("chat_id") == 880100 and "Ro'yxatdan o'tish so'rovi" in p.get("text", "") for m, p in sent)
    c = j("/api/v1/auth/check", {"phone": "+998905554433"}).json()
    assert c["exists"] is False and c["join"] == "pending"
    assert j("/api/v1/auth/otp", {"phone": "+998905554433"}).status_code == 404            # kira olmaydi
    assert j("/api/v1/auth/tg-login", {"phone": "+998905554433"}).status_code == 404
    # botda raqamni tasdiqlash
    from integrations.telegram.api import process_update
    with schema_context("lazzat"):
        from public.models import Tenant
        t = Tenant.objects.get(slug="lazzat")
        process_update(t, {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 880200, "type": "private"}, "from": {"id": 880200}, "text": f"/start join_{r['id']}"}})
        from core import join
        assert join.after_contact(t, 880200, "998905554433") is True
    joins = api.get("/api/v1/access/joins").json()
    assert joins[0]["verified"] is True and joins[0]["full_name"] == "Yangi Ofitsiant"
    u = api.post("/api/v1/access/users", {"phone": "+998905554433", "full_name": "Yangi Ofitsiant", "role_codes": ["waiter"], "join_id": r["id"]}).json()
    assert u["telegram_linked"] is True and api.get("/api/v1/access/joins").json() == []
    assert any(p.get("chat_id") == 880200 and "tasdiqlandi" in p.get("text", "") for m, p in sent)
    assert j("/api/v1/auth/check", {"phone": "+998905554433"}).json()["exists"] is True
    # rad etish
    r2 = j("/api/v1/auth/join", {"phone": "+998905554434", "full_name": "Begona Odam"}).json()
    assert api.post(f"/api/v1/access/joins/{r2['id']}/reject").status_code == 200
    assert j("/api/v1/auth/check", {"phone": "+998905554434"}).json()["join"] == "rejected"
    # ro'yxatdagi odam so'rov yubora olmaydi
    assert j("/api/v1/auth/join", {"phone": "+998905554433", "full_name": "Yangi Ofitsiant"}).status_code == 400


@pytest.mark.django_db
def test_hq_password_login(client):
    from core.models import User
    from public.models import PlatformStaff
    pub = {"HTTP_HOST": "testserver"}
    with schema_context("public"):
        u, _ = User.objects.get_or_create(phone="+998900007777", defaults={"full_name": "Dev"})
        u.set_password("Kuchli1234")
        u.save()
        PlatformStaff.objects.update_or_create(user=u, defaults={"role": "developer", "is_active": True})
    bad = client.post("/api/v1/hq/auth/login", {"phone": "900007777", "password": "xato"}, content_type="application/json", **pub)
    assert bad.status_code == 400
    ok = client.post("/api/v1/hq/auth/login", {"phone": "900007777", "password": "Kuchli1234"}, content_type="application/json", **pub).json()
    assert ok["token"] and ok["staff"]["role"] == "developer"
