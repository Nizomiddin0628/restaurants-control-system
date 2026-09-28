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
MAX_STEPS = 5

SYSTEM = """Sen — «{restaurant}» restoranining AI kotibisan. Seni {user} ({role}) ishlatyapti. Bugun: {today}, {weekday}, soat {time} (Toshkent).
Ko'radigan filiallar: {scope}.
Qoidalar:
1. Raqam, ism, sana — faqat asboblardan (funksiyalardan) ol. O'zingdan hech narsa to'qima. Ma'lumot bo'lmasa — «tizimda bu ma'lumot yo'q» de.
2. Javob — o'zbek tilida (lotin), to'liq va tushunarli (rahbar saytga kirmasdan hammasini bilsin):
   • boshida 1–2 gapli xulosa — eng muhim raqam bilan;
   • keyin tafsilotlar: 4–10 punkt — raqamlar, taqqoslash (o'tgan hafta/oy, filiallar), o'zgarish foizi;
   • ma'lumotdan sabab ko'rinsa — «Nima uchun» qisqa izoh;
   • oxirida 🎯 1–3 ta aniq tavsiya (kim, nima, qachongacha).
   To'liqroq javob uchun bir nechta asbobni birga chaqir (masalan sales + top_products + finance). Pul — «so'm», katta summalar «12,5 mln so'm».
3. Formatlash: faqat <b>qalin</b> va <i>kursiv</i>. Markdown (**, #, jadval) ishlatma. Bo'lim sarlavhalari — mos emoji + <b>sarlavha</b> (📊 Savdo, ⚠️ E'tibor, 🎯 Tavsiya). Punktlar «• » bilan, bo'limlar orasida bo'sh qator.
4. Diagramma: dinamika (kunlar bo'yicha), taqqoslash (filiallar, davrlar), reyting (top taomlar) yoki ulush bo'lsa — make_chart bilan 1 ta diagramma qo'sh (juda zarur bo'lsa 2 ta). Oddiy bitta raqamli savolga yoki ro'yxatga chizma. Rasm chizma — faqat make_chart.
5. Foydalanuvchi aniq buyursa (masalan «Rustamga ertaga 10:00 gacha ... vazifa ber») — create_task asbobini chaqir va natijasini ayt. Buyruq bo'lmasa vazifa yaratma.
6. Ovozdan yozilgan matnda xatolar bo'lishi mumkin — ma'nosini tushunishga harakat qil. Juda noaniq bo'lsa, qisqa aniqlashtiruvchi savol ber.
7. «Kecha», «bugun», «o'tgan hafta», «shu oy» kabi so'zlarni aniq sanaga aylantir (YYYY-MM-DD).
8. Pastdagi «HOZIRGI HOLAT» — tizimdan olingan tayyor raqamlar. Savolga ular yetarli bo'lsa — asbob chaqirmasdan darhol javob ber (tezroq). Batafsilroq yoki boshqa davr kerak bo'lsa — asbobni chaqir.
{persona}
{mode_rules}
HOZIRGI HOLAT ({snap_time} holatiga):
{snapshot}"""

PERSONA = """Sen ishlayotgan tizim — {platform}. Tizim haqida so'rashsa yoki boshqa dastur/xizmat bilan solishtirishsa:
• {platform}'ni ishonch va g'urur bilan tanishtir: O'zbekistonga birinchi bo'lib kirib kelgan, restoranning HAMMA ishini bitta joyda boshqaradigan tizim —
  kassa, oshxona ekrani, zal va bron, ombor va tannarx, zakup va bozorlik, xodimlar, smena va oylik, o'qitish, vazifalar, loyihalar, mijozlar va bonus,
  Telegram bot, sayt, ko'p filial, bayram va ob-havo prognozi hamda sening o'zing — ovoz bilan ishlaydigan AI Kotib.
• Uslub — hazil aralash ishonch (masalan: «Agar u yaxshiroq bo'lganida, siz hozir o'sha tizimda ishlayotgan bo'lardingiz 😉»), keyin 2–4 ta aniq afzallik.
• Boshqalarni yomonlama va ular haqida fakt to'qima; faqat {platform}'ning haqiqiy imkoniyatlarini ayt."""

MODE_LOCAL = "Rejim: 🏠 RESTORAN — faqat restoran ma'lumotlari (asboblar). Internetdagi yangilik yoki umumiy bilim so'ralsa, «🌐 Global qidiruv» rejimini tanlashni maslahat ber."
MODE_WEB = """Rejim: 🌐 GLOBAL (restoran + internet). Internetdan Google qidiruvi bilan izla: narxlar, bozor, raqobatchilar, trendlar, qonunlar, retseptlar, bayram g'oyalari va hokazo.
Restoran raqamlarini HOZIRGI HOLAT'dan ol va internet ma'lumoti bilan BIRLASHTIRIB, shu restoran uchun aniq tavsiya ber (masalan: «bozorda go'sht narxi … — sizda tannarx …, shuning uchun …»).
Internetdan olingan faktlarni qisqa ayt; manbalar javob oxiriga o'zi qo'shiladi."""


def snapshot(tenant, branch_ids) -> tuple[str, str]:
    """Bugungi holat (hisobot matni, teglarsiz) — AI savolga ko'pincha asbobsiz, bitta chaqiruvda javob beradi. 5 daqiqa keshlanadi."""
    from django.core.cache import cache
    key = "ai:snap:" + (",".join(map(str, sorted(branch_ids))) if branch_ids else "all")
    try:
        got = cache.get(key)
    except Exception:
        got = None
    if got:
        return got
    try:
        txt = re.sub(r"<[^>]+>", "", report.render(report.build(tenant, branch_ids)))
        txt = html.unescape(re.sub(r"\n{3,}", "\n\n", txt)).strip()[:6000]
    except Exception:
        log.exception("ai snapshot")
        txt = "(hozircha ma'lumot olinmadi — asboblardan foydalan)"
    val = (txt, timezone.localtime().strftime("%H:%M"))
    try:
        cache.set(key, val, 300)
    except Exception:
        pass
    return val


def _thinking(tenant) -> str:
    v = (gemini.conf(tenant).get("thinking") or "").strip()
    return v if v in ("minimal", "low", "medium", "high") else "minimal"


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
    return t[:12000]


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


def ask(tenant, user, question: str, *, channel: str = "telegram", kind: str = "ask", history: list[dict] | None = None,
        on_text=None, stop=None, mode: str = "local") -> dict:
    """Savolga javob. Natija: {"ok", "answer" (HTML), "error", "tasks": [...], "charts": [{"title", "png"}]}; har holda AiLog yoziladi.
    on_text(delta) — javob matni tayyor bo'lgani sari (oqim); on_text(None) — oldingi qoralama bekor (model asbob chaqirdi).
    stop() True bo'lsa — to'xtatiladi: {"ok": False, "stopped": True}."""
    t0 = time.monotonic()
    lg = AiLog(user=user, channel=channel, kind=kind, question=question[:4000])
    if limit_left(tenant) <= 0:
        lg.ok, lg.error = False, "kunlik chegara"
        lg.save()
        return {"ok": False, "error": "Bugungi AI so'rovlar chegarasi tugadi. Ertaga qayta urinib ko'ring (yoki panelda chegarani oshiring)."}
    now = timezone.localtime()
    ctx = _ctx(tenant, user)
    ctx.charts = []
    from django.conf import settings as dj
    web = mode == "web"
    snap, snap_time = snapshot(tenant, ctx.branch_ids)
    platform = getattr(dj, "PLATFORM_NAME", "RestoPOS")
    system = SYSTEM.format(restaurant=tenant.name, user=user.full_name or user.phone, role=_role(user), today=now.strftime("%Y-%m-%d"),
                           weekday=report.WD[now.weekday()], time=now.strftime("%H:%M"), scope=report._scope_name(ctx.branch_ids) or "bitta filial",
                           persona=PERSONA.format(platform=platform), mode_rules=MODE_WEB if web else MODE_LOCAL, snapshot=snap, snap_time=snap_time)
    decls = tools.available(tenant)
    think = _thinking(tenant)
    contents: list[dict] = [*_history(history), {"role": "user", "parts": [{"text": question}]}]
    created: list[dict] = []
    answer, calls, tokens, model = "", 0, 0, ""
    sources: list[dict] = []
    try:
        for step in range(MAX_STEPS + 1):
            final = step == MAX_STEPS
            if stop and stop():
                raise gemini.Stopped()
            if web:            # internet rejimi: Google qidiruvi (restoran raqamlari — HOZIRGI HOLAT'da), bitta chaqiruv
                tl = [{"google_search": {}}]
            else:
                tl = None if final else [{"function_declarations": decls}]
            res = gemini.generate(tenant, contents, system=system, tools=tl, temperature=0.3, on_text=on_text, stop=stop, fast=think)
            calls += 1
            tokens += gemini.tokens_of(res["data"])
            model = res["model"]
            fcalls = [] if final else gemini.calls_of(res["data"])
            if not fcalls:
                answer = gemini.text_of(res["data"])
                sources = gemini.sources_of(res["data"]) if web else []
                break
            if on_text:
                on_text(None)
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
        out = clean(answer)
        if sources:
            out += "\n\n🔗 <b>Manbalar:</b>\n" + "\n".join(
                f'• <a href="{html.escape(x["url"], quote=True)}" target="_blank" rel="noopener">{html.escape(x["title"][:60])}</a>' for x in sources)
        return {"ok": True, "answer": out, "tasks": created, "charts": ctx.charts, "sources": sources, "mode": mode}
    except gemini.Stopped:
        lg.ok, lg.error, lg.calls, lg.tokens, lg.model = False, "to'xtatildi", calls, tokens, model
        lg.ms = int((time.monotonic() - t0) * 1000)
        lg.save()
        return {"ok": False, "stopped": True, "error": "To'xtatildi", "tasks": created, "charts": []}
    except gemini.AiError as e:
        lg.ok, lg.error, lg.calls, lg.tokens, lg.model = False, str(e)[:240], calls, tokens, model
        lg.ms = int((time.monotonic() - t0) * 1000)
        lg.save()
        return {"ok": False, "error": str(e), "tasks": created, "charts": []}


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
