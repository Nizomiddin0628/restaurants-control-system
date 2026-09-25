"""
Hodisalar → mijozga Telegram xabari (modul o'chirilgan bo'lsa ishlamaydi).

pos.order_paid       → "Rahmat!" + chek xulosasi, mijoz statistikasi (buyurtmalar soni, summa)
kds.ticket_ready     → buyurtmaning barcha cheklari tayyor bo'lsa: "Buyurtmangiz tayyor!"
reservations.created → mehmonga bron tasdig'i
"""
from __future__ import annotations

import logging

from django.db.models import F

from core.events import on

log = logging.getLogger("tgbot")


def _bot_user(phone: str):
    from core.models import User

    from .models import BotUser
    if not phone:
        return None
    return BotUser.objects.filter(phone=User.objects.normalize_phone(phone), is_blocked=False).first()


@on("pos.order_paid")
def thank_customer(payload: dict) -> None:
    from . import services
    from .models import BotUser
    tenant = payload.get("_tenant")
    bu = _bot_user(payload.get("customer_phone") or "")
    if bu is None:
        return
    BotUser.objects.filter(pk=bu.pk).update(orders_count=F("orders_count") + 1, spent_total=F("spent_total") + int(payload.get("total") or 0))
    if tenant is None or not services.conf(tenant).get("notify_paid"):
        return
    items = "\n".join(f"• {i['name']} × {i['qty']}" for i in (payload.get("items") or [])[:12])
    services.say(tenant, bu.chat_id, f"🧾 <b>Buyurtma #{payload.get('number')}</b> to'landi — rahmat!\n{items}\n"
                                     f"<b>Jami: {services.money(payload.get('total') or 0)} so'm</b>")


@on("kds.ticket_ready")
def order_ready(payload: dict) -> None:
    from django.db import connection

    from modules.kds.models import Ticket

    from . import services
    tenant = getattr(connection, "tenant", None)
    t = Ticket.objects.select_related("order").filter(pk=payload.get("ticket_id")).first()
    if t is None or tenant is None or not services.conf(tenant).get("notify_ready"):
        return
    order = t.order
    if order.kds_tickets.exclude(status__in=["ready", "served", "cancelled"]).exists():
        return                                  # boshqa stansiyada hali tayyorlanmoqda
    bu = _bot_user(order.customer_phone)
    if bu:
        how = {"delivery": "Kuryer yo'lga chiqmoqda 🚗", "takeaway": "Olib ketishingiz mumkin 🛍", "dine_in": "Stolingizga olib boramiz 🍽"}
        services.say(tenant, bu.chat_id, f"✅ <b>Buyurtma #{order.number} tayyor!</b>\n{how.get(order.type, '')}")


@on("reservations.created")
def booking_confirmed(payload: dict) -> None:
    from modules.reservations.models import Reservation

    from . import services
    tenant = payload.get("_tenant")
    res = Reservation.objects.select_related("table").filter(pk=payload.get("reservation_id")).first()
    if res is None or tenant is None or res.source == "telegram":
        return                                  # botdan kelgan bronga tasdiq allaqachon yuborilgan
    bu = _bot_user(res.phone)
    if bu:
        from django.utils import timezone
        at = timezone.localtime(res.starts_at)
        services.say(tenant, bu.chat_id, f"📅 <b>{tenant.name}</b>: bron tasdiqlandi\n{at:%d.%m.%Y} · {at:%H:%M} · {res.guests} kishi"
                                         + (f" · stol {res.table.number}" if res.table else ""))
