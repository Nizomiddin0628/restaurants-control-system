"""
Telegram bot "miyasi": har restoran o'z boti (token sozlamada), mijoz bilan suhbat, Mini App tekshiruvi.

handle_update(tenant, update, base_url) → True bo'lsa xabar shu yerda ko'rib chiqildi.
False — xodimlar buyruqlari (/vazifalar, /keldim, /ketdim) eski ishlovchiga o'tadi.

Mini App xavfsizligi: Telegram yuborgan initData HMAC-SHA256 bilan tekshiriladi
(secret = HMAC_SHA256(key="WebAppData", msg=bot_token)). Soxta buyurtma yuborib bo'lmaydi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from django.conf import settings as dj_settings
from django.utils import timezone

from core.models import User
from integrations.telegram import call, send_message

from .models import Audience, BotUser, Broadcast, BroadcastStatus

log = logging.getLogger("tgbot")

_DEFAULTS = {k: v.get("default") for k, v in json.loads(
    (Path(__file__).parent / "module.json").read_text(encoding="utf-8"))["settings_schema"]["properties"].items()}

STAFF_COMMANDS = ("/vazifalar", "/keldim", "/ketdim")
BTN_MENU, BTN_BOOK, BTN_ORDERS, BTN_CONTACT, BTN_PHONE, BTN_CANCEL = (
    "🍔 Menyu va buyurtma", "📅 Stol bron qilish", "🧾 Buyurtmalarim", "☎️ Aloqa", "📱 Telefonni ulashish", "✖️ Bekor qilish")
BTN_BONUS, BTN_SKIP = "🎁 Bonuslarim", "⏭ O'tkazib yuborish"
# xodimlar (rahbar/menejer) klaviaturasi — mijoz tugmalari ularga kerak emas
BTN_TASKS, BTN_IN, BTN_OUT, BTN_ME = "📋 Vazifalarim", "🕘 Keldim", "🏁 Ketdim", "👤 Profilim"
STAFF_BUTTONS = {BTN_TASKS: "/vazifalar", BTN_IN: "/keldim", BTN_OUT: "/ketdim"}


# ------------------------------------------------------------------ sozlamalar
def conf(tenant) -> dict:
    saved = ((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("telegram") or {}
    return {**_DEFAULTS, **saved}


def token(tenant) -> str | None:
    return (conf(tenant).get("bot_token") or "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN") or None


def say(tenant, chat_id, text: str, markup: dict | None = None) -> bool:
    return send_message(chat_id, text, token=token(tenant), reply_markup=markup)


def miniapp_url(base_url: str | None) -> str | None:
    """Mini App faqat https orqali ochiladi (Telegram talabi)."""
    if base_url and base_url.startswith("https://"):
        return base_url.rstrip("/") + "/tg/"
    return None


def staff_keyboard(tenant, bu: BotUser) -> dict:
    """Xodim klaviaturasi: AI Kotib (rahbar/menejer), vazifalar, keldim/ketdim."""
    rows: list[list] = []
    if _ai_ok(tenant, bu.staff):
        from modules.ai.tg import keyboard_rows
        rows.extend(keyboard_rows())
    if tenant.module_enabled("tasks"):
        rows.append([{"text": BTN_TASKS}])
    if tenant.module_enabled("hr"):
        rows.append([{"text": BTN_IN}, {"text": BTN_OUT}])
    rows.append([{"text": BTN_ME}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def staff_only(tenant) -> bool:
    return bool(conf(tenant).get("staff_only", True))


def main_keyboard(tenant, bu: BotUser, base_url: str | None) -> dict:
    if bu.staff_id:
        return staff_keyboard(tenant, bu)
    if staff_only(tenant):
        return {"keyboard": [[{"text": BTN_PHONE, "request_contact": True}]], "resize_keyboard": True}
    cfg = conf(tenant)
    url = miniapp_url(base_url)
    rows = [[{"text": BTN_MENU, "web_app": {"url": url}} if url else {"text": BTN_MENU}]]
    second = []
    if cfg.get("enable_booking") and tenant.module_enabled("reservations"):
        second.append({"text": BTN_BOOK})
    second.append({"text": BTN_ORDERS})
    rows.append(second)
    extra = []
    if tenant.module_enabled("crm"):
        extra.append({"text": BTN_BONUS})
    if tenant.module_enabled("hr") and not bu.staff_id:
        from .hr_flow import open_jobs
        if open_jobs():
            extra.append({"text": "💼 Vakansiyalar"})
    if extra:
        rows.append(extra)
    rows.append([{"text": BTN_PHONE, "request_contact": True}] if not bu.phone else [{"text": BTN_CONTACT}])
    return {"keyboard": rows, "resize_keyboard": True}


# ------------------------------------------------------------------ yordamchilar
def _staff_help(tenant, user) -> str:
    lines = []
    if _ai_ok(tenant, user):
        lines += ["🤖 <b>AI Kotib</b> — ovozli yoki yozma buyruq bering: «kecha savdo qancha?», «7 kunlik savdoni diagrammada ko'rsat», «Rustamga vazifa ber»…",
                  "🌐 <b>Global qidiruv</b> — restoran ma'lumoti + internet: «go'sht narxi qancha, bizga qanday ta'sir qiladi?», «bayramga qanday aksiya qilsak bo'ladi?»",
                  "📊 <b>Bugungi hisobot</b> — kecha, bugun va nimadan boshlash kerak (har kuni ertalab o'zi ham keladi)"]
    if tenant.module_enabled("tasks"):
        lines.append("📋 <b>Vazifalarim</b> — ochiq vazifalaringiz")
    if tenant.module_enabled("hr"):
        lines.append("🕘 <b>Keldim</b> / 🏁 <b>Ketdim</b> — davomat")
    lines.append("👤 <b>Profilim</b> — saytga kirish havolasi, yangi parol, hamma qurilmalardan chiqish")
    lines.append("💻 <b>Saytga kirish</b>: telefon raqamingiz → «Telegram orqali kirish» → shu yerda «✅ Ha»")
    return "\n".join(lines)


def staff_card(tenant, user, *, first: bool = False) -> str:
    """Xodim tasdiqlanganda / /start bosganda: ismi, lavozimi, roli, filiali, AI Kotib ruxsati va nimalar qila olishi."""
    name = (user.full_name or "").strip()
    first_name = name.split()[0] if name else ""
    ms = list(user.memberships.filter(is_active=True).select_related("role").prefetch_related("branches"))
    roles = ", ".join(m.role.name for m in sorted(ms, key=lambda m: -m.role.level)) or "—"
    position = ""
    try:
        from modules.hr.models import Employee
        e = Employee.objects.filter(user=user).select_related("position", "branch").first()
        if e and e.position_id:
            position = e.position.name
    except Exception:
        pass
    scope = user.branch_scope()
    if scope is None:
        from core.models import Branch
        many = Branch.objects.filter(deleted_at__isnull=True, is_active=True).count() > 1
        branch = "barcha filiallar" if many else (Branch.objects.filter(deleted_at__isnull=True).values_list("name", flat=True).first() or "—")
    else:
        from core.models import Branch
        branch = ", ".join(Branch.objects.filter(pk__in=scope).values_list("name", flat=True)) or "—"
    ai = _ai_ok(tenant, user)
    head = (f"👋 <b>Xush kelibsiz, {first_name or 'hurmatli xodim'}!</b>\n"
            + (f"✅ Raqamingiz tekshirildi — siz <b>{tenant.name}</b> xodimisiz.\n" if first else f"<b>{tenant.name}</b> — xodimlar boti\n"))
    card = [f"👤 <b>{name or user.phone}</b> · {user.phone}"]
    if position:
        card.append(f"💼 Lavozim: <b>{position}</b>")
    card.append(f"🏷 Tizimdagi roli: <b>{roles}</b>")
    card.append(f"📍 Filial: <b>{branch}</b>")
    if tenant.module_enabled("ai"):
        card.append("🤖 AI Kotib: <b>✅ ruxsat berilgan</b>" if ai else "🤖 AI Kotib: ruxsat yo'q <i>(kerak bo'lsa — rahbaringiz yoqib beradi)</i>")
    return head + "\n" + "\n".join(card) + "\n\n<b>Nimalar qila olasiz:</b>\n" + _staff_help(tenant, user)


def _ai_ok(tenant, user) -> bool:
    try:
        from modules.ai.tg import eligible
        return eligible(tenant, user)
    except Exception:
        return False


def normalize(phone: str) -> str:
    return User.objects.normalize_phone(phone) if phone else ""


def touch(msg: dict) -> BotUser:
    frm = msg.get("from") or {}
    chat = msg.get("chat") or {}
    bu, _ = BotUser.objects.get_or_create(chat_id=chat.get("id"))
    name = " ".join(x for x in [frm.get("first_name"), frm.get("last_name")] if x)
    bu.full_name = name or bu.full_name
    bu.username = frm.get("username") or bu.username
    bu.language = (frm.get("language_code") or bu.language or "uz")[:5]
    bu.last_seen_at = timezone.now()
    bu.is_blocked = False
    bu.save()
    return bu


def _orders_for(phone: str, n: int = 5):
    from modules.pos.models import Order
    return list(Order.objects.filter(customer_phone=phone).order_by("-created_at")[:n])


STATUS_UZ = {"open": "qabul qilindi", "paid": "to'langan", "cancelled": "bekor qilingan"}
TYPE_UZ = {"delivery": "yetkazib berish", "takeaway": "olib ketish", "dine_in": "zalda"}


def money(v: int) -> str:
    return f"{int(v):,}".replace(",", " ")


# ------------------------------------------------------------------ asosiy ishlovchi
def handle_update(tenant, update: dict, base_url: str | None = None) -> bool:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        cq = update.get("callback_query")
        if cq:
            from . import hr_flow
            hr_flow.handle_callback(tenant, cq)
        return bool(cq or update.get("my_chat_member"))
    chat = msg.get("chat") or {}
    if chat.get("type") not in (None, "private"):
        return True                         # guruhlarda javob bermaymiz (xodimlar guruhi — faqat bildirishnoma uchun)
    text = (msg.get("text") or "").strip()
    bu = touch(msg)

    # --- ishga ariza suhbati (HR) — kontakt ham shu yerda qabul qilinadi
    if str((bu.state or {}).get("step") or "").startswith("rec_") and text not in (BTN_CANCEL, "/cancel") and not text.startswith("/start"):
        from . import hr_flow
        if hr_flow.step(tenant, bu, msg, text):
            return True
    # --- xodim taklif havolasi: t.me/<bot>?start=inv_<kod> — telefon ulashmasdan, bir bosishda ulanadi
    if text.startswith("/start inv_"):
        from core.security import accept_invite
        staff = accept_invite(tenant, bu.chat_id, text.split("inv_", 1)[1])
        if staff:
            bu.staff, bu.phone, bu.state = staff, staff.phone, {}
            bu.save()
            say(tenant, bu.chat_id, staff_card(tenant, staff, first=True), staff_keyboard(tenant, bu))
        else:
            say(tenant, bu.chat_id, "⌛ Taklif havolasi eskirgan yoki noto'g'ri. Rahbaringizdan yangisini so'rang yoki telefon raqamingizni ulashing 👇",
                main_keyboard(tenant, bu, base_url))
        return True

    # --- «👤 Profilim»: kirish ma'lumotlari, saytga havola, yangi parol, hamma qurilmalardan chiqish
    if bu.staff_id and text in (BTN_ME, "/profil", "/profile"):
        from core.security import profile_markup, profile_text
        say(tenant, bu.chat_id, staff_card(tenant, bu.staff) + "\n\n" + profile_text(tenant, bu.staff), profile_markup(tenant))
        return True

    if text.startswith("/start job_") and tenant.module_enabled("hr"):
        from . import hr_flow
        vid = text.split("job_", 1)[1].split()[0]
        return hr_flow.start_apply(tenant, bu, int(vid)) if vid.isdigit() else hr_flow.show_jobs(tenant, bu)

    # --- telefon ulashildi
    contact = msg.get("contact")
    if contact and contact.get("phone_number"):
        if contact.get("user_id") and contact["user_id"] != chat.get("id"):
            say(tenant, bu.chat_id, "Iltimos, o'zingizning raqamingizni ulashing — tugmani bosing 👇", main_keyboard(tenant, bu, base_url))
            return True
        bu.phone = normalize(contact["phone_number"])
        # rostdan ham shu restoran xodimimi: faol va kamida bitta faol lavozimi bor
        staff = User.objects.filter(phone=bu.phone, is_active=True, memberships__is_active=True).distinct().first()
        if staff:
            User.objects.filter(telegram_id=bu.chat_id).exclude(pk=staff.pk).update(telegram_id=None)   # bitta Telegram — bitta xodim
            staff.telegram_id = bu.chat_id
            staff.save(update_fields=["telegram_id"])
            bu.staff = staff
        bu.save()
        if staff:
            say(tenant, bu.chat_id, staff_card(tenant, staff, first=True), main_keyboard(tenant, bu, base_url))
            from core.tglogin import after_contact
            after_contact(tenant, bu.chat_id, staff)          # saytdan kirish kutilayotgan bo'lsa — tasdiqlanadi
            return True
        from core import join
        from core.tglogin import after_contact
        if join.after_contact(tenant, bu.chat_id, bu.phone) or after_contact(tenant, bu.chat_id, None):
            return True
        if staff_only(tenant):
            say(tenant, bu.chat_id, "Bu raqam xodimlar ro'yxatida topilmadi. Bot hozircha faqat restoran xodimlari uchun — menejerga murojaat qiling.",
                main_keyboard(tenant, bu, base_url))
            return True
        else:
            say(tenant, bu.chat_id, "✅ Rahmat! Raqamingiz saqlandi — endi buyurtmalaringiz va bonuslaringiz shu yerda.",
                main_keyboard(tenant, bu, base_url))
        if tenant.module_enabled("crm"):
            from modules.crm import services as crm
            c, _ = crm.get_or_create(tenant, bu.phone, bu.full_name, source="telegram")
            if c and not c.birthday and not staff:
                bu.state = {"step": "crm_bday"}
                bu.save(update_fields=["state"])
                bonus = int(crm.conf(tenant).get("birthday_bonus") or 0)
                say(tenant, bu.chat_id, "🎂 Tug'ilgan kuningizni yozing (masalan <b>25.09.1995</b>)"
                    + (f" — o'sha kuni <b>{money(bonus)} so'm</b> sovg'a bonus olasiz!" if bonus else ""),
                    {"keyboard": [[BTN_SKIP]], "resize_keyboard": True})
        return True

    # --- xodim buyruqlari (tugmalar ham) — eski ishlovchiga
    if bu.staff_id and (text.split(" ")[0].split("@")[0] in STAFF_COMMANDS or text in STAFF_BUTTONS):
        return False

    # --- xodim: /start va boshqa gaplar — xodim menyusi
    if bu.staff_id and (text.startswith("/start") or text in ("/menu", BTN_CANCEL, "/cancel") or not text):
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, staff_card(tenant, bu.staff), staff_keyboard(tenant, bu))
        return True

    # --- bot hozircha faqat xodimlar uchun: mijoz menyusi yopiq (vakansiyaga ariza — yuqorida, ishlayveradi)
    if staff_only(tenant) and not bu.staff_id:
        say(tenant, bu.chat_id, f"Assalomu alaykum! Bu <b>{tenant.name}</b> xodimlari uchun bot.\n"
                                "Xodim bo'lsangiz — telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
        return True

    # --- bekor qilish / start
    if text in (BTN_CANCEL, "/cancel"):
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Bekor qilindi.", main_keyboard(tenant, bu, base_url))
        return True
    if text.startswith("/start") or text == "/menu":
        bu.state = {}
        bu.save(update_fields=["state"])
        cfg = conf(tenant)
        say(tenant, bu.chat_id, f"<b>{tenant.name}</b>\n{cfg.get('welcome_text') or ''}", main_keyboard(tenant, bu, base_url))
        return True

    # --- bron suhbati davom etmoqda
    step = (bu.state or {}).get("step")
    if step and step.startswith("book_"):
        return _booking_step(tenant, bu, text, base_url)
    if step == "crm_bday":
        if text in (BTN_MENU, BTN_BOOK, BTN_ORDERS, BTN_CONTACT, BTN_BONUS) or text.startswith("/"):
            bu.state = {}                       # mijoz boshqa tugmani bosdi — so'rovni tashlab, o'shani bajaramiz
            bu.save(update_fields=["state"])
        else:
            return _birthday_step(tenant, bu, text, base_url)

    if text == BTN_BONUS or text == "/bonus":
        return _bonus_info(tenant, bu, base_url)

    if (text == "💼 Vakansiyalar" or text == "/vakansiyalar") and tenant.module_enabled("hr"):
        from . import hr_flow
        return hr_flow.show_jobs(tenant, bu)

    if text == BTN_BOOK:
        if not (conf(tenant).get("enable_booking") and tenant.module_enabled("reservations")):
            say(tenant, bu.chat_id, "Hozircha bot orqali bron qilib bo'lmaydi — qo'ng'iroq qiling.", main_keyboard(tenant, bu, base_url))
            return True
        if not bu.phone:
            say(tenant, bu.chat_id, "Bron uchun avval telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
            return True
        bu.state = {"step": "book_guests"}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Necha kishi bo'lasiz?", {"keyboard": [["1", "2", "3", "4"], ["5", "6", "8", "10"], [BTN_CANCEL]], "resize_keyboard": True})
        return True

    if text == BTN_ORDERS or text == "/buyurtmalarim":
        if not bu.phone:
            say(tenant, bu.chat_id, "Buyurtmalaringizni ko'rish uchun telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
            return True
        if not tenant.module_enabled("pos"):
            say(tenant, bu.chat_id, "Buyurtmalar tarixi hozircha mavjud emas.")
            return True
        rows = _orders_for(bu.phone)
        if not rows:
            say(tenant, bu.chat_id, "Hali buyurtmangiz yo'q. «" + BTN_MENU + "» tugmasini bosing 🙂", main_keyboard(tenant, bu, base_url))
        else:
            lines = [f"#{o.number} · {o.created_at.astimezone(timezone.get_current_timezone()):%d.%m %H:%M} · {money(o.total)} so'm · {STATUS_UZ.get(o.status, o.status)}" for o in rows]
            say(tenant, bu.chat_id, "<b>Oxirgi buyurtmalaringiz</b>\n" + "\n".join(lines)
                + f"\n\nJami: {bu.orders_count} ta buyurtma · {money(bu.spent_total)} so'm", main_keyboard(tenant, bu, base_url))
        return True

    if text == BTN_MENU:
        url = miniapp_url(base_url)
        if url:
            say(tenant, bu.chat_id, "Menyuni ochish uchun pastdagi tugmani bosing 👇",
                {"inline_keyboard": [[{"text": "🍔 Menyuni ochish", "web_app": {"url": url}}]]})
        else:
            say(tenant, bu.chat_id, _menu_text(), main_keyboard(tenant, bu, base_url))
        return True

    if text == BTN_CONTACT:
        say(tenant, bu.chat_id, _contact_text(tenant), main_keyboard(tenant, bu, base_url))
        return True

    if bu.staff_id and text.startswith("/"):
        return False
    say(tenant, bu.chat_id, "Quyidagi tugmalardan birini tanlang 👇", main_keyboard(tenant, bu, base_url))
    return True


def _menu_text() -> str:
    from modules.catalog.services import current_snapshot
    snap = current_snapshot() or {"categories": []}
    lines = []
    for c in snap["categories"][:6]:
        lines.append(f"\n<b>{c['name'].get('uz')}</b>")
        for p in c["products"][:8]:
            lines.append(f"• {p['name'].get('uz')} — {money(p['price'])} so'm")
    return ("<b>Taomnoma</b>" + "\n".join(lines)) if lines else "Taomnoma hali e'lon qilinmagan."


def _contact_text(tenant) -> str:
    try:
        from modules.cms.models import SiteSettings
        s = SiteSettings.get()
        parts = [f"<b>{s.title or tenant.name}</b>"]
        if s.phone:
            parts.append(f"☎️ {s.phone}")
        if s.address:
            parts.append(f"📍 {s.address}")
        return "\n".join(parts)
    except Exception:
        return tenant.name


# ------------------------------------------------------------------ bron suhbati
def _slots(day, guests: int, tenant) -> list[str]:
    from modules.reservations.services import free_tables
    now = timezone.localtime()
    out = []
    for h in range(11, 23):
        for m in (0, 30):
            at = timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m))
            if at < now + timedelta(minutes=30):
                continue
            if free_tables(at, 90, guests, tenant=tenant):
                out.append(f"{h:02d}:{m:02d}")
    return out


def _booking_step(tenant, bu: BotUser, text: str, base_url) -> bool:
    st = dict(bu.state or {})
    today = timezone.localdate()
    days = {"Bugun": today, "Ertaga": today + timedelta(days=1), "Indinga": today + timedelta(days=2)}
    if st["step"] == "book_guests":
        if not text.isdigit() or not (1 <= int(text) <= 30):
            say(tenant, bu.chat_id, "Mehmonlar sonini raqam bilan yozing (masalan: 4).")
            return True
        st.update(step="book_day", guests=int(text))
        bu.state = st
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Qaysi kunga?", {"keyboard": [list(days.keys()), [BTN_CANCEL]], "resize_keyboard": True})
        return True
    if st["step"] == "book_day":
        if text not in days:
            say(tenant, bu.chat_id, "Tugmalardan birini tanlang: Bugun / Ertaga / Indinga.")
            return True
        day = days[text]
        slots = _slots(day, st["guests"], tenant)
        if not slots:
            say(tenant, bu.chat_id, f"{text} {st['guests']} kishilik bo'sh stol qolmagan 😔 Boshqa kunni tanlang.",
                {"keyboard": [list(days.keys()), [BTN_CANCEL]], "resize_keyboard": True})
            return True
        st.update(step="book_time", day=day.isoformat())
        bu.state = st
        bu.save(update_fields=["state"])
        rows = [slots[i:i + 4] for i in range(0, min(len(slots), 16), 4)] + [[BTN_CANCEL]]
        say(tenant, bu.chat_id, "Soatni tanlang (bo'sh vaqtlar):", {"keyboard": rows, "resize_keyboard": True})
        return True
    if st["step"] == "book_time":
        try:
            hh, mm = (int(x) for x in text.split(":"))
            day = datetime.fromisoformat(st["day"]).date()
            at = timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm))
        except Exception:
            say(tenant, bu.chat_id, "Vaqtni tugmadan tanlang (masalan: 19:00).")
            return True
        res = create_booking(tenant, bu, at, st["guests"])
        bu.state = {}
        bu.save(update_fields=["state"])
        if res is None:
            say(tenant, bu.chat_id, "Afsus, bu vaqt hozirgina band bo'ldi. Qaytadan urinib ko'ring.", main_keyboard(tenant, bu, base_url))
        else:
            tbl = f" · stol {res.table.number}" if res.table else ""
            say(tenant, bu.chat_id, f"✅ Bron qilindi!\n📅 {at:%d.%m.%Y} · ⏰ {at:%H:%M} · 👥 {res.guests} kishi{tbl}\n"
                                    "Kutamiz! O'zgartirish uchun qo'ng'iroq qiling.", main_keyboard(tenant, bu, base_url))
            notify_staff(tenant, f"📅 <b>Yangi bron (Telegram)</b>\n{bu.full_name or bu.phone} · {bu.phone}\n"
                                 f"{at:%d.%m %H:%M} · {res.guests} kishi{tbl}")
        return True
    bu.state = {}
    bu.save(update_fields=["state"])
    return True


def create_booking(tenant, bu: BotUser, at, guests: int):
    from modules.reservations.models import Reservation
    from modules.reservations.services import auto_table, free_tables
    if not free_tables(at, 90, guests, tenant=tenant):
        return None
    res = Reservation(guest_name=bu.full_name or bu.phone, phone=bu.phone, guests=guests, starts_at=at,
                      duration_minutes=90, source="telegram")
    res.table = auto_table(res, tenant=tenant)
    res.save()
    return res


def notify_staff(tenant, text: str) -> None:
    chat = (conf(tenant).get("notify_staff_chat_id") or "").strip()
    if chat:
        say(tenant, chat, text)


# ------------------------------------------------------------------ Mini App: initData tekshiruvi
class InitDataError(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age_hours: int = 24) -> dict:
    """Telegram WebApp initData'ni tekshiradi va foydalanuvchi ma'lumotini qaytaradi."""
    if not init_data or not bot_token:
        raise InitDataError("initData yoki token yo'q")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise InitDataError("imzo noto'g'ri")
    auth_date = int(pairs.get("auth_date", "0") or 0)
    if auth_date and timezone.now().timestamp() - auth_date > max_age_hours * 3600:
        raise InitDataError("initData eskirgan")
    try:
        return json.loads(pairs.get("user", "{}"))
    except ValueError as e:
        raise InitDataError("user noto'g'ri") from e


def sign_init_data(user: dict, bot_token: str, auth_date: int | None = None) -> str:
    """Testlar va dev uchun: haqiqiy Telegram kabi imzolangan initData yasaydi."""
    from urllib.parse import urlencode
    pairs = {"auth_date": str(auth_date or int(timezone.now().timestamp())), "query_id": "AAH-dev", "user": json.dumps(user, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def miniapp_user(tenant, init_data: str) -> BotUser | None:
    """initData → BotUser. Token yo'q bo'lsa (dev rejim) — tekshiruvsiz, mehmon sifatida."""
    tok = token(tenant)
    if not tok:
        if dj_settings.DEBUG:
            return None
        raise InitDataError("Bot sozlanmagan")
    user = verify_init_data(init_data, tok)
    if not user.get("id"):
        raise InitDataError("user yo'q")
    bu, _ = BotUser.objects.get_or_create(chat_id=user["id"])
    bu.full_name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or bu.full_name
    bu.username = user.get("username") or bu.username
    bu.last_seen_at = timezone.now()
    bu.save()
    return bu


# ------------------------------------------------------------------ ommaviy xabar
def audience_qs(audience: str):
    qs = BotUser.objects.filter(is_blocked=False)
    if audience == Audience.WITH_PHONE:
        qs = qs.exclude(phone="")
    elif audience == Audience.BUYERS:
        qs = qs.filter(orders_count__gt=0)
    return qs


def send_broadcast(tenant, b: Broadcast) -> Broadcast:
    tok = token(tenant)
    markup = {"inline_keyboard": [[{"text": b.button_text, "url": b.button_url}]]} if b.button_text and b.button_url else None
    sent = failed = 0
    users = list(audience_qs(b.audience))
    for u in users:
        r = call("sendMessage", {"chat_id": u.chat_id, "text": b.text, "parse_mode": "HTML",
                                 **({"reply_markup": markup} if markup else {})}, tok)
        if r.get("ok"):
            sent += 1
        else:
            failed += 1
            if r.get("error_code") == 403:          # botni bloklagan
                BotUser.objects.filter(pk=u.pk).update(is_blocked=True)
    b.total, b.sent, b.failed = len(users), sent, failed
    b.status, b.sent_at = BroadcastStatus.SENT, timezone.now()
    b.save()
    return b


# ------------------------------------------------------------------ bonus (CRM moduli yoqilgan bo'lsa)
def _birthday_step(tenant, bu: BotUser, text: str, base_url) -> bool:
    from datetime import date as _date
    bu.state = {}
    if text != BTN_SKIP:
        parts = [p for p in text.replace("/", ".").replace("-", ".").replace(" ", ".").split(".") if p]
        try:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            y = y + 1900 if y < 100 and y > 30 else (y + 2000 if y < 100 else y)
            bd = _date(y, m, d)
            if not (1920 <= bd.year <= timezone.localdate().year - 5):
                raise ValueError
        except (ValueError, IndexError):
            bu.state = {"step": "crm_bday"}
            bu.save(update_fields=["state"])
            say(tenant, bu.chat_id, "Tushunmadim 🙂 Kun.oy.yil ko'rinishida yozing, masalan <b>25.09.1995</b>",
                {"keyboard": [[BTN_SKIP]], "resize_keyboard": True})
            return True
        from modules.crm.models import Customer
        Customer.objects.filter(phone=bu.phone, birthday__isnull=True).update(birthday=bd)
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, f"🎉 Saqlandi: {bd:%d.%m.%Y}. Tug'ilgan kuningizda sovg'a kutib turadi!", main_keyboard(tenant, bu, base_url))
        return True
    bu.save(update_fields=["state"])
    say(tenant, bu.chat_id, "Mayli. Kerak bo'lsa keyin yozishingiz mumkin.", main_keyboard(tenant, bu, base_url))
    return True


def _bonus_info(tenant, bu: BotUser, base_url) -> bool:
    if not tenant.module_enabled("crm"):
        say(tenant, bu.chat_id, "Bonus tizimi hozircha yoqilmagan.", main_keyboard(tenant, bu, base_url))
        return True
    if not bu.phone:
        say(tenant, bu.chat_id, "Bonuslaringizni ko'rish uchun telefon raqamingizni ulashing 👇", main_keyboard(tenant, bu, base_url))
        return True
    from modules.crm import services as crm
    from modules.crm.models import Promo
    c, _ = crm.get_or_create(tenant, bu.phone, bu.full_name, source="telegram")
    cfg = crm.conf(tenant)
    lvl = crm.level_of(c, cfg)
    lines = [f"🎁 <b>Bonus balansingiz: {money(c.balance)} so'm</b>",
             f"Daraja: <b>{lvl['name']}</b> — har xariddan {lvl['percent']}% qaytadi"]
    if lvl["next"]:
        lines.append(f"{lvl['next']} darajagacha: {money(lvl['next_left'])} so'm xarid")
    lines.append(f"Bonus bilan chekning {cfg['max_pay_percent']}% gacha to'lash mumkin — kassada raqamingizni ayting.")
    promos = [p for p in Promo.objects.filter(is_active=True)[:10] if not (p.ends_on and p.ends_on < timezone.localdate())]
    if promos:
        lines.append("\n<b>Aksiyalar</b>")
        lines += [f"• {p.name}" + (f" — promokod <code>{p.code}</code>" if p.code else "") for p in promos[:6]]
    say(tenant, bu.chat_id, "\n".join(lines), main_keyboard(tenant, bu, base_url))
    return True
