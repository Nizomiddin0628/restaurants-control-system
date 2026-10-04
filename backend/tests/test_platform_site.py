"""
Platforma sayti: narxlar HQ'dan o'zgaradi va saytda ko'rinadi; AI maslahatchi (Gemini soxta) javob beradi,
rasm qabul qiladi, telefon bersa ariza (lead) saqlaydi; IP bo'yicha cheklov; HQ'da arizalar.
"""
import base64
import json

import pytest
from django.core.cache import cache
from django_tenants.utils import schema_context

from tests.test_hq import PUB, hq  # noqa: F401  (fixture)


def _stream(resp) -> list[dict]:
    return [json.loads(x) for x in b"".join(resp.streaming_content).decode().splitlines() if x.strip()]


class FakeGemini:
    def __init__(self, script):
        self.script, self.seen = list(script), []

    def __call__(self, tenant, contents, **kw):
        self.seen.append({"contents": contents, **kw})
        step = self.script.pop(0) if self.script else {"text": "ok"}
        parts = [{"functionCall": {"name": step["call"][0], "args": step["call"][1]}}] if "call" in step else [{"text": step["text"]}]
        if kw.get("on_text") and "text" in step:
            kw["on_text"](step["text"][:10])
        return {"model": "gemini-test", "ms": 3, "data": {"candidates": [{"content": {"role": "model", "parts": parts}}]}}


@pytest.mark.django_db
def test_offer_edit_in_hq_and_landing(client, hq):  # noqa: F811
    r = client.get("/", **PUB)
    assert r.status_code == 200
    html = r.content.decode()
    assert "100" in html and "150" in html and "30 kun bepul" in html
    assert "Restoraningiz bilan" in html and 'id="solishtirish"' in html and "chirish — bepul" in html   # v44: o'z uslubimiz
    assert hq.get("/api/v1/hq/offer").json()["base_price"] == 100
    r = hq.put("/api/v1/hq/offer", {"currency": "$", "base_price": 120, "ai_price": 180, "trial_days": 14, "free_setup": False,
                                     "includes": ["Server", " ", "Domen"], "telegram": "@restopos_uz", "price_note": "oyiga"})
    assert r.status_code == 200, r.content
    assert r.json()["includes"] == ["Server", "Domen"] and r.json()["telegram"] == "restopos_uz"
    html = client.get("/", **PUB).content.decode()
    assert "180" in html and "14 kun bepul" in html and "Aksiya:" not in html and "chirish — bepul" not in html and "t.me/restopos_uz" in html
    assert "14 kun bepul" in client.get("/signup/", **PUB).content.decode()
    assert hq.put("/api/v1/hq/offer", {"base_price": 0, "ai_price": 10}).status_code == 400


@pytest.mark.django_db
def test_sales_ai_answers_with_image_and_saves_lead(client, hq, monkeypatch):  # noqa: F811
    cache.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-1234567890abcdef")
    from modules.ai import gemini
    fake = FakeGemini([{"call": ("save_lead", {"name": "Akmal", "phone": "90 111 22 33", "business": "Lazzat, 2 filial", "note": "AI tarif"})},
                       {"text": "Rahmat, Akmal! **Mutaxassisimiz** tez orada bog'lanadi.\n<script>x</script>"}])
    monkeypatch.setattr(gemini, "generate", fake)
    img = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake").decode()
    r = client.post("/api/v1/sales/ask-stream", {"question": "Narxi qancha? Tel: 90 111 22 33", "image": img,
                                                 "history": [{"role": "ai", "text": "Salom"}, {"role": "me", "text": "Menda kafe bor"}]},
                    content_type="application/json", **PUB)
    assert r.status_code == 200
    rows = _stream(r)
    done = rows[-1]
    assert done["done"] and done["ok"] and done["lead"] is True
    assert "<b>Mutaxassisimiz</b>" in done["answer"] and "<script>" not in done["answer"]
    first = fake.seen[0]
    assert "$100" in first["system"] and "$150" in first["system"]                     # narxlar HQ'dagi taklifdan
    assert first["contents"][0]["role"] == "user"                                        # tarix «user» bilan boshlanadi
    assert any("inline_data" in p for c in first["contents"] for p in c["parts"])           # rasm yuborildi
    assert first["tools"][0]["function_declarations"][0]["name"] == "save_lead"
    with schema_context("public"):
        from public.models import Lead
        lead = Lead.objects.get()
        assert (lead.phone, lead.name, lead.source) == ("+998901112233", "Akmal", "ai_chat")
    items = hq.get("/api/v1/hq/leads").json()
    assert items["new"] == 1 and items["items"][0]["business"] == "Lazzat, 2 filial"
    assert hq.post(f"/api/v1/hq/leads/{lead.pk}", {"status": "contacted"}).json()["status"] == "contacted"
    # forma orqali
    assert client.post("/api/v1/sales/lead", {"phone": "12"}, content_type="application/json", **PUB).status_code == 400
    assert client.post("/api/v1/sales/lead", {"phone": "+998 93 555 44 33", "name": "Dilnoza"}, content_type="application/json", **PUB).status_code == 200


@pytest.mark.django_db
def test_sales_ai_limits_and_off(client, hq, monkeypatch):  # noqa: F811
    cache.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-1234567890abcdef")
    from modules.ai import gemini
    from website import sales_ai
    monkeypatch.setattr(gemini, "generate", FakeGemini([]))
    monkeypatch.setattr(sales_ai, "PER_IP_HOUR", 2)
    post = lambda: client.post("/api/v1/sales/ask-stream", {"question": "salom"}, content_type="application/json", **PUB)  # noqa: E731
    assert post().status_code == 200 and post().status_code == 200
    assert post().status_code == 429
    assert client.post("/api/v1/sales/ask-stream", {"question": ""}, content_type="application/json", **PUB).status_code == 400
    hq.put("/api/v1/hq/offer", {"base_price": 100, "ai_price": 150, "ai_chat": False})
    assert post().status_code == 403
    assert 'id="aicFab"' not in client.get("/", **PUB).content.decode()


@pytest.mark.django_db
def test_sales_key_fallback_sessions_and_voice(client, hq, tenant, monkeypatch):  # noqa: F811
    """Kalit: .env bo'lmasa — HQ kaliti, u ham bo'lmasa — restoranning AI Kotib kaliti. Suhbatlar HQ'da. Ovoz → matn."""
    cache.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from modules.ai import gemini
    from website import sales_ai
    with schema_context("public"):
        from public.models import Tenant
        t = Tenant.objects.get(pk=tenant.pk)
        t.settings = {**(t.settings or {}), "modules": {**((t.settings or {}).get("modules") or {}), "ai": {"api_key": "tenant-key-123456789"}}}
        t.save()
        assert sales_ai.key_holder().settings["modules"]["ai"]["api_key"] == "tenant-key-123456789"
    assert "restoran" in hq.get("/api/v1/hq/offer").json()["ai_key_source"]
    r = hq.put("/api/v1/hq/offer", {"base_price": 100, "ai_price": 150, "ai_key": "hq-key-abcdefghijklmnop"})
    assert r.json()["ai_key"].startswith("hq-k") and "abcdefghij" not in r.json()["ai_key"]
    with schema_context("public"):
        assert sales_ai.key_holder().settings["modules"]["ai"]["api_key"] == "hq-key-abcdefghijklmnop"
    hq.put("/api/v1/hq/offer", {"base_price": 100, "ai_price": 150, "ai_key": r.json()["ai_key"]})          # niqoblangan qiymat — o'zgarmaydi
    with schema_context("public"):
        assert sales_ai.key_holder().settings["modules"]["ai"]["api_key"] == "hq-key-abcdefghijklmnop"

    seen = []
    monkeypatch.setattr(gemini, "generate", lambda tenant, contents, **kw: seen.append(tenant) or
                        {"model": "m", "ms": 1, "data": {"candidates": [{"content": {"parts": [{"text": "Salom! Narx $100."}]}}]}})
    r = client.post("/api/v1/sales/ask-stream", {"question": "Narxi?", "sid": "abc12345xyz"}, content_type="application/json", **PUB)
    assert _stream(r)[-1]["ok"]
    assert seen[0].settings["modules"]["ai"]["api_key"] == "hq-key-abcdefghijklmnop"
    chats = hq.get("/api/v1/hq/chats").json()["items"]
    assert chats[0]["count"] == 1 and chats[0]["first"] == "Narxi?" and chats[0]["messages"][1]["text"].startswith("Salom")

    monkeypatch.setattr(gemini, "transcribe", lambda tenant, raw, mime: {"text": "kassa haqida aytib bering", "model": "m", "ms": 1, "tokens": 1})
    audio = "data:audio/webm;base64," + base64.b64encode(b"\x1aE" * 600).decode()
    r = client.post("/api/v1/sales/transcribe", {"audio": audio}, content_type="application/json", **PUB)
    assert r.status_code == 200 and r.json()["text"] == "kassa haqida aytib bering"
    assert client.post("/api/v1/sales/transcribe", {"audio": "data:audio/webm;base64,AAAA"}, content_type="application/json", **PUB).status_code == 400


@pytest.mark.django_db
def test_russian_site_and_telegram_notify(client, hq, monkeypatch):  # noqa: F811
    """v47: /ru/ — ruscha sayt va AI ruscha javob beradi; ariza va ro'yxatdan o'tish HQ'dagi chat ID'ga Telegram orqali boradi."""
    cache.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-1234567890abcdef")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    html = client.get("/ru/", **PUB).content.decode()
    assert 'lang="ru"' in html and "Говорите со своим" in html and "30 дней бесплатно" in html and 'href="/"' in html and "рестораном" in html
    assert "Restoraningiz bilan" not in html and "за один ресторан, в месяц" in html
    assert "Запустите свой ресторан" in client.get("/ru/signup/", **PUB).content.decode()
    r = hq.put("/api/v1/hq/offer", {"base_price": 100, "ai_price": 150, "trial_days": 21, "lead_chat": " 777 ", "price_note_ru": "в месяц", "includes_ru": ["Сервер"]})
    assert r.status_code == 200 and r.json()["lead_chat"] == "777" and r.json()["notify_ready"] is True
    html = client.get("/ru/", **PUB).content.decode()
    assert "21 день бесплатно" in html and "в месяц" in html and "Сервер" in html
    # AI: ruscha qoida system promptda; ariza → Telegram
    from modules.ai import gemini
    fake = FakeGemini([{"call": ("save_lead", {"name": "Иван", "phone": "90 222 33 44"})}, {"text": "Спасибо!"}])
    monkeypatch.setattr(gemini, "generate", fake)
    sent = []
    import integrations.telegram as tg
    monkeypatch.setattr(tg, "call", lambda method, payload, token=None: sent.append((method, payload, token)) or {"ok": True})
    r = client.post("/api/v1/sales/ask-stream", {"question": "Сколько стоит? 90 222 33 44", "lang": "ru"}, content_type="application/json", **PUB)
    assert _stream(r)[-1]["ok"]
    assert "RUS tilida" in fake.seen[0]["system"]
    assert sent and sent[0][1]["chat_id"] == "777" and "Иван" in sent[0][1]["text"] and sent[0][2] == "123:abc"
    # sinov xabari va ro'yxatdan o'tish
    assert hq.post("/api/v1/hq/offer/test-notify", {}).status_code == 200 and "Sinov" in sent[-1][1]["text"]
    r = client.post("/api/v1/signup", {"name": "Yangi", "slug": "yangi-resto", "phone": "+998 90 999 88 77", "preset": "cafe"}, content_type="application/json", **PUB)
    assert r.status_code == 200, r.content
    assert "Yangi restoran" in sent[-1][1]["text"] and "yangi-resto" in sent[-1][1]["text"]
