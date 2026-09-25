"""Telegram bot API — /api/v1/bot/... (mavjud /telegram/webhook bilan to'qnashmaydi)."""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record
from core.auth import auth, require_module, require_perm
from core.events import emit
from integrations.telegram import call

from . import services
from .models import Audience, BotUser, Broadcast, BroadcastStatus

router = Router(tags=["telegram"])
SECRET_FIELDS = ("bot_token",)


def _guard(request, perm: str):
    require_module(request, "telegram")
    require_perm(request, perm)


def _base(request) -> str:
    return request.build_absolute_uri("/").rstrip("/")


def _mask(v: str) -> str:
    return ("•" * 8 + v[-4:]) if v else ""


# ------------------------------------------------------------------ sozlamalar
class SettingsIn(Schema):
    bot_token: Optional[str] = None
    bot_username: str = ""
    welcome_text: str = ""
    notify_staff_chat_id: str = ""
    allow_delivery: bool = True
    allow_pickup: bool = True
    allow_dine_in: bool = False
    delivery_fee: int = 0
    free_delivery_from: int = 0
    min_order: int = 0
    enable_booking: bool = True
    notify_paid: bool = True
    notify_ready: bool = True


def _settings_out(request) -> dict:
    cfg = services.conf(request.tenant)
    base = _base(request)
    return {**{k: v for k, v in cfg.items() if k not in SECRET_FIELDS and k != "webhook_secret"},
            "bot_token_masked": _mask(cfg.get("bot_token") or ""), "has_token": bool(services.token(request.tenant)),
            "webhook_url": f"{base}/api/v1/telegram/webhook", "miniapp_url": f"{base}/tg/",
            "https": base.startswith("https://"), "webhook_set": bool(cfg.get("webhook_secret"))}


@router.get("/settings", auth=auth)
def get_settings(request):
    _guard(request, "telegram.view")
    return _settings_out(request)


@router.put("/settings", auth=auth)
def put_settings(request, data: SettingsIn):
    _guard(request, "telegram.manage")
    t = request.tenant
    mods = dict((t.settings or {}).get("modules") or {})
    cur = dict(mods.get("telegram") or {})
    new = data.dict()
    tok = (new.pop("bot_token") or "").strip()
    if tok and "•" not in tok:
        if ":" not in tok:
            raise HttpError(400, "Token noto'g'ri ko'rinishda. @BotFather bergan tokenni to'liq nusxalang (123456:ABC...).")
        cur["bot_token"] = tok
    elif data.bot_token == "":
        cur.pop("bot_token", None)             # bo'sh yuborilsa — token o'chiriladi
    new["bot_username"] = new["bot_username"].strip().lstrip("@")
    cur.update(new)
    mods["telegram"] = cur
    t.settings = {**(t.settings or {}), "modules": mods}
    t.save(update_fields=["settings"])
    record(request, "update", model="TelegramSettings", after={k: v for k, v in cur.items() if k not in ("bot_token", "webhook_secret")})
    return _settings_out(request)


@router.get("/info", auth=auth)
def bot_info(request):
    """Token to'g'rimi — Telegram'dan bot nomini so'raymiz."""
    _guard(request, "telegram.view")
    tok = services.token(request.tenant)
    if not tok:
        return {"ok": False, "detail": "Token kiritilmagan — hozircha xabarlar faqat logga yoziladi (sinov rejimi)."}
    r = call("getMe", {}, tok)
    if not r.get("ok"):
        return {"ok": False, "detail": r.get("description") or r.get("error") or "Telegram javob bermadi"}
    return {"ok": True, "username": r["result"].get("username"), "name": r["result"].get("first_name")}


@router.post("/set-webhook", auth=auth)
def set_webhook(request):
    """Webhook + Mini App menyu tugmasi. Faqat https domen bilan ishlaydi (Telegram talabi)."""
    _guard(request, "telegram.manage")
    tok = services.token(request.tenant)
    if not tok:
        raise HttpError(400, "Avval bot tokenini kiriting va saqlang.")
    base = _base(request)
    if not base.startswith("https://"):
        raise HttpError(400, f"Webhook uchun sayt https bilan ochilishi kerak. Hozir: {base}. Serverga joylaganda shu tugmani bosing.")
    t = request.tenant
    mods = dict((t.settings or {}).get("modules") or {})
    cur = dict(mods.get("telegram") or {})
    cur["webhook_secret"] = cur.get("webhook_secret") or secrets.token_urlsafe(24)
    mods["telegram"] = cur
    t.settings = {**(t.settings or {}), "modules": mods}
    t.save(update_fields=["settings"])
    r = call("setWebhook", {"url": f"{base}/api/v1/telegram/webhook", "secret_token": cur["webhook_secret"],
                            "allowed_updates": ["message", "callback_query", "my_chat_member"]}, tok)
    call("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Menyu", "web_app": {"url": f"{base}/tg/"}}}, tok)
    if not r.get("ok"):
        raise HttpError(400, f"Telegram rad etdi: {r.get('description') or r.get('error')}")
    return {"ok": True, "url": f"{base}/api/v1/telegram/webhook"}


class TestIn(Schema):
    chat_id: str = ""


@router.post("/test", auth=auth)
def send_test(request, data: TestIn):
    _guard(request, "telegram.manage")
    chat = data.chat_id.strip() or (services.conf(request.tenant).get("notify_staff_chat_id") or "").strip()
    if not chat and request.auth.telegram_id:
        chat = str(request.auth.telegram_id)
    if not chat:
        raise HttpError(400, "Kimga yuborish kerak? Xodimlar guruhi chat ID sini yozing yoki o'zingiz botga /start bosib, telefoningizni ulashing.")
    ok = services.say(request.tenant, chat, f"✅ Sinov xabari — <b>{request.tenant.name}</b> boti ishlayapti.")
    dev = not services.token(request.tenant)
    return {"ok": ok, "chat_id": chat, "dev": dev,
            "detail": "Token yo'q — xabar faqat server logiga yozildi (sinov rejimi)." if dev else ("Yuborildi" if ok else "Yuborilmadi — chat ID yoki tokenni tekshiring")}


# ------------------------------------------------------------------ mijozlar va statistika
def _bu_out(u: BotUser) -> dict:
    return {"id": u.pk, "chat_id": u.chat_id, "full_name": u.full_name, "username": u.username, "phone": u.phone,
            "orders_count": u.orders_count, "spent_total": u.spent_total, "is_blocked": u.is_blocked,
            "is_staff": u.staff_id is not None, "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            "created_at": u.created_at.isoformat()}


@router.get("/users", auth=auth)
def list_users(request, q: str = "", filter: str = "all", limit: int = 200):
    _guard(request, "telegram.view")
    qs = BotUser.objects.all()
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(username__icontains=q))
    if filter == "buyers":
        qs = qs.filter(orders_count__gt=0)
    elif filter == "with_phone":
        qs = qs.exclude(phone="")
    elif filter == "blocked":
        qs = qs.filter(is_blocked=True)
    return [_bu_out(u) for u in qs.order_by("-last_seen_at")[: min(limit, 500)]]


@router.get("/stats", auth=auth)
def stats(request):
    _guard(request, "telegram.view")
    total = BotUser.objects.count()
    week = timezone.now() - timedelta(days=7)
    out = {
        "subscribers": total, "with_phone": BotUser.objects.exclude(phone="").count(),
        "buyers": BotUser.objects.filter(orders_count__gt=0).count(), "blocked": BotUser.objects.filter(is_blocked=True).count(),
        "new_week": BotUser.objects.filter(created_at__gte=week).count(),
        "active_week": BotUser.objects.filter(last_seen_at__gte=week).count(),
        "broadcasts": Broadcast.objects.filter(status=BroadcastStatus.SENT).count(),
        "orders_today": 0, "orders_30d": 0, "revenue_30d": 0,
    }
    out["conversion"] = round(100 * out["buyers"] / total, 1) if total else 0
    if request.tenant.module_enabled("pos"):
        from modules.pos.models import Order
        tg = Order.objects.filter(source="telegram")
        out["orders_today"] = tg.filter(created_at__date=timezone.localdate()).count()
        m = tg.filter(created_at__gte=timezone.now() - timedelta(days=30))
        out["orders_30d"] = m.count()
        out["revenue_30d"] = int(m.filter(status="paid").aggregate(s=Sum("total"))["s"] or 0)
    return out


# ------------------------------------------------------------------ ommaviy xabar
class BroadcastIn(Schema):
    text: str
    audience: str = Audience.ALL
    button_text: str = ""
    button_url: str = ""


def _b_out(b: Broadcast) -> dict:
    return {"id": b.pk, "text": b.text, "audience": b.audience, "button_text": b.button_text, "button_url": b.button_url,
            "status": b.status, "total": b.total, "sent": b.sent, "failed": b.failed,
            "sent_at": b.sent_at.isoformat() if b.sent_at else None, "created_at": b.created_at.isoformat(),
            "reach": services.audience_qs(b.audience).count()}


@router.get("/broadcasts", auth=auth)
def list_broadcasts(request):
    _guard(request, "telegram.view")
    return [_b_out(b) for b in Broadcast.objects.all()[:50]]


@router.post("/broadcasts", auth=auth)
def create_broadcast(request, data: BroadcastIn):
    _guard(request, "telegram.broadcast")
    if not data.text.strip():
        raise HttpError(400, "Xabar matnini yozing.")
    if data.audience not in Audience.values:
        raise HttpError(400, "Auditoriya noto'g'ri.")
    if bool(data.button_text) != bool(data.button_url):
        raise HttpError(400, "Tugma uchun ham matn, ham havola kerak.")
    b = Broadcast.objects.create(created_by=request.auth, **data.dict())
    return _b_out(b)


@router.post("/broadcasts/{int:bid}/send", auth=auth)
def send_broadcast(request, bid: int):
    _guard(request, "telegram.broadcast")
    b = get_object_or_404(Broadcast, pk=bid)
    if b.status == BroadcastStatus.SENT:
        raise HttpError(400, "Bu xabar allaqachon yuborilgan. Qayta yuborish uchun nusxa yarating.")
    b = services.send_broadcast(request.tenant, b)
    record(request, "broadcast", model="Broadcast", object_id=b.pk, after={"sent": b.sent, "failed": b.failed})
    return _b_out(b)


@router.delete("/broadcasts/{int:bid}", auth=auth)
def delete_broadcast(request, bid: int):
    _guard(request, "telegram.broadcast")
    b = get_object_or_404(Broadcast, pk=bid, status=BroadcastStatus.DRAFT)
    b.delete()
    return {"ok": True}


# ------------------------------------------------------------------ Mini App (Telegram ichida ochiladi)
class MiniAppAuth(Schema):
    init_data: str = ""


class MiniItem(Schema):
    product_id: int
    qty: int = 1
    modifiers: list[dict] = []
    note: str = ""


class MiniOrderIn(MiniAppAuth):
    items: list[MiniItem]
    type: str = "delivery"          # delivery | pickup | dine_in
    phone: str = ""
    name: str = ""
    address: str = ""
    note: str = ""


def _mini_user(request, init_data: str):
    require_module(request, "telegram")
    try:
        return services.miniapp_user(request.tenant, init_data)
    except services.InitDataError as e:
        raise HttpError(403, "Mini App faqat Telegram ichida ochiladi — botga qaytib, «Menyu» tugmasini bosing.") from e


@router.post("/miniapp/me", auth=None)
def miniapp_me(request, data: MiniAppAuth):
    bu = _mini_user(request, data.init_data)
    cfg = services.conf(request.tenant)
    return {"user": {"name": bu.full_name if bu else "", "phone": bu.phone if bu else ""},
            "rules": {k: cfg[k] for k in ("allow_delivery", "allow_pickup", "allow_dine_in", "delivery_fee", "free_delivery_from", "min_order")}}


@router.post("/miniapp/order", auth=None)
def miniapp_order(request, data: MiniOrderIn):
    """Mini App buyurtmasi → kassadagi buyurtma (source=telegram). Oshxona ekraniga ham tushadi."""
    bu = _mini_user(request, data.init_data)
    t = request.tenant
    if not t.module_enabled("pos"):
        raise HttpError(400, "Onlayn buyurtma hozircha qabul qilinmayapti — qo'ng'iroq qiling.")
    cfg = services.conf(t)
    kind = {"delivery": "delivery", "pickup": "takeaway", "dine_in": "dine_in"}.get(data.type)
    allowed = {"delivery": cfg["allow_delivery"], "pickup": cfg["allow_pickup"], "dine_in": cfg["allow_dine_in"]}
    if not kind or not allowed.get(data.type):
        raise HttpError(400, "Bu buyurtma turi hozircha mavjud emas.")
    if not data.items:
        raise HttpError(400, "Savat bo'sh.")
    phone = services.normalize(data.phone) if data.phone else (bu.phone if bu else "")
    if not phone or len(phone) < 12:
        raise HttpError(400, "Telefon raqamingizni yozing — kuryer yoki kassir siz bilan bog'lanadi.")
    if data.type == "delivery" and len(data.address.strip()) < 5:
        raise HttpError(400, "Yetkazish manzilini yozing (ko'cha, uy, mo'ljal).")

    from modules.catalog.models import Product
    from modules.pos.models import CashShift, Order, OrderItem
    with transaction.atomic():
        shift = CashShift.objects.filter(closed_at__isnull=True).first()
        o = Order.objects.create(branch_id=shift.branch_id if shift else None, shift=shift, type=kind, source="telegram",
                                 customer_phone=phone, customer_name=(data.name or (bu.full_name if bu else ""))[:80],
                                 note=" · ".join(x for x in [data.address.strip() and f"Manzil: {data.address.strip()}", data.note.strip()] if x)[:200])
        for it in data.items:
            p = Product.objects.filter(pk=it.product_id, deleted_at__isnull=True, is_active=True).first()
            if p is None or p.in_stop_list:
                raise HttpError(400, f"«{p.name.get('uz') if p else 'Taom'}» hozir mavjud emas — savatdan olib tashlang.")
            # modifikator narxi bazadan olinadi (brauzerga ishonmaymiz)
            mods = []
            ids = [m.get("id") for m in it.modifiers if m.get("id")]
            if ids:
                for g in p.modifier_groups.filter(is_active=True).prefetch_related("options"):
                    for opt in g.options.filter(is_active=True, pk__in=ids):
                        mods.append({"name": opt.name.get("uz") if isinstance(opt.name, dict) else str(opt.name), "price": opt.price})
            OrderItem.objects.create(order=o, product=p, name=p.name.get("uz") or str(p), qty=max(1, min(it.qty, 50)),
                                     price=p.price, cost=p.cost, modifiers=mods, note=it.note[:120])
        o.recalc()
        if o.subtotal < int(cfg["min_order"] or 0):
            raise HttpError(400, f"Eng kam buyurtma — {services.money(cfg['min_order'])} so'm.")
        if kind == "delivery" and cfg["delivery_fee"] and not (cfg["free_delivery_from"] and o.subtotal >= cfg["free_delivery_from"]):
            OrderItem.objects.create(order=o, name="Yetkazib berish", qty=1, price=int(cfg["delivery_fee"]), cost=0)
            o.recalc()
        o.save()
        if bu:
            if not bu.phone:
                bu.phone = phone
                bu.save(update_fields=["phone"])
    emit("pos.order_created", {"order_id": o.pk, "number": o.number, "total": o.total, "source": "telegram", "_tenant": t}, tenant=t)
    lines = "\n".join(f"• {i.name} × {i.qty}" for i in o.items.all())
    type_uz = services.TYPE_UZ.get(kind, kind)
    if bu:
        services.say(t, bu.chat_id, f"✅ <b>Buyurtma #{o.number} qabul qilindi</b> ({type_uz})\n{lines}\n<b>Jami: {services.money(o.total)} so'm</b>\n"
                                    "Tayyor bo'lganda shu yerga xabar beramiz.")
    services.notify_staff(t, f"🆕 <b>Telegram buyurtma #{o.number}</b> · {type_uz}\n{o.customer_name} · {phone}\n{lines}\n"
                             f"<b>{services.money(o.total)} so'm</b>" + (f"\n{o.note}" if o.note else ""))
    return {"ok": True, "number": o.number, "total": o.total}
