<script setup lang="ts">
/**
 * Kassa smenasi — ochish va TOPSHIRISH (3 qadam):
 *   1) Hisobot — savdo, to'lov turlari, kirim/chiqim, bekor qilinganlar;
 *   2) Naqd sanash — kupyuralar bo'yicha (+/−) yoki summani yozish; kutilgan bilan farq darhol ko'rinadi, farq bo'lsa sabab;
 *      terminal (Z) summasi bilan karta solishtiriladi;
 *   3) Topshirish — kassada qancha qoladi, qancha kimga topshiriladi; qabul qiluvchiga Telegram'da «✅ Qabul qildim».
 * Ochishda: oldingi smenadan qolgan summa taklif qilinadi, sizga topshirilgan kassani qabul qilasiz.
 */
import { computed, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiInput, money, toast } from '@restopos/ui'

const props = defineProps<{ open: boolean; shift: any | null; branchId?: string | number | null }>()
const emit = defineEmits<{ close: []; changed: [any] }>()

type Helpers = { left_from_last: number | null; last_closed_by: string | null; receivers: { id: string; name: string; role: string }[]; to_accept: any[]; recent: any[]; denoms: number[] }
const H = ref<Helpers | null>(null), R = ref<any>(null), busy = ref(false)
const step = ref(1), done = ref<any>(null)
const cashStart = ref<number | ''>('')
const counts = ref<Record<string, number>>({}), manual = ref(false), manualSum = ref<number | ''>('')
const cardZ = ref<number | ''>(''), reason = ref(''), left = ref<number | ''>(0), handedTo = ref(''), note = ref('')

watch(() => props.open, async (o) => {
  if (!o) return
  step.value = 1; done.value = null; counts.value = {}; manual.value = false; manualSum.value = ''; cardZ.value = ''; reason.value = ''; note.value = ''; handedTo.value = ''
  try {
    H.value = await api.get<Helpers>('/pos/shift-helpers', props.branchId ? { branch_id: props.branchId } : {})
    if (!props.shift) cashStart.value = H.value.left_from_last ?? 0
    else { R.value = await api.get(`/pos/shift/${props.shift.id}/report`); left.value = Math.min(props.shift.cash_start || 0, R.value.shift.totals.expected_cash) }
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}, { immediate: true })

const T = computed(() => R.value?.shift?.totals ?? props.shift?.totals ?? {})
const denoms = computed(() => H.value?.denoms ?? [200000, 100000, 50000, 20000, 10000, 5000, 2000, 1000, 500])
const counted = computed(() => manual.value ? Number(manualSum.value || 0) : denoms.value.reduce((s, d) => s + d * (counts.value[d] || 0), 0))
const diff = computed(() => counted.value - (T.value.expected_cash ?? 0))
const cardDiff = computed(() => (cardZ.value === '' ? null : Number(cardZ.value) - (T.value.by_method?.card ?? 0)))
const handed = computed(() => Math.max(0, counted.value - Number(left.value || 0)))
const METHOD: Record<string, string> = { cash: '💵 Naqd', card: '💳 Karta (terminal)', click: 'Click', payme: 'Payme', uzum: 'Uzum', transfer: "O'tkazma" }
const methods = computed(() => Object.entries(T.value.by_method ?? {}).filter(([, v]) => (v as number) > 0) as [string, number][])
function inc(d: number, n: number) { counts.value = { ...counts.value, [d]: Math.max(0, (counts.value[d] || 0) + n) } }
const dur = computed(() => {
  const s = props.shift?.opened_at; if (!s) return ''
  const m = Math.round((Date.now() - new Date(s).getTime()) / 60000); return `${Math.floor(m / 60)} soat ${m % 60} daq`
})
const tm = (v: string | null) => (v ? new Date(v).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')

async function openShift() {
  busy.value = true
  try { const s = await api.post('/pos/shift/open', { cash_start: Number(cashStart.value || 0), branch_id: props.branchId ? Number(props.branchId) : null }); toast('Smena ochildi'); emit('changed', s); emit('close') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function accept(x: any) {
  try { await api.post(`/pos/shift/${x.id}/accept`); toast('Qabul qilindi'); H.value = await api.get<Helpers>('/pos/shift-helpers') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function next() {
  if (step.value === 1 && R.value?.open_orders) { toast(`${R.value.open_orders} ta ochiq buyurtma bor — avval to'lang yoki bekor qiling`, 'danger'); return }
  if (step.value === 2) {
    if (!counted.value && !confirm('Kassada naqd yo\'q (0 so\'m) deb yozilsinmi?')) return
    if (diff.value !== 0 && reason.value.trim().length < 3) { toast('Farq bor — sababini yozing', 'danger'); return }
  }
  step.value++
}
async function closeShift() {
  busy.value = true
  const body: any = { card_terminal: cardZ.value === '' ? null : Number(cardZ.value), left_amount: Number(left.value || 0), handed_to: handedTo.value || null, diff_reason: reason.value, note: note.value }
  if (manual.value) body.cash_end = Number(manualSum.value || 0); else body.counted = counts.value
  try {
    const s = await api.post(`/pos/shift/${props.shift.id}/close`, body)
    done.value = await api.get(`/pos/shift/${s.id}/report`); emit('changed', null)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
function print() {
  const w = window.open('', '_blank', 'width=420,height=700'); if (!w || !done.value) return
  w.document.write(`<div style="font:14px/1.5 system-ui,sans-serif;padding:14px;max-width:380px">${String(done.value.text).replace(/\n/g, '<br>')}<br><br>Kassir imzosi: ____________<br><br>Qabul qildi: ____________</div>`)
  w.document.close(); w.print()
}
const title = computed(() => (done.value ? 'Kassa topshirildi' : props.shift ? 'Kassani topshirish' : 'Smena ochish'))
</script>

<template>
  <UiDrawer :open="open" :title="title" width="620px" :state="done ? 'clean' : undefined" @close="emit('close')">
    <!-- ============ OCHISH ============ -->
    <template v-if="!shift && !done">
      <div v-for="x in H?.to_accept ?? []" :key="x.id" class="acc">
        <span>🤝 Sizga topshirilgan kassa: <b>{{ money(x.handed_amount) }}</b><small>{{ x.closed_by }} · {{ tm(x.closed_at) }}</small></span>
        <UiButton size="s" variant="brand" @click="accept(x)">✅ Qabul qildim</UiButton>
      </div>
      <UiInput v-model="cashStart" type="number" label="Kassadagi boshlang'ich naqd" suffix="so'm" />
      <p v-if="H?.left_from_last !== null && H?.left_from_last !== undefined" class="hint">Oldingi smenada kassada qoldirilgan: <b>{{ money(H.left_from_last) }}</b>{{ H.last_closed_by ? ` (${H.last_closed_by})` : '' }}. Sanab, farq bo'lsa to'g'rilang.</p>
      <div v-if="H?.recent.length" class="recent">
        <h4>Oxirgi smenalar</h4>
        <div v-for="x in H.recent" :key="x.id" class="rr">
          <span><b>{{ tm(x.closed_at) }}</b><small>{{ x.closed_by || x.opened_by }}{{ x.branch ? ' · ' + x.branch : '' }}</small></span>
          <span>{{ money(x.totals.total) }}</span>
          <UiChip :tone="(x.totals.cash_diff ?? 0) === 0 ? 'ok' : 'danger'">{{ (x.totals.cash_diff ?? 0) === 0 ? 'farqsiz' : (x.totals.cash_diff > 0 ? '+' : '') + money(x.totals.cash_diff) }}</UiChip>
          <UiChip :tone="x.accepted_at ? 'info' : 'neutral'">{{ x.accepted_at ? 'qabul qilingan' : x.handed_to ? 'kutilmoqda' : '—' }}</UiChip>
        </div>
      </div>
    </template>

    <!-- ============ TOPSHIRILDI ============ -->
    <template v-else-if="done">
      <div class="z" v-html="String(done.text).replace(/\n/g, '<br>')"></div>
      <p class="hint">{{ done.shift.handed_to ? `${done.shift.handed_to}ga Telegram'da xabar ketdi — u «✅ Qabul qildim»ni bosadi.` : 'Hisobot saqlandi.' }}</p>
    </template>

    <!-- ============ TOPSHIRISH (3 qadam) ============ -->
    <template v-else-if="R">
      <ol class="steps">
        <li :class="{ on: step === 1, ok: step > 1 }" @click="step > 1 && (step = 1)"><i>1</i>Hisobot</li>
        <li :class="{ on: step === 2, ok: step > 2 }" @click="step > 2 && (step = 2)"><i>2</i>Naqd sanash</li>
        <li :class="{ on: step === 3 }"><i>3</i>Topshirish</li>
      </ol>

      <div v-if="step === 1" class="pane">
        <div class="tiles">
          <div><small>Savdo</small><b>{{ money(T.total) }}</b></div>
          <div><small>Cheklar</small><b>{{ T.orders }}</b></div>
          <div><small>O'rtacha chek</small><b>{{ money(T.avg_check) }}</b></div>
          <div><small>Smena</small><b>{{ dur }}</b></div>
        </div>
        <div class="list">
          <div v-for="[k, v] in methods" :key="k" class="li"><span>{{ METHOD[k] ?? k }}</span><b>{{ money(v) }}</b></div>
          <div class="li mu"><span>Boshlang'ich naqd</span><b>{{ money(R.shift.cash_start) }}</b></div>
          <div v-if="T.cash_in" class="li mu"><span>↓ Kassaga kirim</span><b>+{{ money(T.cash_in) }}</b></div>
          <div v-if="T.cash_out" class="li mu"><span>↑ Kassadan chiqim</span><b>−{{ money(T.cash_out) }}</b></div>
          <div v-if="T.cancelled" class="li mu"><span>✖️ Bekor qilingan cheklar</span><b>{{ T.cancelled }} ta</b></div>
          <div class="li big"><span>Kassada bo'lishi kerak (naqd)</span><b>{{ money(T.expected_cash) }}</b></div>
        </div>
        <div v-if="R.moves.length" class="moves"><h4>Kirim / chiqim</h4>
          <div v-for="(mv, i) in R.moves" :key="i" class="li"><span>{{ mv.kind === 'in' ? '↓' : '↑' }} {{ mv.reason }} <small>{{ mv.user }} · {{ tm(mv.at) }}</small></span><b>{{ mv.kind === 'in' ? '+' : '−' }}{{ money(mv.amount) }}</b></div>
        </div>
        <p v-if="R.open_orders" class="warn">⚠️ {{ R.open_orders }} ta ochiq buyurtma bor — topshirishdan oldin to'lang yoki bekor qiling.</p>
      </div>

      <div v-else-if="step === 2" class="pane">
        <div class="mode"><button type="button" :class="{ on: !manual }" @click="manual = false">Kupyuralar bo'yicha</button><button type="button" :class="{ on: manual }" @click="manual = true">Summani yozaman</button></div>
        <div v-if="!manual" class="den">
          <div v-for="d in denoms" :key="d" class="dr" :class="{ has: counts[d] }">
            <span class="nt">{{ money(d).replace(' so\'m', '') }}</span>
            <button type="button" aria-label="kamaytirish" @click="inc(d, -1)">−</button>
            <input :value="counts[d] || ''" inputmode="numeric" placeholder="0" :aria-label="`${d} so'mlik soni`" @input="counts = { ...counts, [d]: Math.max(0, parseInt(($event.target as HTMLInputElement).value) || 0) }" />
            <button type="button" aria-label="ko'paytirish" @click="inc(d, 1)">+</button>
            <b>{{ counts[d] ? money(d * counts[d]) : '' }}</b>
          </div>
        </div>
        <UiInput v-else v-model="manualSum" type="number" label="Kassadagi naqd (sanab yozing)" suffix="so'm" />
        <div class="cmp">
          <div><small>Kutilgan</small><b>{{ money(T.expected_cash) }}</b></div>
          <div><small>Sanalgan</small><b>{{ money(counted) }}</b></div>
          <div :class="diff === 0 ? 'ok' : 'bad'"><small>{{ diff === 0 ? 'Farq' : diff < 0 ? 'Kamomad' : 'Ortiqcha' }}</small><b>{{ diff === 0 ? '✓ 0' : money(Math.abs(diff)) }}</b></div>
        </div>
        <UiInput v-if="diff !== 0" v-model="reason" label="Farq sababi (majburiy)" placeholder="Masalan: qaytim xato berildi, 10 000 so'm yirtiq kupyura" />
        <UiInput v-if="T.by_method?.card" v-model="cardZ" type="number" label="Terminal Z-hisoboti (karta), ixtiyoriy" suffix="so'm" :hint="cardDiff === null ? `Tizimda karta: ${money(T.by_method.card)}` : cardDiff === 0 ? '✓ Terminal bilan mos' : `⚠️ Terminal farqi: ${money(cardDiff)}`" />
      </div>

      <div v-else class="pane">
        <div class="cmp">
          <div><small>Sanalgan naqd</small><b>{{ money(counted) }}</b></div>
          <div><small>Kassada qoladi</small><b>{{ money(Number(left || 0)) }}</b></div>
          <div class="ok"><small>Topshiriladi</small><b>{{ money(handed) }}</b></div>
        </div>
        <UiInput v-model="left" type="number" label="Kassada keyingi smenaga qoldiriladi (maydalash uchun)" suffix="so'm" />
        <div class="quick"><button type="button" @click="left = 0">Hammasini topshirish</button><button type="button" @click="left = Math.min(R.shift.cash_start, counted)">Boshlang'ich ({{ money(R.shift.cash_start) }})</button></div>
        <label class="sel"><span>Kimga topshiriladi</span>
          <select v-model="handedTo"><option value="">— tanlang (ixtiyoriy) —</option><option v-for="p in H?.receivers ?? []" :key="p.id" :value="p.id">{{ p.name }}{{ p.role ? ' · ' + p.role : '' }}</option></select>
        </label>
        <UiInput v-model="note" label="Izoh (ixtiyoriy)" />
        <p class="hint">Qabul qiluvchiga Telegram'da hisobot va «✅ Qabul qildim» tugmasi boradi. Farq bo'lsa — rahbarlarga ham xabar ketadi.</p>
      </div>
    </template>

    <template #footer>
      <template v-if="!shift && !done"><span class="sp"></span><UiButton variant="brand" :loading="busy" @click="openShift">Smenani ochish</UiButton></template>
      <template v-else-if="done"><UiButton variant="secondary" @click="print">🖨 Chop etish</UiButton><span class="sp"></span><UiButton @click="emit('close')">Tayyor</UiButton></template>
      <template v-else>
        <UiButton v-if="step > 1" variant="ghost" @click="step--">← Orqaga</UiButton><span class="sp"></span>
        <UiButton v-if="step < 3" variant="brand" @click="next">Keyingi →</UiButton>
        <UiButton v-else variant="brand" :loading="busy" @click="closeShift">🤝 Kassani topshirish</UiButton>
      </template>
    </template>
  </UiDrawer>
</template>

<style scoped>
.hint { margin: 0; font-size: var(--fs-xs); color: var(--muted); }
.acc { display: flex; gap: 10px; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 12px; background: var(--info-tint); flex-wrap: wrap; }
.acc span { display: flex; flex-direction: column; } .acc small { color: var(--muted); font-size: var(--fs-xs); }
.recent h4, .moves h4 { margin: 4px 0 6px; font-size: var(--fs-s); }
.rr { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 8px; align-items: center; padding: 7px 0; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.rr span:first-child { display: flex; flex-direction: column; } .rr small { color: var(--muted); font-size: var(--fs-xs); }
.steps { list-style: none; margin: 0; padding: 0; display: flex; gap: 6px; }
.steps li { flex: 1; display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 12px; background: var(--surface-2); font-weight: 700; font-size: var(--fs-s); color: var(--muted); }
.steps li i { font-style: normal; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-3); font-size: 12px; }
.steps li.on { background: var(--accent-tint); color: var(--accent); } .steps li.on i { background: var(--accent); color: #fff; }
.steps li.ok { color: var(--ok); cursor: pointer; } .steps li.ok i { background: var(--ok); color: #fff; }
.pane { display: flex; flex-direction: column; gap: 12px; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.tiles div, .cmp div { padding: 10px 12px; border-radius: 12px; background: var(--surface-2); display: flex; flex-direction: column; min-width: 0; }
.tiles small, .cmp small { color: var(--muted); font-size: var(--fs-xs); font-weight: 700; } .tiles b, .cmp b { font-size: var(--fs-b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.list, .moves { display: flex; flex-direction: column; }
.li { display: flex; justify-content: space-between; gap: 10px; padding: 8px 2px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.li.mu span { color: var(--ink-2); } .li small { color: var(--muted); font-size: var(--fs-xs); }
.li.big { font-size: var(--fs-b); border-top: 2px solid var(--line); } .li.big b { color: var(--accent); }
.warn { margin: 0; padding: 8px 12px; border-radius: 10px; background: var(--warn-tint); color: var(--warn-ink); font-weight: 700; font-size: var(--fs-s); }
.mode { display: flex; gap: 6px; } .mode button { flex: 1; border: 1px solid var(--line); background: var(--surface-2); border-radius: 10px; padding: 8px; font: inherit; font-weight: 700; cursor: pointer; color: var(--ink-2); }
.mode button.on { background: var(--ink); color: var(--surface); border-color: var(--ink); }
.den { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 14px; }
.dr { display: grid; grid-template-columns: 76px 36px 58px 36px minmax(0, 1fr); gap: 4px; align-items: center; }
.dr .nt { font-weight: 800; font-size: var(--fs-s); } .dr.has .nt { color: var(--accent); }
.dr button { height: 36px; border-radius: 9px; border: 1px solid var(--line); background: var(--surface); font-size: 18px; font-weight: 800; cursor: pointer; color: var(--ink); }
.dr input { height: 36px; border-radius: 9px; border: 1px solid var(--line); background: var(--surface); text-align: center; font: inherit; font-weight: 800; color: var(--ink); min-width: 0; }
.dr b { font-size: var(--fs-xs); text-align: right; color: var(--ink-2); white-space: nowrap; }
.cmp { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.cmp .ok { background: var(--ok-tint); } .cmp .ok b { color: var(--ok); } .cmp .bad { background: var(--danger-tint); } .cmp .bad b { color: var(--danger); }
.quick { display: flex; gap: 6px; flex-wrap: wrap; } .quick button { border: 1px dashed var(--line); background: transparent; border-radius: 999px; padding: 5px 11px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink-2); }
.sel { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); font-weight: 700; color: var(--ink-2); }
.sel select { min-height: 44px; border: 1px solid var(--line); border-radius: 12px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); }
.z { padding: 14px; border-radius: 12px; background: var(--surface-2); font-size: var(--fs-s); line-height: 1.55; }
.sp { flex: 1; }
@media (max-width: 600px) { .tiles { grid-template-columns: 1fr 1fr; } .den { grid-template-columns: 1fr; } .rr { grid-template-columns: minmax(0, 1fr) auto; } }
</style>
