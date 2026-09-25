"""
CRM mantiqi: mijoz kartasi, darajalar (Oddiy/Kumush/Oltin), keshbek, aksiyalar, tug'ilgan kun, segmentlar.

Pul qoidalari (kassir va mijoz uchun oddiy):
  • Keshbek to'langan puldan hisoblanadi (bonus bilan to'langan qismidan emas).
  • Bonus bilan chekning `max_pay_percent` foizigacha to'lash mumkin.
  • Bir chekka bitta aksiya — eng foydalisi (yoki kassir kiritgan promokod).
  • Chek bekor qilinsa: ishlatilgan bonus qaytadi, yig'ilgan keshbek olib tashlanadi.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from core.models import User

from .models import BonusTxn, Customer, OrderLink, Promo, PromoAudience, PromoKind, TxnKind

log = logging.getLogger("crm")

_DEFAULTS = {k: v.get("default") for k, v in json.loads(
    (Path(__file__).parent / "module.json").read_text(encoding="utf-8"))["settings_schema"]["properties"].items()}

LEVELS = {"basic": "Oddiy", "silver": "Kumush", "gold": "Oltin"}


def conf(tenant) -> dict:
    saved = ((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("crm") or {}
    return {**_DEFAULTS, **saved}


def money(v: int) -> str:
    return f"{int(v):,}".replace(",", " ")


def normalize(phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        return ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 9:                       # 901234567 → +998901234567
        digits = "998" + digits
    return User.objects.normalize_phone(digits) if len(digits) >= 9 else ""


# ------------------------------------------------------------------ darajalar
def level_of(c: Customer, cfg: dict) -> dict:
    spent = c.spent_total
    if spent >= cfg["gold_from"]:
        code, pct, nxt, nxt_from = "gold", cfg["gold_percent"], None, None
    elif spent >= cfg["silver_from"]:
        code, pct, nxt, nxt_from = "silver", cfg["silver_percent"], "gold", cfg["gold_from"]
    else:
        code, pct, nxt, nxt_from = "basic", cfg["cashback_percent"], "silver", cfg["silver_from"]
    return {"code": code, "name": LEVELS[code], "percent": int(pct),
            "next": LEVELS.get(nxt) if nxt else None, "next_left": max(0, nxt_from - spent) if nxt_from else 0}


def birthday_in(c: Customer, today: date, window: int) -> bool:
    if not c.birthday:
        return False
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            b = c.birthday.replace(year=y)
        except ValueError:                      # 29-fevral
            b = date(y, 3, 1)
        if abs((b - today).days) <= window:
            return True
    return False


# ------------------------------------------------------------------ mijoz va bonus
def get_or_create(tenant, phone: str, name: str = "", source: str = "pos") -> tuple[Customer | None, bool]:
    p = normalize(phone)
    if not p:
        return None, False
    c, created = Customer.objects.get_or_create(phone=p, defaults={"name": name[:120], "source": source})
    if not created and name and not c.name:
        c.name = name[:120]
        c.save(update_fields=["name", "updated_at"])
    if created:
        bonus = int(conf(tenant).get("welcome_bonus") or 0) if tenant is not None else 0
        if bonus > 0:
            add_txn(tenant, c, TxnKind.WELCOME, bonus, note="Xush kelibsiz!")
    return c, created


def add_txn(tenant, c: Customer, kind: str, amount: int, *, order_id: int | None = None, note: str = "",
            user=None, notify: bool = True) -> BonusTxn | None:
    amount = int(amount)
    if amount == 0:
        return None
    with transaction.atomic():
        t = BonusTxn.objects.create(customer=c, kind=kind, amount=amount, order_id=order_id, note=note[:200], created_by=user)
        Customer.objects.filter(pk=c.pk).update(balance=F("balance") + amount)
    c.refresh_from_db(fields=["balance"])
    if notify and amount > 0 and tenant is not None and conf(tenant).get("notify_bonus"):
        label = {TxnKind.EARN: "Xarid uchun keshbek", TxnKind.WELCOME: "Xush kelibsiz sovg'asi",
                 TxnKind.ADJUST: "Bonus qo'shildi", TxnKind.REFUND: "Bonus qaytarildi"}.get(kind)
        if label:
            tell(tenant, c, f"🎁 <b>+{money(amount)} bonus</b> — {label}\nBalans: <b>{money(c.balance)} so'm</b>")
    return t


def tell(tenant, c: Customer, text: str, marketing: bool = False) -> bool:
    """Mijozga Telegram orqali xabar (bot ulangan va mijoz botga telefon ulashgan bo'lsa).
    marketing=True — reklama xabari: mijoz rad etgan bo'lsa yuborilmaydi."""
    if tenant is None or not tenant.module_enabled("telegram") or (marketing and not c.marketing_ok):
        return False
    try:
        from modules.telegram import services as tg
        from modules.telegram.models import BotUser
        bu = BotUser.objects.filter(phone=c.phone, is_blocked=False).first()
        return bool(bu and tg.say(tenant, bu.chat_id, text))
    except Exception:                           # bot xatosi kassani to'xtatmasin
        log.exception("crm tell failed")
        return False


# ------------------------------------------------------------------ aksiyalar
def _lines_from_items(items: list[dict]) -> list[dict]:
    """[{product_id, qty}] → [{product_id, category_id, amount}] — narx bazadan."""
    from modules.catalog.models import Product
    ids = [int(i.get("product_id") or 0) for i in items]
    prods = {p.pk: p for p in Product.objects.filter(pk__in=ids)}
    out = []
    for i in items:
        p = prods.get(int(i.get("product_id") or 0))
        if p:
            out.append({"product_id": p.pk, "category_id": p.category_id, "amount": p.price * max(1, int(i.get("qty") or 1))})
    return out


def _lines_from_order(order) -> list[dict]:
    return [{"product_id": i.product_id, "category_id": i.product.category_id if i.product_id else None, "amount": i.line_total}
            for i in order.items.select_related("product")]


def promo_check(p: Promo, lines: list[dict], c: Customer | None, cfg: dict, now=None) -> tuple[int, str]:
    """(chegirma so'mda, sabab). Chegirma 0 bo'lsa — sabab nima uchun ishlamaganini aytadi."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    if not p.is_active:
        return 0, "Aksiya o'chirilgan"
    if p.starts_on and today < p.starts_on:
        return 0, f"Aksiya {p.starts_on:%d.%m} dan boshlanadi"
    if p.ends_on and today > p.ends_on:
        return 0, "Aksiya muddati tugagan"
    if p.weekdays and today.weekday() not in p.weekdays:
        return 0, "Bugun bu aksiya kuni emas"
    if p.hour_from is not None and p.hour_to is not None:
        h = now.hour
        ok = p.hour_from <= h < p.hour_to if p.hour_from < p.hour_to else (h >= p.hour_from or h < p.hour_to)
        if not ok:
            return 0, f"Aksiya {p.hour_from:02d}:00–{p.hour_to:02d}:00 da ishlaydi"
    if p.max_uses and p.used_count >= p.max_uses:
        return 0, "Aksiya limiti tugagan"
    if p.audience != PromoAudience.ALL:
        if c is None:
            return 0, "Bu aksiya uchun mijoz telefoni kerak"
        if p.audience == PromoAudience.NEW and c.orders_count > 0:
            return 0, "Faqat birinchi xarid uchun"
        if p.audience == PromoAudience.BIRTHDAY and not birthday_in(c, today, int(cfg["birthday_window"])):
            return 0, "Faqat tug'ilgan kun atrofida"
        lvl = level_of(c, cfg)["code"]
        if p.audience == PromoAudience.SILVER and lvl == "basic":
            return 0, "Faqat Kumush va Oltin mijozlar uchun"
        if p.audience == PromoAudience.GOLD and lvl != "gold":
            return 0, "Faqat Oltin mijozlar uchun"
    total = sum(x["amount"] for x in lines)
    if total < p.min_order:
        return 0, f"Eng kam summa {money(p.min_order)} so'm"
    if p.product_ids or p.category_ids:
        base = sum(x["amount"] for x in lines if x["product_id"] in (p.product_ids or []) or x["category_id"] in (p.category_ids or []))
        if base <= 0:
            return 0, "Savatda aksiyadagi taom yo'q"
    else:
        base = total
    if p.kind == PromoKind.PERCENT:
        d = base * min(100, p.value) // 100
        if p.max_discount:
            d = min(d, p.max_discount)
    else:
        d = min(p.value, base)
    return int(d), ""


def best_promo(lines, c, cfg, code: str = "") -> tuple[Promo | None, int, str]:
    code = (code or "").strip().upper()
    if code:
        p = Promo.objects.filter(code__iexact=code).first()
        if p is None:
            return None, 0, "Bunday promokod yo'q"
        d, why = promo_check(p, lines, c, cfg)
        return (p, d, "") if d else (None, 0, why)
    best, best_d = None, 0
    for p in Promo.objects.filter(is_active=True, code=""):
        d, _ = promo_check(p, lines, c, cfg)
        if d > best_d:
            best, best_d = p, d
    return best, best_d, ""


def quote(tenant, *, phone: str, lines: list[dict], promo_code: str = "", manual_discount: int = 0, use_bonus: int | None = None) -> dict:
    """Kassa uchun hisob: mijoz kartasi, aksiya chegirmasi, ishlatish mumkin bo'lgan bonus."""
    cfg = conf(tenant)
    p = normalize(phone)
    c = Customer.objects.filter(phone=p).first() if p else None
    subtotal = sum(x["amount"] for x in lines)
    promo, pd, why = best_promo(lines, c, cfg, promo_code)
    after = max(0, subtotal - max(0, manual_discount) - pd)
    max_bonus = min(c.balance, after * int(cfg["max_pay_percent"]) // 100) if c else 0
    bonus = max_bonus if use_bonus is None else max(0, min(int(use_bonus), max_bonus))
    total = max(0, after - bonus)
    lvl = level_of(c, cfg) if c else level_of(Customer(spent_total=0), cfg)
    return {
        "phone": p, "is_new": c is None and bool(p),
        "customer": customer_card(c, cfg) if c else None,
        "subtotal": subtotal, "manual_discount": max(0, manual_discount),
        "promo": {"id": promo.pk, "name": promo.name, "code": promo.code, "discount": pd} if promo else None,
        "promo_error": why, "max_bonus": max_bonus, "bonus": bonus, "total": total,
        "will_earn": total * lvl["percent"] // 100 if p else 0,
    }


def customer_card(c: Customer, cfg: dict) -> dict:
    today = timezone.localdate()
    return {"id": c.pk, "phone": c.phone, "name": c.name, "balance": c.balance, "orders_count": c.orders_count,
            "spent_total": c.spent_total, "level": level_of(c, cfg),
            "birthday": c.birthday.isoformat() if c.birthday else None,
            "birthday_soon": birthday_in(c, today, int(cfg["birthday_window"])),
            "last_order_at": c.last_order_at.isoformat() if c.last_order_at else None,
            "tags": c.tags, "note": c.note, "source": c.source, "marketing_ok": c.marketing_ok, "gender": c.gender,
            "avg_check": c.spent_total // c.orders_count if c.orders_count else 0,
            "created_at": c.created_at.isoformat()}


def attach(tenant, order, *, phone: str, promo_code: str = "", manual_discount: int = 0, use_bonus: int = 0) -> dict:
    """Ochiq buyurtmaga mijoz/aksiya/bonusni biriktiradi va chegirmani serverda qayta hisoblaydi."""
    lines = _lines_from_order(order)
    q = quote(tenant, phone=phone, lines=lines, promo_code=promo_code, manual_discount=manual_discount, use_bonus=use_bonus)
    c = None
    if q["phone"]:
        c, _ = get_or_create(tenant, q["phone"], order.customer_name, source=order.source or "pos")
    link, _ = OrderLink.objects.update_or_create(order_id=order.pk, defaults={
        "customer": c, "promo_id": (q["promo"] or {}).get("id"),
        "promo_discount": (q["promo"] or {}).get("discount", 0), "bonus_used": q["bonus"]})
    order.customer_phone = q["phone"] or order.customer_phone
    order.discount = q["manual_discount"] + link.promo_discount + link.bonus_used
    order.recalc()
    order.save()
    return q


# ------------------------------------------------------------------ to'lov / bekor
def settle_paid(tenant, order) -> None:
    link = OrderLink.objects.filter(order_id=order.pk).first()
    if link and link.settled:
        return
    c = link.customer if link and link.customer_id else None
    if c is None and order.customer_phone:
        c, _ = get_or_create(tenant, order.customer_phone, order.customer_name, source=order.source or "pos")
    if c is None:
        return
    cfg = conf(tenant)
    now = order.paid_at or timezone.now()
    lvl = level_of(c, cfg)                               # daraja — shu xariddan oldingi holat bo'yicha
    with transaction.atomic():
        if link is None:
            link = OrderLink.objects.create(order_id=order.pk, customer=c)
        link.customer = c
        if link.bonus_used:
            c.refresh_from_db(fields=["balance"])
            used = min(link.bonus_used, max(0, c.balance))
            if used:
                add_txn(tenant, c, TxnKind.SPEND, -used, order_id=order.pk, note=f"Chek #{order.number}", notify=False)
            link.bonus_used = used
        earned = order.total * lvl["percent"] // 100
        Customer.objects.filter(pk=c.pk).update(
            orders_count=F("orders_count") + 1, spent_total=F("spent_total") + order.total, last_order_at=now)
        Customer.objects.filter(pk=c.pk, first_order_at__isnull=True).update(first_order_at=now)
        if link.promo_id:
            Promo.objects.filter(pk=link.promo_id).update(used_count=F("used_count") + 1,
                                                          discount_total=F("discount_total") + link.promo_discount,
                                                          revenue_total=F("revenue_total") + order.total)
        link.earned, link.settled = earned, True
        link.save()
    if earned:
        add_txn(tenant, c, TxnKind.EARN, earned, order_id=order.pk, note=f"Chek #{order.number} · {lvl['percent']}%")


def reverse(tenant, order_id: int) -> None:
    link = OrderLink.objects.select_related("customer").filter(order_id=order_id, settled=True).first()
    if link is None or link.customer is None:
        return
    from modules.pos.models import Order
    o = Order.objects.filter(pk=order_id).first()
    c = link.customer
    with transaction.atomic():
        if link.bonus_used:
            add_txn(tenant, c, TxnKind.REFUND, link.bonus_used, order_id=order_id, note="Chek bekor — bonus qaytdi", notify=False)
        if link.earned:
            add_txn(tenant, c, TxnKind.REFUND, -link.earned, order_id=order_id, note="Chek bekor — keshbek olindi", notify=False)
        total = o.total if o else 0
        Customer.objects.filter(pk=c.pk).update(orders_count=F("orders_count") - 1, spent_total=F("spent_total") - total)
        if link.promo_id:
            Promo.objects.filter(pk=link.promo_id, used_count__gt=0).update(used_count=F("used_count") - 1)
        link.settled = False
        link.save(update_fields=["settled"])


# ------------------------------------------------------------------ tug'ilgan kun (kuniga bir marta)
_daily_done: dict[str, date] = {}


def daily(tenant, force: bool = False) -> int:
    """Bugun tug'ilganlarga bonus + tabrik. Qayta chaqirilsa ikki marta bermaydi (yiliga bitta)."""
    today = timezone.localdate()
    key = getattr(tenant, "schema_name", "?")
    if not force and _daily_done.get(key) == today:
        return 0
    _daily_done[key] = today
    cfg = conf(tenant)
    bonus = int(cfg.get("birthday_bonus") or 0)
    n = 0
    for c in Customer.objects.filter(birthday__month=today.month, birthday__day=today.day):
        if BonusTxn.objects.filter(customer=c, kind=TxnKind.BIRTHDAY, created_at__year=today.year).exists():
            continue
        if bonus > 0:
            add_txn(tenant, c, TxnKind.BIRTHDAY, bonus, note=f"{today.year}-yil tug'ilgan kun", notify=False)
        else:
            BonusTxn.objects.create(customer=c, kind=TxnKind.BIRTHDAY, amount=0, note="tabrik")
        text = (cfg.get("birthday_text") or "").replace("{name}", c.name or "aziz mijoz").replace("{bonus}", money(bonus))
        tell(tenant, c, text)
        n += 1
    return n


# ------------------------------------------------------------------ segmentlar
SEGMENTS = {
    "all": "Hammasi", "new": "Yangi (30 kun)", "regular": "Doimiy (3+ xarid)", "vip": "Oltin",
    "sleeping": "Uxlab qolgan", "birthday": "Tug'ilgan kuni yaqin (7 kun)", "never": "Hali xarid qilmagan",
}


def segment_qs(seg: str, cfg: dict):
    now = timezone.now()
    qs = Customer.objects.all()
    if seg == "new":
        return qs.filter(created_at__gte=now - timedelta(days=30))
    if seg == "regular":
        return qs.filter(orders_count__gte=3)
    if seg == "vip":
        return qs.filter(spent_total__gte=cfg["gold_from"])
    if seg == "sleeping":
        return qs.filter(orders_count__gte=1, last_order_at__lt=now - timedelta(days=int(cfg["sleeping_days"])))
    if seg == "never":
        return qs.filter(orders_count=0)
    if seg == "birthday":
        today = timezone.localdate()
        cond = Q()
        for d in range(0, 8):
            x = today + timedelta(days=d)
            cond |= Q(birthday__month=x.month, birthday__day=x.day)
        return qs.filter(cond)
    return qs
