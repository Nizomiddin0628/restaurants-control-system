"""AI Kotib API — /api/v1/ai/... (panel: holat, sozlamalar, hisobotni ko'rish/yuborish, savol berish, jurnal)."""
from __future__ import annotations

import re
from typing import Optional

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.auth import auth, require_module, require_perm

from . import agent, gemini, report, services, tg
from .models import AiDaily, AiLog

router = Router(tags=["ai"])


def _guard(request, perm: str = "ai.use"):
    require_module(request, "ai")
    require_perm(request, perm)


def _mask(v: str) -> str:
    return (v[:4] + "…" + v[-4:]) if v and len(v) > 10 else ("••••" if v else "")


def _status(request) -> dict:
    t = request.tenant
    c = gemini.conf(t)
    key = gemini.api_key(t) or ""
    users = services.recipients(t)
    today = timezone.localdate()
    got = {d.user_id: d for d in AiDaily.objects.filter(date=today)}
    from core.models import User
    staff = [u for u in User.objects.filter(is_active=True, memberships__is_active=True).distinct() if tg.eligible(t, u)]
    return {
        "has_key": bool(key), "key_source": gemini.key_source(t), "key_masked": _mask(key),
        "model": (c.get("model") or "").strip(), "models": gemini.MODELS,
        "morning_enabled": services.morning_on(t), "morning_time": services.morning_time(t).strftime("%H:%M"),
        "daily_limit": int(c.get("daily_limit") or 60), "used_today": agent.used_today(), "bot_connected": bool(tg._tok(t)),
        "recipients": [{"id": str(u.pk), "name": u.full_name or u.phone, "telegram": bool(u.telegram_id),
                        "role": ", ".join(m.role.name for m in u.memberships.filter(is_active=True).select_related("role")),
                        "sent_today": (got[u.pk].ok if u.pk in got else None)} for u in staff],
        "recipients_ready": len(users),
        "can_manage": request.auth.has_perm_code("ai.manage"),
    }


@router.get("/status", auth=auth)
def status(request):
    _guard(request)
    return _status(request)


class SettingsIn(Schema):
    morning_enabled: Optional[bool] = None
    morning_time: Optional[str] = None
    api_key: Optional[str] = None
    clear_key: bool = False
    model: Optional[str] = None
    daily_limit: Optional[int] = None


@router.put("/settings", auth=auth)
def put_settings(request, data: SettingsIn):
    _guard(request, "ai.manage")
    t = request.tenant
    s = dict(t.settings or {})
    mods = dict(s.get("modules") or {})
    c = dict(mods.get("ai") or {})
    if data.morning_enabled is not None:
        c["morning_enabled"] = data.morning_enabled
    if data.morning_time is not None:
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", data.morning_time.strip()):
            raise HttpError(400, "Vaqtni SS:DD ko'rinishida kiriting (masalan 08:30)")
        c["morning_time"] = data.morning_time.strip().zfill(5)
    if data.clear_key:
        c["api_key"] = ""
    elif data.api_key and data.api_key.strip():
        k = data.api_key.strip()
        if len(k) < 20 or " " in k:
            raise HttpError(400, "Kalit noto'g'ri ko'rinadi — AI Studio'dagi «Copy» tugmasi bilan to'liq nusxalang")
        c["api_key"] = k
    if data.model is not None:
        c["model"] = data.model.strip()
    if data.daily_limit is not None:
        c["daily_limit"] = max(5, min(int(data.daily_limit), 1000))
    mods["ai"] = c
    s["modules"] = mods
    t.settings = s
    t.save(update_fields=["settings"])
    return _status(request)


@router.post("/test", auth=auth)
def test_key(request):
    """Kalitni tekshirish — AI'ga bitta qisqa so'rov."""
    _guard(request, "ai.manage")
    try:
        r = gemini.generate(request.tenant, [{"role": "user", "parts": [{"text": "Bitta so'z bilan javob ber: Salom"}]}], temperature=0, max_tokens=256, timeout=40)
    except gemini.AiError as e:
        AiLog.objects.create(user=request.auth, channel="panel", kind="test", question="Kalit tekshiruvi", ok=False, error=str(e)[:240])
        return {"ok": False, "error": str(e)}
    AiLog.objects.create(user=request.auth, channel="panel", kind="test", question="Kalit tekshiruvi", answer=gemini.text_of(r["data"])[:200],
                         model=r["model"], calls=1, tokens=gemini.tokens_of(r["data"]), ms=r["ms"])
    return {"ok": True, "model": r["model"], "ms": r["ms"], "answer": gemini.text_of(r["data"])[:120]}


@router.get("/report", auth=auth)
def get_report(request, ai: int = 0, branch_id: Optional[int] = None):
    """Hisobot ko'rinishi (Telegram'dagidek). ai=1 — AI xulosasi bilan (1 ta so'rov)."""
    _guard(request)
    u = request.auth
    scope = report.scope_of(u)
    ids = scope
    if branch_id:
        if scope and branch_id not in scope:
            raise HttpError(403, "Bu filialga ruxsat yo'q")
        ids = [branch_id]
    use_ai = bool(ai) and agent.limit_left(request.tenant) > 0
    text, info = report.full_text(request.tenant, u, ids, use_ai=use_ai)
    if use_ai:
        a = info["ai"]
        AiLog.objects.create(user=u, channel="panel", kind="report", question="Kunlik hisobot (panel)", answer=text[:8000],
                             ok=not a.get("error"), error=(a.get("error") or "")[:240], model=a.get("model") or "", calls=a.get("calls") or 0, tokens=a.get("tokens") or 0)
    return {"html": text, "ai": info.get("ai"), "generated_at": timezone.localtime().strftime("%H:%M")}


@router.post("/report/send", auth=auth)
def send_report(request):
    """Hisobotni hozir Telegram'ga yuborish (sinov): o'zimga yoki hammaga."""
    _guard(request, "ai.manage")
    t = request.tenant
    if not tg._tok(t):
        raise HttpError(400, "Telegram bot ulanmagan — avval «Telegram bot» sahifasida tokenni kiriting")
    rec = services.recipients(t)
    if not rec:
        raise HttpError(400, "Hisobot oluvchi yo'q: rahbar/menejerlar botga telefon raqamini ulashishi kerak")
    r = services.send_morning(t, force=True, users=rec)
    return {"ok": True, **r}


class AskIn(Schema):
    question: str


@router.post("/ask", auth=auth)
def ask(request, data: AskIn):
    _guard(request)
    q = (data.question or "").strip()
    if len(q) < 3:
        raise HttpError(400, "Savolni yozing")
    res = agent.ask(request.tenant, request.auth, q[:1500], channel="panel")
    return res


@router.get("/logs", auth=auth)
def logs(request, limit: int = 30):
    _guard(request)
    qs = AiLog.objects.select_related("user")
    if not request.auth.has_perm_code("ai.manage"):
        qs = qs.filter(user=request.auth)
    return [{"id": x.pk, "at": timezone.localtime(x.created_at).strftime("%d.%m %H:%M"), "user": (x.user.full_name or x.user.phone) if x.user_id else "Tizim",
             "channel": x.channel, "kind": x.kind, "question": x.question[:300], "answer": x.answer[:600] if x.kind in ("ask", "voice", "test") else "",
             "ok": x.ok, "error": x.error, "model": x.model, "calls": x.calls, "tokens": x.tokens, "sec": round(x.ms / 1000, 1)} for x in qs[:max(1, min(limit, 100))]]
