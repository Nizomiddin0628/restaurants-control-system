<script setup lang="ts">
/**
 * Bozorlik va bozor xarajatlari. Bozorchi telefondan ishlatadi:
 * avans oladi → ro'yxat bo'yicha xarid qiladi (narx yoki jami summa, chek rasmi) → taksi/hammol/qop xarajatlarini yozadi →
 * qolgan pulni topshiradi. Menejer/kassir hisobni yopadi: mahsulotlar omborga kiradi, xarajat tannarxga yoki Moliyaga yoziladi.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'

const route = useRoute()
type Tab = 'trips' | 'stats' | 'help'
const tab = ref<Tab>('trips')
const M = ref<any>(null)
const trips = ref<any[]>([])
const T = ref<any>(null)             // ochiq bozorlik (to'liq)
const it = ref<any>(null)            // mahsulot formasi
const ex = ref<any>(null)            // xarajat formasi
const closing = ref<any>(null)       // yopish paneli
const nt = ref<any>(null)            // yangi bozorlik
const S = ref<any>(null), days = ref(30)
const busy = ref(false)

const EXP_ICON: Record<string, string> = { taxi: '🚕', porter: '💪', fuel: '⛽', fee: '🅿️', pack: '🛍️', food: '🍞', other: '➕' }
const QUICK = [10_000, 20_000, 30_000, 50_000, 100_000]
const ADV = [500_000, 1_000_000, 1_500_000, 2_000_000, 3_000_000]
const TONE: Record<string, any> = { planned: 'info', active: 'warn', closed: 'ok', cancelled: 'danger' }
const canClose = computed(() => M.value?.can_edit || M.value?.can_pay)
const d = (s?: string | null) => s ? s.slice(0, 10).split('-').reverse().join('.') : '—'
const open = computed(() => trips.value.filter((t) => t.status === 'planned' || t.status === 'active'))
const done = computed(() => trips.value.filter((t) => t.status === 'closed' || t.status === 'cancelled'))
const todo = computed(() => (T.value?.items ?? []).filter((i: any) => !i.qty))
const got = computed(() => (T.value?.items ?? []).filter((i: any) => i.qty))
const isOpen = computed(() => T.value && (T.value.status === 'planned' || T.value.status === 'active'))
const ingOpts = computed(() => [{ value: '', label: '— ro\'yxatda yo\'q (nomini yozing) —' }, ...(M.value?.ingredients ?? []).map((i: any) => ({ value: String(i.id), label: `${i.name} (${i.unit})` }))])

async function load() { trips.value = await api.get('/procurement/trips') }
async function loadStats() { S.value = await api.get('/procurement/trip-stats', { days: days.value }) }
onMounted(async () => {
  M.value = await api.get('/procurement/meta')
  await load()
  if (route.query.plan) { try { newTrip(JSON.parse(String(route.query.plan))) } catch { /* noto'g'ri havola */ } }
  else if (route.query.trip) openTrip(Number(route.query.trip))
})
watch(tab, (t) => { if (t === 'stats') loadStats() })
watch(days, loadStats)

async function openTrip(id: number) { it.value = ex.value = closing.value = null; T.value = await api.get(`/procurement/trips/${id}`) }
function after(t: any) { T.value = t; load() }
async function run(fn: () => Promise<any>, ok?: string) {
  busy.value = true
  try { const r = await fn(); if (r && r.id) after(r); if (ok) toast(ok); return true } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); return false } finally { busy.value = false }
}

// ---- yangi bozorlik
function newTrip(plan: any[] = []) {
  nt.value = { buyer_id: M.value.me, advance: 1_000_000, market_id: '', branch_id: M.value.branches.length === 1 ? String(M.value.branches[0].id) : '', note: '',
    plan: plan.length ? plan.map((p: any) => ({ ingredient_id: p.ingredient_id ? String(p.ingredient_id) : '', name: p.name ?? '', qty: p.qty ?? 0, unit: p.unit ?? 'kg' })) : [{ ingredient_id: '', name: '', qty: 0, unit: 'kg' }] }
}
async function saveTrip() {
  const b = { ...nt.value, advance: Number(nt.value.advance) || 0, market_id: nt.value.market_id ? Number(nt.value.market_id) : null, branch_id: nt.value.branch_id ? Number(nt.value.branch_id) : null,
    plan: nt.value.plan.filter((p: any) => p.ingredient_id || p.name.trim()).map((p: any) => ({ ...p, ingredient_id: p.ingredient_id ? Number(p.ingredient_id) : null, qty: Number(p.qty) || 0 })) }
  if (await run(() => api.post('/procurement/trips', b), 'Bozorlik ochildi')) nt.value = null
}

// ---- mahsulot
function buy(i?: any) {
  it.value = i ? { id: i.qty ? i.id : null, plan_id: i.id, ingredient_id: i.ingredient_id ? String(i.ingredient_id) : '', name: i.name, unit: i.unit, qty: i.qty || i.planned_qty || '', mode: 'price', price: i.price || '', total: i.total || '', seller: i.seller, planned: Number(i.planned_qty) || 0 }
    : { id: null, ingredient_id: '', name: '', unit: 'kg', qty: '', mode: 'price', price: '', total: '', seller: '' }
  ex.value = null
}
const itTotal = computed(() => !it.value ? 0 : it.value.mode === 'total' ? Number(it.value.total) || 0 : Math.round((Number(it.value.qty) || 0) * (Number(it.value.price) || 0)))
const itUnit = computed(() => { const i = M.value?.ingredients.find((x: any) => String(x.id) === it.value?.ingredient_id); return i?.unit ?? it.value?.unit ?? 'kg' })
const itRef = computed(() => { const i = M.value?.ingredients.find((x: any) => String(x.id) === it.value?.ingredient_id); return i ? i.price : null })
async function saveItem() {
  const v = it.value
  const b = { ingredient_id: v.ingredient_id ? Number(v.ingredient_id) : null, name: v.name, unit: v.unit, qty: Number(v.qty) || 0,
    price: v.mode === 'price' ? Number(v.price) || 0 : 0, total: v.mode === 'total' ? Number(v.total) || 0 : 0, seller: v.seller }
  const url = v.id ? `/procurement/trips/${T.value.id}/items/${v.id}` : v.plan_id && !v.ingredient_id ? `/procurement/trips/${T.value.id}/items/${v.plan_id}` : `/procurement/trips/${T.value.id}/items`
  const method = v.id || (v.plan_id && !v.ingredient_id) ? api.put : api.post
  if (await run(() => method(url, b))) {
    it.value = null
    const next = todo.value[0]
    toast(next ? `Yozildi ✓ Keyingisi: ${next.name}` : 'Yozildi ✓ Ro\'yxat tugadi')
  }
}
const stepOf = (u: string) => (/dona|ta|bog|pachka|quti/i.test(u) ? 1 : 0.5)
function refPrice(i: any): number | null { const x = M.value?.ingredients.find((g: any) => g.id === i.ingredient_id); return x?.price ? Math.round(x.price) : null }
async function delItem(i: any) { if (confirm(`«${i.name}» o'chirilsinmi?`)) run(() => api.del(`/procurement/trips/${T.value.id}/items/${i.id}`)) }
async function photo(i: any, e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) run(() => api.upload(`/procurement/trips/${T.value.id}/items/${i.id}/photo`, f), 'Rasm saqlandi')
}

// ---- xarajat
function addExp(kind: string) { ex.value = { kind, amount: '', note: '' }; it.value = null }
async function saveExp() {
  if (await run(() => api.post(`/procurement/trips/${T.value.id}/expenses`, { ...ex.value, amount: Number(ex.value.amount) || 0 }), 'Xarajat yozildi')) ex.value = null
}
async function delExp(e: any) { if (confirm('Xarajat o\'chirilsinmi?')) run(() => api.del(`/procurement/trips/${T.value.id}/expenses/${e.id}`)) }
const expLabel = (k: string) => M.value?.expense_kinds.find((x: any) => x.code === k)?.label ?? k

// ---- yopish
function startClose() { closing.value = { returned: T.value.to_return }; it.value = ex.value = null }
const closeDiff = computed(() => closing.value ? (Number(closing.value.returned) || 0) - T.value.to_return : 0)
async function doClose() { if (await run(() => api.post(`/procurement/trips/${T.value.id}/close`, { returned: Number(closing.value.returned) || 0 }), 'Hisob yopildi — mahsulotlar omborga kirdi')) closing.value = null }
async function cancelTrip() { if (confirm('Bozorlik bekor qilinsinmi? Kiritilganlar omborga tushmaydi.')) run(() => api.post(`/procurement/trips/${T.value.id}/cancel`), 'Bekor qilindi') }

function reveal() { nextTick(() => document.querySelector('.mk-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' })) }
watch([it, ex, closing], ([a, b, c], [a0, b0, c0]) => { if ((a && !a0) || (b && !b0) || (c && !c0)) reveal() })
const kindMax = computed(() => Math.max(1, ...(S.value?.by_kind ?? []).map((k: any) => k.amount)))
</script>

<template>
  <div v-if="M" class="mk">
    <nav class="tabs">
      <button :class="{ on: tab === 'trips' }" @click="tab = 'trips'">🧺 Bozorliklar</button>
      <button v-if="canClose" :class="{ on: tab === 'stats' }" @click="tab = 'stats'">📊 Xarajat tahlili</button>
      <button :class="{ on: tab === 'help' }" @click="tab = 'help'">❓ Qanday ishlaydi</button>
    </nav>

    <!-- BOZORLIKLAR -->
    <template v-if="tab === 'trips'">
      <button type="button" class="cta" @click="newTrip()"><span>＋</span><b>Yangi bozorlik</b><small>Avans, bozor va xarid ro'yxati</small></button>
      <h3 v-if="open.length">Hozir davom etayotgan</h3>
      <div class="cards">
        <button v-for="t in open" :key="t.id" type="button" class="tc" @click="openTrip(t.id)">
          <div class="th"><b>#{{ t.number }} · {{ t.market?.name ?? 'Bozor tanlanmagan' }}</b><UiChip :tone="TONE[t.status]">{{ t.status_label }}</UiChip></div>
          <small>{{ d(t.date) }} · {{ t.buyer }}</small>
          <div class="nums"><span><small>Avans</small><b>{{ money(t.advance) }}</b></span><span><small>Sarflandi</small><b>{{ money(t.spent) }}</b></span>
            <span><small>{{ t.balance >= 0 ? 'Qo\'lda' : 'O\'z pulidan' }}</small><b :class="t.balance >= 0 ? 'ok' : 'bad'">{{ money(Math.abs(t.balance)) }}</b></span></div>
          <div class="prog"><i :style="{ width: `${t.planned ? (100 * Math.min(t.bought, t.planned)) / t.planned : t.bought ? 100 : 0}%` }"></i></div>
          <small>{{ t.bought }} / {{ t.planned || t.bought }} mahsulot olindi</small>
        </button>
      </div>
      <UiEmpty v-if="!open.length && !done.length" title="Hali bozorlik yo'q" text="«Yangi bozorlik» tugmasini bosing yoki Ombor → Xarid rejasi → «Bozorlik ro'yxati»." />
      <UiCard v-if="done.length" title="Yopilgan bozorliklar" :padded="false">
        <button v-for="t in done" :key="t.id" type="button" class="dr" @click="openTrip(t.id)">
          <span><b>#{{ t.number }} · {{ t.market?.name ?? '—' }}</b><small>{{ d(t.date) }} · {{ t.buyer }} · {{ t.bought }} mahsulot</small></span>
          <span class="r"><b>{{ money(t.spent) }}</b><small>xarajat {{ money(t.expenses_sum) }}{{ t.overhead_percent != null ? ` (${t.overhead_percent}%)` : '' }}</small></span>
          <UiChip v-if="t.status === 'cancelled'" tone="danger">Bekor</UiChip>
          <UiChip v-else-if="t.diff" :tone="t.diff < 0 ? 'danger' : 'info'">{{ t.diff < 0 ? 'Kam' : 'Ortiq' }} {{ money(Math.abs(t.diff)) }}</UiChip>
          <UiChip v-else tone="ok">To'g'ri</UiChip>
        </button>
      </UiCard>
    </template>

    <!-- TAHLIL -->
    <template v-else-if="tab === 'stats'">
      <div class="per"><button v-for="n in [7, 30, 90]" :key="n" :class="{ on: days === n }" @click="days = n">{{ n }} kun</button></div>
      <template v-if="S">
        <section class="kp">
          <div><small>Bozorliklar</small><b>{{ S.trips }}</b><em>{{ S.open ? `${S.open} tasi hali ochiq` : 'hammasi yopilgan' }}</em></div>
          <div><small>Mahsulotga</small><b>{{ money(S.items) }}</b><em>so'm</em></div>
          <div><small>Bozor xarajati</small><b>{{ money(S.expenses) }}</b><em>o'rtacha {{ money(S.avg_expense) }} / bozorlik</em></div>
          <div :class="{ warnbox: (S.overhead_percent ?? 0) > 5 }"><small>Xarajat ulushi</small><b>{{ S.overhead_percent ?? 0 }}%</b><em>har 1 mln mahsulotga {{ money(Math.round((S.overhead_percent ?? 0) * 10_000)) }} so'm</em></div>
          <div v-if="S.unreturned"><small>Qaytmagan pul</small><b class="bad">{{ money(S.unreturned) }}</b><em>ochiq bozorliklarda</em></div>
        </section>
        <p class="exp">💡 <b>Xarajat ulushi</b> — mahsulot narxiga qo'shimcha qancha yo'l, hammol va qop puli ketgani. 3–5% me'yor. Undan yuqori bo'lsa: bir martada ko'proq oling, yetkazib beruvchi ta'minotchiga o'ting yoki yaqinroq bozorni tanlang.</p>
        <div class="two">
          <UiCard title="Xarajat turlari" subtitle="Pul nimaga ketyapti">
            <ul class="bars"><li v-for="k in S.by_kind" :key="k.kind"><span>{{ EXP_ICON[k.kind] }} {{ k.label }}</span><span class="bar"><i :style="{ width: `${(100 * k.amount) / kindMax}%` }"></i></span><b>{{ money(k.amount) }}</b></li></ul>
            <UiEmpty v-if="!S.by_kind.length" title="Xarajat yo'q" />
          </UiCard>
          <UiCard title="Bozorlar bo'yicha" subtitle="Qaysi bozor qimmatga tushyapti (xarajat % bilan)" :padded="false">
            <div v-for="(m, i) in S.by_market" :key="m.market" class="mr"><span><b>{{ m.market }}</b><small>{{ m.trips }} marta · mahsulot {{ money(m.items) }}</small></span>
              <span class="r"><b>{{ money(m.expenses) }}</b><UiChip :tone="(m.overhead_percent ?? 0) <= 3 ? 'ok' : (m.overhead_percent ?? 0) <= 6 ? 'warn' : 'danger'">{{ m.overhead_percent ?? 0 }}%</UiChip></span>
              <em v-if="i === 0 && S.by_market.length > 1" class="tag">eng ko'p xarid</em></div>
          </UiCard>
        </div>
        <UiCard title="Bozorchilar" subtitle="Kamomad — qaytishi kerak bo'lgan puldan kam topshirilgani" :padded="false">
          <div v-for="b in S.by_buyer" :key="b.buyer" class="mr"><span><b>{{ b.buyer }}</b><small>{{ b.trips }} bozorlik · {{ money(b.spent) }} sarflagan</small></span>
            <UiChip :tone="b.diff < 0 ? 'danger' : b.diff > 0 ? 'info' : 'ok'">{{ b.diff < 0 ? `Kamomad ${money(-b.diff)}` : b.diff > 0 ? `Ortiqcha ${money(b.diff)}` : 'Hisob toza' }}</UiChip></div>
        </UiCard>
      </template>
    </template>

    <!-- YORDAM -->
    <template v-else>
      <ol class="how">
        <li><b>Bozorlik ochiladi.</b> Menejer (yoki bozorchining o'zi) «Yangi bozorlik»ni bosadi: kim boradi, qancha avans berildi, qaysi bozor va nima olish kerak. Ro'yxatni Ombor → «Xarid rejasi»dan bir tugma bilan olish mumkin.</li>
        <li><b>Bozorda — telefondan.</b> Har bir mahsulotni olganda «Oldim» ni bosing: miqdor va <i>1 kg narxi</i> yoki <i>jami to'lagan summa</i>. Sotuvchi ismi va chek/tarozi rasmini qo'shsangiz — keyin tekshirish oson.</li>
        <li><b>Bozor xarajatlari.</b> Taksi 🚕, hammol 💪, yoqilg'i ⛽, joy to'lovi 🅿️, qop/paket 🛍️ — bittadan tugma. Summani yozing, tamom. Ekranning tepasida doim <i>«Qo'lda qolishi kerak»</i> summa ko'rinib turadi.</li>
        <li><b>Qaytib kelgach.</b> Kassir yoki menejer qolgan pulni sanaydi va «Hisobni yopish»ni bosadi. Tizim o'zi solishtiradi: kam bo'lsa — <b>kamomad</b>, ko'p bo'lsa — <b>ortiqcha</b>.</li>
        <li><b>Omborga avtomatik.</b> Yopilganda mahsulotlar omborga kirim bo'ladi, narxlar «Zakup → Narxlar» tarixiga yoziladi. Bozor xarajatlari sozlamaga qarab mahsulot <b>tannarxiga</b> taqsimlanadi (masalan, 50 000 taksi 1 mln go'shtga qo'shiladi) yoki <b>Moliya</b>ga «Bozor xarajatlari» bo'lib yoziladi.</li>
        <li><b>Nazorat.</b> «Xarajat tahlili»da: qaysi bozor qimmatga tushyapti, pul nimaga ketyapti, qaysi bozorchida kamomad bor.</li>
      </ol>
      <p class="foot">Bozorlar ro'yxati (manzil, ish vaqti, maslahat): <RouterLink to="/procurement?tab=markets">Zakup → Bozorlar</RouterLink></p>
    </template>

    <!-- BOZORLIK KARTASI -->
    <UiDrawer :open="!!T" :title="T ? `Bozorlik #${T.number}` : ''" width="560px" @close="T = null">
      <template v-if="T">
        <p class="sub">{{ d(T.date) }} · {{ T.buyer }} · {{ T.market?.name ?? 'bozor tanlanmagan' }}{{ T.branch ? ` · ${T.branch}` : '' }} <UiChip :tone="TONE[T.status]">{{ T.status_label }}</UiChip></p>
        <section class="bal" :class="{ neg: T.balance < 0 }">
          <div><small>Avans</small><b>{{ money(T.advance) }}</b></div>
          <div><small>Mahsulot</small><b>{{ money(T.items_sum) }}</b></div>
          <div><small>Xarajat</small><b>{{ money(T.expenses_sum) }}</b></div>
          <div class="big"><small>{{ T.balance >= 0 ? 'Qo\'lda qolishi kerak' : 'Bozorchi o\'z pulidan qo\'shgan' }}</small><b>{{ money(Math.abs(T.balance)) }} so'm</b></div>
        </section>

        <!-- olish kerak -->
        <template v-if="todo.length">
          <h4>Olish kerak <small>{{ todo.length }}</small></h4>
          <component :is="isOpen ? 'button' : 'div'" v-for="i in todo" :key="i.id" type="button" class="todo2" @click="isOpen && buy(i)">
            <span class="tn"><b>{{ i.name }}</b><small>{{ i.planned_qty }} {{ i.unit }}<template v-if="refPrice(i)"> · ~{{ money(refPrice(i)!) }} so'm/{{ i.unit }}</template></small></span>
            <span v-if="isOpen" class="ob">✓ Oldim</span>
          </component>
        </template>

        <h4>Olindi <small>{{ got.length }}</small></h4>
        <div v-for="i in got" :key="i.id" class="row">
          <label v-if="isOpen" class="ph" :title="i.photo ? 'Rasmni almashtirish' : 'Chek / tarozi rasmi'">
            <img v-if="i.photo" :src="i.photo" alt="" /><span v-else>📷</span>
            <input type="file" accept="image/*" capture="environment" @change="photo(i, $event)" /></label>
          <a v-else-if="i.photo" class="ph" :href="i.photo" target="_blank" rel="noopener"><img :src="i.photo" alt="" /></a>
          <span><b>{{ i.name }}</b><small>{{ i.qty }} {{ i.unit }} × {{ money(i.price) }}{{ i.seller ? ` · ${i.seller}` : '' }}</small></span>
          <b>{{ money(i.total) }}</b>
          <span v-if="isOpen" class="ia"><button aria-label="Tahrirlash" @click="buy(i)"><UiIcon name="edit" :size="15" /></button><button aria-label="O'chirish" @click="delItem(i)"><UiIcon name="trash" :size="15" /></button></span>
        </div>
        <p v-if="!got.length" class="mut">Hali hech narsa olinmadi.</p>
        <UiButton v-if="isOpen" variant="secondary" block style="margin-top: 10px" @click="buy()"><UiIcon name="plus" :size="14" /> Ro'yxatda yo'q mahsulot oldim</UiButton>

        <h4>Bozor xarajatlari <small>{{ money(T.expenses_sum) }}{{ T.overhead_percent != null ? ` · ${T.overhead_percent}%` : '' }}</small></h4>
        <div v-if="isOpen" class="ek"><button v-for="k in M.expense_kinds" :key="k.code" type="button" :class="{ on: ex?.kind === k.code }" @click="addExp(k.code)"><span>{{ EXP_ICON[k.code] }}</span>{{ k.label.split(' /')[0].split(',')[0] }}</button></div>
        <div v-if="ex" class="form mk-form">
          <h4>{{ EXP_ICON[ex.kind] }} {{ expLabel(ex.kind) }}</h4>
          <UiInput v-model="ex.amount" type="number" label="Summa (so'm)" />
          <div class="qk"><button v-for="q in QUICK" :key="q" type="button" @click="ex.amount = q">{{ money(q) }}</button></div>
          <UiInput v-model="ex.note" label="Izoh (ixtiyoriy)" placeholder="Bozorga borish-qaytish" />
          <div class="fb"><UiButton variant="ghost" @click="ex = null">Bekor</UiButton><UiButton variant="brand" :loading="busy" :disabled="!ex.amount" @click="saveExp()">Yozish</UiButton></div>
        </div>
        <div v-for="e in T.expenses" :key="e.id" class="row">
          <span class="ei">{{ EXP_ICON[e.kind] }}</span><span><b>{{ e.label }}</b><small>{{ e.note }}</small></span><b>{{ money(e.amount) }}</b>
          <span v-if="isOpen" class="ia"><button aria-label="O'chirish" @click="delExp(e)"><UiIcon name="trash" :size="15" /></button></span>
        </div>

        <!-- yopish -->
        <div v-if="closing" class="form cl mk-form">
          <h4>Hisobni yopish</h4>
          <p>Avans {{ money(T.advance) }} − sarflangan {{ money(T.spent) }} = <b>{{ T.balance >= 0 ? `${money(T.to_return)} so'm qaytishi kerak` : `bozorchiga ${money(T.owed_to_buyer)} so'm berish kerak` }}</b></p>
          <UiInput v-model="closing.returned" type="number" label="Haqiqatda qaytarilgan pul (so'm)" />
          <p v-if="closeDiff" :class="closeDiff < 0 ? 'bad' : 'info'">{{ closeDiff < 0 ? `⚠️ Kamomad: ${money(-closeDiff)} so'm` : `Ortiqcha: ${money(closeDiff)} so'm` }}</p>
          <p class="mut">{{ T.overhead_to_cost ? `Bozor xarajatlari (${money(T.expenses_sum)}) mahsulotlar tannarxiga summasiga qarab taqsimlanadi.` : `Bozor xarajatlari (${money(T.expenses_sum)}) Moliyaga «Bozor xarajatlari» bo'lib yoziladi.` }} Mahsulotlar omborga kirim qilinadi.</p>
          <div class="fb"><UiButton variant="ghost" @click="closing = null">Orqaga</UiButton><UiButton variant="brand" :loading="busy" @click="doClose()">Tasdiqlash va yopish</UiButton></div>
        </div>
        <div v-if="T.status === 'closed'" class="done">
          <p>✅ Yopilgan: {{ d(T.closed_at) }}. Qaytarildi: <b>{{ money(T.returned) }}</b>.
            <b v-if="T.diff" :class="T.diff < 0 ? 'bad' : ''">{{ T.diff < 0 ? ` Kamomad ${money(-T.diff)}` : ` Ortiqcha ${money(T.diff)}` }}</b></p>
          <RouterLink to="/inventory">Omborga kirimni ko'rish →</RouterLink>
        </div>
      </template>
      <template #footer>
        <template v-if="isOpen && !closing">
          <UiButton v-if="M.can_edit" variant="ghost" @click="cancelTrip()">Bekor qilish</UiButton>
          <UiButton v-if="canClose" variant="brand" :disabled="!got.length && !T.expenses.length" @click="startClose()">Hisobni yopish</UiButton>
          <span v-else class="mut">Qaytib kelgach, qolgan pulni kassirga topshiring — u hisobni yopadi.</span>
        </template>
      </template>
    </UiDrawer>

    <!-- «OLDIM» — bozorda bitta qo'l bilan: miqdor, narx, saqlash -->
    <UiDrawer :open="!!it" :title="it ? (it.id ? 'Tahrirlash' : it.plan_id ? `✓ ${it.name}` : 'Mahsulot oldim') : ''" width="460px" @close="it = null">
      <div v-if="it" class="buy">
        <template v-if="!it.plan_id">
          <UiSelect v-model="it.ingredient_id" label="Mahsulot" :options="ingOpts" />
          <div v-if="!it.ingredient_id" class="g2"><UiInput v-model="it.name" label="Nomi" placeholder="Masalan: shivit" /><UiInput v-model="it.unit" label="O'lchov" placeholder="kg / dona / bog'" /></div>
        </template>
        <label class="big-l">Qancha oldingiz? <small>{{ itUnit }}</small></label>
        <div class="stepper">
          <button type="button" aria-label="Kamaytirish" @click="it.qty = Math.max(0, +(Number(it.qty || 0) - stepOf(itUnit)).toFixed(2))">−</button>
          <input v-model="it.qty" type="number" inputmode="decimal" step="any" min="0" aria-label="Miqdor" />
          <button type="button" aria-label="Ko'paytirish" @click="it.qty = +(Number(it.qty || 0) + stepOf(itUnit)).toFixed(2)">+</button>
        </div>
        <div v-if="it.planned" class="qk"><button type="button" :class="{ on: Number(it.qty) === it.planned }" @click="it.qty = it.planned">Rejadagi: {{ it.planned }} {{ itUnit }}</button></div>
        <div class="seg"><button type="button" :class="{ on: it.mode === 'price' }" @click="it.mode = 'price'">1 {{ itUnit }} narxi</button><button type="button" :class="{ on: it.mode === 'total' }" @click="it.mode = 'total'">Jami to'ladim</button></div>
        <label class="big-l">{{ it.mode === 'price' ? `1 ${itUnit} narxi` : 'Jami to\'lagan summa' }} <small>so'm</small></label>
        <input v-if="it.mode === 'price'" v-model="it.price" class="big-in" type="number" inputmode="numeric" min="0" :placeholder="itRef ? String(Math.round(itRef)) : '0'" aria-label="Narx" />
        <input v-else v-model="it.total" class="big-in" type="number" inputmode="numeric" min="0" placeholder="0" aria-label="Jami summa" />
        <div v-if="it.mode === 'price' && itRef" class="qk"><button type="button" @click="it.price = Math.round(itRef)">Ombordagi narx: {{ money(Math.round(itRef)) }}</button></div>
        <div class="sum"><span>Jami</span><b>{{ money(itTotal) }} so'm</b></div>
        <p v-if="it.mode === 'price' && itRef && Number(it.price) > itRef * 1.15" class="warn">⚠️ Odatdagidan {{ Math.round((100 * Number(it.price)) / itRef - 100) }}% qimmat</p>
        <details class="more"><summary>Sotuvchi (ixtiyoriy)</summary><UiInput v-model="it.seller" placeholder="Ahmad aka, 12-qator" /></details>
      </div>
      <template #footer>
        <UiButton variant="brand" size="l" block :loading="busy" :disabled="!Number(it?.qty) || !itTotal" @click="saveItem()">✓ Saqlash</UiButton>
      </template>
    </UiDrawer>

    <!-- YANGI BOZORLIK -->
    <UiDrawer :open="!!nt" title="Yangi bozorlik" width="520px" @close="nt = null">
      <template v-if="nt">
        <UiSelect v-if="M.can_edit" v-model="nt.buyer_id" label="Kim boradi" :options="M.buyers.map((b: any) => ({ value: b.id, label: b.name }))" />
        <UiInput v-model="nt.advance" type="number" label="Berilgan avans (so'm)" />
        <div class="qk"><button v-for="a in ADV" :key="a" type="button" :class="{ on: Number(nt.advance) === a }" @click="nt.advance = a">{{ money(a) }}</button></div>
        <div class="g2">
          <UiSelect v-model="nt.market_id" label="Qaysi bozor" :options="[{ value: '', label: '— keyin tanlanadi —' }, ...M.markets.map((m: any) => ({ value: String(m.id), label: m.name }))]" />
          <UiSelect v-if="M.branches.length > 1" v-model="nt.branch_id" label="Qaysi filial uchun" :options="[{ value: '', label: '— asosiy —' }, ...M.branches.map((b: any) => ({ value: String(b.id), label: b.name }))]" />
        </div>
        <h4>Nima olish kerak</h4>
        <div v-for="(p, k) in nt.plan" :key="k" class="pl">
          <UiSelect v-model="p.ingredient_id" :options="ingOpts" />
          <UiInput v-if="!p.ingredient_id" v-model="p.name" placeholder="Nomi" />
          <UiInput v-model="p.qty" type="number" placeholder="Miqdor" />
          <button type="button" aria-label="O'chirish" @click="nt.plan.splice(k, 1)"><UiIcon name="x" :size="16" /></button>
        </div>
        <UiButton variant="ghost" size="s" @click="nt.plan.push({ ingredient_id: '', name: '', qty: 0, unit: 'kg' })"><UiIcon name="plus" :size="14" /> Qator</UiButton>
        <UiInput v-model="nt.note" label="Izoh" placeholder="Masalan: go'shtni Aziz akadan oling" style="margin-top: 10px" />
      </template>
      <template #footer><UiButton variant="ghost" @click="nt = null">Bekor</UiButton><UiButton variant="brand" :loading="busy" @click="saveTrip()">Bozorlikni ochish</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.mk { display: flex; flex-direction: column; gap: 14px; max-width: 1100px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { flex-shrink: 0; border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.cta { display: grid; grid-template-columns: 52px 1fr; grid-template-rows: auto auto; align-items: center; gap: 0 12px; padding: 14px 16px; border: 2px dashed var(--accent); border-radius: 16px; background: var(--accent-tint); cursor: pointer; text-align: left; font: inherit; color: var(--ink); }
.cta span { grid-row: span 2; width: 52px; height: 52px; border-radius: 14px; background: var(--accent); color: var(--accent-ink); display: grid; place-items: center; font-size: 28px; font-weight: 800; }
.cta b { font-size: var(--fs-l); } .cta small { color: var(--muted); }
h3 { margin: 4px 0 0; font-size: var(--fs-m); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.tc { display: flex; flex-direction: column; gap: 6px; padding: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; text-align: left; font: inherit; cursor: pointer; color: var(--ink); }
.tc:hover { border-color: var(--accent); } .tc > small { color: var(--muted); font-size: var(--fs-xs); }
.th { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.nums { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 4px; }
.nums span { display: flex; flex-direction: column; background: var(--surface-2); border-radius: 10px; padding: 6px 8px; min-width: 0; }
.nums small { font-size: 10px; color: var(--muted); font-weight: 700; } .nums b { font-size: var(--fs-s); white-space: nowrap; }
.ok { color: var(--ok); } .bad { color: var(--danger); } .info { color: var(--info, #2563eb); }
.prog { height: 6px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .prog i { display: block; height: 100%; background: var(--ok); border-radius: 99px; }
.dr, .mr { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; width: 100%; padding: 12px 16px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; color: var(--ink); cursor: pointer; position: relative; }
.mr { cursor: default; grid-template-columns: minmax(0, 1fr) auto; }
.dr:hover { background: var(--surface-2); }
.dr span, .mr span { display: flex; flex-direction: column; min-width: 0; } .dr small, .mr small { color: var(--muted); font-size: var(--fs-xs); }
.r { align-items: flex-end; } .mr .r { flex-direction: row; gap: 8px; align-items: center; }
.tag { position: absolute; right: 16px; top: 2px; font-size: 10px; color: var(--muted); font-style: normal; }
.per { display: flex; gap: 6px; } .per button { min-height: 36px; padding: 0 14px; border: 1px solid var(--line); border-radius: 99px; background: var(--surface); font: inherit; font-weight: 700; cursor: pointer; color: var(--ink); }
.per button.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
.kp { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
.kp div { display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; }
.kp small { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .kp b { font-family: var(--font-display); font-size: 22px; } .kp em { font-style: normal; font-size: 11px; color: var(--muted); }
.kp .warnbox { background: var(--warn-tint); }
.exp { margin: 0; padding: 10px 14px; border-radius: 12px; background: var(--surface-2); font-size: var(--fs-s); line-height: 1.5; }
.two { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.bars { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.bars li { display: grid; grid-template-columns: minmax(0, 1fr) 100px auto; gap: 8px; align-items: center; font-size: var(--fs-s); }
.bar { height: 8px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: var(--series-3, #f59e0b); border-radius: 99px; }
.how { margin: 0; padding: 0 0 0 22px; display: flex; flex-direction: column; gap: 12px; font-size: var(--fs-m); line-height: 1.55; max-width: 760px; }
.foot { color: var(--muted); font-size: var(--fs-s); } .foot a, .done a { color: var(--accent); font-weight: 700; }
.sub { margin: 0 0 10px; color: var(--muted); font-size: var(--fs-s); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.bal { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 12px; border-radius: 16px; background: color-mix(in srgb, var(--ok) 12%, var(--surface)); position: sticky; top: -16px; z-index: 2; }
.bal.neg { background: var(--danger-tint); }
.bal div { display: flex; flex-direction: column; } .bal small { font-size: 11px; color: var(--ink-2); font-weight: 700; } .bal b { font-size: var(--fs-s); }
.bal .big { grid-column: 1 / -1; border-top: 1px solid rgba(0,0,0,.08); padding-top: 6px; } .bal .big b { font-family: var(--font-display); font-size: 24px; }
h4 { margin: 16px 0 6px; font-size: var(--fs-s); display: flex; gap: 6px; align-items: baseline; } h4 small { color: var(--muted); font-weight: 600; }
.row { display: flex; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); }
.row > span:not(.ia):not(.ei) { flex: 1; display: flex; flex-direction: column; min-width: 0; } .row small { color: var(--muted); font-size: var(--fs-xs); }
.row.todo { background: var(--warn-tint); border-radius: 10px; padding: 8px 10px; border: 0; margin-bottom: 6px; }
.ph { width: 40px; height: 40px; border-radius: 10px; background: var(--surface-2); display: grid; place-items: center; overflow: hidden; cursor: pointer; flex-shrink: 0; position: relative; font-size: 18px; }
.ph img { width: 100%; height: 100%; object-fit: cover; } .ph input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.ei { font-size: 20px; width: 40px; text-align: center; }
.ia { display: flex; gap: 2px; } .ia button { border: 0; background: transparent; color: var(--muted); cursor: pointer; padding: 6px; }
.form { margin-top: 10px; padding: 12px; border: 2px solid var(--accent); border-radius: 14px; background: var(--surface); display: flex; flex-direction: column; gap: 8px; }
.form h4 { margin: 0; } .form p { margin: 0; font-size: var(--fs-s); }
.form.cl { border-color: var(--ok); }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; background: var(--surface-2); padding: 4px; border-radius: 12px; }
.seg button { min-height: 38px; border: 0; border-radius: 9px; background: transparent; font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; color: var(--muted); }
.seg button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.tot { font-size: var(--fs-m) !important; } .fb { display: flex; justify-content: flex-end; gap: 8px; }
.ek { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.ek button { display: flex; flex-direction: column; align-items: center; gap: 2px; min-height: 64px; padding: 6px 2px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; color: var(--ink); text-align: center; line-height: 1.15; }
.ek button span { font-size: 22px; } .ek button.on { border-color: var(--accent); background: var(--accent-tint); }
.qk { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.qk button { min-height: 34px; padding: 0 10px; border: 1px solid var(--line); border-radius: 99px; background: var(--surface); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink); }
.qk button.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.pl { display: grid; grid-template-columns: minmax(0, 1fr) 90px 32px; gap: 6px; align-items: end; margin-bottom: 6px; }
.pl:has(> :nth-child(4)) { grid-template-columns: minmax(0, 1fr) minmax(0, .8fr) 80px 32px; }
.pl > button { border: 0; background: transparent; color: var(--muted); cursor: pointer; height: 40px; }
.mut { color: var(--muted); font-size: var(--fs-s); }
.todo2 { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 58px; padding: 10px 12px; margin-bottom: 8px; border: 1px solid color-mix(in srgb, var(--warn, #F59E0B) 35%, var(--line)); border-radius: 14px; background: var(--warn-tint); font: inherit; color: var(--ink); text-align: left; cursor: pointer; }
.todo2:active { transform: scale(.99); }
.tn { flex: 1; display: flex; flex-direction: column; min-width: 0; } .tn b { font-size: var(--fs-b); } .tn small { color: var(--ink-2); font-size: var(--fs-xs); }
.ob { flex-shrink: 0; padding: 9px 14px; border-radius: 12px; background: var(--accent); color: var(--accent-ink); font-weight: 800; font-size: var(--fs-s); }
.buy { display: flex; flex-direction: column; gap: 10px; }
.big-l { font-weight: 800; font-size: var(--fs-s); display: flex; justify-content: space-between; margin-top: 4px; } .big-l small { color: var(--muted); font-weight: 700; }
.stepper { display: grid; grid-template-columns: 64px 1fr 64px; gap: 8px; }
.stepper button { height: 60px; border-radius: 14px; border: 1px solid var(--line); background: var(--surface-2); font-size: 28px; font-weight: 700; cursor: pointer; color: var(--ink); }
.stepper input, .big-in { height: 60px; border-radius: 14px; border: 2px solid var(--line); background: var(--surface); text-align: center; font: inherit; font-size: 26px; font-weight: 800; color: var(--ink); min-width: 0; width: 100%; box-sizing: border-box; font-variant-numeric: tabular-nums; }
.stepper input:focus, .big-in:focus { border-color: var(--accent); outline: none; }
.sum { display: flex; justify-content: space-between; align-items: baseline; padding: 12px 14px; border-radius: 14px; background: var(--surface-2); } .sum span { color: var(--muted); font-weight: 700; } .sum b { font-size: 24px; font-variant-numeric: tabular-nums; }
.warn { margin: 0; color: var(--danger); font-weight: 700; font-size: var(--fs-s); }
.more summary { cursor: pointer; color: var(--muted); font-weight: 700; font-size: var(--fs-s); padding: 6px 0; }
.done { margin-top: 14px; padding: 12px; border-radius: 12px; background: var(--surface-2); font-size: var(--fs-s); } .done p { margin: 0 0 6px; }
@media (max-width: 800px) { .two { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 640px) {
  .cards { grid-template-columns: minmax(0, 1fr); } .g2 { grid-template-columns: 1fr; }
  .pl, .pl:has(> :nth-child(4)) { grid-template-columns: minmax(0, 1fr) 76px 28px; } .pl > :nth-child(2):not(:last-child):not(:nth-last-child(2)) { grid-column: 1 / -1; order: 5; }
  .bars li { grid-template-columns: minmax(0, 1fr) 60px auto; }
  .dr { grid-template-columns: minmax(0, 1fr) auto; } .dr > :last-child { grid-column: 1 / -1; justify-self: start; }
}
</style>
