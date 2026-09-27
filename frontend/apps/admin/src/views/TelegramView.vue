<script setup lang="ts">
/**
 * Telegram bot: ulash (token → tekshirish → webhook → sinov), mijozlar, ommaviy xabar, statistika.
 * Har restoranning o'z boti. Token yo'q bo'lsa tizim ishlayveradi — xabarlar faqat logga yoziladi.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
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
    <div class="kpis k5">
      <button type="button" class="k kpi-click" :class="{ on: tab === 'users' }" @click="tab = 'users'"><b>{{ stats.subscribers }}</b><span>Obunachi</span><small>+{{ stats.new_week }} shu hafta</small></button>
      <button type="button" class="k kpi-click" @click="tab = 'users'"><b>{{ stats.with_phone }}</b><span>Telefon ulagan</span></button>
      <RouterLink to="/reports" class="k kpi-click"><b>{{ stats.orders_today }}</b><span>Bugungi buyurtma</span><small>30 kunda {{ stats.orders_30d }}</small></RouterLink>
      <RouterLink to="/reports" class="k kpi-click"><b>{{ money(stats.revenue_30d) }}</b><span>Botdan savdo (30 kun)</span></RouterLink>
      <button type="button" class="k kpi-click" @click="tab = 'users'"><b>{{ stats.conversion }}%</b><span>Konversiya</span><small>{{ stats.buyers }} xaridor</small></button>
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
/* 5 ta KPI planshetda: 3 + 2 (oxirgi ikkitasi kengroq) — bo'sh katak qolmaydi */
@media (min-width: 601px) and (max-width: 1100px) { .kpis.k5 { grid-template-columns: repeat(6, minmax(0, 1fr)) !important; } .kpis.k5 > * { grid-column: span 2; } .kpis.k5 > :nth-child(n+4) { grid-column: span 3; } }
</style>
