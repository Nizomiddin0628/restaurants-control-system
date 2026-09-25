"""
Telegram webhook — /api/v1/telegram/webhook (restoran domenida).

1) Sir tekshiruvi (restoran boti sozlamasidagi webhook_secret yoki .env TELEGRAM_WEBHOOK_SECRET).
2) "Telegram bot" moduli yoqilgan bo'lsa — mijoz suhbati modules.telegram.services.handle_update() da.
3) Qolgani — xodimlar uchun: telefon orqali bog'lash, /vazifalar, /keldim, /ketdim.
"""
from __future__ import annotations

import json
import logging
import os

from django.http import JsonResponse
from ninja import Router

from core.auth import auth, require_perm
from core.models import User

from . import CONTACT_KEYBOARD, send_message, set_webhook

router = Router(tags=["telegram"])
log = logging.getLogger("telegram")


def _tenant_cfg(tenant) -> dict:
    return (((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("telegram") or {})


@router.post("/set-webhook", auth=auth)
def set_webhook_view(request):
    require_perm(request, "core.settings.edit")
    base = request.build_absolute_uri("/").rstrip("/")
    secret = _tenant_cfg(request.tenant).get("webhook_secret") or os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos")
    return set_webhook(base, secret)


@router.post("/webhook", auth=None)
def webhook(request):
    tenant = request.tenant
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    allowed = {s for s in (_tenant_cfg(tenant).get("webhook_secret"), os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos")) if s}
    if given not in allowed:
        return JsonResponse({"ok": False}, status=403)
    upd = json.loads(request.body or b"{}")

    if tenant.module_enabled("telegram"):
        try:
            from modules.telegram.services import handle_update
            if handle_update(tenant, upd, request.build_absolute_uri("/").rstrip("/")):
                return JsonResponse({"ok": True})
        except Exception:  # bot xatosi Telegram'ga 500 qaytarmasin (aks holda qayta-qayta yuboradi)
            log.exception("telegram bot handle_update xato")
            return JsonResponse({"ok": True})

    msg = upd.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id:
        return JsonResponse({"ok": True})
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")

    if contact and contact.get("phone_number"):
        phone = User.objects.normalize_phone(contact["phone_number"])
        user = User.objects.filter(phone=phone).first()
        if user:
            user.telegram_id = chat_id
            user.save(update_fields=["telegram_id"])
            send_message(chat_id, f"✅ <b>{user.full_name or phone}</b>, siz <b>{tenant.name}</b> tizimiga ulandingiz.\n"
                                  "Endi vazifalar, muddatlar va tasdiqlar shu yerga keladi.\n/vazifalar — ochiq vazifalarim")
        else:
            send_message(chat_id, "Bu raqam xodimlar ro'yxatida yo'q. Menejerga murojaat qiling.")
        return JsonResponse({"ok": True})

    user = User.objects.filter(telegram_id=chat_id).first()
    if text.startswith("/start") or not user:
        send_message(chat_id, f"Salom! Bu <b>{tenant.name}</b> xodimlari uchun bot.\nTelefon raqamingizni ulashing:",
                     reply_markup=CONTACT_KEYBOARD)
        return JsonResponse({"ok": True})

    if text.startswith("/vazifalar"):
        try:
            from modules.tasks.models import Task
            rows = Task.objects.live().filter(assignee=user, is_archived=False).open().select_related("column")[:10]
            if not rows:
                send_message(chat_id, "Ochiq vazifangiz yo'q 👍")
            else:
                lines = [f"#{t.number} {'⚠️ ' if t.is_overdue else ''}{t.title} — {t.column.name.get('uz')}"
                         + (f" (muddat {t.due_at:%d.%m %H:%M})" if t.due_at else "") for t in rows]
                send_message(chat_id, "<b>Ochiq vazifalarim</b>\n" + "\n".join(lines))
        except Exception:
            send_message(chat_id, "Vazifalar moduli yoqilmagan.")
        return JsonResponse({"ok": True})

    if text.startswith("/keldim") or text.startswith("/ketdim"):
        try:
            from django.utils import timezone

            from modules.hr.models import Attendance, Employee
            e = Employee.objects.get(user=user)
            if text.startswith("/keldim"):
                if e.attendance.filter(check_out__isnull=True).exists():
                    send_message(chat_id, "Siz allaqachon smenadasiz.")
                else:
                    Attendance.objects.create(employee=e, branch=e.branch, source="telegram")
                    send_message(chat_id, f"✅ Keldingiz: {timezone.localtime():%H:%M}")
            else:
                a = e.attendance.filter(check_out__isnull=True).first()
                if a:
                    a.check_out = timezone.now(); a.save()
                    send_message(chat_id, f"👋 Ketdingiz: {timezone.localtime():%H:%M} · {a.hours} soat")
                else:
                    send_message(chat_id, "Ochiq smena yo'q.")
        except Exception:
            send_message(chat_id, "Davomat moduli yoqilmagan yoki siz xodim sifatida ro'yxatda yo'qsiz.")
        return JsonResponse({"ok": True})

    send_message(chat_id, "Buyruqlar: /vazifalar · /keldim · /ketdim")
    return JsonResponse({"ok": True})
