"""
Kassa topshirish: smena yopilganda qabul qiluvchiga Telegram'da xabar + «✅ Qabul qildim» tugmasi,
farq bo'lsa — rahbarlarga ogohlantirish. Z-hisobot matni (bot va chop etish uchun).
"""
from __future__ import annotations

import logging

from django.utils import timezone

from core.models import User

from .models import CashShift, PayMethod

log = logging.getLogger("pos")
DENOMS = [200000, 100000, 50000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100]


def m(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ") + " so'm"


def counted_sum(counted: dict) -> int:
    total = 0
    for k, v in (counted or {}).items():
        try:
            total += int(k) * max(0, int(v or 0))
        except (TypeError, ValueError):
            continue
    return total


def z_text(s: CashShift, tenant_name: str = "") -> str:
    t = s.totals()
    labels = dict(PayMethod.choices)
    lines = [f"🧾 <b>Kassa topshirildi</b>{' — ' + tenant_name if tenant_name else ''}",
             f"🏪 {s.branch.name if s.branch_id else 'Kassa'} · smena #{s.pk}",
             f"🕘 {timezone.localtime(s.opened_at):%d.%m %H:%M} → {timezone.localtime(s.closed_at):%H:%M}" if s.closed_at else "",
             f"👤 Kassir: {(s.closed_by or s.opened_by).full_name if (s.closed_by_id or s.opened_by_id) else '—'}",
             "",
             f"💰 Savdo: <b>{m(t['total'])}</b> · {t['orders']} chek (o'rtacha {m(t['avg_check'])})"]
    for k, v in t["by_method"].items():
        if v:
            lines.append(f"   • {labels.get(k, k)}: {m(v)}")
    if t["cash_in"] or t["cash_out"]:
        lines.append(f"↕️ Kirim: {m(t['cash_in'])} · Chiqim: {m(t['cash_out'])}")
    if t["cancelled"]:
        lines.append(f"✖️ Bekor qilingan: {t['cancelled']} ta" + (f" (qaytarilgan {m(t['refunded'])})" if t["refunded"] else ""))
    lines += ["", f"💵 Kutilgan naqd: {m(t['expected_cash'])}", f"💵 Sanalgan naqd: <b>{m(s.cash_end)}</b>"]
    d = t["cash_diff"] or 0
    lines.append("✅ Farq yo'q" if d == 0 else (f"⚠️ Kamomad: <b>{m(-d)}</b>" if d < 0 else f"⚠️ Ortiqcha: <b>{m(d)}</b>"))
    if t["card_diff"]:
        lines.append(f"💳 Terminal farqi: {m(t['card_diff'])}")
    if s.diff_reason:
        lines.append(f"📝 Sabab: {s.diff_reason}")
    if s.left_amount is not None:
        lines.append(f"🗄 Kassada qoldi: {m(s.left_amount)}")
    if s.handed_amount is not None:
        lines.append(f"🤝 Topshirildi: <b>{m(s.handed_amount)}</b>" + (f" → {s.handed_to.full_name or s.handed_to.phone}" if s.handed_to_id else ""))
    return "\n".join(x for x in lines if x is not None)


def notify(tenant, s: CashShift) -> None:
    """Qabul qiluvchiga — tasdiq tugmasi bilan; farq bo'lsa — kassa rahbarlariga ham."""
    try:
        from integrations.telegram import call
        from modules.telegram.services import token
        tok = token(tenant)
        if not tok:
            return
        text = z_text(s, tenant.name)
        sent = set()
        if s.handed_to_id and s.handed_to.telegram_id:
            call("sendMessage", {"chat_id": s.handed_to.telegram_id, "text": text + "\n\nPulni sanab oldingizmi?", "parse_mode": "HTML",
                                 "reply_markup": {"inline_keyboard": [[{"text": "✅ Qabul qildim", "callback_data": f"shift:ok:{s.pk}"}]]}}, tok)
            sent.add(s.handed_to.telegram_id)
        if (s.totals()["cash_diff"] or 0) != 0:
            for u in User.objects.filter(is_active=True, telegram_id__isnull=False).exclude(telegram_id__in=sent):
                if u.has_perm_code("pos.view_all") and u.pk != (s.closed_by_id or 0):
                    call("sendMessage", {"chat_id": u.telegram_id, "text": "⚠️ <b>Kassada farq!</b>\n\n" + text, "parse_mode": "HTML"}, tok)
    except Exception:
        log.exception("kassa topshirish xabari")


def accept(s: CashShift, user) -> bool:
    if s.accepted_at or not s.closed_at or (s.handed_to_id and s.handed_to_id != user.pk):
        return False
    s.accepted_at, s.accepted_by = timezone.now(), user
    s.save(update_fields=["accepted_at", "accepted_by"])
    return True


def handle_callback(tenant, cq: dict) -> bool:
    data = str(cq.get("data") or "")
    if not data.startswith("shift:"):
        return False
    from integrations.telegram import call
    from modules.telegram.services import token
    tok = token(tenant)
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
    user = User.objects.filter(telegram_id=chat_id, is_active=True).first()
    s = CashShift.objects.filter(pk=(data.split(":")[-1] or "0")).first() if data.split(":")[-1].isdigit() else None
    ok = bool(user and s and accept(s, user))
    call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "✅ Qabul qilindi" if ok else "Bu topshiriq sizga emas yoki allaqachon qabul qilingan"}, tok)
    if ok and cq.get("message", {}).get("message_id"):
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": cq["message"]["message_id"],
                                        "reply_markup": {"inline_keyboard": [[{"text": f"✅ Qabul qilindi · {timezone.localtime():%H:%M}", "callback_data": "shift:done"}]]}}, tok)
    return True
