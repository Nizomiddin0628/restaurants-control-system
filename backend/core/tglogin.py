"""
Telegram orqali kirish (parolsiz, kodsiz):
  1) saytda telefon → POST /auth/tg-login → botga «Kirishni tasdiqlaysizmi?» [✅ Ha] [❌ Yo'q]
  2) xodim «Ha» bosadi (callback login:ok:<id>) → so'rov tasdiqlanadi
  3) sayt har 2 soniyada GET /auth/tg-login/<id> so'raydi → tasdiqlangan bo'lsa token oladi va kiradi.
Xodim avval botga /start bosib telefonini ulashgan bo'lishi kerak (telegram_id).
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta

from django.utils import timezone

from integrations.telegram import call

from .models import LoginRequest, User
from .security import device

log = logging.getLogger("telegram")
PREFIX = "login:"


def _token(tenant) -> str | None:
    from modules.telegram.services import token
    return token(tenant)


def _prompt(tenant, req: LoginRequest, chat_id) -> bool:
    now = timezone.localtime()
    text = (f"🔐 <b>{tenant.name}</b> — boshqaruv paneliga kirish\n\n"
            f"👤 {req.user.full_name or req.user.phone}\n💻 {req.device}\n🕘 {now:%H:%M}\n\n"
            "Hozir o'zingiz kiryapsizmi? <b>«Ha»</b> ni bosing.\nSiz bo'lmasangiz — <b>«Yo'q»</b>ni bosing va hech kimga kod bermang.")
    kb = {"inline_keyboard": [[{"text": "✅ Ha, men kiryapman", "callback_data": f"{PREFIX}ok:{req.pk}"},
                               {"text": "❌ Yo'q, men emas", "callback_data": f"{PREFIX}no:{req.pk}"}]]}
    r = call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": kb}, _token(tenant))
    return bool(r.get("ok"))


def start(tenant, user: User, ip: str = "", ua: str = "") -> LoginRequest | None:
    """So'rov yaratadi. Telegram ulangan bo'lsa — botga «Ha/Yo'q» yuboriladi; ulanmagan (yoki xabar yetmagan) bo'lsa ham
    so'rov kutib turadi — xodim saytdagi havola orqali botni ochadi (/start login_<id>) va raqamini ulashib tasdiqlaydi.
    Bot umuman sozlanmagan bo'lsa — None."""
    tok = _token(tenant)
    if not tok:
        return None
    recent = LoginRequest.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(minutes=10)).count()
    if recent >= 8:
        raise PermissionError("Juda ko'p urinish — 10 daqiqadan keyin qayta urinib ko'ring yoki parol bilan kiring")
    LoginRequest.objects.filter(user=user, status=LoginRequest.PENDING).update(status=LoginRequest.NO)
    req = LoginRequest.objects.create(user=user, secret=secrets.token_urlsafe(24), ip=(ip or "")[:64], device=device(ua)[:160])
    if user.telegram_id:
        _prompt(tenant, req, user.telegram_id)      # yetmasa ham — havola orqali davom etadi
    return req


def _pending(code: str) -> LoginRequest | None:
    try:
        req = LoginRequest.objects.select_related("user").filter(pk=uuid.UUID(hex=code[:32]), status=LoginRequest.PENDING).first()
    except (ValueError, TypeError):
        return None
    return req if req and not req.expired else None


def on_start(tenant, chat_id, code: str) -> None:
    """Botda /start login_<id> (saytdagi «Telegram'ni ochish» havolasi)."""
    req = _pending(code)
    if req is None:
        call("sendMessage", {"chat_id": chat_id, "text": "⌛ Kirish so'rovi eskirgan. Saytda qaytadan «Telegram orqali kirish»ni bosing."}, _token(tenant))
        return
    if req.user.telegram_id == chat_id:
        _prompt(tenant, req, chat_id)
        return
    from django.core.cache import cache
    try:
        cache.set(f"tgl:{chat_id}", str(req.pk), 600)
    except Exception:
        log.exception("tg-login cache")
    from integrations.telegram import CONTACT_KEYBOARD
    call("sendMessage", {"chat_id": chat_id, "parse_mode": "HTML", "reply_markup": CONTACT_KEYBOARD,
                         "text": f"🔐 <b>{tenant.name}</b> — saytga kirish\n\nRaqamingizni tasdiqlang: pastdagi <b>«📱 Telefonni ulashish»</b> tugmasini bosing.\n"
                                 "Raqam saytda yozganingizga mos kelsa — sayt o'zi ochiladi."}, _token(tenant))


def after_contact(tenant, chat_id, user: User | None) -> bool:
    """Xodim botda raqamini ulashdi — agar saytdan kirish kutilayotgan bo'lsa, raqam mos kelsa tasdiqlaymiz."""
    from django.core.cache import cache
    try:
        rid = cache.get(f"tgl:{chat_id}")
    except Exception:
        rid = None
    if not rid:
        return False
    try:
        cache.delete(f"tgl:{chat_id}")
    except Exception:
        pass
    req = _pending(uuid.UUID(rid).hex)
    if req is None:
        return False
    if user is None or req.user_id != user.pk:
        call("sendMessage", {"chat_id": chat_id, "text": "❌ Bu raqam saytda yozilgan raqamga mos emas. Saytda o'z raqamingizni yozing."}, _token(tenant))
        return True
    req.status, req.decided_at = LoginRequest.OK, timezone.now()
    req.save(update_fields=["status", "decided_at"])
    call("sendMessage", {"chat_id": chat_id, "text": "✅ Raqam tasdiqlandi — saytga kirildi. Brauzerga qayting 👌"}, _token(tenant))
    return True


def handle_callback(tenant, cq: dict) -> bool:
    data = str(cq.get("data") or "")
    if not data.startswith(PREFIX):
        return False
    tok = _token(tenant)
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id") or (cq.get("from") or {}).get("id")
    msg_id = (cq.get("message") or {}).get("message_id")
    try:
        _, action, rid = data.split(":", 2)
        req = LoginRequest.objects.select_related("user").get(pk=rid)
    except Exception:
        call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "So'rov topilmadi"}, tok)
        return True
    if req.user.telegram_id != chat_id:
        call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Bu so'rov sizga tegishli emas"}, tok)
        return True
    if req.status != LoginRequest.PENDING or req.expired:
        txt = "⌛ Bu so'rov eskirgan. Saytda qaytadan «Telegram orqali kirish»ni bosing."
    elif action == "ok":
        req.status, req.decided_at = LoginRequest.OK, timezone.now()
        req.save(update_fields=["status", "decided_at"])
        txt = f"✅ Kirish tasdiqlandi — {tenant.name} paneli ochilmoqda."
    else:
        req.status, req.decided_at = LoginRequest.NO, timezone.now()
        req.save(update_fields=["status", "decided_at"])
        txt = "❌ Kirish rad etildi. Agar bu siz bo'lmasangiz — rahbaringizga ayting va parolingizni almashtiring."
    call("answerCallbackQuery", {"callback_query_id": cq.get("id")}, tok)
    if msg_id:
        call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": txt}, tok)
    return True


def poll(rid: str, secret: str) -> tuple[str, User | None]:
    """→ (holat, foydalanuvchi): pending | ok | no | expired."""
    try:
        req = LoginRequest.objects.select_related("user").filter(pk=rid).first()
    except Exception:          # noto'g'ri id
        req = None
    if req is None or not secrets.compare_digest(req.secret, secret or ""):
        return "no", None
    if req.status == LoginRequest.OK:
        if (timezone.now() - (req.decided_at or req.created_at)).total_seconds() > 120:
            return "expired", None
        if not LoginRequest.objects.filter(pk=req.pk, status=LoginRequest.OK).update(status=LoginRequest.USED):
            return "expired", None             # bir so'rov bilan faqat bir marta kiriladi
        return "ok", req.user
    if req.status == LoginRequest.PENDING and req.expired:
        return "expired", None
    if req.status == LoginRequest.PENDING:
        return "pending", None
    return ("no" if req.status == LoginRequest.NO else "expired"), None
