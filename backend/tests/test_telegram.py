"""
Telegram bot va Mini App: webhook siri, /start → mijoz, kontakt → telefon (xodim bo'lsa bog'lanadi),
bot orqali stol bron, Mini App buyurtmasi (imzo tekshiruvi, yetkazish narxi, eng kam summa) → kassa,
to'lov → mijoz statistikasi, ommaviy xabar sanog'i, modul o'chirilsa 404.
"""
import json
import os

import pytest
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}
TOKEN = "123456:TEST-token-for-hmac"
SECRET = "restopos"   # .env bo'lmasa standart sir


@pytest.fixture
def bot(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "telegram", "pos", "catalog", "tables", "reservations"}))
        tenant.settings = {**tenant.settings, "modules": {**(tenant.settings.get("modules") or {}),
                                                          "telegram": {"min_order": 20000, "delivery_fee": 9000, "free_delivery_from": 100000}}}
        tenant.save()
    with schema_context("lazzat"):
        from modules.catalog.models import Category, Product
        from modules.tables.models import Table
        from modules.telegram.models import BotUser, Broadcast
        BotUser.objects.all().delete(); Broadcast.objects.all().delete()
        cat, _ = Category.objects.get_or_create(name={"uz": "TG test", "ru": "", "en": ""})
        p, _ = Product.objects.get_or_create(name={"uz": "TG burger", "ru": "", "en": ""}, defaults={"category": cat, "price": 15000, "cost": 5000})
        Table.objects.get_or_create(number="T1", defaults={"seats": 6})
        yield {"product": p}


def _hook(client, update, secret=None):
    secret = secret or os.environ.get("TELEGRAM_WEBHOOK_SECRET", SECRET)
    return client.post("/api/v1/telegram/webhook", data=json.dumps(update), content_type="application/json",
                       HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret, **H)


def _msg(chat_id, text=None, contact=None, first="Ali"):
    m = {"message_id": 1, "chat": {"id": chat_id, "type": "private"}, "from": {"id": chat_id, "first_name": first}}
    if text is not None:
        m["text"] = text
    if contact:
        m["contact"] = contact
    return {"update_id": 1, "message": m}


@pytest.mark.django_db
def test_webhook_secret_and_start_creates_customer(client, bot):
    assert _hook(client, _msg(5001, "/start"), secret="wrong").status_code == 403
    assert _hook(client, _msg(5001, "/start")).status_code == 200
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        bu = BotUser.objects.get(chat_id=5001)
        assert bu.full_name == "Ali" and bu.phone == ""


@pytest.mark.django_db
def test_contact_saves_phone_and_links_staff(client, bot):
    _hook(client, _msg(5002, "/start"))
    _hook(client, _msg(5002, contact={"phone_number": "998901112233", "user_id": 5002}))
    _hook(client, _msg(5003, contact={"phone_number": "+998901234567", "user_id": 5003}))   # egasi (xodim)
    with schema_context("lazzat"):
        from core.models import User
        from modules.telegram.models import BotUser
        assert BotUser.objects.get(chat_id=5002).phone == "+998901112233"
        assert BotUser.objects.get(chat_id=5003).staff is not None
        assert User.objects.get(phone="+998901234567").telegram_id == 5003


@pytest.mark.django_db
def test_booking_via_bot(client, bot):
    _hook(client, _msg(5004, contact={"phone_number": "998901110099", "user_id": 5004}))
    _hook(client, _msg(5004, "📅 Stol bron qilish"))
    _hook(client, _msg(5004, "4"))
    _hook(client, _msg(5004, "Ertaga"))
    _hook(client, _msg(5004, "19:00"))
    with schema_context("lazzat"):
        from modules.reservations.models import Reservation
        r = Reservation.objects.filter(phone="+998901110099", source="telegram").first()
        assert r is not None and r.guests == 4 and r.table is not None


@pytest.mark.django_db
def test_miniapp_order_signed_and_rules(client, bot, tenant):
    from modules.telegram.services import sign_init_data
    with schema_context("public"):
        tenant.settings["modules"]["telegram"]["bot_token"] = TOKEN
        tenant.save()
    good = sign_init_data({"id": 7001, "first_name": "Vali"}, TOKEN)
    bad = sign_init_data({"id": 7001, "first_name": "Vali"}, "999:other-token")
    body = {"items": [{"product_id": bot["product"].pk, "qty": 2}], "type": "delivery", "phone": "901234000", "address": "Chilonzor 5-kvartal, 12-uy"}
    post = lambda d: client.post("/api/v1/bot/miniapp/order", data=json.dumps(d), content_type="application/json", **H)  # noqa: E731
    assert post({**body, "init_data": bad}).status_code == 403                                   # soxta imzo
    assert post({**body, "init_data": good, "items": [{"product_id": bot["product"].pk, "qty": 1}]}).status_code == 400   # 15 000 < 20 000
    r = post({**body, "init_data": good})
    assert r.status_code == 200, r.content
    assert r.json()["total"] == 30000 + 9000                                                   # yetkazish narxi qo'shildi
    with schema_context("lazzat"):
        from modules.pos.models import Order
        from modules.telegram.models import BotUser
        o = Order.objects.get(number=r.json()["number"])
        assert o.source == "telegram" and o.type == "delivery" and o.customer_phone == "+998901234000"
        assert BotUser.objects.get(chat_id=7001).phone == "+998901234000"


@pytest.mark.django_db
def test_paid_order_updates_customer_stats(api, bot):
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        BotUser.objects.create(chat_id=7002, phone="+998905556677")
    api.post("/api/v1/pos/shifts/open", {"cash_start": 0})
    r = api.post("/api/v1/pos/orders", {"items": [{"product_id": bot["product"].pk, "qty": 1}], "customer_phone": "+998905556677"})
    assert r.status_code == 200, r.content
    assert api.post(f"/api/v1/pos/orders/{r.json()['id']}/pay", {"payment_method": "cash"}).status_code == 200
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        bu = BotUser.objects.get(chat_id=7002)
        assert bu.orders_count == 1 and bu.spent_total == 15000


@pytest.mark.django_db
def test_broadcast_counts_and_stats(api, bot):
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        BotUser.objects.create(chat_id=8001, phone="+998900000001", orders_count=1)
        BotUser.objects.create(chat_id=8002)
    b = api.post("/api/v1/bot/broadcasts", {"text": "Bugun -20%!", "audience": "buyers"}).json()
    assert b["reach"] == 1
    r = api.post(f"/api/v1/bot/broadcasts/{b['id']}/send").json()
    assert r["status"] == "sent" and r["total"] == 1 and r["sent"] == 1
    assert api.post(f"/api/v1/bot/broadcasts/{b['id']}/send").status_code == 400                # ikki marta yuborilmaydi
    s = api.get("/api/v1/bot/stats").json()
    assert s["subscribers"] == 2 and s["buyers"] == 1 and s["conversion"] == 50.0


@pytest.mark.django_db
def test_settings_token_masked(api, bot):
    r = api.put("/api/v1/bot/settings", {"bot_token": "111:ABCDEFGH", "bot_username": "@lazzat_bot", "min_order": 0})
    assert r.status_code == 200 and "bot_token" not in r.json() and r.json()["bot_token_masked"].endswith("EFGH")
    assert r.json()["bot_username"] == "lazzat_bot"
    assert api.put("/api/v1/bot/settings", {"bot_token": "notatoken"}).status_code == 400


@pytest.mark.django_db
def test_module_disabled_404(api, tenant, bot):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "telegram"])
    assert api.get("/api/v1/bot/stats").status_code == 404
    with schema_context("public"):
        set_modules(tenant, [*tenant.enabled_modules, "telegram"])


@pytest.mark.django_db
def test_polling_command_handles_start(bot, tenant, monkeypatch):
    """Lokal rejim: telegram_polling getUpdates'dan /start oladi → mijoz yaratiladi va javob yuboriladi."""
    import requests as rq
    from django.core.management import call_command
    with schema_context("public"):
        tenant.settings["modules"]["telegram"]["bot_token"] = TOKEN
        tenant.save()
    sent, calls = [], {"n": 0}

    class R:
        def __init__(self, d): self.d = d
        def json(self): return self.d

    def fake_get(url, params=None, timeout=None):
        if url.endswith("getMe"):
            return R({"ok": True, "result": {"username": "lazzat_bot"}})
        calls["n"] += 1
        if calls["n"] == 1:
            return R({"ok": True, "result": [{"update_id": 10, **{k: v for k, v in _msg(9001, "/start").items() if k != "update_id"}}]})
        raise KeyboardInterrupt

    def fake_post(url, json=None, timeout=None):
        if url.endswith("sendMessage"):
            sent.append(json)
        return R({"ok": True})
    monkeypatch.setattr(rq, "get", fake_get)
    monkeypatch.setattr(rq, "post", fake_post)
    call_command("telegram_polling", "--slug", "lazzat")
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        assert BotUser.objects.filter(chat_id=9001).exists()
    assert sent and sent[0]["chat_id"] == 9001
