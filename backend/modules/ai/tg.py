"""
Telegram'da «🤖 AI Kotib» — rahbar va menejerlar uchun (ruxsat: ai.use, platforma tarifi doirasida).

Oqim (v34):
  1) Ovozli xabar yoki matn (tugma bosmasdan ham) → darhol ishga tushadi (tasdiq so'ralmaydi —
     noto'g'ri yozilsa, xodim uni o'chirib qayta yuboradi).
  2) Ovoz → «🗣 «…»» (eshitilgan matn) → javob chatdagidek YOZILA BORADI (xabar tahrirlanib to'ladi).
  3) Yozilayotganda «⏹ To'xtatish» — AI ishi to'xtaydi, savol saqlanadi: «🔁 Qayta so'rash» yoki o'zgartirib yuborish.
  4) Kerak bo'lsa — diagramma (rasm) ham keladi (make_chart asbobi).
  «📊 Bugungi hisobot» → kunlik hisobot darhol.
Bitta so'rov qoidasi: javob yozilayotganda yangi buyruq qabul qilinmaydi (⏹ bilan to'xtatish mumkin).
Uzoq ishlar alohida ipda — Telegram webhook'i darhol javob oladi.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import timedelta

import requests
from django.db import transaction
from django.utils import timezone

from core.models import User
from integrations.telegram import call

from . import agent, gemini, report
from .models import AiChat, AiLog, ChatState

log = logging.getLogger("ai")
BTN_AI, BTN_REPORT, BTN_WEB = "🤖 AI Kotib", "📊 Bugungi hisobot", "🌐 Global qidiruv"
TRIG_AI = (BTN_AI, "/ai", "/kotib")
TRIG_WEB = (BTN_WEB, "/global", "/internet")
TRIG_REPORT = (BTN_REPORT, "/hisobot")
CANCEL = ("✖️ Bekor qilish", "/cancel", "/bekor")
STALE = timedelta(minutes=4)          # «busy» shundan uzoq tursa — ip o'lgan deb hisoblanadi, holat tiklanadi
MAX_VOICE_SEC = 180
RUN_ASYNC = True                      # testlarda False — hammasi shu ipda


# ------------------------------------------------------------------ yordamchilar
def _tok(tenant) -> str | None:
    import os
    saved = ((((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("telegram") or {}).get("bot_token") or "").strip()
    return saved or os.environ.get("TELEGRAM_BOT_TOKEN") or None


def send(tenant, chat_id, text: str, markup: dict | None = None) -> int | None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    r = call("sendMessage", payload, _tok(tenant))
    if not r.get("ok") and "parse" in str(r.get("description", "")).lower():
        payload.pop("parse_mode")                  # HTML buzilgan bo'lsa — oddiy matn sifatida
        r = call("sendMessage", payload, _tok(tenant))
    return ((r.get("result") or {}).get("message_id")) if r.get("ok") else None


def send_long(tenant, chat_id, text: str) -> bool:
    ok = True
    for part in report.split(text):
        ok = send(tenant, chat_id, part) is not None and ok
    return ok


def typing(tenant, chat_id, action: str = "typing") -> None:
    call("sendChatAction", {"chat_id": chat_id, "action": action}, _tok(tenant))


def _drop_buttons(tenant, chat_id, message_id) -> None:
    if not message_id:
        return
    call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}}, _tok(tenant))


def download(tenant, file_id: str) -> bytes:
    tok = _tok(tenant)
    r = call("getFile", {"file_id": file_id}, tok)
    path = (r.get("result") or {}).get("file_path")
    if not (tok and path):
        raise gemini.AiError("Ovozli xabarni Telegram'dan yuklab bo'lmadi.")
    resp = requests.get(f"https://api.telegram.org/file/bot{tok}/{path}", timeout=30)
    resp.raise_for_status()
    return resp.content


def eligible(tenant, user) -> bool:
    from .limits import platform
    return bool(user and user.is_active and tenant.module_enabled("ai") and platform(tenant)["enabled"] and user.has_perm_code("ai.use")
                and user.memberships.filter(is_active=True).exists())


def staff_user(tenant, chat_id) -> User | None:
    u = User.objects.filter(telegram_id=chat_id, is_active=True).first()
    return u if eligible(tenant, u) else None


def _known_buttons() -> set[str]:
    try:
        from modules.telegram import services as tgs
        return {tgs.BTN_MENU, tgs.BTN_BOOK, tgs.BTN_ORDERS, tgs.BTN_CONTACT, tgs.BTN_BONUS, tgs.BTN_PHONE, tgs.BTN_CANCEL, tgs.BTN_ME, "💼 Vakansiyalar", *tgs.STAFF_BUTTONS}
    except Exception:
        return set()


def keyboard_row() -> list[dict]:
    return [{"text": BTN_AI}, {"text": BTN_WEB}]


def keyboard_rows() -> list[list[dict]]:
    """Xodim klaviaturasidagi AI qatorlari: [🤖 AI Kotib] [🌐 Global qidiruv] / [📊 Bugungi hisobot]."""
    return [keyboard_row(), [{"text": BTN_REPORT}]]


def mode_kb(mode: str) -> dict:
    web = mode == "web"
    return {"inline_keyboard": [[{"text": ("◻️ " if web else "✅ ") + "🏠 Restoran", "callback_data": "ai:mode:local"},
                                 {"text": ("✅ " if web else "◻️ ") + "🌐 Global (internet)", "callback_data": "ai:mode:web"}],
                                [{"text": "✖️ Bekor qilish", "callback_data": "ai:no"}]]}


PROMPT_WEB = ("🌐 <b>Global qidiruv</b> — restoran ma'lumotlari + internet (Google).\n\n"
              "Ovozli xabar yuboring yoki yozing. Masalan:\n• «Go'sht narxi hozir qancha, bizning tannarxga qanday ta'sir qiladi?»\n"
              "• «30-oktabr bayramiga qanday aksiya va bonuslar qilsak bo'ladi?»\n• «Toshkentda restoranlarda qanday trendlar bor?»\n\n"
              "<i>Rejimni pastdagi tugma bilan almashtirasiz.</i>")


def _stale(c: AiChat) -> bool:
    return c.state == ChatState.BUSY and timezone.now() - c.updated_at > STALE


def _set(chat_id, state: str, *, expect: tuple | None = None, **fields) -> bool:
    """Holatni atomar o'zgartirish. expect berilsa — faqat shu holatlardan o'tadi (ikki marta bosishdan himoya)."""
    with transaction.atomic():
        c = AiChat.objects.select_for_update().filter(chat_id=chat_id).first()
        if c is None:
            return False
        if expect and c.state not in expect and not _stale(c):
            return False
        c.state = state
        c.updated_at = timezone.now()
        for k, v in fields.items():
            setattr(c, k, v)
        c.save()
        return True


def _spawn(tenant, fn, *args) -> None:
    if not RUN_ASYNC:
        fn(tenant, *args)
        return
    schema = tenant.schema_name

    def run():
        from django.db import connection
        from django_tenants.utils import schema_context
        try:
            with schema_context(schema):
                connection.set_tenant(tenant)
                fn(tenant, *args)
        except Exception:
            log.exception("ai ipi: %s", getattr(fn, "__name__", "?"))
            try:
                with schema_context(schema):
                    _set(args[1], ChatState.IDLE)
            except Exception:
                pass
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()


STOP_KB = {"inline_keyboard": [[{"text": "⏹ To'xtatish", "callback_data": "ai:stop"}]]}
WAIT_KB = {"inline_keyboard": [[{"text": "✖️ Bekor qilish", "callback_data": "ai:no"}]]}
SAVED_KB = {"inline_keyboard": [[{"text": "🔁 Qayta so'rash", "callback_data": "ai:again"}, {"text": "✖️ Bekor", "callback_data": "ai:no"}]]}
PROMPT = ("🎙 <b>Ovozli xabar yuboring</b> (yoki yozing) — nima kerakligini ayting.\n\n"
          "Masalan:\n• «Kecha qancha savdo bo'ldi, o'tgan haftadan farqi qancha?»\n• «Omborda nima tugayapti?»\n"
          "• «Oxirgi 7 kun savdosini filiallar bo'yicha diagrammada ko'rsat»\n"
          "• «Rustamga ertaga soat 10 gacha muzlatgichni tozalash vazifasini ber»\n\n"
          "<i>Javob yozilayotganda «⏹ To'xtatish» tugmasi bo'ladi.</i>")
EDIT_EVERY = 1.1                      # soniya: javob qoralamasi shunchalik tez-tez yangilanadi
PREVIEW_MAX = 3500


def edit(tenant, chat_id, message_id, text: str, markup: dict | None = None) -> bool:
    if not message_id:
        return False
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
               "reply_markup": markup or {"inline_keyboard": []}}
    r = call("editMessageText", payload, _tok(tenant))
    if not r.get("ok") and "parse" in str(r.get("description", "")).lower():
        payload.pop("parse_mode")
        r = call("editMessageText", payload, _tok(tenant))
    return bool(r.get("ok")) or "not modified" in str(r.get("description", ""))


def send_photo(tenant, chat_id, png: bytes, caption: str = "") -> bool:
    tok = _tok(tenant)
    if not tok:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat_id, "caption": caption[:900]},
                          files={"photo": ("diagramma.png", png, "image/png")}, timeout=30)
        return bool(r.json().get("ok"))
    except Exception as e:
        log.warning("sendPhoto xato: %s", e)
        return False


def _preview(buf: str) -> str:
    t = agent.clean(buf)[:PREVIEW_MAX]
    t = re.sub(r"&lt;/?[bi]&gt;", "", t)            # hali yopilmagan teglar ko'rinmasin
    return (t + " ▍") if t else "✍️ <i>Yozyapman…</i>"


class _Stopper:
    """«⏹ To'xtatish» bosilganini tekshiradi (bazaga har 0.7 soniyada bir marta)."""

    def __init__(self, chat_id, run):
        self.chat_id, self.run, self.at, self.stopped = chat_id, run, 0.0, False

    def __call__(self) -> bool:
        if self.stopped:
            return True
        now = time.monotonic()
        if now - self.at >= 0.7:
            self.at = now
            self.stopped = not AiChat.objects.filter(chat_id=self.chat_id, run=self.run, state=ChatState.BUSY).exists()
        return self.stopped


def _finish(chat_id, run) -> None:
    """Ish tugadi — holat bo'shaydi (agar orada «To'xtatish» bosilmagan bo'lsa)."""
    AiChat.objects.filter(chat_id=chat_id, run=run).update(state=ChatState.IDLE, pending="", run="", confirm_msg_id=None, updated_at=timezone.now())


# ------------------------------------------------------------------ fon ishlari
def _do_run(tenant, user_id: int, chat_id: int, run: str, text: str = "", file_id: str = "", mime: str = "") -> None:
    user = User.objects.get(pk=user_id)
    mode = (AiChat.objects.filter(chat_id=chat_id).values_list("mode", flat=True).first() or "local")
    stop = _Stopper(chat_id, run)
    try:
        if file_id:
            lg = AiLog(user=user, channel="telegram", kind="voice", question="(ovozli xabar)")
            mid = send(tenant, chat_id, "🎧 <i>Eshityapman…</i>", STOP_KB)
            typing(tenant, chat_id, "typing")
            try:
                audio = download(tenant, file_id)
                tr = gemini.transcribe(tenant, audio, mime or "audio/ogg")
            except gemini.AiError as e:
                lg.ok, lg.error = False, str(e)[:240]
                lg.save()
                edit(tenant, chat_id, mid, f"⚠️ {report.esc(e)}\n\nBuyruqni matn bilan yozib yuborishingiz ham mumkin.")
                return
            text = (tr["text"] or "").strip()
            lg.answer, lg.model, lg.calls, lg.tokens, lg.ms = text[:4000], tr["model"], 1, tr["tokens"], tr["ms"]
            lg.save()
            if stop():
                edit(tenant, chat_id, mid, "⏹ To'xtatildi.")
                return
            if not text or "[tushunarsiz]" in text.lower():
                edit(tenant, chat_id, mid, "😕 Ovozni tushunib bo'lmadi. Tinchroq joyda, aniqroq gapirib qayta yuboring (yoki yozib yuboring).")
                return
            edit(tenant, chat_id, mid, f"🗣 <i>«{report.esc(text)}»</i>")
            AiChat.objects.filter(chat_id=chat_id, run=run).update(pending=text[:1500])
        draft = send(tenant, chat_id, "🌐 <i>Internetdan qidiryapman…</i>" if mode == "web" else "✍️ <i>Yozyapman…</i>", STOP_KB)
        state = {"buf": "", "at": time.monotonic(), "shown": ""}

        def on_text(delta):
            if delta is None:                        # model asbob chaqirdi — qoralama qaytadan
                state["buf"] = ""
                return
            state["buf"] += delta
            now = time.monotonic()
            if now - state["at"] >= EDIT_EVERY and len(state["buf"]) <= PREVIEW_MAX and not stop():
                pv = _preview(state["buf"])
                if pv != state["shown"]:
                    edit(tenant, chat_id, draft, pv, STOP_KB)
                    state["shown"] = pv
                state["at"] = now

        typing(tenant, chat_id)
        res = agent.ask(tenant, user, text, channel="telegram", on_text=on_text, stop=stop, mode=mode)
        if res.get("stopped") or stop():
            edit(tenant, chat_id, draft, (_preview(state["buf"]).rstrip(" ▍") + "\n\n" if state["buf"] else "") + "⏹ <i>To'xtatildi.</i>")
            return
        if not res["ok"]:
            edit(tenant, chat_id, draft, f"⚠️ {report.esc(res['error'])}")
            return
        parts = report.split(res["answer"].replace(' target="_blank" rel="noopener"', ""))
        if not edit(tenant, chat_id, draft, parts[0]):
            send(tenant, chat_id, parts[0])
        for p in parts[1:]:
            send(tenant, chat_id, p)
        for ch in res.get("charts") or []:
            send_photo(tenant, chat_id, ch["png"], "📈 " + ch["title"] if ch["title"] else "")
    finally:
        _finish(chat_id, run)


def _do_report(tenant, user_id: int, chat_id: int, run: str = "") -> None:
    user = User.objects.get(pk=user_id)
    try:
        typing(tenant, chat_id)
        parts, _ = agent.morning(tenant, user, channel="telegram")
        for p in parts:
            send(tenant, chat_id, p)
    finally:
        _finish(chat_id, run)


def _start(tenant, user, chat_id, *, text: str = "", voice: dict | None = None) -> bool:
    """Yangi ishni boshlash (holat → BUSY, yangi run kaliti)."""
    run = uuid.uuid4().hex
    if not _set(chat_id, ChatState.BUSY, expect=(ChatState.IDLE, ChatState.WAIT, ChatState.CONFIRM), run=run, pending=text[:1500], confirm_msg_id=None):
        return False
    if voice:
        _spawn(tenant, _do_run, user.pk, chat_id, run, "", voice.get("file_id") or "", voice.get("mime_type") or "audio/ogg")
    else:
        _spawn(tenant, _do_run, user.pk, chat_id, run, text[:1500])
    return True


# ------------------------------------------------------------------ kirish nuqtasi
def maybe_handle(tenant, upd: dict, base_url: str | None = None) -> bool:
    """AI Kotibga tegishli xabar bo'lsa — shu yerda ko'rib chiqiladi (True). Aks holda boshqa ishlovchilarga (False)."""
    if not tenant.module_enabled("ai"):
        return False
    cq = upd.get("callback_query")
    if cq:
        data = cq.get("data") or ""
        if not data.startswith("ai:"):
            return False
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        call("answerCallbackQuery", {"callback_query_id": cq.get("id")}, _tok(tenant))
        user = staff_user(tenant, chat_id) if chat_id else None
        if user:
            _on_callback(tenant, user, chat_id, data[3:], msg.get("message_id"))
        return True

    msg = upd.get("message") or {}
    chat = msg.get("chat") or {}
    if not msg or chat.get("type") not in (None, "private"):
        return False
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    cmd = text.split("@")[0]
    voice = msg.get("voice") or msg.get("audio")
    c = AiChat.objects.filter(chat_id=chat_id).first()
    if c and _stale(c):
        _set(chat_id, ChatState.IDLE)
        c.refresh_from_db()
    active = c is not None and c.state != ChatState.IDLE
    trig = cmd in TRIG_AI or cmd in TRIG_REPORT or cmd in TRIG_WEB
    direct = False
    if not trig and not active:
        # rahbar/menejer tugma bosmasdan ovozli xabar (yoki oddiy gap) yuborsa ham — AI Kotibga (darhol)
        if not (voice or (text and not text.startswith("/"))) or text in _known_buttons():
            return False
        if staff_user(tenant, chat_id) is None:
            return False
        direct = True
    user = staff_user(tenant, chat_id)
    if not user:
        if trig:
            linked = User.objects.filter(telegram_id=chat_id, is_active=True).first()
            send(tenant, chat_id, ("🤖 AI Kotib sizga hali berilmagan.\nRahbaringiz (Superadmin) panelda «AI Kotib → Kimlar foydalanadi» bo'limida bir bosishda yoqib beradi."
                                   if linked else "🤖 Avval telefon raqamingizni ulashing — /start bosing va «📱 Telefonni ulashish» tugmasini bosing."))
            return True
        return False
    if c is None:
        c = AiChat.objects.create(chat_id=chat_id, user=user, base_url=base_url or "")
    elif c.user_id != user.pk or (base_url and c.base_url != base_url):
        AiChat.objects.filter(pk=c.pk).update(user=user, base_url=base_url or c.base_url)

    # 1) javob yozilayotganda — yangi buyruq yo'q (⏹ bilan to'xtatish mumkin)
    if c.state == ChatState.BUSY:
        send(tenant, chat_id, "⏳ Javob tayyorlanyapti. Kuting yoki «⏹ To'xtatish»ni bosing — keyin yangi buyruq berasiz.", STOP_KB)
        return True

    # 2) bekor qilish
    if cmd in CANCEL:
        _set(chat_id, ChatState.IDLE, pending="", confirm_msg_id=None, run="")
        send(tenant, chat_id, "Bekor qilindi.")
        return True

    # 3) kunlik hisobot
    if cmd in TRIG_REPORT:
        run = uuid.uuid4().hex
        if not _set(chat_id, ChatState.BUSY, pending="", confirm_msg_id=None, run=run):
            return True
        send(tenant, chat_id, "⏳ Hisobot tayyorlanyapti…")
        _spawn(tenant, _do_report, user.pk, chat_id, run)
        return True

    # 4) AI Kotib / Global qidiruv tugmasi — rejim tanlanadi, ovozli xabar kutamiz
    if cmd in TRIG_AI or cmd in TRIG_WEB:
        mode = "web" if cmd in TRIG_WEB else "local"
        _set(chat_id, ChatState.WAIT, pending="", confirm_msg_id=None, run="", mode=mode)
        left = agent.limit_left(tenant)
        extra = "" if gemini.api_key(tenant) else "\n\n⚠️ AI kaliti hali kiritilmagan — panelda «AI Kotib» sahifasida kalitni qo'ying."
        send(tenant, chat_id, (PROMPT_WEB if mode == "web" else PROMPT) + (f"\n\n<i>Bugun yana {left} ta so'rov mumkin.</i>" if left < 10 else "") + extra,
             mode_kb(mode))
        return True

    # 5) ovozli xabar yoki matn — darhol bajariladi (tasdiqsiz)
    if direct or c.state in (ChatState.WAIT, ChatState.CONFIRM):
        # boshqa bot tugmasi bosildi — AI suhbatini yopib, oddiy menyuga o'tkazamiz
        if text in _known_buttons() or (text.startswith("/") and not voice):
            _set(chat_id, ChatState.IDLE, pending="", confirm_msg_id=None, run="")
            return False
        if voice:
            dur = int(voice.get("duration") or 0)
            if dur > MAX_VOICE_SEC:
                send(tenant, chat_id, f"Xabar juda uzun ({dur} s). Iltimos, {MAX_VOICE_SEC // 60} daqiqagacha qilib qayta yuboring.", WAIT_KB)
                return True
            _start(tenant, user, chat_id, voice=voice)
            return True
        if text:
            _start(tenant, user, chat_id, text=text)
            return True
        send(tenant, chat_id, "Ovozli xabar yoki matn yuboring 🎙", WAIT_KB)
        return True
    return False


def _on_callback(tenant, user, chat_id, action: str, message_id) -> None:
    c = AiChat.objects.filter(chat_id=chat_id).first()
    if c is None:
        return
    if action.startswith("mode:"):
        mode = "web" if action.endswith("web") else "local"
        AiChat.objects.filter(chat_id=chat_id).update(mode=mode)
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": mode_kb(mode)}, _tok(tenant))
        send(tenant, chat_id, "🌐 Global qidiruv yoqildi — restoran ma'lumoti + internet. Savolingizni yuboring." if mode == "web"
             else "🏠 Restoran rejimi — faqat restoran ma'lumotlari. Savolingizni yuboring.")
        return
    if action == "stop":
        if c.state != ChatState.BUSY:
            _drop_buttons(tenant, chat_id, message_id)
            return
        q = c.pending
        _set(chat_id, ChatState.WAIT, run="")            # ishlayotgan ip buni ko'rib to'xtaydi
        _drop_buttons(tenant, chat_id, message_id)
        if q:
            send(tenant, chat_id, "⏹ <b>To'xtatildi.</b> Savolingiz saqlandi:\n\n"
                                  f"<code>{report.esc(q)}</code>\n\n"
                                  "Ustiga bosing — nusxalanadi, o'zgartirib yuboring. Yoki yangi buyruq bering (ovoz yoki matn).", SAVED_KB)
        else:
            send(tenant, chat_id, "⏹ <b>To'xtatildi.</b> Yangi buyruq bering — ovoz yoki matn.", WAIT_KB)
        return
    if c.state == ChatState.BUSY and not _stale(c):
        send(tenant, chat_id, "⏳ Javob tayyorlanyapti — kuting yoki «⏹ To'xtatish»ni bosing.", STOP_KB)
        return
    _drop_buttons(tenant, chat_id, message_id)
    if action == "no":
        _set(chat_id, ChatState.IDLE, pending="", confirm_msg_id=None, run="")
        send(tenant, chat_id, "Bekor qilindi.")
        return
    if action == "redo":
        _set(chat_id, ChatState.WAIT, pending="", confirm_msg_id=None, run="")
        send(tenant, chat_id, "🎙 Mayli, qaytadan aytib yuboring.", WAIT_KB)
        return
    if action in ("again", "yes"):
        if not c.pending:
            send(tenant, chat_id, "Saqlangan savol yo'q. Yangi buyruq bering — ovoz yoki matn.", WAIT_KB)
            return
        _start(tenant, user, chat_id, text=c.pending)
