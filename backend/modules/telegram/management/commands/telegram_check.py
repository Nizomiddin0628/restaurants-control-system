"""
Telegram botni tekshirish va tuzatish (serverda):
    restopos-manage telegram_check                 — holat: token, bot nomi, webhook, kutib turgan xabarlar, oxirgi xato
    restopos-manage telegram_check --fix           — webhook'ni to'g'ri manzilga qayta o'rnatadi, buyruqlar menyusini qo'yadi
    restopos-manage telegram_check --fix --slug lazzat

.env dagi TELEGRAM_BOT_TOKEN bitta restoranga tegishli: TELEGRAM_TENANT (standart — lazzat).
O'z tokeni sozlamada saqlangan restoranlar — o'z botlari bilan alohida tekshiriladi.
"""
from __future__ import annotations

import os
import secrets

import requests
from django.core.management.base import BaseCommand

from public.models import Domain, Tenant

API = "https://api.telegram.org/bot{token}/{method}"
COMMANDS = [
    {"command": "start", "description": "Boshlash / menyu"},
    {"command": "vazifalar", "description": "Ochiq vazifalarim"},
    {"command": "keldim", "description": "Ishga keldim"},
    {"command": "ketdim", "description": "Ishdan ketdim"},
    {"command": "ai", "description": "AI Kotib (restoran)"},
    {"command": "global", "description": "Global qidiruv (restoran + internet)"},
    {"command": "hisobot", "description": "Bugungi hisobot"},
    {"command": "profil", "description": "Profilim: kirish, parol, xavfsizlik"},
]


def tg(token: str, method: str, payload: dict | None = None) -> dict:
    try:
        return requests.post(API.format(token=token, method=method), json=payload or {}, timeout=20).json()
    except Exception as e:  # tarmoq xatosi
        return {"ok": False, "description": str(e)}


def env_tenant_slug() -> str:
    want = (os.environ.get("TELEGRAM_TENANT") or "lazzat").strip()
    if Tenant.objects.filter(slug=want).exists():
        return want
    t = Tenant.objects.exclude(schema_name="public").order_by("pk").first()
    return t.slug if t else want


def targets(slug: str | None = None) -> list[tuple[Tenant, str, str]]:
    """[(restoran, token, manba)] — har bir bot faqat bitta restoranga webhook qiladi."""
    out, seen = [], set()
    env_tok = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    env_slug = env_tenant_slug()
    for t in Tenant.objects.exclude(schema_name="public").order_by("pk"):
        own = (((t.settings or {}).get("modules") or {}).get("telegram") or {}).get("bot_token") or ""
        own = own.strip()
        if own:
            tok, src = own, "restoran sozlamasi"
        elif env_tok and t.slug == env_slug:
            tok, src = env_tok, ".env TELEGRAM_BOT_TOKEN"
        else:
            continue
        if slug and t.slug != slug:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append((t, tok, src))
    return out


def base_url(t: Tenant) -> str:
    d = Domain.objects.filter(tenant=t, is_primary=True).first() or Domain.objects.filter(tenant=t).first()
    sch = "https" if os.environ.get("HTTPS") == "1" else "http"
    return f"{sch}://{d.domain}" if d else ""


def ensure_secret(t: Tenant) -> str:
    s = dict(t.settings or {})
    mods = dict(s.get("modules") or {})
    cur = dict(mods.get("telegram") or {})
    if not cur.get("webhook_secret"):
        cur["webhook_secret"] = secrets.token_urlsafe(24)
        mods["telegram"] = cur
        s["modules"] = mods
        t.settings = s
        t.save(update_fields=["settings"])
    return cur["webhook_secret"]


def remember_username(t: Tenant, username: str) -> None:
    """Bot nomi saytdagi «Telegram orqali kirish» havolasi uchun kerak (t.me/<bot>)."""
    if not username:
        return
    s = dict(t.settings or {})
    mods = dict(s.get("modules") or {})
    cur = dict(mods.get("telegram") or {})
    if cur.get("bot_username") != username:
        cur["bot_username"] = username
        mods["telegram"] = cur
        s["modules"] = mods
        t.settings = s
        t.save(update_fields=["settings"])


def staff_only(t: Tenant) -> bool:
    return bool((((t.settings or {}).get("modules") or {}).get("telegram") or {}).get("staff_only", True))


def fix(t: Tenant, tok: str, drop: bool) -> tuple[bool, str]:
    base = base_url(t)
    if not base.startswith("https://"):
        return False, f"sayt https emas ({base or 'domen yoq'}) — Telegram webhook faqat https bilan ishlaydi"
    secret = ensure_secret(t)
    url = f"{base}/api/v1/telegram/webhook"
    r = tg(tok, "setWebhook", {"url": url, "secret_token": secret, "drop_pending_updates": drop,
                               "allowed_updates": ["message", "callback_query", "my_chat_member"]})
    if not r.get("ok"):
        return False, f"setWebhook rad etildi: {r.get('description')}"
    tg(tok, "setMyCommands", {"commands": COMMANDS})
    if staff_only(t) or not t.module_enabled("telegram"):
        tg(tok, "setChatMenuButton", {"menu_button": {"type": "commands"}})
    else:
        tg(tok, "setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Menyu", "web_app": {"url": f"{base}/tg/"}}})
    return True, url


class Command(BaseCommand):
    help = "Telegram bot holatini tekshiradi (--fix — webhook va menyuni qayta o'rnatadi)"

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true")
        parser.add_argument("--slug", default=None)
        parser.add_argument("--drop", action="store_true", help="Telegram'da to'planib qolgan eski xabarlarni tashlab yuborish")

    def handle(self, *args, **o):
        rows = targets(o["slug"])
        if not rows:
            self.stdout.write("   Telegram: bot tokeni topilmadi (.env TELEGRAM_BOT_TOKEN yoki panel → Telegram bot)")
            return
        for t, tok, src in rows:
            me = tg(tok, "getMe")
            if not me.get("ok"):
                self.stdout.write(self.style.ERROR(f"   {t.name}: token ishlamayapti ({src}): {me.get('description')}"))
                continue
            name = "@" + me["result"].get("username", "?")
            remember_username(t, me["result"].get("username") or "")
            info = (tg(tok, "getWebhookInfo").get("result") or {})
            want = f"{base_url(t)}/api/v1/telegram/webhook"
            err = info.get("last_error_message") or ""
            broken = info.get("url") != want or bool(err)
            if o["fix"] and broken:
                ok, msg = fix(t, tok, drop=o["drop"] or bool(err) or info.get("url") != want)
                if ok:
                    self.stdout.write(self.style.SUCCESS(f"   {t.name} {name}: webhook o'rnatildi → {msg}"))
                else:
                    self.stdout.write(self.style.ERROR(f"   {t.name} {name}: {msg}"))
                continue
            if o["fix"]:
                fix(t, tok, drop=o["drop"])      # menyu/buyruqlarni ham yangilab qo'yamiz
            state = "ishlayapti ✓" if not broken else ("webhook o'rnatilmagan" if not info.get("url") else f"muammo: {err or 'manzil boshqa: ' + info.get('url', '')}")
            self.stdout.write(f"   {t.name} {name} ({src}): {state}; kutayotgan xabarlar: {info.get('pending_update_count', 0)}")
