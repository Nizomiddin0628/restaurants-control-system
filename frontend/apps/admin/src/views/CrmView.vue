<script setup lang="ts">
/**
 * Mijozlar va bonus: umumiy ko'rinish (segmentlar, tug'ilgan kunlar), mijozlar bazasi va karta,
 * aksiyalar (foiz/summa, avtomatik yoki promokod), sozlamalar (keshbek, darajalar, sovg'alar).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, UiToggle, money, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

type Tab = 'overview' | 'customers' | 'promos' | 'settings'
const a = useAuth(), ui = useUi(), route = useRoute(), router = useRouter()
const tab = ref<Tab>((route.query.tab as Tab) || 'overview')
watch(tab, (v) => { router.replace({ query: { tab: v } }); loadTab() })
const canManage = computed(() => a.can('crm.manage'))
const stats = ref<any>(null)
const bdays = ref<any[]>([])
const SEG: Record<string, string> = { all: 'Hammasi', new: 'Yangi (30 kun)', regular: 'Doimiy (3+ xarid)', vip: 'Oltin', sleeping: 'Uxlab qolgan', birthday: "Tug'ilgan kuni yaqin", never: 'Hali xarid qilmagan' }
const SEG_HINT: Record<string, string> = { new: 'Birinchi taassurot — ikkinchi tashrifga taklif qiling', regular: "Eng qadrli mijozlar — ularni yo'qotmang", vip: 'Shaxsiy aksiya va e\'tibor', sleeping: 'Qaytarish uchun maxsus chegirma yuboring', birthday: 'Tabrik va sovg\'a — sadoqatni oshiradi', never: 'Ro\'yxatdan o\'tgan, lekin hali xarid qilmagan' }
const LVL_TONE: Record<string, any> = { basic: 'neutral', silver: 'info', gold: 'warn' }

async function loadStats() { stats.value = await api.get('/crm/stats') }
async function loadTab() {
  if (tab.value === 'overview') { await loadStats(); bdays.value = await api.get('/crm/birthdays', { days: 14 }) }
  if (tab.value === 'customers') loadCustomers()
  if (tab.value === 'promos') loadPromos()
  if (tab.value === 'settings') cfg.value = await api.get('/crm/settings')
}
onMounted(async () => { await loadStats(); await loadTab() })

// ---------------- segmentga xabar
const msg = ref<{ seg: string; text: string } | null>(null)
const sending = ref(false)
async function sendMsg() {
  if (!msg.value) return
  sending.value = true
  try {
    const r = await api.post(`/crm/segments/${msg.value.seg}/message`, { text: msg.value.text })
    toast(`Yuborildi: ${r.sent} · botda yo'q: ${r.no_bot}` + (r.failed ? ` · xato: ${r.failed}` : ''))
    msg.value = null
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { sending.value = false }
}
async function runBdays() { const r = await api.post('/crm/birthdays/run'); toast(r.greeted ? `${r.greeted} kishi tabriklandi 🎂` : 'Bugun tabriklanadigan yangi mijoz yo\'q'); bdays.value = await api.get('/crm/birthdays', { days: 14 }) }

// ---------------- mijozlar
const list = ref<any>({ total: 0, items: [] })
const q = ref(''), seg = ref('all'), sort = ref('recent')
async function loadCustomers() { list.value = await api.get('/crm/customers', { q: q.value, segment: seg.value, sort: sort.value }) }
watch([seg, sort], () => tab.value === 'customers' && loadCustomers())
function openSeg(s: string) { seg.value = s; tab.value = 'customers' }
async function syncOrders() {
  const r = await api.post('/crm/sync'); toast(`Yangi kartalar: ${r.created} · jami ${r.total}`); loadCustomers(); loadStats()
}

const card = ref<any>(null)
const edit = ref<any>(null)
const bonus = ref({ amount: 0, note: '' })
async function openCard(c: any) { card.value = await api.get(`/crm/customers/${c.id}`); edit.value = null; bonus.value = { amount: 0, note: '' } }
function startEdit(c: any | null) {
  edit.value = c ? { id: c.id, phone: c.phone, name: c.name, birthday: c.birthday || '', gender: c.gender || '', note: c.note, tags: (c.tags || []).join(', '), marketing_ok: c.marketing_ok }
    : { id: null, phone: '+998 ', name: '', birthday: '', gender: '', note: '', tags: '', marketing_ok: true }
  if (!c) card.value = { _new: true }
}
async function saveEdit() {
  const e = edit.value
  const body = { ...e, birthday: e.birthday || null, tags: e.tags.split(',').map((x: string) => x.trim()).filter(Boolean) }
  try {
    const r = e.id ? await api.put(`/crm/customers/${e.id}`, body) : await api.post('/crm/customers', body)
    toast('Saqlandi'); await openCard(r); loadCustomers()
  } catch (er: any) { toast(er.detail ?? 'Xato', 'danger') }
}
async function giveBonus(sign: number) {
  try {
    await api.post(`/crm/customers/${card.value.id}/bonus`, { amount: sign * Math.abs(Number(bonus.value.amount) || 0), note: bonus.value.note })
    toast(sign > 0 ? 'Bonus qo\'shildi' : 'Bonus ayirildi'); await openCard(card.value); loadCustomers()
  } catch (er: any) { toast(er.detail ?? 'Xato', 'danger') }
}

// ---------------- aksiyalar
const promos = ref<any[]>([])
const cats = ref<any[]>([])
const pe = ref<any>(null)
const WD = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']
const AUD = [{ value: 'all', label: 'Hamma' }, { value: 'new', label: 'Yangi mijozlar (birinchi xarid)' }, { value: 'birthday', label: "Tug'ilgan kuni yaqin" }, { value: 'silver', label: 'Kumush va Oltin' }, { value: 'gold', label: 'Faqat Oltin' }]
async function loadPromos() { promos.value = await api.get('/crm/promos'); if (!cats.value.length) cats.value = await api.get('/catalog/categories').catch(() => []) }
function newPromo() { pe.value = { id: null, name: '', description: '', kind: 'percent', value: 10, max_discount: 0, code: '', audience: 'all', min_order: 0, starts_on: '', ends_on: '', weekdays: [], hour_from: '', hour_to: '', category_ids: [], product_ids: [], max_uses: 0, is_active: true, _auto: true } }
function editPromo(p: any) { pe.value = { ...p, starts_on: p.starts_on || '', ends_on: p.ends_on || '', hour_from: p.hour_from ?? '', hour_to: p.hour_to ?? '', _auto: !p.code } }
function toggleWd(d: number) { const w = pe.value.weekdays; const i = w.indexOf(d); i >= 0 ? w.splice(i, 1) : w.push(d) }
function toggleCat(id: number) { const w = pe.value.category_ids; const i = w.indexOf(id); i >= 0 ? w.splice(i, 1) : w.push(id) }
async function savePromo() {
  const p = pe.value
  const num = (v: any) => (v === '' || v === null ? null : Number(v))
  const body = { ...p, code: p._auto ? '' : p.code, value: Number(p.value) || 0, max_discount: Number(p.max_discount) || 0, min_order: Number(p.min_order) || 0,
    max_uses: Number(p.max_uses) || 0, starts_on: p.starts_on || null, ends_on: p.ends_on || null, hour_from: num(p.hour_from), hour_to: num(p.hour_to) }
  try { p.id ? await api.put(`/crm/promos/${p.id}`, body) : await api.post('/crm/promos', body); pe.value = null; toast('Aksiya saqlandi'); loadPromos() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delPromo(p: any) {
  if (!confirm(`«${p.name}» o'chirilsinmi?`)) return
  const r = await api.del(`/crm/promos/${p.id}`); toast(r.archived ? 'Ishlatilgan aksiya — arxivga o\'tkazildi' : 'O\'chirildi'); pe.value = null; loadPromos()
}
async function togglePromo(p: any) { await api.put(`/crm/promos/${p.id}`, { ...p, is_active: !p.is_active }); loadPromos() }
function promoRule(p: any) {
  const r: string[] = []
  r.push(p.kind === 'percent' ? `−${p.value}%` + (p.max_discount ? ` (≤ ${money(p.max_discount)})` : '') : `−${money(p.value)} so'm`)
  if (p.hour_from !== null && p.hour_from !== undefined && p.hour_to !== null) r.push(`${String(p.hour_from).padStart(2, '0')}:00–${String(p.hour_to).padStart(2, '0')}:00`)
  if (p.weekdays?.length && p.weekdays.length < 7) r.push(p.weekdays.map((d: number) => WD[d]).join(', '))
  if (p.min_order) r.push(`${money(p.min_order)} dan`)
  if (p.audience !== 'all') r.push(p.audience_label)
  if (p.category_ids?.length) r.push(p.category_ids.map((id: number) => t(cats.value.find((c: any) => c.id === id)?.name, ui.lang)).filter(Boolean).join(', ') || 'tanlangan taomlar')
  if (p.ends_on) r.push(`${when(p.ends_on)} gacha`)
  return r.join(' · ')
}

// ---------------- sozlamalar
const cfg = ref<any>(null)
async function saveCfg() {
  const c = { ...cfg.value }
  for (const k of ['cashback_percent', 'silver_from', 'silver_percent', 'gold_from', 'gold_percent', 'max_pay_percent', 'welcome_bonus', 'birthday_bonus', 'birthday_window', 'sleeping_days']) c[k] = Number(c[k]) || 0
  try { cfg.value = await api.put('/crm/settings', c); toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

const p2 = (n: number) => String(n).padStart(2, '0')
const when = (v?: string | null) => { if (!v) return '—'; const d = new Date(v); return `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.${d.getFullYear()}` }
const ago = (v?: string | null) => { if (!v) return 'hali yo\'q'; const d = Math.floor((Date.now() - new Date(v).getTime()) / 864e5); return d <= 0 ? 'bugun' : d === 1 ? 'kecha' : `${d} kun oldin` }
const bdLabel = (d: number) => (d === 0 ? 'Bugun 🎂' : d === 1 ? 'Ertaga' : `${d} kundan keyin`)
</script>

<template>
  <div class="crm">
    <div v-if="stats" class="kpis">
      <div class="k"><b>{{ stats.customers }}</b><span>Mijoz bazasi</span><small>+{{ stats.new_30d }} 30 kunda</small></div>
      <div class="k"><b>{{ stats.returning_rate }}%</b><span>Qaytib keladi</span><small>2+ marta xarid qilgan</small></div>
      <div class="k"><b>{{ stats.identified_share }}%</b><span>Cheklarda telefon</span><small>30 kun · qancha ko'p — shuncha yaxshi</small></div>
      <div class="k"><b>{{ money(stats.avg_check_customer) }}</b><span>Mijoz o'rtacha cheki</span><small>umumiy: {{ money(stats.avg_check_all) }}</small></div>
      <div class="k"><b>{{ money(stats.bonus_liability) }}</b><span>Mijozlardagi bonus</span><small>+{{ money(stats.bonus_earned_30d) }} / −{{ money(stats.bonus_spent_30d) }} (30 kun)</small></div>
    </div>

    <nav class="tabs">
      <button :class="{ on: tab === 'overview' }" @click="tab = 'overview'"><UiIcon name="chart" :size="15" /> Umumiy</button>
      <button :class="{ on: tab === 'customers' }" @click="tab = 'customers'"><UiIcon name="users" :size="15" /> Mijozlar</button>
      <button :class="{ on: tab === 'promos' }" @click="tab = 'promos'"><UiIcon name="gift" :size="15" /> Aksiyalar</button>
      <button :class="{ on: tab === 'settings' }" @click="tab = 'settings'"><UiIcon name="sliders" :size="15" /> Bonus qoidalari</button>
    </nav>

    <!-- UMUMIY -->
    <div v-if="tab === 'overview' && stats" class="two">
      <UiCard title="Mijoz guruhlari" subtitle="Har bir guruhga alohida yondashuv — bosing va ro'yxatni ko'ring">
        <div class="segs">
          <div v-for="(label, k) in SEG" v-show="k !== 'all'" :key="k" class="seg">
            <button type="button" class="sb" @click="openSeg(String(k))"><b>{{ stats.segments[k] }}</b><span>{{ label }}</span><small>{{ SEG_HINT[k] }}</small></button>
            <button v-if="a.can('crm.message') && stats.segments[k]" type="button" class="sm" title="Telegram orqali xabar" @click="msg = { seg: String(k), text: '' }"><UiIcon name="send" :size="14" /></button>
          </div>
        </div>
        <div class="lvls">
          <span><UiChip tone="info">Kumush</UiChip> {{ stats.levels.silver }} kishi</span>
          <span><UiChip tone="warn">Oltin</UiChip> {{ stats.levels.gold }} kishi</span>
          <span class="mut">· faol aksiyalar: {{ stats.promos_active }}</span>
        </div>
      </UiCard>
      <UiCard title="Tug'ilgan kunlar" subtitle="Keyingi 14 kun. Kuni kelganda bonus va tabrik avtomatik ketadi">
        <template #actions><UiButton v-if="canManage" size="s" variant="secondary" @click="runBdays">Bugungilarni tabriklash</UiButton></template>
        <div v-for="c in bdays" :key="c.id" class="bd" @click="tab = 'customers'; openCard(c)">
          <UiAvatar :name="c.name || c.phone" :size="36" />
          <span class="nm"><b>{{ c.name || c.phone }}</b><small>{{ c.phone }} · {{ c.age }} yosh</small></span>
          <UiChip :tone="c.in_days === 0 ? 'accent' : 'neutral'">{{ bdLabel(c.in_days) }}</UiChip>
          <UiChip v-if="c.greeted" tone="ok">tabriklandi</UiChip>
        </div>
        <UiEmpty v-if="!bdays.length" title="Yaqin kunlarda tug'ilgan kun yo'q" text="Mijoz tug'ilgan kunini botda yoki kartasida kiritadi." />
      </UiCard>
    </div>

    <!-- MIJOZLAR -->
    <UiCard v-else-if="tab === 'customers'" :padded="false" :title="`Mijozlar · ${list.total}`" subtitle="Kassada telefon kiritilsa — karta o'zi ochiladi va bonus yig'iladi">
      <template #actions>
        <UiButton v-if="canManage" size="s" variant="ghost" @click="syncOrders">Eski cheklardan yig'ish</UiButton>
        <UiButton v-if="canManage" size="s" @click="startEdit(null)"><UiIcon name="plus" :size="14" /> Mijoz</UiButton>
      </template>
      <div class="bar">
        <input v-model="q" class="in" placeholder="Ism yoki telefon" @keydown.enter="loadCustomers" @input="q.length === 0 && loadCustomers()" />
        <UiSelect v-model="seg" :options="Object.entries(SEG).map(([value, label]) => ({ value, label }))" />
        <UiSelect v-model="sort" :options="[{ value: 'recent', label: 'Oxirgi kelgan' }, { value: 'spent', label: 'Eng ko\'p xarid' }, { value: 'orders', label: 'Eng ko\'p tashrif' }, { value: 'balance', label: 'Bonusi ko\'p' }, { value: 'new', label: 'Yangi qo\'shilgan' }]" />
      </div>
      <div class="cl">
        <button v-for="c in list.items" :key="c.id" type="button" class="cr" @click="openCard(c)">
          <UiAvatar :name="c.name || c.phone" :size="36" />
          <span class="nm"><b>{{ c.name || 'Ismsiz' }} <span v-if="c.birthday_soon" title="Tug'ilgan kuni yaqin">🎂</span></b><small>{{ c.phone }}</small></span>
          <UiChip :tone="LVL_TONE[c.level.code]">{{ c.level.name }}</UiChip>
          <span class="n"><b>{{ c.orders_count }}</b><small>tashrif</small></span>
          <span class="n"><b>{{ money(c.spent_total) }}</b><small>jami xarid</small></span>
          <span class="n bonus"><b>{{ money(c.balance) }}</b><small>bonus</small></span>
          <span class="ls">{{ ago(c.last_order_at) }}</span>
        </button>
        <UiEmpty v-if="!list.items.length" title="Mijoz topilmadi" text="Kassada mijoz telefonini kiriting yoki «Eski cheklardan yig'ish»ni bosing." />
      </div>
    </UiCard>

    <!-- AKSIYALAR -->
    <div v-else-if="tab === 'promos'" class="pl">
      <div class="phd"><p class="mut">Kassada avtomatik qo'llanadi — bir chekka eng foydali bitta aksiya. Promokodli aksiya faqat kod aytilganda ishlaydi.</p>
        <UiButton v-if="canManage" @click="newPromo"><UiIcon name="plus" :size="14" /> Yangi aksiya</UiButton></div>
      <div class="pgrid">
        <div v-for="p in promos" :key="p.id" class="pc" :class="{ off: !p.is_active || p.expired }">
          <div class="pt"><b>{{ p.name }}</b><UiChip v-if="p.code" tone="accent">{{ p.code }}</UiChip><UiChip v-else tone="info">avtomatik</UiChip>
            <UiChip v-if="p.expired" tone="danger">muddati o'tgan</UiChip><UiChip v-else-if="!p.is_active">o'chiq</UiChip></div>
          <p v-if="p.description" class="pd">{{ p.description }}</p>
          <p class="pr">{{ promoRule(p) }}</p>
          <div class="pn"><span><b>{{ p.used_count }}</b>{{ p.max_uses ? ' / ' + p.max_uses : '' }} marta</span><span>chegirma <b>{{ money(p.discount_total) }}</b></span><span>savdo <b>{{ money(p.revenue_total) }}</b></span></div>
          <div v-if="canManage" class="row"><UiToggle :model-value="p.is_active" label="Faol" @update:model-value="togglePromo(p)" /><span class="sp"></span><UiButton size="s" variant="secondary" @click="editPromo(p)"><UiIcon name="edit" :size="14" /> O'zgartirish</UiButton></div>
        </div>
      </div>
      <UiEmpty v-if="!promos.length" title="Hali aksiya yo'q" text="Masalan: «Happy hour 15:00–17:00 −15%» yoki «Birinchi buyurtma −10 000»." />
    </div>

    <!-- SOZLAMALAR -->
    <div v-else-if="tab === 'settings' && cfg" class="two">
      <UiCard title="Keshbek va darajalar" subtitle="Mijoz qancha ko'p xarid qilsa — shuncha ko'p qaytadi">
        <div class="lv"><UiChip>Oddiy</UiChip><span>boshlang'ich</span><UiInput v-model="cfg.cashback_percent" type="number" suffix="%" /></div>
        <div class="lv"><UiChip tone="info">Kumush</UiChip><UiInput v-model="cfg.silver_from" type="number" suffix="so'm dan" /><UiInput v-model="cfg.silver_percent" type="number" suffix="%" /></div>
        <div class="lv"><UiChip tone="warn">Oltin</UiChip><UiInput v-model="cfg.gold_from" type="number" suffix="so'm dan" /><UiInput v-model="cfg.gold_percent" type="number" suffix="%" /></div>
        <UiInput v-model="cfg.max_pay_percent" type="number" label="Chekning necha foizini bonus bilan to'lash mumkin" suffix="%" hint="Masalan 50% — 100 000 so'mlik chekning 50 000 si bonus bilan" />
        <p class="tip">Misol: Oddiy mijoz 100 000 so'm to'lasa, {{ money(100000 * (Number(cfg.cashback_percent) || 0) / 100) }} so'm bonus oladi. Keshbek faqat pul bilan to'langan qismidan hisoblanadi.</p>
      </UiCard>
      <UiCard title="Sovg'alar va xabarlar">
        <UiInput v-model="cfg.welcome_bonus" type="number" label="Yangi mijozga sovg'a (birinchi marta telefon kiritilganda)" suffix="so'm" />
        <UiInput v-model="cfg.birthday_bonus" type="number" label="Tug'ilgan kun sovg'asi" suffix="so'm" />
        <label class="fld"><span>Tug'ilgan kun tabrigi</span><textarea v-model="cfg.birthday_text" rows="3"></textarea><small>{name} — mijoz ismi, {bonus} — sovg'a summasi</small></label>
        <div class="g2"><UiInput v-model="cfg.birthday_window" type="number" label="Tug'ilgan kun aksiyasi (± kun)" suffix="kun" /><UiInput v-model="cfg.sleeping_days" type="number" label="«Uxlab qolgan» — necha kun kelmasa" suffix="kun" /></div>
        <UiToggle v-model="cfg.notify_bonus" label="Bonus qo'shilganda mijozga Telegram'da xabar" />
        <div v-if="canManage"><UiButton variant="brand" @click="saveCfg">Saqlash</UiButton></div>
      </UiCard>
    </div>

    <!-- MIJOZ KARTASI -->
    <UiDrawer :open="!!card" :title="card?._new ? 'Yangi mijoz' : (card?.name || card?.phone || '')" width="560px" @close="card = null; edit = null">
      <template v-if="edit">
        <UiInput v-model="edit.phone" label="Telefon" />
        <UiInput v-model="edit.name" label="Ism" />
        <div class="g2"><UiInput v-model="edit.birthday" type="date" label="Tug'ilgan kun" />
          <UiSelect v-model="edit.gender" label="Jinsi" :options="[{ value: '', label: '—' }, { value: 'm', label: 'Erkak' }, { value: 'f', label: 'Ayol' }]" /></div>
        <UiInput v-model="edit.tags" label="Belgilar (vergul bilan)" placeholder="ofis, vegetarian, katta oila" />
        <UiInput v-model="edit.note" label="Izoh" placeholder="Masalan: achchiq yemaydi" />
        <UiToggle v-model="edit.marketing_ok" label="Aksiya xabarlarini oladi" />
        <div class="row"><UiButton variant="brand" @click="saveEdit">Saqlash</UiButton><UiButton variant="ghost" @click="edit = null; card?._new && (card = null)">Bekor</UiButton></div>
      </template>
      <template v-else-if="card && !card._new">
        <div class="ch">
          <UiAvatar :name="card.name || card.phone" :size="56" />
          <div><b class="cn">{{ card.name || 'Ismsiz' }}</b><div class="mut">{{ card.phone }}<template v-if="card.birthday"> · 🎂 {{ when(card.birthday) }}</template></div>
            <div class="chips"><UiChip :tone="LVL_TONE[card.level.code]">{{ card.level.name }} · {{ card.level.percent }}%</UiChip><UiChip v-for="tg in card.tags" :key="tg">{{ tg }}</UiChip><UiChip v-if="!card.marketing_ok" tone="danger">reklama rad</UiChip></div></div>
          <span class="sp"></span><UiButton v-if="canManage" size="s" variant="secondary" @click="startEdit(card)"><UiIcon name="edit" :size="14" /></UiButton>
        </div>
        <div class="cst">
          <div><b>{{ money(card.balance) }}</b><span>bonus</span></div>
          <div><b>{{ card.orders_count }}</b><span>tashrif</span></div>
          <div><b>{{ money(card.spent_total) }}</b><span>jami</span></div>
          <div><b>{{ money(card.avg_check) }}</b><span>o'rtacha chek</span></div>
        </div>
        <p v-if="card.level.next" class="tip">{{ card.level.next }} darajagacha: <b>{{ money(card.level.next_left) }} so'm</b> xarid</p>
        <p v-if="card.note" class="note">📝 {{ card.note }}</p>
        <div v-if="card.favorites.length"><b class="lbl">Sevimli taomlari</b><div class="chips"><UiChip v-for="f in card.favorites" :key="f.name">{{ f.name }} × {{ f.qty }}</UiChip></div></div>
        <div v-if="a.can('crm.bonus')" class="adj">
          <b class="lbl">Bonusni qo'lda o'zgartirish</b>
          <div class="row"><input v-model="bonus.amount" class="in n" type="number" min="0" step="1000" placeholder="Summa" /><input v-model="bonus.note" class="in" placeholder="Sababi (majburiy)" /></div>
          <div class="row"><UiButton size="s" @click="giveBonus(1)">+ Qo'shish</UiButton><UiButton size="s" variant="ghost" @click="giveBonus(-1)">− Ayirish</UiButton></div>
        </div>
        <b class="lbl">Bonus tarixi</b>
        <div class="tx">
          <div v-for="x in card.txns" :key="x.id" class="txr"><span><b>{{ x.kind_label }}</b><small>{{ x.note }}<template v-if="x.by"> · {{ x.by }}</template></small></span><span class="ls">{{ when(x.created_at) }}</span><b :class="x.amount > 0 ? 'pos' : 'neg'">{{ x.amount > 0 ? '+' : '' }}{{ money(x.amount) }}</b></div>
          <p v-if="!card.txns.length" class="mut">Hali harakat yo'q</p>
        </div>
        <b class="lbl">Oxirgi buyurtmalar</b>
        <div class="tx">
          <div v-for="o in card.orders" :key="o.id" class="txr"><span><b>#{{ o.number }}</b><small>{{ ({ pos: 'kassa', telegram: 'Telegram', site: 'sayt' } as any)[o.source] || o.source }}</small></span><span class="ls">{{ when(o.created_at) }}</span><b :class="{ neg: o.status === 'cancelled' }">{{ money(o.total) }}</b></div>
          <p v-if="!card.orders.length" class="mut">Buyurtma yo'q</p>
        </div>
      </template>
    </UiDrawer>

    <!-- AKSIYA MUHARRIRI -->
    <UiDrawer :open="!!pe" :title="pe?.id ? 'Aksiyani o\'zgartirish' : 'Yangi aksiya'" width="560px" @close="pe = null">
      <template v-if="pe">
        <UiInput v-model="pe.name" label="Nomi" placeholder="Happy hour −15%" />
        <UiInput v-model="pe.description" label="Qisqa izoh (mijozga ko'rinadi)" />
        <div class="seg2"><button type="button" :class="{ on: pe.kind === 'percent' }" @click="pe.kind = 'percent'">Foiz %</button><button type="button" :class="{ on: pe.kind === 'fixed' }" @click="pe.kind = 'fixed'">Summa so'm</button></div>
        <div class="g2"><UiInput v-model="pe.value" type="number" :label="pe.kind === 'percent' ? 'Chegirma' : 'Chegirma summasi'" :suffix="pe.kind === 'percent' ? '%' : 'so\'m'" />
          <UiInput v-if="pe.kind === 'percent'" v-model="pe.max_discount" type="number" label="Eng ko'p (0 — cheksiz)" suffix="so'm" />
          <UiInput v-else v-model="pe.min_order" type="number" label="Eng kam chek" suffix="so'm" /></div>
        <div class="seg2"><button type="button" :class="{ on: pe._auto }" @click="pe._auto = true">Avtomatik</button><button type="button" :class="{ on: !pe._auto }" @click="pe._auto = false">Promokod bilan</button></div>
        <UiInput v-if="!pe._auto" v-model="pe.code" label="Promokod" placeholder="LAZZAT10" hint="Mijoz kassada aytadi yoki kassir kiritadi" />
        <UiSelect v-model="pe.audience" label="Kimga" :options="AUD" />
        <b class="lbl">Qachon</b>
        <div class="g2"><UiInput v-model="pe.starts_on" type="date" label="Boshlanishi" /><UiInput v-model="pe.ends_on" type="date" label="Tugashi" /></div>
        <div class="wd"><button v-for="(d, i) in WD" :key="i" type="button" :class="{ on: pe.weekdays.includes(i) }" @click="toggleWd(i)">{{ d }}</button><small>bo'sh — har kuni</small></div>
        <div class="g2"><UiInput v-model="pe.hour_from" type="number" label="Soat (dan)" placeholder="15" /><UiInput v-model="pe.hour_to" type="number" label="Soat (gacha)" placeholder="17" /></div>
        <b class="lbl">Qaysi taomlarga</b>
        <div class="wd cats"><button v-for="c in cats" :key="c.id" type="button" :class="{ on: pe.category_ids.includes(c.id) }" @click="toggleCat(c.id)">{{ t(c.name, ui.lang) }}</button><small>bo'sh — butun menyu</small></div>
        <div class="g2"><UiInput v-if="pe.kind === 'percent'" v-model="pe.min_order" type="number" label="Eng kam chek" suffix="so'm" /><UiInput v-model="pe.max_uses" type="number" label="Necha marta (0 — cheksiz)" /></div>
      </template>
      <template #footer>
        <UiButton v-if="pe?.id" variant="ghost" @click="delPromo(pe)"><UiIcon name="trash" :size="14" /></UiButton><span class="sp"></span>
        <UiButton variant="ghost" @click="pe = null">Bekor</UiButton><UiButton variant="brand" @click="savePromo">Saqlash</UiButton>
      </template>
    </UiDrawer>

    <!-- SEGMENTGA XABAR -->
    <UiDrawer :open="!!msg" :title="`Xabar: ${msg ? SEG[msg.seg] : ''}`" width="480px" @close="msg = null">
      <template v-if="msg">
        <p class="mut">{{ stats?.segments[msg.seg] }} mijoz. Xabar Telegram bot orqali faqat botga telefon ulashgan va reklamani rad etmaganlarga boradi.</p>
        <label class="fld"><span>Matn</span><textarea v-model="msg.text" rows="6" :placeholder="msg.seg === 'sleeping' ? 'Sizni sog\'indik! 🙂 Shu hafta −20% promokod: QAYT20' : 'Matn...'"></textarea></label>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="msg = null">Bekor</UiButton><UiButton variant="brand" :loading="sending" :disabled="!msg?.text.trim()" @click="sendMsg"><UiIcon name="send" :size="14" /> Yuborish</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.crm { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.k { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 14px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.k b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.k span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .k small { font-size: var(--fs-xs); color: var(--muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 10px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.two { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.segs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.seg { position: relative; }
.sb { width: 100%; text-align: left; border: 1px solid var(--line); background: var(--surface-2); border-radius: var(--radius-l); padding: 12px 14px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; font: inherit; color: var(--ink); }
.sb:hover { border-color: var(--accent); }
.sb b { font-family: var(--font-display); font-size: var(--fs-xl); } .sb span { font-weight: 700; font-size: var(--fs-s); } .sb small { color: var(--muted); font-size: var(--fs-xs); padding-right: 28px; }
.sm { position: absolute; top: 10px; right: 10px; width: 30px; height: 30px; border-radius: 50%; border: 1px solid var(--line); background: var(--surface); color: var(--accent); cursor: pointer; display: grid; place-items: center; }
.lvls { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; font-size: var(--fs-s); }
.mut { color: var(--muted); font-size: var(--fs-s); margin: 0; }
.bd { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid var(--line-2); cursor: pointer; } .bd:first-child { border-top: 0; }
.nm { display: flex; flex-direction: column; min-width: 0; flex: 1; } .nm b { font-size: var(--fs-m); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .nm small { color: var(--muted); font-size: var(--fs-xs); }
.bar { display: flex; gap: 10px; padding: 12px 20px; flex-wrap: wrap; }
.in { flex: 1; min-width: 160px; min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); }
.in.n { flex: 0 0 130px; min-width: 0; }
.cl { display: flex; flex-direction: column; }
.cr { display: grid; grid-template-columns: 36px minmax(0, 1.5fr) 90px 80px 120px 100px 90px; gap: 12px; align-items: center; padding: 10px 20px; border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; color: var(--ink); text-align: left; cursor: pointer; }
.cr:hover { background: var(--surface-2); }
.n { display: flex; flex-direction: column; } .n b { font-size: var(--fs-m); white-space: nowrap; } .n small { color: var(--muted); font-size: var(--fs-xs); }
.bonus b { color: var(--accent); }
.ls { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; }
.pl { display: flex; flex-direction: column; gap: 12px; }
.phd { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
.pgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.pc { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.pc.off { opacity: .6; }
.pt { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; } .pt b { font-size: var(--fs-b); margin-right: 4px; }
.pd { margin: 0; color: var(--muted); font-size: var(--fs-s); } .pr { margin: 0; font-weight: 700; font-size: var(--fs-s); color: var(--accent); }
.pn { display: flex; gap: 12px; flex-wrap: wrap; font-size: var(--fs-xs); color: var(--muted); } .pn b { color: var(--ink); }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .sp { flex: 1; }
.lv { display: grid; grid-template-columns: 90px 1fr 110px; gap: 10px; align-items: center; } .lv > span { color: var(--muted); font-size: var(--fs-s); }
.tip { margin: 0; font-size: var(--fs-s); color: var(--muted); background: var(--surface-2); padding: 10px 12px; border-radius: var(--radius); }
.fld { display: flex; flex-direction: column; gap: 6px; } .fld span, .lbl { font-size: var(--fs-s); font-weight: 700; color: var(--muted); display: block; }
.fld small { font-size: var(--fs-xs); color: var(--muted); }
.fld textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); resize: vertical; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ch { display: flex; gap: 12px; align-items: flex-start; } .cn { font-size: var(--fs-l); }
.chips { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
.cst { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.cst div { background: var(--surface-2); border-radius: var(--radius); padding: 10px; display: flex; flex-direction: column; min-width: 0; }
.cst b { font-family: var(--font-display); font-size: var(--fs-b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .cst span { font-size: var(--fs-xs); color: var(--muted); }
.note { margin: 0; background: var(--warn-tint, #FFF6E0); padding: 8px 12px; border-radius: var(--radius); font-size: var(--fs-s); }
.adj { border: 1px dashed var(--line); border-radius: var(--radius); padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.tx { display: flex; flex-direction: column; }
.txr { display: grid; grid-template-columns: 1fr auto 90px; gap: 10px; align-items: center; padding: 8px 0; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.txr:first-child { border-top: 0; } .txr span { display: flex; flex-direction: column; min-width: 0; } .txr small { color: var(--muted); font-size: var(--fs-xs); }
.txr > b { text-align: right; } .pos { color: var(--ok); } .neg { color: var(--danger); }
.seg2 { display: flex; background: var(--surface-2); border-radius: var(--radius); padding: 4px; gap: 4px; }
.seg2 button { flex: 1; border: 0; background: transparent; padding: 9px; border-radius: 8px; font: inherit; font-weight: 700; color: var(--muted); cursor: pointer; }
.seg2 button.on { background: var(--surface); color: var(--ink); box-shadow: var(--shadow-s, 0 1px 3px rgba(0,0,0,.08)); }
.wd { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.wd button { min-width: 42px; height: 38px; padding: 0 10px; border: 1px solid var(--line); background: var(--surface); border-radius: 10px; font: inherit; font-weight: 700; cursor: pointer; color: var(--ink); }
.wd button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.wd small { color: var(--muted); font-size: var(--fs-xs); }
@media (max-width: 1100px) { .two { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .cr { grid-template-columns: 36px minmax(0, 1fr) auto 100px 90px; } .cr .n:nth-of-type(1), .cr .ls { display: none; } }
@media (max-width: 600px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } .k:last-child { grid-column: span 2; }
  .segs { grid-template-columns: 1fr; } .g2 { grid-template-columns: 1fr; }
  .cr { grid-template-columns: 36px minmax(0, 1fr) auto; padding: 10px 16px; row-gap: 4px; } .cr .n { display: none; } .cr .bonus { display: flex; grid-column: 2 / 4; flex-direction: row; gap: 6px; align-items: baseline; }
  .bar { padding: 12px 16px; } .cst { grid-template-columns: repeat(2, 1fr); } .lv { grid-template-columns: 70px 1fr 90px; }
}
</style>
