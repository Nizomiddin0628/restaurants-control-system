"""
Telegram'da «🤖 AI Kotib» — rahbar va menejerlar uchun.

Oqim:
  1) «🤖 AI Kotib» → bot: «Ovozli xabar yuboring (yoki yozing)».
  2) Ovozli xabar → matnga aylantiriladi → «📝 Siz aytdingiz: «…». Bajaraymi?» [✅ Ha] [🔁 Qayta aytaman] [✖️ Bekor].
     (Gap chala qolgan yoki noto'g'ri eshitilgan bo'lsa — «Qayta aytaman».)
  3) «Ha» → tahlil qilinadi → javob.
  «📊 Bugungi hisobot» → kunlik hisobot darhol.
Bitta so'rov qoidasi: holat «busy» bo'lganda (javob kelmaguncha) yangi buyruq qabul qilinmaydi — «kuting» deyiladi.
Uzoq ishlar (ovozni tanish, tahlil) alohida ipda bajariladi — Telegram webhook'i darhol javob oladi.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

import requests
from django.db import transaction
from django.utils import timezone

from core.models import User
from integrations.telegram import call

from . import agent, gemini, report
from .models import AiChat, AiLog, ChatState

log = logging.getLogger("ai")
BTN_AI, BTN_REPORT = "🤖 AI Kotib", "📊 Bugungi hisobot"
TRIG_AI = (BTN_AI, "/ai", "/kotib")
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
    return bool(user and user.is_active and tenant.module_enabled("ai") and user.has_perm_code("ai.use")
                and user.memberships.filter(is_active=True).exists())


def staff_user(tenant, chat_id) -> User | None:
    u = User.objects.filter(telegram_id=chat_id, is_active=True).first()
    return u if eligible(tenant, u) else None


def _known_buttons() -> set[str]:
    try:
        from modules.telegram import services as tgs
        return {tgs.BTN_MENU, tgs.BTN_BOOK, tgs.BTN_ORDERS, tgs.BTN_CONTACT, tgs.BTN_BONUS, tgs.BTN_PHONE, tgs.BTN_CANCEL, "💼 Vakansiyalar", *tgs.STAFF_BUTTONS}
    except Exception:
        return set()


def keyboard_row() -> list[dict]:
    return [{"text": BTN_AI}, {"text": BTN_REPORT}]


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


CONFIRM_KB = {"inline_keyboard": [[{"text": "✅ Ha, bajar", "callback_data": "ai:yes"}],
                                  [{"text": "🔁 Qayta aytaman", "callback_data": "ai:redo"}, {"text": "✖️ Bekor", "callback_data": "ai:no"}]]}
WAIT_KB = {"inline_keyboard": [[{"text": "✖️ Bekor qilish", "callback_data": "ai:no"}]]}
PROMPT = ("🎙 <b>Ovozli xabar yuboring</b> (yoki yozing) — nima kerakligini ayting.\n\n"
          "Masalan:\n• «Kecha qancha savdo bo'ldi, o'tgan haftadan farqi qancha?»\n• «Omborda nima tugayapti?»\n"
          "• «Rustamga ertaga soat 10 gacha muzlatgichni tozalash vazifasini ber»")


def _ask_confirm(tenant, chat_id, text: str) -> None:
    mid = send(tenant, chat_id, f"📝 <b>Siz aytdingiz:</b>\n«{report.esc(text)}»\n\nShu buyruqni bajaraymi?", CONFIRM_KB)
    _set(chat_id, ChatState.CONFIRM, pending=text, confirm_msg_id=mid)


# ------------------------------------------------------------------ fon ishlari
def _do_voice(tenant, user_id: int, chat_id: int, file_id: str, mime: str) -> None:
    user = User.objects.get(pk=user_id)
    lg = AiLog(user=user, channel="telegram", kind="voice", question="(ovozli xabar)")
    try:
        typing(tenant, chat_id)
        audio = download(tenant, file_id)
        tr = gemini.transcribe(tenant, audio, mime or "audio/ogg")
        text = (tr["text"] or "").strip()
        lg.answer, lg.model, lg.calls, lg.tokens, lg.ms = text[:4000], tr["model"], 1, tr["tokens"], tr["ms"]
        lg.save()
        if not text or "[tushunarsiz]" in text.lower():
            _set(chat_id, ChatState.WAIT)
            send(tenant, chat_id, "😕 Ovozni tushunib bo'lmadi. Iltimos, tinchroq joyda, aniqroq gapirib qayta yuboring (yoki yozib yuboring).", WAIT_KB)
            return
        _ask_confirm(tenant, chat_id, text)
    except gemini.AiError as e:
        lg.ok, lg.error = False, str(e)[:240]
        lg.save()
        _set(chat_id, ChatState.WAIT)
        send(tenant, chat_id, f"⚠️ {report.esc(e)}\n\nBuyruqni matn bilan yozib yuborishingiz ham mumkin.", WAIT_KB)
    except Exception:
        log.exception("ovozli xabar")
        lg.ok, lg.error = False, "ichki xato"
        lg.save()
        _set(chat_id, ChatState.WAIT)
        send(tenant, chat_id, "⚠️ Ovozli xabarni o'qib bo'lmadi. Qayta yuboring yoki matn bilan yozing.", WAIT_KB)


def _do_ask(tenant, user_id: int, chat_id: int, text: str) -> None:
    user = User.objects.get(pk=user_id)
    try:
        typing(tenant, chat_id)
        res = agent.ask(tenant, user, text, channel="telegram")
        if res["ok"]:
            send_long(tenant, chat_id, res["answer"])
        else:
            send(tenant, chat_id, f"⚠️ {report.esc(res['error'])}")
    finally:
        _set(chat_id, ChatState.IDLE, pending="")


def _do_report(tenant, user_id: int, chat_id: int) -> None:
    user = User.objects.get(pk=user_id)
    try:
        typing(tenant, chat_id)
        parts, _ = agent.morning(tenant, user, channel="telegram")
        for p in parts:
            send(tenant, chat_id, p)
    finally:
        _set(chat_id, ChatState.IDLE)


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
    trig = cmd in TRIG_AI or cmd in TRIG_REPORT
    direct = False
    if not trig and not active:
        # rahbar/menejer tugma bosmasdan ovozli xabar (yoki oddiy gap) yuborsa ham — AI Kotibga (tasdiq bilan)
        if not (voice or (text and not text.startswith("/"))) or text in _known_buttons():
            return False
        if staff_user(tenant, chat_id) is None:
            return False
        direct = True
    user = staff_user(tenant, chat_id)
    if not user:
        if trig:
            send(tenant, chat_id, "🤖 AI Kotib faqat rahbar va menejerlar uchun.\nTelefon raqamingizni botga ulashganingizni va panelda sizga «AI Kotib» ruxsati berilganini tekshiring.")
            return True
        return False
    if c is None:
        c = AiChat.objects.create(chat_id=chat_id, user=user, base_url=base_url or "")
    elif c.user_id != user.pk or (base_url and c.base_url != base_url):
        AiChat.objects.filter(pk=c.pk).update(user=user, base_url=base_url or c.base_url)

    # 1) javob kelmaguncha — yangi buyruq yo'q
    if c.state == ChatState.BUSY:
        send(tenant, chat_id, "⏳ Oldingi so'rovingiz bajarilmoqda — javob kelishini kuting, keyin yangi buyruq berasiz.")
        return True

    # 2) bekor qilish
    if cmd in CANCEL:
        _drop_buttons(tenant, chat_id, c.confirm_msg_id)
        _set(chat_id, ChatState.IDLE, pending="", confirm_msg_id=None)
        send(tenant, chat_id, "Bekor qilindi.")
        return True

    # 3) kunlik hisobot
    if cmd in TRIG_REPORT:
        _drop_buttons(tenant, chat_id, c.confirm_msg_id)
        if not _set(chat_id, ChatState.BUSY, pending="", confirm_msg_id=None):
            return True
        send(tenant, chat_id, "⏳ Hisobot tayyorlanyapti…")
        _spawn(tenant, _do_report, user.pk, chat_id)
        return True

    # 4) AI Kotib — ovozli xabar kutamiz
    if cmd in TRIG_AI:
        _drop_buttons(tenant, chat_id, c.confirm_msg_id)
        _set(chat_id, ChatState.WAIT, pending="", confirm_msg_id=None)
        left = agent.limit_left(tenant)
        extra = "" if gemini.api_key(tenant) else "\n\n⚠️ AI kaliti hali kiritilmagan — panelda «AI Kotib» sahifasida kalitni qo'ying."
        send(tenant, chat_id, PROMPT + (f"\n\n<i>Bugun yana {left} ta so'rov mumkin.</i>" if left < 10 else "") + extra, WAIT_KB)
        return True

    # 5) ovozli xabar yoki matn (kutish yoki tasdiq holatida; yoki to'g'ridan-to'g'ri yuborilgan)
    if direct:
        _set(chat_id, ChatState.WAIT, pending="", confirm_msg_id=None)
        c.state = ChatState.WAIT
    if c.state in (ChatState.WAIT, ChatState.CONFIRM):
        # boshqa bot tugmasi bosildi — AI suhbatini yopib, oddiy menyuga o'tkazamiz
        if text in _known_buttons() or (text.startswith("/") and not voice):
            _drop_buttons(tenant, chat_id, c.confirm_msg_id)
            _set(chat_id, ChatState.IDLE, pending="", confirm_msg_id=None)
            return False
        if voice:
            dur = int(voice.get("duration") or 0)
            if dur > MAX_VOICE_SEC:
                send(tenant, chat_id, f"Xabar juda uzun ({dur} s). Iltimos, {MAX_VOICE_SEC // 60} daqiqagacha qilib qayta yuboring.", WAIT_KB)
                return True
            _drop_buttons(tenant, chat_id, c.confirm_msg_id)
            if not _set(chat_id, ChatState.BUSY, expect=(ChatState.WAIT, ChatState.CONFIRM), confirm_msg_id=None):
                return True
            send(tenant, chat_id, "🎧 Eshityapman…")
            _spawn(tenant, _do_voice, user.pk, chat_id, voice.get("file_id"), voice.get("mime_type") or "audio/ogg")
            return True
        if text:
            _drop_buttons(tenant, chat_id, c.confirm_msg_id)
            _ask_confirm(tenant, chat_id, text[:1500])
            return True
        send(tenant, chat_id, "Ovozli xabar yoki matn yuboring 🎙", WAIT_KB)
        return True
    return False


def _on_callback(tenant, user, chat_id, action: str, message_id) -> None:
    c = AiChat.objects.filter(chat_id=chat_id).first()
    if c is None:
        return
    if c.state == ChatState.BUSY and not _stale(c):
        send(tenant, chat_id, "⏳ Oldingi so'rovingiz bajarilmoqda — javobni kuting.")
        return
    if action == "no":
        _drop_buttons(tenant, chat_id, message_id)
        _set(chat_id, ChatState.IDLE, pending="", confirm_msg_id=None)
        send(tenant, chat_id, "Bekor qilindi.")
        return
    if action == "redo":
        _drop_buttons(tenant, chat_id, message_id)
        _set(chat_id, ChatState.WAIT, pending="", confirm_msg_id=None)
        send(tenant, chat_id, "🎙 Mayli, qaytadan to'liq aytib yuboring.", WAIT_KB)
        return
    if action == "yes":
        if c.state != ChatState.CONFIRM or (c.confirm_msg_id and message_id and c.confirm_msg_id != message_id) or not c.pending:
            _drop_buttons(tenant, chat_id, message_id)
            send(tenant, chat_id, "Bu buyruq eskirgan. «🤖 AI Kotib» tugmasini bosib, qaytadan yuboring.")
            return
        text = c.pending
        if not _set(chat_id, ChatState.BUSY, expect=(ChatState.CONFIRM,), confirm_msg_id=None):
            return
        _drop_buttons(tenant, chat_id, message_id)
        send(tenant, chat_id, "⏳ Tahlil qilyapman… Javob tayyor bo'lguncha yangi buyruq qabul qilinmaydi.")
        _spawn(tenant, _do_ask, user.pk, chat_id, text)
