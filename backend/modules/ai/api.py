"""AI Kotib API — /api/v1/ai/... (panel: holat, sozlamalar, hisobotni ko'rish/yuborish, savol berish, jurnal)."""
from __future__ import annotations

import re
from typing import Optional

from django.utils import timezone
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.auth import auth, require_module, require_perm

from . import agent, gemini, limits, report, services, tg
from .models import AiDaily, AiLog

router = Router(tags=["ai"])


def _guard(request, perm: str = "ai.use"):
    require_module(request, "ai")
    if not limits.platform(request.tenant)["enabled"]:
        raise HttpError(403, "AI Kotib tarifingizda yoqilmagan — platforma bilan bog'laning")
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
        "daily_limit": agent.daily_limit(t), "daily_limit_own": int(c.get("daily_limit") or 0), "used_today": agent.used_today(), "bot_connected": bool(tg._tok(t)),
        "recipients": [{"id": str(u.pk), "name": u.full_name or u.phone, "telegram": bool(u.telegram_id),
                        "role": ", ".join(m.role.name for m in u.memberships.filter(is_active=True).select_related("role")),
                        "sent_today": (got[u.pk].ok if u.pk in got else None)} for u in staff],
        "recipients_ready": len(users),
        "can_manage": request.auth.has_perm_code("ai.manage"),
        "platform": limits.platform(t), "seats": limits.seats_info(t),
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
        c["daily_limit"] = 0 if int(data.daily_limit) <= 0 else max(1, min(int(data.daily_limit), 5000))
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


class Turn(Schema):
    role: str = "user"
    text: str = ""


class AskIn(Schema):
    question: str
    history: list[Turn] = []


def _web(res: dict) -> dict:
    """Panel uchun: diagrammalar rasm-manzil (data URL) ko'rinishida."""
    from . import charts
    return {**{k: v for k, v in res.items() if k != "charts"},
            "charts": [{"title": c["title"], "src": charts.data_url(c["png"])} for c in res.get("charts") or []]}


@router.post("/ask", auth=auth)
def ask(request, data: AskIn):
    _guard(request)
    q = (data.question or "").strip()
    if len(q) < 2:
        raise HttpError(400, "Savolni yozing")
    return _web(agent.ask(request.tenant, request.auth, q[:1500], channel="panel", history=[h.dict() for h in data.history]))


@router.post("/ask-stream", auth=auth)
def ask_stream(request, data: AskIn):
    """Chatdagidek: javob yozila boradi. Qatorlar (JSON): {"t": bo'lak} | {"reset": true} | {"done": true, ...natija}.
    Brauzer ulanishni uzsa («⏹ To'xtatish») — AI ishi ham to'xtaydi."""
    import json
    import queue
    import threading

    from django.db import connection
    from django.http import StreamingHttpResponse
    from django_tenants.utils import schema_context
    _guard(request)
    q = (data.question or "").strip()
    if len(q) < 2:
        raise HttpError(400, "Savolni yozing")
    tenant, user, hist = request.tenant, request.auth, [h.dict() for h in data.history]
    box: queue.Queue = queue.Queue()
    flag = {"stop": False}

    def work():
        try:
            with schema_context(tenant.schema_name):
                connection.set_tenant(tenant)
                res = agent.ask(tenant, user, q[:1500], channel="panel", history=hist,
                                on_text=lambda d: box.put(("t", d)), stop=lambda: flag["stop"])
                box.put(("done", _web(res)))
        except Exception as e:  # noqa: BLE001 — foydalanuvchiga tushunarli xato
            box.put(("done", {"ok": False, "error": f"Ichki xato: {type(e).__name__}"}))
        finally:
            connection.close()

    threading.Thread(target=work, daemon=True).start()

    def gen():
        try:
            yield json.dumps({"start": True}) + "\n"
            while True:
                try:
                    kind, val = box.get(timeout=170)
                except queue.Empty:
                    flag["stop"] = True
                    yield json.dumps({"done": True, "ok": False, "error": "AI juda uzoq javob bermadi — qayta urinib ko'ring"}) + "\n"
                    return
                if kind == "t":
                    yield json.dumps({"reset": True} if val is None else {"t": val}, ensure_ascii=False) + "\n"
                else:
                    yield json.dumps({"done": True, **val}, ensure_ascii=False) + "\n"
                    return
        finally:
            flag["stop"] = True          # brauzer uzdi yoki tugadi — AI ishini to'xtatish

    resp = StreamingHttpResponse(gen(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@router.post("/transcribe", auth=auth)
def transcribe(request, file: UploadedFile = File(...)):
    """Paneldagi mikrofon: ovoz → matn (keyin foydalanuvchi ko'rib, «Yuborish»ni bosadi — tasdiq)."""
    _guard(request)
    if file.size and file.size > 12 * 1024 * 1024:
        raise HttpError(400, "Ovozli xabar juda katta (12 MB gacha)")
    if agent.limit_left(request.tenant) <= 0:
        raise HttpError(429, "Bugungi AI so'rovlar chegarasi tugadi")
    mime = (file.content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    lg = AiLog(user=request.auth, channel="panel", kind="voice", question="(ovozli xabar)")
    try:
        tr = gemini.transcribe(request.tenant, file.read(), mime)
    except gemini.AiError as e:
        lg.ok, lg.error = False, str(e)[:240]
        lg.save()
        raise HttpError(400, str(e)) from None
    text = (tr["text"] or "").strip()
    lg.answer, lg.model, lg.calls, lg.tokens, lg.ms = text[:4000], tr["model"], 1, tr["tokens"], tr["ms"]
    lg.save()
    if not text or "[tushunarsiz]" in text.lower():
        raise HttpError(400, "Ovozni tushunib bo'lmadi — aniqroq gapirib qayta yozing")
    return {"text": text}


@router.get("/logs", auth=auth)
def logs(request, limit: int = 30):
    _guard(request)
    qs = AiLog.objects.select_related("user")
    if not request.auth.has_perm_code("ai.manage"):
        qs = qs.filter(user=request.auth)
    return [{"id": x.pk, "at": timezone.localtime(x.created_at).strftime("%d.%m %H:%M"), "user": (x.user.full_name or x.user.phone) if x.user_id else "Tizim",
             "channel": x.channel, "kind": x.kind, "question": x.question[:300], "answer": x.answer[:600] if x.kind in ("ask", "voice", "test") else "",
             "ok": x.ok, "error": x.error, "model": x.model, "calls": x.calls, "tokens": x.tokens, "sec": round(x.ms / 1000, 1)} for x in qs[:max(1, min(limit, 100))]]


# ------------------------------------------------------------------ AI Kotib kimlarda bor (Superadmin taqsimlaydi)
def _seat_row(u, actor) -> dict:
    from core.access import can_manage_user, covers
    role_perms = u.role_permissions()
    return {"id": str(u.pk), "name": u.full_name or u.phone, "phone": u.phone, "telegram": bool(u.telegram_id),
            "role": ", ".join(m.role.name for m in u.memberships.filter(is_active=True).select_related("role")),
            "on": u.has_perm_code("ai.use"), "by_role": covers(role_perms, "ai.use"),
            "editable": can_manage_user(actor, u) and not covers(role_perms, "ai.use")}


@router.get("/seats", auth=auth)
def seats(request):
    """Kimlar AI Kotibdan foydalanadi: platforma bergan o'rinlar va xodimlar ro'yxati (yoqish/o'chirish)."""
    _guard(request, "ai.manage")
    from core.models import User
    actor = request.auth
    users = (User.objects.filter(is_active=True, memberships__is_active=True).exclude(memberships__role__code="platform_support")
             .distinct().order_by("full_name"))
    scope = actor.branch_scope()
    if scope is not None:
        users = users.filter(memberships__branches__in=scope).distinct()
    rows = [_seat_row(u, actor) for u in users]
    rows.sort(key=lambda r: (not r["on"], r["name"]))
    return {**limits.seats_info(request.tenant), "users": rows}


class SeatIn(Schema):
    user_id: str
    on: bool


@router.post("/seats", auth=auth)
def set_seat(request, data: SeatIn):
    _guard(request, "ai.manage")
    from django.db import transaction
    from django.shortcuts import get_object_or_404

    from core.access import can_manage_user
    from core.audit import record
    from core.models import User
    u = get_object_or_404(User, pk=data.user_id, is_active=True)
    if not can_manage_user(request.auth, u):
        raise HttpError(403, "Bu xodimga AI Kotibni bera olmaysiz (sizdan yuqori daraja yoki boshqa filial)")
    extra = [p for p in (u.extra_permissions or []) if p != "ai.use"]
    with transaction.atomic():
        if data.on:
            u.extra_permissions = [*extra, "ai.use"]
            u.save(update_fields=["extra_permissions"])
            if limits.over_seats(request.tenant):
                raise HttpError(400, f"O'rinlar tugagan: tarifingizda {limits.platform(request.tenant)['seats']} kishi. Avval boshqa xodimdan oling.")
        else:
            u.extra_permissions = extra
            u.save(update_fields=["extra_permissions"])
            if u.has_perm_code("ai.use"):
                raise HttpError(400, "Bu xodimda AI Kotib roli orqali bor — «Xodimlar kirishi» sahifasida rolini o'zgartiring")
    record(request, "update", u, after={"ai": data.on})
    return {**limits.seats_info(request.tenant), "user": _seat_row(u, request.auth)}
