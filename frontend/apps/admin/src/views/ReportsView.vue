<script setup lang="ts">
/**
 * Hisobotlar: P&L (daromad − tannarx − mehnat − chiqimlar), kunlik savdo, soatlar, top taomlar,
 * menyu muhandisligi (Yulduz/Ot/Jumboq/It), to'lov usullari, filiallar; chiqimlar; to'lov sozlamalari; Excel.
 * Grafiklar: bitta o'lchov = bitta rang (--chart-bar); sinflar rang + yozuv bilan.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api, auth as apiAuth } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth()
type Tab = 'pnl' | 'sales' | 'menu' | 'expenses' | 'payments'
const tab = ref<Tab>('pnl')
const d = ref<any>(null)
const loading = ref(false)
const branches = ref<any[]>([])
const iso = (x: Date) => x.toISOString().slice(0, 10)
const today = new Date()
const range = ref({ start: iso(new Date(today.getTime() - 29 * 86400000)), end: iso(today), branch_id: '' })
const PRESETS = [
  { l: 'Bugun', f: () => [iso(today), iso(today)] }, { l: 'Kecha', f: () => { const y = new Date(today.getTime() - 86400000); return [iso(y), iso(y)] } },
  { l: '7 kun', f: () => [iso(new Date(today.getTime() - 6 * 86400000)), iso(today)] }, { l: '30 kun', f: () => [iso(new Date(today.getTime() - 29 * 86400000)), iso(today)] },
  { l: 'Shu oy', f: () => [iso(new Date(today.getFullYear(), today.getMonth(), 1)), iso(today)] },
]
const TARGET = { fc: 32, labor: 25 }

async function load() {
  loading.value = true
  try {
    d.value = await api.get('/finance/dashboard', { start: range.value.start, end: range.value.end, branch_id: range.value.branch_id || undefined })
    if (!branches.value.length) branches.value = (await api.get('/branches')) ?? []
  } catch (e: any) { toast(e.detail ?? 'Hisobot yuklanmadi', 'danger') } finally { loading.value = false }
}
onMounted(() => { load(); loadExpenses(); loadPay() })
watch(range, load, { deep: true })

const p = computed(() => d.value?.pnl)
const daily = computed(() => d.value?.daily ?? [])
const maxDaily = computed(() => Math.max(1, ...daily.value.map((x: any) => x.revenue)))
const hourly = computed(() => d.value?.hourly ?? [])
const maxHour = computed(() => Math.max(1, ...hourly.value.map((x: any) => x.revenue)))
const methods = computed(() => d.value?.by_method ?? [])
const maxMethod = computed(() => Math.max(1, ...methods.value.map((x: any) => x.total)))
const ME: Record<string, { l: string; tone: any; tip: string }> = {
  star: { l: 'Yulduz', tone: 'ok', tip: 'Ko\'p sotiladi, marjasi baland — saqlang, birinchi qatorga qo\'ying' },
  plowhorse: { l: 'Ot', tone: 'warn', tip: 'Ko\'p sotiladi, marjasi past — narxni oshiring yoki tex-kartani arzonlashtiring' },
  puzzle: { l: 'Jumboq', tone: 'info', tip: 'Kam sotiladi, marjasi baland — reklama qiling, kombo\'ga qo\'shing' },
  dog: { l: 'It', tone: 'danger', tip: 'Kam sotiladi, marjasi past — menyudan olib tashlashni o\'ylang' },
}
const METHOD_L: Record<string, string> = { cash: 'Naqd', card: 'Karta', click: 'Click', payme: 'Payme', uzum: 'Uzum', transfer: 'O\'tkazma' }
const fmtD = (s: string) => new Date(s).toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit' })
const short = (v: number) => v >= 1_000_000 ? (v / 1_000_000).toFixed(1) + ' mln' : v >= 1000 ? Math.round(v / 1000) + ' ming' : String(v)
const deltaTone = (v: number | null, invert = false) => v == null ? 'muted' : (invert ? v <= 0 : v >= 0) ? 'ok' : 'danger'
function exportXlsx() {
  const url = `/api/v1/finance/export.xlsx?start=${range.value.start}&end=${range.value.end}${range.value.branch_id ? '&branch_id=' + range.value.branch_id : ''}`
  fetch(url, { headers: { Authorization: `Bearer ${apiAuth.token}` } }).then(r => r.blob()).then(b => { const u = URL.createObjectURL(b); const el = document.createElement('a'); el.href = u; el.download = `hisobot_${range.value.start}_${range.value.end}.xlsx`; el.click() })
}

// ---- chiqimlar
const expenses = ref<any[]>([]); const cats = ref<any[]>([]); const expDrawer = ref(false); const exp = ref<any>(null)
async function loadExpenses() { cats.value = await api.get('/finance/categories'); expenses.value = await api.get('/finance/expenses', { start: range.value.start, end: range.value.end }) }
function openExp(x?: any) { exp.value = x ? { ...x } : { date: iso(today), category_id: cats.value[0]?.id, amount: 0, note: '', branch_id: null }; expDrawer.value = true }
async function saveExp() {
  try { exp.value.id ? await api.put(`/finance/expenses/${exp.value.id}`, { ...exp.value, amount: Number(exp.value.amount) }) : await api.post('/finance/expenses', { ...exp.value, amount: Number(exp.value.amount) }); expDrawer.value = false; await loadExpenses(); await load(); toast('Saqlandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delExp(x: any) { if (!confirm('O\'chirilsinmi?')) return; await api.del(`/finance/expenses/${x.id}`); await loadExpenses(); await load() }
async function addCat() { const name = prompt('Yangi chiqim kategoriyasi:'); if (!name) return; await api.post('/finance/categories', { name }); await loadExpenses() }

// ---- to'lov sozlamalari
const pay = ref<any>(null); const rates = ref<any>(null)
async function loadPay() { if (a.can('core.settings.view')) pay.value = await api.get('/payments/settings').catch(() => null); rates.value = await api.get('/finance/rates').catch(() => null) }
async function savePay() { try { await api.put('/payments/settings', pay.value); toast('To\'lov sozlamalari saqlandi'); await loadPay() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
</script>

<template>
  <div class="rep">
    <div class="bar">
      <div class="presets"><button v-for="pr in PRESETS" :key="pr.l" @click="[range.start, range.end] = pr.f()">{{ pr.l }}</button></div>
      <input v-model="range.start" type="date" /><span>—</span><input v-model="range.end" type="date" />
      <UiSelect v-model="range.branch_id" :options="[{ value: '', label: 'Barcha filiallar' }, ...branches.map((b: any) => ({ value: String(b.id), label: b.name }))]" />
      <div class="sp"></div>
      <UiButton size="s" variant="secondary" @click="exportXlsx()"><UiIcon name="upload" :size="14" /> Excel</UiButton>
    </div>

    <div v-if="p" class="kpis">
      <div class="kpi inv"><span>Daromad</span><b>{{ money(p.revenue) }}</b><i :class="deltaTone(d.delta.revenue)">{{ d.delta.revenue != null ? (d.delta.revenue >= 0 ? '▲ ' : '▼ ') + Math.abs(d.delta.revenue) + '% oldingi davrga' : '' }}</i></div>
      <div class="kpi"><span>Buyurtmalar</span><b>{{ p.orders }}</b><i :class="deltaTone(d.delta.orders)">o'rtacha chek {{ money(p.avg_check) }}</i></div>
      <div class="kpi"><span>Food cost</span><b :class="{ danger: p.food_cost_percent > TARGET.fc + 8, warn: p.food_cost_percent > TARGET.fc }">{{ p.food_cost_percent }}%</b><i class="muted">maqsad ≤ {{ TARGET.fc }}% · {{ money(p.cogs) }}</i></div>
      <div class="kpi"><span>Mehnat</span><b :class="{ danger: p.labor_percent > TARGET.labor + 5, warn: p.labor_percent > TARGET.labor }">{{ p.labor_percent }}%</b><i class="muted">maqsad ≤ {{ TARGET.labor }}% · {{ money(p.labor) }}</i></div>
      <div class="kpi"><span>Prime cost</span><b>{{ p.prime_cost_percent }}%</b><i class="muted">tannarx + mehnat · me'yor ≤ 60%</i></div>
      <div class="kpi" :class="p.net_profit >= 0 ? 'good' : 'bad'"><span>Sof foyda</span><b>{{ money(p.net_profit) }}</b><i :class="deltaTone(d.delta.net_profit)">marja {{ p.net_margin_percent }}%</i></div>
    </div>

    <nav class="tabs">
      <button :class="{ on: tab === 'pnl' }" @click="tab = 'pnl'">Foyda-zarar (P&L)</button>
      <button :class="{ on: tab === 'sales' }" @click="tab = 'sales'">Savdo</button>
      <button :class="{ on: tab === 'menu' }" @click="tab = 'menu'">Menyu tahlili</button>
      <button :class="{ on: tab === 'expenses' }" @click="tab = 'expenses'">Chiqimlar</button>
      <button v-if="pay" :class="{ on: tab === 'payments' }" @click="tab = 'payments'">To'lov API (Payme/Click)</button>
    </nav>

    <!-- P&L -->
    <div v-if="tab === 'pnl' && p" class="two">
      <UiCard title="Foyda-zarar hisoboti" :subtitle="`${p.period.start} — ${p.period.end} · ${p.period.days} kun`">
        <table class="pl">
          <tbody>
            <tr class="h"><td>Daromad (savdo)</td><td>{{ money(p.revenue) }}</td><td>100%</td></tr>
            <tr><td class="in">Chegirmalar</td><td class="mut">−{{ money(p.discount) }}</td><td></td></tr>
            <tr><td>Tannarx (xomashyo, tex-karta bo'yicha)</td><td>−{{ money(p.cogs) }}</td><td>{{ p.food_cost_percent }}%</td></tr>
            <tr class="h"><td>Yalpi foyda</td><td>{{ money(p.gross_profit) }}</td><td>{{ p.gross_margin_percent }}%</td></tr>
            <tr><td>Mehnat (oyliklar, HR)</td><td>−{{ money(p.labor) }}</td><td>{{ p.labor_percent }}%</td></tr>
            <tr v-for="x in p.expenses" :key="x.code"><td class="in">{{ x.category }} <small v-if="x.is_fixed" class="mut">doimiy</small></td><td>−{{ money(x.amount) }}</td><td>{{ p.revenue ? Math.round(1000 * x.amount / p.revenue) / 10 : 0 }}%</td></tr>
            <tr><td>Chiqimlar jami</td><td>−{{ money(p.expenses_total) }}</td><td>{{ p.expenses_percent }}%</td></tr>
            <tr class="h net" :class="p.net_profit >= 0 ? 'good' : 'bad'"><td>Sof foyda</td><td>{{ money(p.net_profit) }}</td><td>{{ p.net_margin_percent }}%</td></tr>
          </tbody>
        </table>
        <p v-if="p.break_even_revenue" class="hint"><UiIcon name="alert" :size="14" /> Zararsizlik nuqtasi: davrda kamida <b>{{ money(p.break_even_revenue) }}</b> savdo kerak (doimiy + mehnat xarajatini yopish uchun). Kuniga o'rtacha savdo: <b>{{ money(p.revenue_per_day) }}</b>.</p>
      </UiCard>
      <div class="col">
        <UiCard title="To'lov usullari">
          <ul class="bars"><li v-for="m in methods" :key="m.method"><span class="nm">{{ METHOD_L[m.method] ?? m.method }}</span><span class="track"><span class="fill" :style="{ width: 100 * m.total / maxMethod + '%' }"></span></span><b>{{ short(m.total) }}</b><i>{{ m.orders }}</i></li></ul>
        </UiCard>
        <UiCard v-if="d.by_branch.length > 1" title="Filiallar">
          <table class="mini"><thead><tr><th>Filial</th><th>Savdo</th><th>Chek</th><th>Food cost</th></tr></thead>
            <tbody><tr v-for="b in d.by_branch" :key="b.branch_id"><td>{{ b.name }}</td><td>{{ money(b.revenue) }}</td><td>{{ b.orders }}</td><td>{{ b.food_cost_percent }}%</td></tr></tbody></table>
        </UiCard>
        <UiCard v-if="rates?.ok" title="Valyuta kursi (MB)" subtitle="cbu.uz — import xomashyo uchun">
          <div class="rates"><span v-for="(r, c) in rates.rates" :key="c"><b>{{ c }}</b> {{ Number(r.rate).toLocaleString('uz-UZ') }} <i :class="r.diff >= 0 ? 'ok' : 'danger'">{{ r.diff >= 0 ? '+' : '' }}{{ r.diff }}</i></span></div>
        </UiCard>
      </div>
    </div>

    <!-- SAVDO -->
    <div v-else-if="tab === 'sales' && d" class="col">
      <UiCard title="Kunlik savdo" subtitle="Ustun — kunlik daromad (so'm); kursorni olib boring">
        <svg class="chart" :viewBox="`0 0 ${Math.max(600, daily.length * 24)} 220`" preserveAspectRatio="none" role="img" aria-label="Kunlik savdo">
          <line v-for="g in [0.25, 0.5, 0.75, 1]" :key="g" x1="0" :x2="Math.max(600, daily.length * 24)" :y1="200 - 180 * g" :y2="200 - 180 * g" stroke="var(--chart-grid)" stroke-width="1" />
          <g v-for="(x, i) in daily" :key="x.date">
            <rect :x="i * (Math.max(600, daily.length * 24) / daily.length) + 3" :y="200 - 180 * x.revenue / maxDaily" :width="Math.max(600, daily.length * 24) / daily.length - 6" :height="180 * x.revenue / maxDaily" rx="3" fill="var(--chart-bar)">
              <title>{{ fmtD(x.date) }}: {{ money(x.revenue) }} · {{ x.orders }} chek · tannarx {{ money(x.cogs) }}</title></rect>
            <text v-if="daily.length <= 31 && (i % Math.ceil(daily.length / 15) === 0)" :x="i * (Math.max(600, daily.length * 24) / daily.length) + (Math.max(600, daily.length * 24) / daily.length) / 2" y="215" text-anchor="middle" class="ax">{{ fmtD(x.date) }}</text>
          </g>
        </svg>
        <div class="legend"><span><i class="sw"></i> Daromad</span><span class="mut">Eng yuqori kun: {{ short(maxDaily) }}</span></div>
      </UiCard>
      <div class="two">
        <UiCard title="Soatlar bo'yicha" subtitle="Qaysi soatda odam ko'p — smena va tayyorgarlik uchun">
          <ul class="bars"><li v-for="h in hourly" :key="h.hour"><span class="nm">{{ String(h.hour).padStart(2, '0') }}:00</span><span class="track"><span class="fill" :style="{ width: 100 * h.revenue / maxHour + '%' }"></span></span><b>{{ short(h.revenue) }}</b><i>{{ h.orders }}</i></li></ul>
        </UiCard>
        <UiCard title="Top taomlar" :padded="false">
          <table class="mini"><thead><tr><th>Taom</th><th>Soni</th><th>Daromad</th><th>Marja</th><th>Ulush</th></tr></thead>
            <tbody><tr v-for="t in d.top_products" :key="t.product_id"><td>{{ t.name }}</td><td>{{ t.qty }}</td><td>{{ money(t.revenue) }}</td><td>{{ money(t.margin) }}</td><td>{{ t.share }}%</td></tr></tbody></table>
        </UiCard>
      </div>
    </div>

    <!-- MENYU TAHLILI -->
    <UiCard v-else-if="tab === 'menu' && d" title="Menyu muhandisligi" subtitle="Mashhurlik × marja (Kasavana–Smith). Har taomga aniq harakat.">
      <div class="me-legend"><span v-for="(v, k) in ME" :key="k"><UiChip :tone="v.tone">{{ v.l }}</UiChip> {{ v.tip }}</span></div>
      <table class="mini me"><thead><tr><th>Taom</th><th>Sinf</th><th>Sotildi</th><th>Bir dona marja</th><th>Daromad</th><th>Tavsiya</th></tr></thead>
        <tbody><tr v-for="t in d.menu_engineering" :key="t.product_id"><td><b>{{ t.name }}</b></td><td><UiChip :tone="ME[t.class].tone">{{ ME[t.class].l }}</UiChip></td><td>{{ t.qty }}</td><td>{{ money(t.unit_margin) }}</td><td>{{ money(t.revenue) }}</td><td class="mut">{{ ME[t.class].tip }}</td></tr></tbody></table>
      <UiEmpty v-if="!d.menu_engineering.length" title="Savdo yo'q" text="Kassa savdosi bo'lgach tahlil paydo bo'ladi." />
    </UiCard>

    <!-- CHIQIMLAR -->
    <UiCard v-else-if="tab === 'expenses'" title="Chiqimlar" subtitle="Ijara, kommunal, marketing… — P&L'ga tushadi" :padded="false">
      <template #actions><UiButton size="s" variant="ghost" @click="addCat()"><UiIcon name="plus" :size="14" /> Kategoriya</UiButton><UiButton v-if="a.can('finance.edit')" size="s" variant="brand" @click="openExp()"><UiIcon name="plus" :size="14" /> Chiqim</UiButton></template>
      <div class="lst">
        <div v-for="x in expenses" :key="x.id" class="e-row"><span class="mut">{{ x.date }}</span><span><b>{{ x.category_name }}</b><small v-if="x.note"> · {{ x.note }}</small></span><span class="mut">{{ x.branch_name ?? '' }}</span><b>{{ money(x.amount) }}</b>
          <span class="acts"><UiButton size="s" variant="ghost" @click="openExp(x)"><UiIcon name="edit" :size="13" /></UiButton><UiButton size="s" variant="ghost" @click="delExp(x)"><UiIcon name="trash" :size="13" /></UiButton></span></div>
        <UiEmpty v-if="!expenses.length" title="Bu davrda chiqim yo'q" />
      </div>
    </UiCard>

    <!-- TO'LOV API -->
    <div v-else-if="tab === 'payments' && pay" class="two">
      <UiCard title="Payme (Merchant API)" subtitle="merchant.paycom.uz → kassa → ID va kalit. Test rejimida test.paycom.uz ishlatiladi">
        <UiInput v-model="pay.payme_merchant_id" label="Merchant ID" /><UiInput v-model="pay.payme_key" label="Kalit (key)" placeholder="••• (o'zgartirish uchun yangisini yozing)" />
        <label class="chk"><input v-model="pay.payme_test" type="checkbox" /> Test rejimi</label>
        <p class="hint">Payme kabinetida endpoint: <code>{{ pay.callback_payme }}</code></p>
      </UiCard>
      <UiCard title="Click (SHOP API)" subtitle="merchant.click.uz → xizmat → service_id, merchant_id, secret key">
        <UiInput v-model="pay.click_service_id" label="Service ID" /><UiInput v-model="pay.click_merchant_id" label="Merchant ID" /><UiInput v-model="pay.click_merchant_user_id" label="Merchant user ID" /><UiInput v-model="pay.click_secret_key" label="Secret key" placeholder="•••" />
        <p class="hint">Prepare URL: <code>{{ pay.callback_click_prepare }}</code><br />Complete URL: <code>{{ pay.callback_click_complete }}</code></p>
        <UiButton variant="brand" @click="savePay()">Saqlash</UiButton>
      </UiCard>
    </div>

    <UiDrawer :open="expDrawer" :title="exp?.id ? 'Chiqim' : 'Yangi chiqim'" width="420px" @close="expDrawer = false">
      <template v-if="exp">
        <label class="fl"><span>Sana</span><input v-model="exp.date" type="date" /></label>
        <UiSelect :model-value="String(exp.category_id)" label="Kategoriya" :options="cats.map((c: any) => ({ value: String(c.id), label: c.name }))" @update:model-value="v => exp.category_id = Number(v)" />
        <UiInput v-model="exp.amount" type="number" label="Summa" suffix="so'm" /><UiInput v-model="exp.note" label="Izoh" />
        <UiSelect :model-value="String(exp.branch_id ?? '')" label="Filial" :options="[{ value: '', label: 'Umumiy' }, ...branches.map((b: any) => ({ value: String(b.id), label: b.name }))]" @update:model-value="v => exp.branch_id = v ? Number(v) : null" />
      </template>
      <template #footer><UiButton variant="ghost" @click="expDrawer = false">Bekor</UiButton><UiButton variant="brand" @click="saveExp()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.rep { display: flex; flex-direction: column; gap: 14px; }
.bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .sp { flex: 1; }
.bar input[type=date] { border: 1px solid var(--line); border-radius: var(--radius); padding: 0 10px; min-height: var(--touch); background: var(--surface); }
.presets { display: flex; gap: 4px; background: var(--surface-2); border-radius: var(--radius); padding: 3px; }
.presets button { border: 0; background: transparent; padding: 6px 10px; border-radius: var(--radius-s); font-weight: 700; font-size: var(--fs-xs); cursor: pointer; }
.presets button:hover { background: var(--surface); }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px 14px; display: flex; flex-direction: column; gap: 2px; }
.kpi.inv { background: var(--ink); color: var(--ink-inv); border-color: transparent; } .kpi.inv span, .kpi.inv i { color: var(--surface-3); }
.kpi span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .kpi b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; line-height: 1.1; }
.kpi i { font-style: normal; font-size: var(--fs-xs); font-weight: 700; } .kpi.good b { color: var(--ok); } .kpi.bad b { color: var(--danger); }
.ok, .kpi i.ok { color: var(--ok); } .danger, .kpi i.danger { color: var(--danger); } .warn { color: var(--warn); } .muted, .mut { color: var(--muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { border: 0; background: transparent; padding: 9px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.two { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; align-items: start; } .col { display: flex; flex-direction: column; gap: 14px; }
.pl { width: 100%; border-collapse: collapse; font-size: var(--fs-s); } .pl td { padding: 8px 6px; border-bottom: 1px solid var(--line-2); } .pl td:nth-child(2), .pl td:nth-child(3) { text-align: right; white-space: nowrap; }
.pl .h td { font-weight: 800; background: var(--surface-2); } .pl .in { padding-left: 22px; } .pl .net td { font-family: var(--font-display); font-size: var(--fs-l); } .pl .net.good td { color: var(--ok); } .pl .net.bad td { color: var(--danger); }
.hint { display: flex; gap: 6px; align-items: flex-start; font-size: var(--fs-xs); color: var(--muted); margin: 10px 0 0; line-height: 1.5; } .hint code { background: var(--surface-3); padding: 1px 5px; border-radius: 4px; }
.bars { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
.bars li { display: grid; grid-template-columns: 70px 1fr 64px 36px; align-items: center; gap: 8px; font-size: var(--fs-s); }
.bars .nm { color: var(--ink-2); } .track { height: 8px; background: var(--surface-3); border-radius: 4px; overflow: hidden; } .fill { display: block; height: 100%; background: var(--chart-bar); border-radius: 4px; }
.bars b { text-align: right; } .bars i { font-style: normal; color: var(--muted); font-size: var(--fs-xs); text-align: right; }
.mini { width: 100%; border-collapse: collapse; font-size: var(--fs-s); } .mini th { text-align: left; font-size: var(--fs-xs); color: var(--muted); padding: 8px 10px; border-bottom: 1px solid var(--line); } .mini td { padding: 7px 10px; border-bottom: 1px solid var(--line-2); }
.chart { width: 100%; height: 220px; } .ax { font-size: 10px; fill: var(--muted); }
.legend { display: flex; gap: 14px; font-size: var(--fs-xs); margin-top: 6px; align-items: center; } .sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; background: var(--chart-bar); vertical-align: middle; margin-right: 4px; }
.me-legend { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); color: var(--muted); margin-bottom: 10px; } .me-legend span { display: flex; gap: 8px; align-items: center; }
.rates { display: flex; gap: 12px; flex-wrap: wrap; font-size: var(--fs-s); } .rates i { font-style: normal; font-size: var(--fs-xs); }
.lst { display: flex; flex-direction: column; }
.e-row { display: grid; grid-template-columns: 90px 1.6fr 1fr auto 70px; gap: 10px; align-items: center; padding: 8px 14px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); } .e-row small { color: var(--muted); } .acts { display: flex; gap: 2px; }
.chk { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); margin: 8px 0; }
.fl { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .fl input { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; min-height: var(--touch); background: var(--surface); }
@media (max-width: 1200px) { .kpis { grid-template-columns: repeat(3, 1fr); } .two { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .kpis { grid-template-columns: 1fr 1fr; } .e-row { grid-template-columns: 1fr auto; } .e-row > :nth-child(3), .e-row > :nth-child(5) { display: none; } }
</style>
