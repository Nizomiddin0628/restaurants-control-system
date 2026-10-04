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
    assert hq.get("/api/v1/hq/offer").json()["base_price"] == 100
    r = hq.put("/api/v1/hq/offer", {"currency": "$", "base_price": 120, "ai_price": 180, "trial_days": 14, "free_setup": False,
                                     "includes": ["Server", " ", "Domen"], "telegram": "@restopos_uz", "price_note": "oyiga"})
    assert r.status_code == 200, r.content
    assert r.json()["includes"] == ["Server", "Domen"] and r.json()["telegram"] == "restopos_uz"
    html = client.get("/", **PUB).content.decode()
    assert "180" in html and "14 kun bepul" in html and "Aksiya:" not in html and "t.me/restopos_uz" in html
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
