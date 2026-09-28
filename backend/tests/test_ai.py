"""AI Kotib: hisobot, agent (asboblar bilan), Telegram oqimi (ovoz → darhol javob oqimi, ⏹ to'xtatish, bitta so'rov qoidasi), ertalabki yuborish, API.
Gemini va Telegram so'rovlari soxtalashtirilgan — internetga chiqilmaydi."""
from datetime import datetime, timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context


def _on(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "ai", "pos", "tasks", "inventory", "hr", "reservations", "telegram"}))


class FakeGemini:
    """Ketma-ket javoblar: har biri dict — {"call": (name, args)} yoki {"text": "..."}."""

    def __init__(self, script):
        self.script, self.seen = list(script), []

    def __call__(self, tenant, contents, **kw):
        self.seen.append({"contents": contents, **kw})
        step = self.script.pop(0) if self.script else {"text": "tayyor"}
        if "call" in step:
            name, args = step["call"]
            parts = [{"functionCall": {"name": name, "args": args}, "thoughtSignature": "sig"}]
        else:
            parts = [{"text": step["text"]}]
        return {"model": "gemini-test", "ms": 5, "data": {"candidates": [{"content": {"role": "model", "parts": parts}}], "usageMetadata": {"totalTokenCount": 100}}}


@pytest.fixture
def ai_env(tenant, monkeypatch):
    _on(tenant)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-1234567890abcdef")
    sent = []

    def fake_call(method, payload, token=None):
        sent.append((method, payload))
        return {"ok": True, "result": {"message_id": 500 + len(sent), "file_path": "voice/1.oga"}}
    from modules.ai import tg
    monkeypatch.setattr(tg, "call", fake_call)
    monkeypatch.setattr(tg, "_tok", lambda t: "123:abc")
    monkeypatch.setattr(tg, "download", lambda t, fid: b"OggS-fake")
    monkeypatch.setattr(tg, "RUN_ASYNC", False)
    with schema_context(tenant.schema_name):
        from django.db import connection
        connection.set_tenant(tenant)
        from core.models import User
        u = User.objects.get(phone="+998901234567")
        u.telegram_id = 777001
        u.save(update_fields=["telegram_id"])
        yield {"sent": sent, "user": u, "tenant": tenant}


def _texts(sent):
    return [p.get("text", "") for m, p in sent if m == "sendMessage"]


@pytest.mark.django_db
def test_report_builds_without_ai(ai_env):
    from modules.ai import report
    text, info = report.full_text(ai_env["tenant"], ai_env["user"], use_ai=False)
    assert "Kecha qanday o'tdi" in text and "Birinchi navbatda" in text
    assert info["ai"]["calls"] == 0
    assert report.split("a\n\n" * 3000, 3900)[0].__len__() <= 3900


@pytest.mark.django_db
def test_agent_uses_tools_and_creates_task(ai_env, monkeypatch):
    from modules.ai import agent, gemini
    from modules.ai.models import AiLog
    from modules.tasks.models import Task
    fake = FakeGemini([{"call": ("sales", {"date_from": "2026-01-01"})},
                       {"call": ("create_task", {"title": "Muzlatgichni tozalash", "assignee": "Mavjudbo'lmagan Odam", "due": "2030-01-01T10:00"})},
                       {"call": ("create_task", {"title": "Muzlatgichni tozalash"})},
                       {"text": "**Savdo** yaxshi.\n* birinchi\n<script>x</script>"}])
    monkeypatch.setattr(gemini, "generate", fake)
    res = agent.ask(ai_env["tenant"], ai_env["user"], "Kecha savdo qancha? Muzlatgich vazifasini ber")
    assert res["ok"], res
    assert "<b>Savdo</b>" in res["answer"] and "• birinchi" in res["answer"] and "<script>" not in res["answer"]
    assert len(res["tasks"]) == 1 and Task.objects.filter(title="Muzlatgichni tozalash").exists()
    # model javobi (thoughtSignature bilan) o'zgarmasdan qaytarildi, funksiya natijasi yuborildi
    last = fake.seen[-1]["contents"]
    assert any(p.get("thoughtSignature") == "sig" for c in last for p in c.get("parts", []))
    assert any("functionResponse" in p for c in last for p in c.get("parts", []))
    lg = AiLog.objects.latest("created_at")
    assert lg.calls == 4 and lg.tokens == 400 and lg.ok


@pytest.mark.django_db
def test_agent_error_and_daily_limit(ai_env, monkeypatch):
    from modules.ai import agent, gemini

    def boom(*a, **k):
        raise gemini.AiError("AI'ning bugungi bepul limiti tugadi.")
    monkeypatch.setattr(gemini, "generate", boom)
    res = agent.ask(ai_env["tenant"], ai_env["user"], "savol")
    assert not res["ok"] and "limit" in res["error"]
    t = ai_env["tenant"]
    t.settings = {**(t.settings or {}), "modules": {**((t.settings or {}).get("modules") or {}), "ai": {"daily_limit": 5}}}
    from modules.ai.models import AiLog
    for _ in range(5):
        AiLog.objects.create(user=ai_env["user"], calls=1)
    res = agent.ask(t, ai_env["user"], "yana savol")
    assert not res["ok"] and "chegara" in res["error"]


def _edits(sent):
    return [p.get("text", "") for m, p in sent if m == "editMessageText"]


@pytest.mark.django_db
def test_telegram_voice_stream_stop_flow(ai_env, monkeypatch):
    """Ovoz → darhol (tasdiqsiz) → javob yozila boradi → ⏹ To'xtatish → savol saqlanadi → 🔁 Qayta so'rash; diagramma rasm bo'lib keladi."""
    from modules.ai import agent, gemini, tg
    from modules.ai.models import AiChat, ChatState
    sent, t = ai_env["sent"], ai_env["tenant"]
    chat = {"id": 777001, "type": "private"}
    monkeypatch.setattr(gemini, "transcribe", lambda tenant, audio, mime="audio/ogg": {"text": "Kecha qancha savdo bo'ldi", "model": "m", "ms": 1, "tokens": 10})
    monkeypatch.setattr(tg, "EDIT_EVERY", 0)
    photos = []
    monkeypatch.setattr(tg, "send_photo", lambda tenant, chat_id, png, caption="": photos.append(caption) or True)
    asked, mode = [], {"stop": False}

    def fake_ask(tenant, user, q, on_text=None, stop=None, **kw):
        assert AiChat.objects.get(chat_id=777001).state == ChatState.BUSY
        assert tg.maybe_handle(tenant, {"message": {"chat": chat, "text": "salom"}})      # band — yangi buyruq yo'q
        asked.append(q)
        if mode["stop"]:
            assert tg.maybe_handle(tenant, {"callback_query": {"id": "s", "data": "ai:stop", "message": {"chat": chat, "message_id": 1}}})
            assert stop()
            return {"ok": False, "stopped": True, "error": "To'xtatildi", "tasks": [], "charts": []}
        on_text("Kecha savdo ")
        on_text("<b>10 mln</b>")
        return {"ok": True, "answer": "Kecha savdo <b>10 mln</b>", "tasks": [], "charts": [{"title": "7 kun", "png": b"PNG"}]}
    monkeypatch.setattr(agent, "ask", fake_ask)

    # 1) tugma → ovozli xabar so'raladi
    assert tg.maybe_handle(t, {"message": {"chat": chat, "text": "🤖 AI Kotib"}})
    assert AiChat.objects.get(chat_id=777001).state == ChatState.WAIT
    # 2) ovoz → tasdiqsiz: eshitilgan matn ko'rsatiladi, javob yozila boradi, oxirida to'liq javob va diagramma
    assert tg.maybe_handle(t, {"message": {"chat": chat, "voice": {"file_id": "F1", "duration": 5, "mime_type": "audio/ogg"}}})
    assert asked == ["Kecha qancha savdo bo'ldi"]
    ed = _edits(sent)
    assert any("Kecha qancha savdo bo'ldi" in x for x in ed)                 # 🗣 «…»
    assert any(x.endswith("▍") for x in ed)                                  # qoralama (yozilmoqda)
    assert ed[-1] == "Kecha savdo <b>10 mln</b>" and photos == ["📈 7 kun"]
    assert any("tayyorlanyapti" in x for x in _texts(sent))
    assert AiChat.objects.get(chat_id=777001).state == ChatState.IDLE
    # 3) tugmasiz matn — darhol bajariladi; ⏹ bosilsa — to'xtaydi, savol saqlanadi
    mode["stop"] = True
    assert tg.maybe_handle(t, {"message": {"chat": chat, "text": "Bugun nechta bron bor?"}})
    c = AiChat.objects.get(chat_id=777001)
    assert c.state == ChatState.WAIT and c.pending == "Bugun nechta bron bor?"
    assert "<code>Bugun nechta bron bor?</code>" in _texts(sent)[-1]
    assert "To'xtatildi" in _edits(sent)[-1]
    # 4) 🔁 Qayta so'rash — o'sha savol qayta ishlaydi
    mode["stop"] = False
    assert tg.maybe_handle(t, {"callback_query": {"id": "a", "data": "ai:again", "message": {"chat": chat, "message_id": 2}}})
    assert asked[-1] == "Bugun nechta bron bor?" and AiChat.objects.get(chat_id=777001).state == ChatState.IDLE
    # boshqa tugma — AI rejimi emas, oddiy ishlovchiga o'tadi
    assert tg.maybe_handle(t, {"message": {"chat": chat, "text": "📋 Vazifalarim"}}) is False
    # mijoz (xodim emas) yozsa — AI'ga tegmaydi
    assert tg.maybe_handle(t, {"message": {"chat": {"id": 12345, "type": "private"}, "text": "salom"}}) is False


@pytest.mark.django_db
def test_telegram_busy_stale_and_permissions(ai_env):
    from modules.ai import tg
    from modules.ai.models import AiChat, ChatState
    t, chat = ai_env["tenant"], {"id": 777001, "type": "private"}
    AiChat.objects.create(chat_id=777001, user=ai_env["user"], state=ChatState.BUSY)
    assert tg.maybe_handle(t, {"message": {"chat": chat, "text": "salom"}})
    assert "tayyorlanyapti" in _texts(ai_env["sent"])[-1]
    AiChat.objects.filter(chat_id=777001).update(updated_at=timezone.now() - timedelta(minutes=10))   # ip o'lgan — tiklanadi
    assert tg.maybe_handle(t, {"message": {"chat": chat, "text": "📋 Vazifalarim"}}) is False
    assert AiChat.objects.get(chat_id=777001).state == ChatState.IDLE
    # ruxsatsiz odam
    assert tg.maybe_handle(t, {"message": {"chat": {"id": 999, "type": "private"}, "text": "🤖 AI Kotib"}})
    assert "telefon raqamingizni ulashing" in _texts(ai_env["sent"])[-1]


@pytest.mark.django_db
def test_morning_report_sent_once_in_window(ai_env, monkeypatch):
    from modules.ai import gemini, services
    from modules.ai.models import AiDaily
    monkeypatch.setattr(gemini, "generate", FakeGemini([{"text": "BIRINCHI:\n1. 🛒 Mayonez oling\nXULOSA: Kecha yaxshi o'tdi."}] * 3))
    t = ai_env["tenant"]
    tz = timezone.get_current_timezone()
    early = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()).replace(hour=7), tz)
    assert services.send_morning(t, now=early) == {"sent": 0, "failed": 0, "skipped": 0}
    on_time = early.replace(hour=8, minute=40)
    r = services.send_morning(t, now=on_time)
    assert r["sent"] == 1 and AiDaily.objects.filter(user=ai_env["user"]).exists()
    msg = _texts(ai_env["sent"])[-1]
    assert "Mayonez oling" in msg and "Kecha yaxshi o'tdi" in msg
    assert services.send_morning(t, now=on_time + timedelta(minutes=5))["sent"] == 0      # takrorlanmaydi
    late = early.replace(hour=20)
    assert not services.due_now(t, late)


@pytest.mark.django_db
def test_ai_api(ai_env, api, monkeypatch):
    from modules.ai import gemini
    monkeypatch.delenv("GEMINI_API_KEY")
    s = api.get("/api/v1/ai/status").json()
    assert s["has_key"] is False and s["morning_time"] == "08:30"
    assert api.put("/api/v1/ai/settings", {"api_key": "short"}).status_code == 400
    assert api.put("/api/v1/ai/settings", {"morning_time": "25:00"}).status_code == 400
    s = api.put("/api/v1/ai/settings", {"api_key": "AIzaSyTESTKEY1234567890abcdef", "morning_time": "7:45"}).json()
    assert s["has_key"] and s["key_source"] == "restoran" and "…" in s["key_masked"] and s["morning_time"] == "07:45"
    r = api.get("/api/v1/ai/report").json()
    assert "Birinchi navbatda" in r["html"]
    monkeypatch.setattr(gemini, "generate", FakeGemini([{"text": "Salom"}]))
    assert api.post("/api/v1/ai/test").json()["ok"] is True
    monkeypatch.setattr(gemini, "generate", FakeGemini([{"text": "Javob: <b>5</b> ta"}]))
    assert "Javob" in api.post("/api/v1/ai/ask", {"question": "Nechta bron bor?"}).json()["answer"]
    assert len(api.get("/api/v1/ai/logs").json()) >= 2


def test_gemini_model_fallback_and_errors(monkeypatch):
    from types import SimpleNamespace

    from modules.ai import gemini
    t = SimpleNamespace(settings={"modules": {"ai": {"api_key": "k" * 30}}})
    calls = []

    class R:
        def __init__(self, code, body):
            self.status_code, self.text, self._b = code, str(body), body

        def json(self):
            return self._b

    def post(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            return R(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
        return R(200, {"candidates": [{"content": {"parts": [{"text": "o'yladim", "thought": True}, {"text": "ok"}]}}]})
    monkeypatch.setattr(gemini.requests, "post", post)
    r = gemini.generate(t, [{"role": "user", "parts": [{"text": "x"}]}])
    assert r["model"] == gemini.MODELS[1] and gemini.text_of(r["data"]) == "ok"
    monkeypatch.setattr(gemini.requests, "post", lambda url, **kw: R(400, {"error": {"message": "API key not valid. API_KEY_INVALID"}}))
    with pytest.raises(gemini.AiError, match="kaliti noto'g'ri"):
        gemini.generate(t, [])
    with pytest.raises(gemini.AiError, match="kiritilmagan"):
        gemini.generate(SimpleNamespace(settings={}), [])


def test_gemini_stream_merge_and_stop(monkeypatch):
    import json
    from types import SimpleNamespace

    from modules.ai import gemini
    t = SimpleNamespace(settings={"modules": {"ai": {"api_key": "k" * 30}}})
    chunks = [{"candidates": [{"content": {"parts": [{"text": "Salom, "}]}}]},
              {"candidates": [{"content": {"parts": [{"text": "dunyo", "thoughtSignature": "s1"}]}, "finishReason": "STOP"}], "usageMetadata": {"totalTokenCount": 7}}]
    sent_bodies = []

    class R:
        status_code = 200
        text = ""

        def iter_lines(self, decode_unicode=True):
            for c in chunks:
                yield "data: " + json.dumps(c)

        def close(self):
            pass

    def post(url, json=None, **kw):
        sent_bodies.append((url, json))
        return R()
    monkeypatch.setattr(gemini.requests, "post", post)
    got = []
    r = gemini.generate(t, [], on_text=got.append)
    assert got == ["Salom, ", "dunyo"] and gemini.text_of(r["data"]) == "Salom, dunyo" and gemini.tokens_of(r["data"]) == 7
    assert "alt=sse" in sent_bodies[0][0] and sent_bodies[0][1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    with pytest.raises(gemini.Stopped):
        gemini.generate(t, [], on_text=got.append, stop=lambda: True)


def test_chart_render_and_validate():
    from modules.ai import charts
    png = charts.render({"kind": "hbar", "title": "Top", "unit": "ta", "labels": ["A", "B"], "series": [{"values": [5, "3"]}]})
    assert png[:4] == b"\x89PNG"
    with pytest.raises(ValueError):
        charts.validate({"kind": "bar", "labels": [], "series": []})
    assert charts.short(12_500_000) == "12,5 mln"


@pytest.mark.django_db
def test_agent_make_chart_tool(ai_env, monkeypatch):
    from modules.ai import agent, gemini
    fake = FakeGemini([{"call": ("make_chart", {"kind": "bar", "title": "7 kun", "labels": ["Du", "Se"], "series": [{"name": "Savdo", "values": [1, 2]}]})},
                       {"text": "Mana diagramma"}])
    monkeypatch.setattr(gemini, "generate", fake)
    r = agent.ask(ai_env["tenant"], ai_env["user"], "7 kunlik savdoni diagrammada ko'rsat", channel="panel")
    assert r["ok"] and len(r["charts"]) == 1 and r["charts"][0]["png"][:4] == b"\x89PNG"
    assert any(d["name"] == "make_chart" for d in fake.seen[0]["tools"][0]["function_declarations"])


@pytest.mark.django_db
def test_ask_stream_endpoint(ai_env, api, monkeypatch):
    import json

    from modules.ai import agent

    def fake_ask(tenant, user, q, on_text=None, stop=None, **kw):
        on_text("Kecha ")
        on_text("10 mln")
        return {"ok": True, "answer": "Kecha 10 mln", "tasks": [], "charts": [{"title": "t", "png": b"\x89PNG"}]}
    monkeypatch.setattr(agent, "ask", fake_ask)
    r = api.post("/api/v1/ai/ask-stream", {"question": "Kecha savdo?"})
    assert r.status_code == 200
    lines = [json.loads(x) for x in b"".join(r.streaming_content).decode().splitlines() if x.strip()]
    assert [x.get("t") for x in lines if "t" in x] == ["Kecha ", "10 mln"]
    done = lines[-1]
    assert done["done"] and done["answer"] == "Kecha 10 mln" and done["charts"][0]["src"].startswith("data:image/png;base64,")
