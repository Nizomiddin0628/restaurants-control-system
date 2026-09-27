"""
AI Kotib — rahbar/menejer savoli yoki buyrug'iga javob.

Oqim: savol → Gemini (asboblar ro'yxati bilan) → kerakli asboblar chaqiriladi (tizimdan raqamlar) → yakuniy javob.
Ko'pi bilan 4 aylanish. Javob Telegram HTML'ga moslab tozalanadi (faqat <b>, <i>).
Har so'rov AiLog'ga yoziladi; restoran bo'yicha kunlik chegarasi bor (sozlama daily_limit).
"""
from __future__ import annotations

import html
import logging
import re
import time
from types import SimpleNamespace

from django.utils import timezone

from . import gemini, report, tools
from .models import AiLog

log = logging.getLogger("ai")
MAX_STEPS = 4

SYSTEM = """Sen — «{restaurant}» restoranining AI kotibisan. Seni {user} ({role}) ishlatyapti. Bugun: {today}, {weekday}, soat {time} (Toshkent).
Ko'radigan filiallar: {scope}.
Qoidalar:
1. Raqam, ism, sana — faqat asboblardan (funksiyalardan) ol. O'zingdan hech narsa to'qima. Ma'lumot bo'lmasa — «tizimda bu ma'lumot yo'q» de.
2. Javob — o'zbek tilida (lotin), qisqa va tartibli: avval asosiy javob (1–2 gap), keyin kerak bo'lsa 3–7 ta punkt. Pul — «so'm», katta summalar «12,5 mln so'm» ko'rinishida.
3. Formatlash: faqat <b>qalin</b> va <i>kursiv</i>. Markdown (**, #, jadval) ishlatma. Punktlar «• » bilan.
4. Oxirida, foydali bo'lsa, 1 ta aniq maslahat yoki keyingi qadam yoz (🎯 bilan).
5. Foydalanuvchi aniq buyursa (masalan «Rustamga ertaga 10:00 gacha ... vazifa ber») — create_task asbobini chaqir va natijasini ayt. Buyruq bo'lmasa vazifa yaratma.
6. Ovozdan yozilgan matnda xatolar bo'lishi mumkin — ma'nosini tushunishga harakat qil. Juda noaniq bo'lsa, qisqa aniqlashtiruvchi savol ber.
7. «Kecha», «bugun», «o'tgan hafta», «shu oy» kabi so'zlarni aniq sanaga aylantir (YYYY-MM-DD)."""


def _ctx(tenant, user) -> SimpleNamespace:
    return SimpleNamespace(tenant=tenant, user=user, branch_ids=report.scope_of(user))


def _role(user) -> str:
    m = user.memberships.filter(is_active=True).select_related("role").first()
    return m.role.name if m else "xodim"


ALLOWED = ("b", "i")


def clean(text: str) -> str:
    """AI matnini Telegram HTML'ga moslash: hammasi ekranlanadi, faqat <b>/<i> qoldiriladi, markdown → teg."""
    t = (text or "").strip()
    t = html.escape(t, quote=False)
    for tag in ALLOWED:
        t = re.sub(rf"&lt;{tag}&gt;(.*?)&lt;/{tag}&gt;", rf"<{tag}>\1</{tag}>", t, flags=re.S)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"<b>\1</b>", t)
    t = re.sub(r"(?m)^\s*[\*\-]\s+", "• ", t)
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t[:3800]


def used_today(user=None) -> int:
    qs = AiLog.objects.filter(created_at__date=timezone.localdate(), calls__gt=0)
    return qs.count()


def daily_limit(tenant) -> int:
    """0 — cheklovsiz. Restoran sozlamasi va platforma (tarif) chegarasidan kichigi."""
    from .limits import combine, platform
    try:
        own = max(0, int(gemini.conf(tenant).get("daily_limit") or 0))
    except (TypeError, ValueError):
        own = 0
    return combine(own, platform(tenant)["daily_limit"])


def limit_left(tenant) -> int:
    lim = daily_limit(tenant)
    return 10**6 if lim == 0 else max(0, lim - used_today())


def _history(history: list[dict] | None) -> list[dict]:
    """Oldingi suhbat (panel chati): so'nggi 8 ta xabar — «bu haqida batafsil», «filiallar bo'yicha-chi?» kabi davom savollari uchun."""
    out: list[dict] = []
    for h in (history or [])[-8:]:
        txt = re.sub(r"<[^>]+>", "", str(h.get("text") or ""))[:1500].strip()
        if txt:
            out.append({"role": "model" if h.get("role") == "ai" else "user", "parts": [{"text": txt}]})
    while out and out[0]["role"] != "user":          # suhbat foydalanuvchi xabari bilan boshlanishi kerak
        out.pop(0)
    return out


def ask(tenant, user, question: str, *, channel: str = "telegram", kind: str = "ask", history: list[dict] | None = None) -> dict:
    """Savolga javob. Natija: {"ok", "answer" (HTML), "error", "tasks": [...]}; har holda AiLog yoziladi."""
    t0 = time.monotonic()
    lg = AiLog(user=user, channel=channel, kind=kind, question=question[:4000])
    if limit_left(tenant) <= 0:
        lg.ok, lg.error = False, "kunlik chegara"
        lg.save()
        return {"ok": False, "error": "Bugungi AI so'rovlar chegarasi tugadi. Ertaga qayta urinib ko'ring (yoki panelda chegarani oshiring)."}
    now = timezone.localtime()
    ctx = _ctx(tenant, user)
    system = SYSTEM.format(restaurant=tenant.name, user=user.full_name or user.phone, role=_role(user), today=now.strftime("%Y-%m-%d"),
                           weekday=report.WD[now.weekday()], time=now.strftime("%H:%M"), scope=report._scope_name(ctx.branch_ids) or "bitta filial")
    decls = tools.available(tenant)
    contents: list[dict] = [*_history(history), {"role": "user", "parts": [{"text": question}]}]
    created: list[dict] = []
    answer, calls, tokens, model = "", 0, 0, ""
    try:
        for step in range(MAX_STEPS + 1):
            final = step == MAX_STEPS
            res = gemini.generate(tenant, contents, system=system, tools=None if final else [{"function_declarations": decls}], temperature=0.3)
            calls += 1
            tokens += gemini.tokens_of(res["data"])
            model = res["model"]
            fcalls = [] if final else gemini.calls_of(res["data"])
            if not fcalls:
                answer = gemini.text_of(res["data"])
                break
            content = (res["data"]["candidates"][0].get("content") or {})
            contents.append({"role": "model", "parts": content.get("parts") or []})
            out_parts = []
            for fc in fcalls[:6]:
                name, args = fc.get("name", ""), fc.get("args") or {}
                result = tools.run(ctx, name, args)
                if name == "create_task" and result.get("ok"):
                    created.append(result)
                resp = {"name": name, "response": {"result": result}}
                if fc.get("id"):
                    resp["id"] = fc["id"]
                out_parts.append({"functionResponse": resp})
            contents.append({"role": "user", "parts": out_parts})
        if not answer:
            answer = "Javob tayyorlab bo'lmadi. Savolni qisqaroq va aniqroq qilib qayta bering."
        lg.answer, lg.model, lg.calls, lg.tokens = answer[:8000], model, calls, tokens
        lg.ms = int((time.monotonic() - t0) * 1000)
        lg.save()
        return {"ok": True, "answer": clean(answer), "tasks": created}
    except gemini.AiError as e:
        lg.ok, lg.error, lg.calls, lg.tokens, lg.model = False, str(e)[:240], calls, tokens, model
        lg.ms = int((time.monotonic() - t0) * 1000)
        lg.save()
        return {"ok": False, "error": str(e), "tasks": created}


def morning(tenant, user, *, channel: str = "morning", use_ai: bool = True) -> tuple[list[str], dict]:
    """Ertalabki hisobot (bo'laklarga bo'lingan) + AiLog."""
    t0 = time.monotonic()
    use_ai = use_ai and limit_left(tenant) > 0
    text, info = report.full_text(tenant, user, use_ai=use_ai)
    ai = info["ai"]
    AiLog.objects.create(user=user, channel=channel, kind="report", question="Kunlik hisobot", answer=text[:8000], ok=not ai.get("error") or ai.get("error") in ("kalit yo'q", "o'chirilgan"),
                         error=(ai.get("error") or "")[:240], model=ai.get("model") or "", calls=ai.get("calls") or 0, tokens=ai.get("tokens") or 0,
                         ms=int((time.monotonic() - t0) * 1000))
    return report.split(text), info
