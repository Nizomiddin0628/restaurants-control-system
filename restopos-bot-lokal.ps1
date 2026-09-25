# RestoPOS — Botni kompyuterda ishga tushirish
# Ishga tushirish (ildiz papkada!):  PS C:\Users\xalil\Desktop\restaurants\restopos>
#   powershell -ExecutionPolicy Bypass -File .\restopos-bot-lokal.ps1
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$PWD\backend\manage.py") -or -not (Test-Path "$PWD\frontend\apps\admin")) {
  Write-Host "XATO: skriptni restopos ildiz papkasida ishga tushiring." -ForegroundColor Red
  exit 1
}
if (-not (Test-Path "$PWD\backend\modules\training\models.py")) {
  Write-Host "XATO: avval O'qitish moduli o'rnatilgan bo'lishi kerak (git pull qiling)." -ForegroundColor Red
  exit 1
}
$enc = New-Object Text.UTF8Encoding $false
function Put([string]$rel, [string]$text) {
  $path = Join-Path $PWD $rel
  $dir = Split-Path $path -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  [IO.File]::WriteAllText($path, $text.Replace("`r`n", "`n") + "`n", $enc)
  Write-Host ("  + " + $rel)
}

Put 'backend\integrations\telegram\api.py' @'
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
    process_update(tenant, upd, request.build_absolute_uri("/").rstrip("/"))
    return JsonResponse({"ok": True})


def process_update(tenant, upd: dict, base_url: str | None = None) -> None:
    """Bitta Telegram xabarini qayta ishlaydi — webhook ham, polling (telegram_polling) ham shuni chaqiradi."""

    if tenant.module_enabled("telegram"):
        try:
            from modules.telegram.services import handle_update
            if handle_update(tenant, upd, base_url):
                return
        except Exception:  # bot xatosi Telegram'ga 500 qaytarmasin (aks holda qayta-qayta yuboradi)
            log.exception("telegram bot handle_update xato")
            return

    msg = upd.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id:
        return
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
        return

    user = User.objects.filter(telegram_id=chat_id).first()
    if text.startswith("/start") or not user:
        send_message(chat_id, f"Salom! Bu <b>{tenant.name}</b> xodimlari uchun bot.\nTelefon raqamingizni ulashing:",
                     reply_markup=CONTACT_KEYBOARD)
        return

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
        return

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
        return

    send_message(chat_id, "Buyruqlar: /vazifalar · /keldim · /ketdim")
    return
'@

Put 'backend\modules\telegram\management\__init__.py' @'

'@

Put 'backend\modules\telegram\management\commands\__init__.py' @'

'@

Put 'backend\modules\telegram\management\commands\telegram_polling.py' @'
"""
Botni https'siz (o'z kompyuteringizda) ishga tushirish — Telegram'dan xabarlarni o'zi so'rab oladi:
    python manage.py telegram_polling              (standart: lazzat)
    python manage.py telegram_polling --slug chopar
To'xtatish: Ctrl+C. Serverga joylaganda buning o'rniga «Webhook o'rnatish» tugmasi ishlatiladi.
"""
import time

import requests
from django.core.management.base import BaseCommand
from django.db import connection

from public.models import Tenant

API = "https://api.telegram.org/bot{token}/{method}"


class Command(BaseCommand):
    help = "Telegram botni polling rejimida ishga tushiradi (lokal sinov uchun, https kerak emas)"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="lazzat")
        parser.add_argument("--base-url", default="", help="Mini App uchun sayt manzili (https bo'lsa)")

    def handle(self, *args, **opts):
        t = Tenant.objects.filter(slug=opts["slug"]).first()
        if t is None:
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        from integrations.telegram.api import process_update
        from modules.telegram import services
        tok = services.token(t)
        if not tok:
            self.stderr.write("Bot tokeni yo'q. Admin panel → Telegram bot → tokenni qo'ying va Saqlang.")
            return
        me = requests.get(API.format(token=tok, method="getMe"), timeout=15).json()
        if not me.get("ok"):
            self.stderr.write(f"Token noto'g'ri: {me.get('description')}")
            return
        requests.post(API.format(token=tok, method="deleteWebhook"), json={"drop_pending_updates": False}, timeout=15)
        self.stdout.write(self.style.SUCCESS(f"Bot ishlayapti: @{me['result']['username']}  ({t.name})"))
        self.stdout.write("Telegram'da botni oching va /start bosing. To'xtatish: Ctrl+C")
        offset = None
        while True:
            try:
                r = requests.get(API.format(token=tok, method="getUpdates"),
                                 params={"timeout": 25, "offset": offset, "allowed_updates": '["message","callback_query"]'}, timeout=40).json()
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.stderr.write(f"Tarmoq xatosi: {e} — 5 soniyadan keyin qayta urinaman")
                time.sleep(5)
                continue
            if not r.get("ok"):
                self.stderr.write(f"Telegram xato: {r.get('description')}")
                time.sleep(5)
                continue
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                t.refresh_from_db()
                connection.set_tenant(t)
                frm = ((upd.get("message") or {}).get("from") or {})
                self.stdout.write(f"← {frm.get('first_name', '')} (@{frm.get('username', '')}): {(upd.get('message') or {}).get('text', '[kontakt/boshqa]')}")
                try:
                    process_update(t, upd, opts["base_url"] or None)
                except Exception as e:
                    self.stderr.write(f"Xato: {e}")
                finally:
                    connection.set_schema_to_public()
'@

Put 'backend\tests\test_telegram.py' @'
"""
Telegram bot va Mini App: webhook siri, /start → mijoz, kontakt → telefon (xodim bo'lsa bog'lanadi),
bot orqali stol bron, Mini App buyurtmasi (imzo tekshiruvi, yetkazish narxi, eng kam summa) → kassa,
to'lov → mijoz statistikasi, ommaviy xabar sanog'i, modul o'chirilsa 404.
"""
import json
import os

import pytest
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}
TOKEN = "123456:TEST-token-for-hmac"
SECRET = "restopos"   # .env bo'lmasa standart sir


@pytest.fixture
def bot(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "telegram", "pos", "catalog", "tables", "reservations"}))
        tenant.settings = {**tenant.settings, "modules": {**(tenant.settings.get("modules") or {}),
                                                          "telegram": {"min_order": 20000, "delivery_fee": 9000, "free_delivery_from": 100000}}}
        tenant.save()
    with schema_context("lazzat"):
        from modules.catalog.models import Category, Product
        from modules.tables.models import Table
        from modules.telegram.models import BotUser, Broadcast
        BotUser.objects.all().delete(); Broadcast.objects.all().delete()
        cat, _ = Category.objects.get_or_create(name={"uz": "TG test", "ru": "", "en": ""})
        p, _ = Product.objects.get_or_create(name={"uz": "TG burger", "ru": "", "en": ""}, defaults={"category": cat, "price": 15000, "cost": 5000})
        Table.objects.get_or_create(number="T1", defaults={"seats": 6})
        yield {"product": p}


def _hook(client, update, secret=None):
    secret = secret or os.environ.get("TELEGRAM_WEBHOOK_SECRET", SECRET)
    return client.post("/api/v1/telegram/webhook", data=json.dumps(update), content_type="application/json",
                       HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret, **H)


def _msg(chat_id, text=None, contact=None, first="Ali"):
    m = {"message_id": 1, "chat": {"id": chat_id, "type": "private"}, "from": {"id": chat_id, "first_name": first}}
    if text is not None:
        m["text"] = text
    if contact:
        m["contact"] = contact
    return {"update_id": 1, "message": m}


@pytest.mark.django_db
def test_webhook_secret_and_start_creates_customer(client, bot):
    assert _hook(client, _msg(5001, "/start"), secret="wrong").status_code == 403
    assert _hook(client, _msg(5001, "/start")).status_code == 200
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        bu = BotUser.objects.get(chat_id=5001)
        assert bu.full_name == "Ali" and bu.phone == ""


@pytest.mark.django_db
def test_contact_saves_phone_and_links_staff(client, bot):
    _hook(client, _msg(5002, "/start"))
    _hook(client, _msg(5002, contact={"phone_number": "998901112233", "user_id": 5002}))
    _hook(client, _msg(5003, contact={"phone_number": "+998901234567", "user_id": 5003}))   # egasi (xodim)
    with schema_context("lazzat"):
        from core.models import User
        from modules.telegram.models import BotUser
        assert BotUser.objects.get(chat_id=5002).phone == "+998901112233"
        assert BotUser.objects.get(chat_id=5003).staff is not None
        assert User.objects.get(phone="+998901234567").telegram_id == 5003


@pytest.mark.django_db
def test_booking_via_bot(client, bot):
    _hook(client, _msg(5004, contact={"phone_number": "998901110099", "user_id": 5004}))
    _hook(client, _msg(5004, "📅 Stol bron qilish"))
    _hook(client, _msg(5004, "4"))
    _hook(client, _msg(5004, "Ertaga"))
    _hook(client, _msg(5004, "19:00"))
    with schema_context("lazzat"):
        from modules.reservations.models import Reservation
        r = Reservation.objects.filter(phone="+998901110099", source="telegram").first()
        assert r is not None and r.guests == 4 and r.table is not None


@pytest.mark.django_db
def test_miniapp_order_signed_and_rules(client, bot, tenant):
    from modules.telegram.services import sign_init_data
    with schema_context("public"):
        tenant.settings["modules"]["telegram"]["bot_token"] = TOKEN
        tenant.save()
    good = sign_init_data({"id": 7001, "first_name": "Vali"}, TOKEN)
    bad = sign_init_data({"id": 7001, "first_name": "Vali"}, "999:other-token")
    body = {"items": [{"product_id": bot["product"].pk, "qty": 2}], "type": "delivery", "phone": "901234000", "address": "Chilonzor 5-kvartal, 12-uy"}
    post = lambda d: client.post("/api/v1/bot/miniapp/order", data=json.dumps(d), content_type="application/json", **H)  # noqa: E731
    assert post({**body, "init_data": bad}).status_code == 403                                   # soxta imzo
    assert post({**body, "init_data": good, "items": [{"product_id": bot["product"].pk, "qty": 1}]}).status_code == 400   # 15 000 < 20 000
    r = post({**body, "init_data": good})
    assert r.status_code == 200, r.content
    assert r.json()["total"] == 30000 + 9000                                                   # yetkazish narxi qo'shildi
    with schema_context("lazzat"):
        from modules.pos.models import Order
        from modules.telegram.models import BotUser
        o = Order.objects.get(number=r.json()["number"])
        assert o.source == "telegram" and o.type == "delivery" and o.customer_phone == "+998901234000"
        assert BotUser.objects.get(chat_id=7001).phone == "+998901234000"


@pytest.mark.django_db
def test_paid_order_updates_customer_stats(api, bot):
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        BotUser.objects.create(chat_id=7002, phone="+998905556677")
    api.post("/api/v1/pos/shifts/open", {"cash_start": 0})
    r = api.post("/api/v1/pos/orders", {"items": [{"product_id": bot["product"].pk, "qty": 1}], "customer_phone": "+998905556677"})
    assert r.status_code == 200, r.content
    assert api.post(f"/api/v1/pos/orders/{r.json()['id']}/pay", {"payment_method": "cash"}).status_code == 200
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        bu = BotUser.objects.get(chat_id=7002)
        assert bu.orders_count == 1 and bu.spent_total == 15000


@pytest.mark.django_db
def test_broadcast_counts_and_stats(api, bot):
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        BotUser.objects.create(chat_id=8001, phone="+998900000001", orders_count=1)
        BotUser.objects.create(chat_id=8002)
    b = api.post("/api/v1/bot/broadcasts", {"text": "Bugun -20%!", "audience": "buyers"}).json()
    assert b["reach"] == 1
    r = api.post(f"/api/v1/bot/broadcasts/{b['id']}/send").json()
    assert r["status"] == "sent" and r["total"] == 1 and r["sent"] == 1
    assert api.post(f"/api/v1/bot/broadcasts/{b['id']}/send").status_code == 400                # ikki marta yuborilmaydi
    s = api.get("/api/v1/bot/stats").json()
    assert s["subscribers"] == 2 and s["buyers"] == 1 and s["conversion"] == 50.0


@pytest.mark.django_db
def test_settings_token_masked(api, bot):
    r = api.put("/api/v1/bot/settings", {"bot_token": "111:ABCDEFGH", "bot_username": "@lazzat_bot", "min_order": 0})
    assert r.status_code == 200 and "bot_token" not in r.json() and r.json()["bot_token_masked"].endswith("EFGH")
    assert r.json()["bot_username"] == "lazzat_bot"
    assert api.put("/api/v1/bot/settings", {"bot_token": "notatoken"}).status_code == 400


@pytest.mark.django_db
def test_module_disabled_404(api, tenant, bot):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "telegram"])
    assert api.get("/api/v1/bot/stats").status_code == 404
    with schema_context("public"):
        set_modules(tenant, [*tenant.enabled_modules, "telegram"])


@pytest.mark.django_db
def test_polling_command_handles_start(bot, tenant, monkeypatch):
    """Lokal rejim: telegram_polling getUpdates'dan /start oladi → mijoz yaratiladi va javob yuboriladi."""
    import requests as rq
    from django.core.management import call_command
    with schema_context("public"):
        tenant.settings["modules"]["telegram"]["bot_token"] = TOKEN
        tenant.save()
    sent, calls = [], {"n": 0}

    class R:
        def __init__(self, d): self.d = d
        def json(self): return self.d

    def fake_get(url, params=None, timeout=None):
        if url.endswith("getMe"):
            return R({"ok": True, "result": {"username": "lazzat_bot"}})
        calls["n"] += 1
        if calls["n"] == 1:
            return R({"ok": True, "result": [{"update_id": 10, **{k: v for k, v in _msg(9001, "/start").items() if k != "update_id"}}]})
        raise KeyboardInterrupt

    def fake_post(url, json=None, timeout=None):
        if url.endswith("sendMessage"):
            sent.append(json)
        return R({"ok": True})
    monkeypatch.setattr(rq, "get", fake_get)
    monkeypatch.setattr(rq, "post", fake_post)
    call_command("telegram_polling", "--slug", "lazzat")
    with schema_context("lazzat"):
        from modules.telegram.models import BotUser
        assert BotUser.objects.filter(chat_id=9001).exists()
    assert sent and sent[0]["chat_id"] == 9001
'@

Put 'frontend\apps\admin\src\views\TelegramView.vue' @'
<script setup lang="ts">
/**
 * Telegram bot: ulash (token → tekshirish → webhook → sinov), mijozlar, ommaviy xabar, statistika.
 * Har restoranning o'z boti. Token yo'q bo'lsa tizim ishlayveradi — xabarlar faqat logga yoziladi.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiEmpty, UiIcon, UiInput, UiSelect, UiToggle, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

type Tab = 'setup' | 'users' | 'broadcast'
const a = useAuth(), route = useRoute(), router = useRouter()
const tab = ref<Tab>((route.query.tab as Tab) || 'setup')
watch(tab, (v) => router.replace({ query: { tab: v } }))
const s = ref<any>(null)
const form = ref<any>(null)
const stats = ref<any>(null)
const info = ref<any>(null)
const busy = ref('')
const canManage = computed(() => a.can('telegram.manage'))
const canSend = computed(() => a.can('telegram.broadcast'))

async function load() {
  const [x, st] = await Promise.all([api.get('/bot/settings'), api.get('/bot/stats')])
  s.value = x; stats.value = st
  form.value = { ...x, bot_token: '' }
  if (x.has_token) info.value = await api.get('/bot/info')
}
onMounted(load)

async function save() {
  busy.value = 'save'
  try {
    const body = { ...form.value, delivery_fee: Number(form.value.delivery_fee) || 0, free_delivery_from: Number(form.value.free_delivery_from) || 0, min_order: Number(form.value.min_order) || 0 }
    if (!body.bot_token) delete body.bot_token
    s.value = await api.put('/bot/settings', body); form.value.bot_token = ''
    info.value = s.value.has_token ? await api.get('/bot/info') : null
    toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = '' }
}
async function removeToken() { if (!confirm('Bot tokeni o\'chirilsinmi? Bot javob berishni to\'xtatadi.')) return; s.value = await api.put('/bot/settings', { ...form.value, bot_token: '' }); info.value = null; toast('Token o\'chirildi') }
async function hook() { busy.value = 'hook'; try { await api.post('/bot/set-webhook'); await load(); toast('Webhook o\'rnatildi — bot endi javob beradi ✓') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = '' } }
const testChat = ref('')
async function test() { busy.value = 'test'; try { const r = await api.post('/bot/test', { chat_id: testChat.value }); toast(r.detail, r.ok ? 'ok' : 'danger') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = '' } }
const copy = (v: string) => { navigator.clipboard?.writeText(v); toast('Nusxalandi') }

// ---- mijozlar
const users = ref<any[]>([]), q = ref(''), uf = ref('all')
async function loadUsers() { users.value = await api.get('/bot/users', { q: q.value, filter: uf.value }) }
watch([tab, uf], () => { if (tab.value === 'users') loadUsers(); if (tab.value === 'broadcast') loadB() })

// ---- ommaviy xabar
const list = ref<any[]>([])
const b = ref({ text: '', audience: 'all', button_text: '', button_url: '' })
async function loadB() { list.value = await api.get('/bot/broadcasts') }
async function createB() {
  try { await api.post('/bot/broadcasts', b.value); b.value = { text: '', audience: 'all', button_text: '', button_url: '' }; await loadB(); toast('Qoralama saqlandi — endi «Yuborish»ni bosing') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function sendB(x: any) {
  if (!confirm(`${x.reach} kishiga yuborilsinmi? Qaytarib bo'lmaydi.`)) return
  busy.value = 'b' + x.id
  try { const r = await api.post(`/bot/broadcasts/${x.id}/send`); toast(`Yuborildi: ${r.sent} · xato: ${r.failed}`); await loadB(); stats.value = await api.get('/bot/stats') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = '' }
}
async function delB(x: any) { await api.del(`/bot/broadcasts/${x.id}`); await loadB() }
const AUD: Record<string, string> = { all: 'Hamma obunachilar', with_phone: 'Telefon ulaganlar', buyers: 'Xarid qilganlar' }
const when = (v?: string | null) => (v ? new Date(v).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—')
</script>

<template>
  <div v-if="s" class="tg">
    <div class="kpis">
      <div class="k"><b>{{ stats.subscribers }}</b><span>Obunachi</span><small>+{{ stats.new_week }} shu hafta</small></div>
      <div class="k"><b>{{ stats.with_phone }}</b><span>Telefon ulagan</span></div>
      <div class="k"><b>{{ stats.orders_today }}</b><span>Bugungi buyurtma</span><small>30 kunda {{ stats.orders_30d }}</small></div>
      <div class="k"><b>{{ money(stats.revenue_30d) }}</b><span>Botdan savdo (30 kun)</span></div>
      <div class="k"><b>{{ stats.conversion }}%</b><span>Konversiya</span><small>{{ stats.buyers }} xaridor</small></div>
    </div>

    <nav class="tabs">
      <button :class="{ on: tab === 'setup' }" @click="tab = 'setup'"><UiIcon name="sliders" :size="15" /> Ulash va sozlash</button>
      <button :class="{ on: tab === 'users' }" @click="tab = 'users'"><UiIcon name="users" :size="15" /> Mijozlar</button>
      <button :class="{ on: tab === 'broadcast' }" @click="tab = 'broadcast'"><UiIcon name="megaphone" :size="15" /> Ommaviy xabar</button>
    </nav>

    <!-- ULASH -->
    <div v-if="tab === 'setup'" class="two">
      <UiCard title="1. Botni ulash" subtitle="4 qadam — dasturchisiz">
        <ol class="steps">
          <li :class="{ ok: s.has_token }"><b>@BotFather</b> da <code>/newbot</code> buyrug'i bilan bot yarating va tokenni oling.</li>
          <li :class="{ ok: info?.ok }">Tokenni pastga qo'ying va <b>Saqlash</b>ni bosing.
            <span v-if="info?.ok" class="good">✓ Bot topildi: @{{ info.username }}</span>
            <span v-else-if="info && !info.ok" class="bad">{{ info.detail }}</span></li>
          <li :class="{ ok: s.webhook_set }"><b>Webhook o'rnatish</b> — Telegram xabarlarni shu saytga yuboradi.
            <span v-if="!s.https" class="warn">Serverga joylaganda (https) ishlaydi. <b>Hozir kompyuterda sinash:</b> ikkinchi terminalda <code>python manage.py telegram_polling</code> — bot shu zahoti javob bera boshlaydi.</span></li>
          <li><b>Sinov xabari</b> yuboring — xodimlar guruhiga yoki o'zingizga.</li>
        </ol>
        <template v-if="canManage">
          <UiInput v-model="form.bot_token" :label="s.has_token ? `Bot tokeni (saqlangan: ${s.bot_token_masked})` : 'Bot tokeni'" placeholder="123456789:AA..." hint="Token maxfiy — hech kimga bermang" />
          <div class="row">
            <UiButton variant="brand" :loading="busy === 'save'" @click="save">Saqlash</UiButton>
            <UiButton variant="secondary" :loading="busy === 'hook'" :disabled="!s.has_token" @click="hook">Webhook o'rnatish</UiButton>
            <UiButton v-if="s.has_token" variant="ghost" size="s" @click="removeToken">Tokenni o'chirish</UiButton>
          </div>
          <div class="row">
            <input v-model="testChat" class="in" placeholder="Chat ID (bo'sh — guruh yoki o'zingiz)" />
            <UiButton variant="secondary" :loading="busy === 'test'" @click="test"><UiIcon name="send" :size="14" /> Sinov xabari</UiButton>
          </div>
        </template>
        <div class="urls">
          <div><span>Mini App manzili</span><code>{{ s.miniapp_url }}</code><button type="button" @click="copy(s.miniapp_url)">Nusxa</button></div>
          <div><span>Webhook manzili</span><code>{{ s.webhook_url }}</code><button type="button" @click="copy(s.webhook_url)">Nusxa</button></div>
          <a :href="s.miniapp_url" target="_blank" rel="noopener" class="prev">👁 Mini App'ni brauzerda ko'rish</a>
        </div>
      </UiCard>

      <UiCard title="2. Bot sozlamalari" subtitle="Mijoz botda nimani ko'radi">
        <UiInput v-model="form.bot_username" label="Bot nomi" placeholder="lazzat_bot" />
        <label class="fld"><span>Salomlashish matni</span><textarea v-model="form.welcome_text" rows="3"></textarea></label>
        <UiInput v-model="form.notify_staff_chat_id" label="Xodimlar guruhi chat ID" placeholder="-1001234567890" hint="Guruhga botni qo'shing — yangi buyurtma va bronlar shu yerga keladi" />
        <b class="lbl">Buyurtma turlari</b>
        <div class="tg3"><UiToggle v-model="form.allow_delivery" label="Yetkazib berish" /><UiToggle v-model="form.allow_pickup" label="Olib ketish" /><UiToggle v-model="form.allow_dine_in" label="Zalda" /></div>
        <div class="g3">
          <UiInput v-model="form.delivery_fee" type="number" label="Yetkazish narxi" suffix="so'm" />
          <UiInput v-model="form.free_delivery_from" type="number" label="Bepul yetkazish (dan)" suffix="so'm" />
          <UiInput v-model="form.min_order" type="number" label="Eng kam buyurtma" suffix="so'm" />
        </div>
        <b class="lbl">Xabarlar</b>
        <UiToggle v-model="form.enable_booking" label="Botda stol bron qilish (Bron moduli yoqilgan bo'lsa)" />
        <UiToggle v-model="form.notify_paid" label="To'langanda mijozga rahmat va chek" />
        <UiToggle v-model="form.notify_ready" label="Buyurtma tayyor bo'lganda xabar" />
        <div v-if="canManage"><UiButton :loading="busy === 'save'" @click="save">Saqlash</UiButton></div>
      </UiCard>
    </div>

    <!-- MIJOZLAR -->
    <UiCard v-else-if="tab === 'users'" :padded="false" title="Bot mijozlari" subtitle="Botga yozgan har bir odam. Telefon ulasa — kassadagi buyurtmalari bog'lanadi.">
      <div class="bar">
        <input v-model="q" class="in" placeholder="Ism, telefon yoki @username" @keydown.enter="loadUsers" />
        <UiSelect v-model="uf" :options="[{ value: 'all', label: 'Hammasi' }, { value: 'with_phone', label: 'Telefon ulaganlar' }, { value: 'buyers', label: 'Xaridorlar' }, { value: 'blocked', label: 'Botni bloklaganlar' }]" />
      </div>
      <div class="ul">
        <div v-for="u in users" :key="u.id" class="ur">
          <span class="nm"><b>{{ u.full_name || 'Ismsiz' }}</b><small>{{ u.username ? '@' + u.username : '' }} {{ u.phone }}</small></span>
          <span class="chips"><UiChip v-if="u.is_staff" tone="accent">xodim</UiChip><UiChip v-if="u.is_blocked" tone="danger">bloklagan</UiChip></span>
          <span class="n"><b>{{ u.orders_count }}</b> buyurtma</span>
          <span class="n">{{ money(u.spent_total) }} so'm</span>
          <span class="ls">{{ when(u.last_seen_at) }}</span>
        </div>
        <UiEmpty v-if="!users.length" title="Hali mijoz yo'q" text="Bot ulangach, kim /start bossa — shu yerda paydo bo'ladi." />
      </div>
    </UiCard>

    <!-- OMMAVIY XABAR -->
    <div v-else class="two">
      <UiCard v-if="canSend" title="Yangi xabar" subtitle="Aksiya, yangi taom, bayram tabrigi — bir bosishda hammaga">
        <label class="fld"><span>Matn</span><textarea v-model="b.text" rows="6" placeholder="🔥 Bugun barcha burgerlarga −20%! Faqat 18:00 gacha."></textarea></label>
        <UiSelect v-model="b.audience" label="Kimga" :options="Object.entries(AUD).map(([value, label]) => ({ value, label }))" />
        <div class="g2"><UiInput v-model="b.button_text" label="Tugma matni (ixtiyoriy)" placeholder="Menyuni ochish" /><UiInput v-model="b.button_url" label="Tugma havolasi" placeholder="https://..." /></div>
        <p class="tip">Matnda <code>&lt;b&gt;qalin&lt;/b&gt;</code> va <code>&lt;i&gt;qiya&lt;/i&gt;</code> ishlaydi. Avval qoralama saqlanadi, keyin «Yuborish».</p>
        <div><UiButton variant="brand" @click="createB">Qoralama saqlash</UiButton></div>
      </UiCard>
      <UiCard title="Xabarlar tarixi">
        <div v-for="x in list" :key="x.id" class="bx">
          <p>{{ x.text }}</p>
          <div class="row">
            <UiChip :tone="x.status === 'sent' ? 'ok' : 'neutral'">{{ x.status === 'sent' ? 'Yuborildi' : 'Qoralama' }}</UiChip>
            <span class="ls">{{ AUD[x.audience] }} · {{ x.status === 'sent' ? `${x.sent}/${x.total} yetib bordi` + (x.failed ? ` · ${x.failed} xato` : '') + ` · ${when(x.sent_at)}` : `${x.reach} kishiga ketadi` }}</span>
            <span class="sp"></span>
            <template v-if="x.status !== 'sent' && canSend">
              <UiButton size="s" variant="ghost" @click="delB(x)"><UiIcon name="trash" :size="14" /></UiButton>
              <UiButton size="s" :loading="busy === 'b' + x.id" @click="sendB(x)"><UiIcon name="send" :size="14" /> Yuborish</UiButton>
            </template>
          </div>
        </div>
        <UiEmpty v-if="!list.length" title="Hali xabar yuborilmagan" />
      </UiCard>
    </div>
  </div>
</template>

<style scoped>
.tg { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.k { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 14px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.k b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.k span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .k small { font-size: var(--fs-xs); color: var(--muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 10px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.two { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.steps { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; font-size: var(--fs-m); }
.steps li { color: var(--ink-2); } .steps li.ok::marker { color: var(--ok); } .steps li.ok { color: var(--ink); }
.steps span { display: block; font-size: var(--fs-s); margin-top: 2px; }
.good { color: var(--ok); font-weight: 700; } .bad { color: var(--danger); font-weight: 700; } .warn { color: var(--warn-ink); }
code { background: var(--surface-3); padding: 1px 6px; border-radius: 6px; font-size: .92em; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .sp { flex: 1; }
.in { flex: 1; min-width: 180px; min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); }
.urls { display: flex; flex-direction: column; gap: 6px; padding: 12px; background: var(--surface-2); border-radius: var(--radius); font-size: var(--fs-s); }
.urls div { display: flex; align-items: center; gap: 8px; min-width: 0; } .urls span { color: var(--muted); width: 120px; flex-shrink: 0; }
.urls code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.urls button { border: 1px solid var(--line); background: var(--surface); border-radius: 8px; padding: 4px 10px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; }
.prev { color: var(--accent); font-weight: 700; text-decoration: none; }
.fld { display: flex; flex-direction: column; gap: 6px; } .fld span, .lbl { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fld textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); resize: vertical; }
.g3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; } .g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tg3 { display: flex; gap: 18px; flex-wrap: wrap; }
.tip { margin: 0; font-size: var(--fs-xs); color: var(--muted); }
.bar { display: flex; gap: 10px; padding: 12px 20px; flex-wrap: wrap; }
.ul { display: flex; flex-direction: column; }
.ur { display: grid; grid-template-columns: minmax(0, 1.6fr) auto 110px 130px 110px; gap: 12px; align-items: center; padding: 10px 20px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { font-size: var(--fs-m); } .nm small { color: var(--muted); }
.chips { display: flex; gap: 4px; } .n b { font-size: var(--fs-m); } .ls { font-size: var(--fs-xs); color: var(--muted); }
.bx { padding: 12px 0; border-top: 1px solid var(--line-2); display: flex; flex-direction: column; gap: 8px; }
.bx:first-child { border-top: 0; } .bx p { margin: 0; white-space: pre-line; }
@media (max-width: 1100px) { .two { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 600px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } .k:last-child { grid-column: span 2; } .g3, .g2 { grid-template-columns: 1fr; } .ur { grid-template-columns: 1fr auto; padding: 10px 16px; } .ur .n, .ur .ls { font-size: var(--fs-xs); } .bar { padding: 12px 16px; } .urls span { width: auto; } .urls div { flex-wrap: wrap; } }
</style>
'@

Write-Host ""
Write-Host "Tayyor: 6 ta fayl yangilandi." -ForegroundColor Green
