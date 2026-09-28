"""
Kirish xavfsizligi — sayt va Telegram bot uchun bitta joyda:
  • har kirish yoziladi (LoginEvent) — «Kirish tarixi»;
  • parol yoki kod bilan kirilsa — xodimning Telegram'iga ogohlantirish: «🔐 Yangi kirish … Siz emasmisiz? [🚪 Hammasidan chiqarish]»;
  • «Barcha qurilmalardan chiqish» — token_version oshadi, eski tokenlar ishlamaydi;
  • Telegram taklif havolasi: t.me/<bot>?start=inv_<kod> — xodim bir bosishda botga ulanadi (telefon ulashish shart emas), 7 kun amal qiladi;
  • botdagi «👤 Profilim»: saytga kirish havolasi, yangi parol, hamma qurilmalardan chiqish.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.utils import timezone

from .models import LoginEvent, User

log = logging.getLogger("security")
INVITE_DAYS = 7
ALERT_METHODS = ("password", "code", "switch")


def device(ua: str) -> str:
    ua = ua or ""
    os_ = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Mac OS", "Mac"), ("Linux", "Linux")) if k in ua), "")
    br = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("YaBrowser", "Yandex"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"), ("Safari/", "Safari")) if k in ua), "brauzer")
    return f"{br}{' · ' + os_ if os_ else ''}"


def _ip(request) -> str:
    fwd = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return (fwd or request.META.get("REMOTE_ADDR") or "")[:64]


def bot_token(tenant) -> str | None:
    try:
        from modules.telegram.services import token
        return token(tenant)
    except Exception:
        return None


def tg(tenant, method: str, payload: dict) -> dict:
    from integrations.telegram import call
    return call(method, payload, bot_token(tenant))


def admin_url(tenant) -> str:
    try:
        from public.hq import tenant_base
        return f"{tenant_base(tenant)}/admin/login"
    except Exception:
        return ""


def bot_username(tenant) -> str:
    return ((((tenant.settings or {}).get("modules") or {}).get("telegram") or {}).get("bot_username") or "").lstrip("@")


# ------------------------------------------------------------------ kirish qayd etish
def record_login(request, user: User, method: str) -> None:
    dev = device(request.headers.get("User-Agent", ""))
    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_seen_at"])
    try:
        LoginEvent.objects.create(user=user, method=method, ip=_ip(request), device=dev[:160])
    except Exception:
        log.exception("login event")
    if method in ALERT_METHODS and user.telegram_id and bot_token(request.tenant):
        how = dict(LoginEvent.METHODS).get(method, method).lower()
        tg(request.tenant, "sendMessage", {
            "chat_id": user.telegram_id, "parse_mode": "HTML",
            "text": (f"🔐 <b>{request.tenant.name}</b> — yangi kirish\n\n💻 {dev}\n🔑 Usul: {how}\n🕘 {timezone.localtime():%d.%m %H:%M}\n\n"
                     "Siz bo'lsangiz — hech narsa qilmang. Siz bo'lmasangiz — pastdagi tugmani bosing."),
            "reply_markup": {"inline_keyboard": [[{"text": "🚪 Bu men emas — hamma qurilmalardan chiqarish", "callback_data": "sec:out"}]]}})


def history(user: User, limit: int = 8) -> list[dict]:
    labels = dict(LoginEvent.METHODS)
    return [{"at": e.at.isoformat(), "method": e.method, "method_label": labels.get(e.method, e.method), "device": e.device, "ip": e.ip}
            for e in user.login_events.all()[:limit]]


def logout_all(user: User) -> None:
    user.token_version = int(user.token_version or 0) + 1
    user.save(update_fields=["token_version"])


# ------------------------------------------------------------------ Telegram taklif havolasi
def invite(tenant, user: User) -> dict:
    """Yangi (yoki amaldagi) taklif havolasi. Bot nomi noma'lum bo'lsa — link bo'sh (panelda ogohlantiriladi)."""
    fresh = user.tg_invite and user.tg_invite_at and timezone.now() - user.tg_invite_at < timedelta(days=INVITE_DAYS - 1)
    if not fresh:
        user.tg_invite = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")[:16]
        user.tg_invite_at = timezone.now()
        user.save(update_fields=["tg_invite", "tg_invite_at"])
    bot = bot_username(tenant)
    return {"link": f"https://t.me/{bot}?start=inv_{user.tg_invite}" if bot else "", "bot": bot,
            "expires": (user.tg_invite_at + timedelta(days=INVITE_DAYS)).isoformat()}


def accept_invite(tenant, chat_id: int, code: str) -> User | None:
    code = (code or "").strip()[:24]
    if not code:
        return None
    u = User.objects.filter(tg_invite=code, is_active=True, memberships__is_active=True).distinct().first()
    if u is None or not u.tg_invite_at or timezone.now() - u.tg_invite_at > timedelta(days=INVITE_DAYS):
        return None
    User.objects.filter(telegram_id=chat_id).exclude(pk=u.pk).update(telegram_id=None)    # bitta Telegram — bitta xodim
    u.telegram_id, u.tg_invite, u.tg_invite_at = chat_id, "", None
    u.save(update_fields=["telegram_id", "tg_invite", "tg_invite_at"])
    return u


# ------------------------------------------------------------------ botdagi «👤 Profilim»
def profile_markup(tenant) -> dict:
    rows = []
    url = admin_url(tenant)
    if url.startswith("https://"):
        rows.append([{"text": "🌐 Saytga kirish", "url": url}])
    rows.append([{"text": "🔑 Yangi parol olish", "callback_data": "sec:pw"}])
    rows.append([{"text": "🚪 Hamma qurilmalardan chiqish", "callback_data": "sec:out"}])
    return {"inline_keyboard": rows}


def profile_text(tenant, user: User) -> str:
    last = user.login_events.first()
    lines = ["🔐 <b>Kirish va xavfsizlik</b>",
             f"• Login: <b>{user.phone}</b>",
             "• Saytga kirish: telefon raqam → «Telegram orqali kirish» → shu yerda «✅ Ha»",
             f"• Parol: {'o‘rnatilgan' if (user.password and user.has_usable_password()) else 'yo‘q (kerak bo‘lsa — «🔑 Yangi parol olish»)'}"]
    if last:
        lines.append(f"• Oxirgi kirish: {timezone.localtime(last.at):%d.%m %H:%M} · {last.device}")
    return "\n".join(lines)


def handle_callback(tenant, cq: dict) -> bool:
    data = str(cq.get("data") or "")
    if not data.startswith("sec:"):
        return False
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id") or (cq.get("from") or {}).get("id")
    user = User.objects.filter(telegram_id=chat_id, is_active=True).first() if chat_id else None
    if user is None:
        tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Avval telefon raqamingizni ulashing (/start)"})
        return True
    action = data[4:]
    if action == "out":
        logout_all(user)
        tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Hamma qurilmalardan chiqarildi"})
        tg(tenant, "sendMessage", {"chat_id": chat_id, "parse_mode": "HTML",
                                   "text": "✅ <b>Hamma qurilmalardan chiqarildi.</b>\nSaytga qaytadan «Telegram orqali kirish» bilan kirasiz.\n"
                                           "Kimdir parolingizni bilgan bo'lsa — «👤 Profilim» → «🔑 Yangi parol olish»."})
    elif action == "pw":
        pw = f"{secrets.randbelow(900000) + 100000}{secrets.choice('abcdefghjkmnpqrstuvwxyz')}{secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"
        user.set_password(pw)
        user.token_version = int(user.token_version or 0) + 1        # eski parol bilan ochilgan kirishlar yopiladi
        user.save(update_fields=["password", "token_version"])
        tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id")})
        tg(tenant, "sendMessage", {"chat_id": chat_id, "parse_mode": "HTML",
                                   "text": f"🔑 Yangi parolingiz: <code>{pw}</code>\nLogin: <b>{user.phone}</b>\n\n"
                                           "Parolni hech kimga bermang va bu xabarni o'chirib qo'ying. Boshqa qurilmalardagi eski kirishlar yopildi."})
    else:
        tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id")})
    return True
