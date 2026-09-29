"""
Ro'yxatdan o'tish so'rovlari (xodim o'zi) — rahbar tasdiqlamaguncha tizimga kira olmaydi.

  1) Saytda «Ro'yxatdan o'tish»: ism, telefon, lavozim/izoh, filial → JoinRequest (pending).
  2) Xohlasa — botda raqamini tasdiqlaydi (t.me/<bot>?start=join_<id> → «📱 Telefonni ulashish») → verified,
     tasdiqlanganda Telegram'ga «✅ Tasdiqlandi» keladi.
  3) Rahbarlarga (core.users.manage, Telegram ulangan) xabar: kim, qaysi raqam, qaysi filial + «Panelda ochish» / «❌ Rad etish».
  4) Panel → «Xodimlar va kirish» → «🆕 So'rovlar»: «Tasdiqlash» — lavozim tanlanadi va xodim qo'shiladi; «Rad etish».
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.utils import timezone

from .models import JoinRequest, User

log = logging.getLogger("security")


def _tg(tenant, method: str, payload: dict) -> dict:
    from .security import tg
    return tg(tenant, method, payload)


def users_url(tenant) -> str:
    from .security import admin_url
    u = admin_url(tenant)
    return u[: -len("/login")] + "/users?joins=1" if u.endswith("/login") else ""


def managers(tenant, branch_id: int | None = None) -> list[User]:
    out = []
    for u in User.objects.filter(is_active=True, telegram_id__isnull=False, memberships__is_active=True).distinct():
        if not u.has_perm_code("core.users.manage"):
            continue
        scope = u.branch_scope()
        if scope is not None and branch_id and branch_id not in scope:
            continue
        out.append(u)
    return out


def text_of(j: JoinRequest) -> str:
    return (f"🆕 <b>Ro'yxatdan o'tish so'rovi</b>\n\n👤 {j.full_name}\n📞 {j.phone}" + (" ✅ (Telegram'da tasdiqlangan)" if j.verified else "")
            + (f"\n📍 {j.branch.name}" if j.branch_id else "") + (f"\n📝 {j.note}" if j.note else "")
            + f"\n🕘 {timezone.localtime(j.created_at):%d.%m %H:%M}\n\nTasdiqlash: panel → «Xodimlar va kirish» → «🆕 So'rovlar» (lavozim tanlaysiz).")


def notify_managers(tenant, j: JoinRequest) -> None:
    try:
        rows = []
        url = users_url(tenant)
        if url.startswith("https://"):
            rows.append([{"text": "👥 Panelda ochish", "url": url}])
        rows.append([{"text": "❌ Rad etish", "callback_data": f"join:no:{j.pk}"}])
        for u in managers(tenant, j.branch_id):
            _tg(tenant, "sendMessage", {"chat_id": u.telegram_id, "text": text_of(j), "parse_mode": "HTML", "reply_markup": {"inline_keyboard": rows}})
    except Exception:
        log.exception("join notify")


def notify_applicant(tenant, j: JoinRequest, approved: bool) -> None:
    if not j.telegram_id:
        return
    from .security import admin_url
    if approved:
        text = (f"✅ <b>{tenant.name}</b> — so'rovingiz tasdiqlandi!\n\nSaytga kiring: telefon raqamingiz → «Telegram orqali kirish».\n{admin_url(tenant)}")
    else:
        text = f"❌ <b>{tenant.name}</b> — ro'yxatdan o'tish so'rovingiz rad etildi. Savol bo'lsa, rahbaringizga murojaat qiling."
    _tg(tenant, "sendMessage", {"chat_id": j.telegram_id, "text": text, "parse_mode": "HTML"})


# ------------------------------------------------------------------ botda raqamni tasdiqlash (ixtiyoriy)
def on_start(tenant, chat_id, code: str) -> None:
    j = JoinRequest.objects.filter(pk=int(code) if str(code).isdigit() else 0, status=JoinRequest.PENDING).first()
    if j is None:
        _tg(tenant, "sendMessage", {"chat_id": chat_id, "text": "So'rov topilmadi yoki allaqachon ko'rib chiqilgan."})
        return
    try:
        cache.set(f"tgj:{chat_id}", j.pk, 900)
    except Exception:
        pass
    from integrations.telegram import CONTACT_KEYBOARD
    _tg(tenant, "sendMessage", {"chat_id": chat_id, "parse_mode": "HTML", "reply_markup": CONTACT_KEYBOARD,
                                "text": f"👋 <b>{tenant.name}</b> — ro'yxatdan o'tish\n\nRaqamingizni tasdiqlang: pastdagi <b>«📱 Telefonni ulashish»</b> tugmasini bosing. "
                                        "Rahbar tasdiqlaganda shu yerga xabar keladi."})


def after_contact(tenant, chat_id, phone: str) -> bool:
    try:
        jid = cache.get(f"tgj:{chat_id}")
    except Exception:
        jid = None
    if not jid:
        return False
    try:
        cache.delete(f"tgj:{chat_id}")
    except Exception:
        pass
    j = JoinRequest.objects.filter(pk=jid, status=JoinRequest.PENDING).first()
    if j is None:
        return False
    if User.objects.normalize_phone(phone) != j.phone:
        _tg(tenant, "sendMessage", {"chat_id": chat_id, "text": "❌ Bu raqam so'rovdagi raqamga mos emas. Saytda o'z raqamingiz bilan so'rov yuboring."})
        return True
    j.telegram_id, j.verified = chat_id, True
    j.save(update_fields=["telegram_id", "verified"])
    _tg(tenant, "sendMessage", {"chat_id": chat_id, "text": "✅ Raqamingiz tasdiqlandi. Rahbar so'rovni ko'rib chiqqach, shu yerga xabar keladi."})
    return True


def handle_callback(tenant, cq: dict) -> bool:
    """Rahbar botda «❌ Rad etish» bosdi."""
    data = str(cq.get("data") or "")
    if not data.startswith("join:"):
        return False
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
    u = User.objects.filter(telegram_id=chat_id, is_active=True).first()
    jid = data.split(":")[-1]
    j = JoinRequest.objects.filter(pk=int(jid) if jid.isdigit() else 0).first()
    if not (u and u.has_perm_code("core.users.manage") and j):
        _tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Ruxsat yo'q"})
        return True
    if j.status != JoinRequest.PENDING:
        _tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Allaqachon ko'rib chiqilgan"})
        return True
    reject(tenant, j, u)
    _tg(tenant, "answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Rad etildi"})
    if (cq.get("message") or {}).get("message_id"):
        _tg(tenant, "editMessageReplyMarkup", {"chat_id": chat_id, "message_id": cq["message"]["message_id"],
                                               "reply_markup": {"inline_keyboard": [[{"text": "❌ Rad etildi", "callback_data": "join:done"}]]}})
    return True


def reject(tenant, j: JoinRequest, by: User) -> None:
    j.status, j.decided_at, j.decided_by = JoinRequest.REJECTED, timezone.now(), by
    j.save(update_fields=["status", "decided_at", "decided_by"])
    notify_applicant(tenant, j, approved=False)


def approve(tenant, j: JoinRequest, by: User, user: User) -> None:
    j.status, j.decided_at, j.decided_by, j.user = JoinRequest.APPROVED, timezone.now(), by, user
    j.save(update_fields=["status", "decided_at", "decided_by", "user"])
    if j.verified and j.telegram_id and not user.telegram_id:
        User.objects.filter(telegram_id=j.telegram_id).exclude(pk=user.pk).update(telegram_id=None)
        user.telegram_id = j.telegram_id
        user.save(update_fields=["telegram_id"])
    notify_applicant(tenant, j, approved=True)
