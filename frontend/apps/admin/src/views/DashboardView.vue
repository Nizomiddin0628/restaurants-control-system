<script setup lang="ts">
/**
 * Boshqaruv paneli (v50) — saytdagi uslubda: rahbar bir qarashda hammasini ko'radi.
 *   sarlavha (salom, sana, ob-havo, davr) · bo'limlar · asosiy grafik (joriy davr ↔ o'tgan davr punktir) · «Bugungi puls»
 *   (ma'lumotdan chiqarilgan xulosalar) · 5 ko'rsatkich · savdo kanallari · buyurtmalar holati · top taomlar ·
 *   filiallar · ombor · so'nggi buyurtmalar · tezkor amallar · vazifalar · faoliyat.
 * Davr (bugun/kecha/7 kun/oy/yil) va filial tanlanadi; «Bugun»da har 60 soniyada yangilanadi. Raqamlar silliq sanaladi.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiChip, UiEmpty, UiIcon, money } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import { useNav, useSectionStats } from '@/nav/sections'
import AreaChart from '@/hq/charts/AreaChart.vue'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'

const a = useAuth(), ui = useUi(), router = useRouter()
const { sections, sectionLink } = useNav()
const { stats: secStats, load: loadSec } = useSectionStats()
/** bo'lim plitkalari qatorlarni teng to'ldirsin (10 → 5×2, 9 → 3×3, 8 → 4×2) */
const secCols = computed(() => { const n = sections.value.length; return [5, 4, 3].find(c => n % c === 0) ?? 5 })
const secKpi = (code: string) => secStats.value?.[code]?.[0]
const D = ref<any>(null)
const S = ref<any>(null)
const loading = ref(false)
const period = ref<string>((() => { try { return localStorage.getItem('dash.period') || 'today' } catch { return 'today' } })())
const branch = computed(() => ui.branch)
const metric = ref<'revenue' | 'orders'>('revenue')
const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
let timer: number | undefined

async function load() {
  loading.value = true
  try {
    const q: Record<string, any> = { period: period.value }
    if (branch.value) q.branch_id = branch.value
    D.value = await api.get('/dashboard/overview', q)
  } finally { loading.value = false }
}
onMounted(async () => {
  await load()
  S.value = await api.get('/dashboard/summary').catch(() => null)
  loadSec(true, period.value)
  timer = window.setInterval(() => { if (period.value === 'today' && !document.hidden) { load(); loadSec(true, period.value) } }, 60000)
  addEventListener('resize', movePill, { passive: true })
})
onBeforeUnmount(() => { clearInterval(timer); removeEventListener('resize', movePill) })
watch([period, branch], () => { try { localStorage.setItem('dash.period', period.value) } catch { /* yopiq */ } load(); loadSec(false, period.value) })

// ---------- sarlavha
const hello = computed(() => { const h = new Date().getHours(); return h < 5 ? 'Xayrli tun' : h < 11 ? 'Xayrli tong' : h < 18 ? 'Xayrli kun' : 'Xayrli kech' })
const setupLeft = computed(() => (S.value?.checklist ?? []).filter((c: any) => !c.done))
const today = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'][new Date().getDay()]
const MON = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr']
const dateLabel = computed(() => { const d = new Date(); return `${d.getDate()}-${MON[d.getMonth()]}` })
const branchName = computed(() => D.value?.branches_list.find((b: any) => String(b.id) === branch.value)?.name)
const accessReq = computed(() => a.can('core.settings.edit') ? (a.me?.tenant.settings as any)?.platform?.access_request ?? null : null)

// davr tanlovi — siljuvchi «pill»
const segEl = ref<HTMLElement | null>(null)
const pill = ref({ x: 0, w: 0 })
function movePill() {
  const el = segEl.value?.querySelector<HTMLElement>('button.on')
  if (el) pill.value = { x: el.offsetLeft, w: el.offsetWidth }
}
watch([period, D], () => nextTick(movePill))

// ---------- raqamlar silliq sanaladi
const shown = ref<Record<string, number>>({})
function countTo(key: string, to: number, dur = 1100) {
  const from = shown.value[key] ?? 0
  if (reduce || from === to) { shown.value[key] = to; return }
  const t0 = performance.now()
  const step = (now: number) => {
    const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3)
    shown.value = { ...shown.value, [key]: from + (to - from) * e }
    if (k < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}
watch(D, (d) => { if (!d) return; for (const k of d.kpis ?? []) countTo(k.key, Number(k.value) || 0) })

// ---------- KPI
const kpi = (key: string) => (D.value?.kpis ?? []).find((k: any) => k.key === key)
const tiles = computed(() => (D.value?.kpis ?? []).filter((k: any) => k.key !== 'revenue'))
const TILE: Record<string, string> = { orders: '--series-1', avg_check: '--series-2', food_cost: '--warn', labor: '--series-4', net: '--ok' }
function short(v: number) {
  const x = Math.abs(v)
  if (x >= 1e9) return `${(v / 1e9).toFixed(2).replace('.', ',')} mlrd`
  if (x >= 1e7) return `${(v / 1e6).toFixed(1).replace('.', ',')} mln`
  return money(Math.round(v))
}
function kval(k: any) {
  const v = shown.value[k.key] ?? 0
  if (k.percent) return `${v.toFixed(1).replace('.', ',').replace(',0', '')}%`
  if (k.money) return short(v)
  return String(Math.round(v))
}
function kgood(k: any) { if (k.delta == null) return null; const up = k.delta > 0; return k.lower_is_better ? !up : up }
function kdelta(k: any) { if (k.delta == null) return ''; const v = Math.abs(k.delta); return `${k.delta > 0 ? '+' : k.delta < 0 ? '−' : ''}${String(v).replace('.', ',')}${k.percent ? ' p.p.' : '%'}` }
function spark(vals: number[] | undefined, w = 120, h = 34) {
  if (!vals || vals.length < 2) return null
  const max = Math.max(...vals), min = Math.min(...vals), r = max - min || 1
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * (w - 6) + 3, h - 4 - ((v - min) / r) * (h - 10)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  return { line, area: `${line} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z`, last: pts[pts.length - 1] }
}

// ---------- asosiy grafik: joriy ↔ o'tgan davr
const rev = computed(() => kpi('revenue'))
/** «Bugun»: hali kelmagan soatlar chizilmaydi (0 ga tushib ketgandek ko'rinmasin) */
const seriesPts = computed(() => {
  const pts = D.value?.series?.points ?? []
  if (period.value !== 'today') return pts
  const h = new Date().getHours(), idx = pts.findIndex((p: any) => Number(p.label.slice(0, 2)) === h)
  if (idx < 0) return pts
  return pts.slice(0, pts[idx].revenue > 0 || idx === 0 ? idx + 1 : idx)   // joriy soatda hali savdo bo'lmasa — oldingi soatgacha
})
const chartPts = computed(() => seriesPts.value.map((p: any) => ({ label: p.label, value: p[metric.value] })))
const comparePts = computed(() => seriesPts.value.map((p: any) => p[metric.value === 'revenue' ? 'prev_revenue' : 'prev_orders'] ?? 0))
const chartH = ref(typeof innerWidth !== 'undefined' && innerWidth < 600 ? 220 : 300)
const hasCompare = computed(() => comparePts.value.some((v: number) => v > 0))
const VS: Record<string, string> = { today: 'kechagi shu vaqtga nisbatan', yesterday: 'avvalgi kunga nisbatan', week: 'oldingi 7 kunga nisbatan', month: "o'tgan oyning shu kunlariga nisbatan", year: "o'tgan yilga nisbatan" }
const PREV_SHORT: Record<string, string> = { today: 'Kecha', yesterday: 'Avvalgi kun', week: 'Oldingi 7 kun', month: "O'tgan oy", year: "O'tgan yil" }

// ---------- «Bugungi puls» — faqat ma'lumotdan chiqarilgan xulosalar
const pulse = computed(() => {
  const d = D.value; if (!d) return []
  const out: { tone: string; icon: string; text: string; to?: string }[] = []
  const r = kpi('revenue')
  if (r && r.delta != null) out.push({ tone: r.delta >= 0 ? 'ok' : 'bad', icon: r.delta >= 0 ? '↗' : '↘', text: `Savdo ${kdelta(r)} — ${VS[period.value]}`, to: '/reports?tab=sales' })
  if (d.series?.best) out.push({ tone: 'info', icon: '⏱', text: `Eng qizg'in ${d.series.unit === 'soat' ? 'vaqt' : d.series.unit}: ${d.series.best}` })
  const ch = (d.channels ?? []).filter((c: any) => c.revenue > 0).sort((x: any, y: any) => y.revenue - x.revenue)[0]
  if (ch) out.push({ tone: 'info', icon: '◔', text: `${ch.label} — savdoning ${String(ch.share).replace('.', ',')}%` })
  if (d.top?.length) out.push({ tone: 'info', icon: '★', text: `Eng ko'p sotilgan: ${d.top[0].name} (${d.top[0].qty} ta)`, to: '/reports?tab=menu' })
  const fc = kpi('food_cost')
  if (fc && fc.value) out.push({ tone: fc.ok ? 'ok' : 'bad', icon: fc.ok ? '✓' : '!', text: `Food cost ${String(fc.value).replace('.', ',')}% — ${fc.ok ? "me'yorda" : "me'yordan yuqori"}`, to: '/reports?tab=menu' })
  if (d.stock?.count) out.push({ tone: 'warn', icon: '!', text: `${d.stock.count} ta xomashyo kam qoldi — buyurtma bering`, to: '/inventory?tab=stock' })
  if (d.tasks?.overdue) out.push({ tone: 'bad', icon: '!', text: `${d.tasks.overdue} ta vazifa muddati o'tgan`, to: '/tasks' })
  if (d.today?.weather?.effect) out.push({ tone: d.today.weather.effect > 0 ? 'ok' : 'warn', icon: d.today.weather.icon, text: `Ob-havo savdoga ta'siri: ${d.today.weather.effect > 0 ? '+' : ''}${d.today.weather.effect}%`, to: a.hasModule('forecast') ? '/forecast' : undefined })
  return out.slice(0, 6)
})

// ---------- kanallar va holat
const CH_COLOR: Record<string, string> = { dine_in: 'var(--series-1)', takeaway: 'var(--series-2)', delivery: 'var(--series-4)' }
const CH_ICON: Record<string, string> = { dine_in: 'sofa', takeaway: 'receipt', delivery: 'truck' }
const ST_COLOR: Record<string, string> = { done: 'var(--series-1)', cooking: 'var(--chart-active)', new: 'var(--series-4)', ready: 'var(--series-3)', cancelled: 'var(--series-mute)' }
const donut = computed(() => {
  const items = (D.value?.status?.items ?? []).filter((x: any) => x.value > 0)
  const total = D.value?.status?.total || 0
  const R = 52, C = 2 * Math.PI * R, gap = items.length > 1 ? 3 : 0
  let acc = 0
  return { total, R, C, segs: items.map((x: any) => { const len = total ? (C * x.value) / total : 0; const s = { ...x, len: Math.max(0, len - gap), off: -acc }; acc += len; return s }) }
})
const hoverSeg = ref<string | null>(null)

// ---------- qolganlar
const RC: Record<string, any> = { new: 'info', cooking: 'warn', ready: 'ok', done: 'neutral', delivered: 'accent' }
const LV: Record<string, [string, any]> = { critical: ['Kritik', 'danger'], low: ['Kam', 'warn'], watch: ['Kuzatuvda', 'neutral'] }
const BST: Record<string, [string, string]> = { ok: ['Yaxshi', 'ok'], warn: ['E\'tibor', 'warn'], bad: ['Yuqori', 'danger'], idle: ['Savdo yo\'q', 'muted'] }
const brMax = computed(() => Math.max(1, ...(D.value?.branches ?? []).map((b: any) => b.revenue)))
const ago = (iso: string) => { const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000); return m < 1 ? 'hozir' : m < 60 ? `${m} daq` : m < 1440 ? `${Math.floor(m / 60)} soat` : `${Math.floor(m / 1440)} kun` }
const QUICK = [
  { to: '/pos', label: 'Yangi buyurtma', icon: 'plus', mod: 'pos', perm: 'pos.sell', main: true },
  { to: '/kds', label: 'Oshxona ekrani', icon: 'play', mod: 'kds', perm: 'kds.view' },
  { to: '/inventory?tab=purchases', label: 'Ombor kirimi', icon: 'box', mod: 'inventory', perm: 'inventory.view' },
  { to: '/reports', label: 'Hisobotlar', icon: 'chart', mod: 'finance', perm: 'finance.view' },
  { to: '/catalog', label: 'Menyu', icon: 'book', mod: 'catalog', perm: 'catalog.view' },
  { to: '/tasks', label: 'Vazifa qo\'shish', icon: 'check', mod: 'tasks', perm: 'tasks.view' },
  { to: '/reservations', label: 'Bron', icon: 'calendar', mod: 'reservations', perm: 'reservations.view' },
  { to: '/users', label: 'Xodim qo\'shish', icon: 'users', mod: '', perm: 'core.users.manage' },
]
const quick = computed(() => QUICK.filter(q => (!q.mod || a.hasModule(q.mod)) && a.can(q.perm)).slice(0, 8))
</script>

<template>
  <div v-if="D" class="db" :class="{ busy: loading }">
    <!-- SARLAVHA -->
    <header class="hd">
      <div class="hi">
        <span class="eyebrow"><i class="live" :class="{ on: period === 'today' }"></i>{{ today }}, {{ dateLabel }}<template v-if="branchName"> · {{ branchName }}</template></span>
        <h1>{{ hello }}, <span class="grad">{{ D.user.first_name || 'rahbar' }}</span></h1>
        <p>{{ D.tenant.name }}
          <RouterLink v-if="D.today?.weather" :to="a.hasModule('forecast') ? '/forecast' : '/'" class="wx" :title="`${D.today.weather.label}${D.today.weather.effect ? ` · savdoga ta'siri ${D.today.weather.effect > 0 ? '+' : ''}${D.today.weather.effect}%` : ''}`">
            {{ D.today.weather.icon }} {{ D.today.weather.t_max }}°<small>/{{ D.today.weather.t_min }}°</small> {{ D.today.weather.city }}</RouterLink></p>
      </div>
      <div ref="segEl" class="seg" role="tablist" aria-label="Davr">
        <span class="pill" :style="{ width: pill.w + 'px', transform: `translateX(${pill.x}px)` }" aria-hidden="true"></span>
        <button v-for="p in D.period.periods" :key="p.code" type="button" role="tab" :aria-selected="period === p.code" :class="{ on: period === p.code }" @click="period = p.code">{{ p.label }}</button>
      </div>
    </header>

    <!-- bayram yaqin -->
    <section v-if="D.today?.alerts?.length" class="prep">
      <HolidayAlert v-for="al in D.today.alerts" :key="al.id" :a="al" :show-link="a.hasModule('inventory')" @plan="router.push('/forecast')">
        <div class="pc-todo">
          <span class="pc-h">Nima qilish kerak:</span>
          <RouterLink v-for="(td, i) in al.todo.slice(1)" :key="i" :to="td.route" :title="td.text" :class="{ done: td.done }">
            <span class="ti">{{ td.done ? '✅' : td.icon }}</span><span class="tt">{{ td.short || td.text }}</span></RouterLink>
          <RouterLink v-if="a.hasModule('forecast')" to="/forecast" class="pc-l">Prognoz →</RouterLink>
        </div>
      </HolidayAlert>
    </section>
    <RouterLink v-else-if="D.today?.holiday" :to="a.hasModule('forecast') ? '/forecast' : '/'" class="hol">
      <span class="hol-i">🎉</span>
      <span class="hol-t"><b>Bugun: {{ D.today.holiday.name.uz || D.today.holiday.name }}</b>
        <small>Savdo odatdagidan {{ D.today.holiday.uplift_percent >= 0 ? '+' : '' }}{{ D.today.holiday.uplift_percent }}% kutilmoqda — xodimlar va xomashyoni tekshiring</small></span>
      <UiIcon name="chevron" :size="16" style="transform: rotate(-90deg)" />
    </RouterLink>

    <RouterLink v-if="accessReq" to="/support" class="setup req">🛟 <b>Platforma yordami panelingizga kirish uchun ruxsat so'rayapti</b> — {{ accessReq.reason }}. Ko'rib chiqish →</RouterLink>
    <RouterLink v-if="setupLeft.length" :to="setupLeft[0].route" class="setup">
      <span class="sp-ring" :style="{ '--p': ((S?.checklist.length ?? 0) - setupLeft.length) / (S?.checklist.length || 1) }"></span>
      <b>Ishga tushirish: {{ (S?.checklist.length ?? 0) - setupLeft.length }}/{{ S?.checklist.length }} tayyor.</b>
      Keyingi qadam: {{ setupLeft[0].label }} <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" />
    </RouterLink>

    <!-- BO'LIMLAR -->
    <nav class="secs" aria-label="Bo'limlar" :style="{ '--cols': secCols }">
      <RouterLink v-for="(sc, i) in sections" :key="sc.code" :to="sectionLink(sc)" class="sec" :style="{ '--sc': sc.color, '--i': i }">
        <span class="sec-i"><UiIcon :name="sc.icon" :size="18" /></span>
        <span class="sec-x"><b>{{ sc.title }}</b>
          <small v-if="secKpi(sc.code)" :class="secKpi(sc.code)?.tone" :title="`${secKpi(sc.code)?.label}: ${secKpi(sc.code)?.value}`"><strong>{{ secKpi(sc.code)?.value }}</strong> {{ secKpi(sc.code)?.label }}</small>
          <small v-else>{{ sc.items.length > 1 ? `${sc.items.length} ta modul` : sc.desc.split(',')[0] }}</small></span>
      </RouterLink>
    </nav>

    <!-- ASOSIY: grafik + puls -->
    <div class="grid g-main">
      <section v-if="D.series && rev" class="card hero">
        <div class="hero-h">
          <div>
            <span class="lbl">Savdo · {{ D.period.label }}</span>
            <div class="big"><b>{{ kval(rev) }}</b><small v-if="!kval(rev).includes('mln') && !kval(rev).includes('mlrd')">so'm</small>
              <span v-if="rev.delta != null" class="dp" :class="kgood(rev) ? 'good' : 'bad'">{{ rev.delta > 0 ? '↑' : rev.delta < 0 ? '↓' : '→' }} {{ kdelta(rev) }}</span></div>
            <span class="sub">{{ rev.prev_label }}: {{ money(rev.prev) }} so'm</span>
          </div>
          <div class="hero-c">
            <div class="mini">
              <button type="button" :class="{ on: metric === 'revenue' }" @click="metric = 'revenue'">Savdo</button>
              <button type="button" :class="{ on: metric === 'orders' }" @click="metric = 'orders'">Buyurtmalar</button>
            </div>
            <div class="legend"><span><i class="l1"></i>{{ D.period.label }}</span><span v-if="hasCompare"><i class="l2"></i>{{ PREV_SHORT[period] }}</span></div>
          </div>
        </div>
        <AreaChart v-if="chartPts.length && chartPts.some((p: any) => p.value > 0)" :key="period + metric" :points="chartPts" :compare="hasCompare ? comparePts : undefined" :compare-label="PREV_SHORT[period]"
                   :money="metric === 'revenue'" :unit="metric === 'orders' ? 'ta' : ''" :height="chartH" color="var(--accent)" />
        <UiEmpty v-else title="Bu davrda savdo yo'q" />
      </section>

      <section class="card pulse">
        <header class="ch"><h3><span class="pdot"></span>Bugungi puls</h3><small>{{ D.period.label }}</small></header>
        <ul>
          <li v-for="(x, i) in pulse" :key="i" :class="x.tone" :style="{ '--i': i }">
            <component :is="x.to ? RouterLink : 'div'" :to="x.to" class="pl">
              <span class="pi">{{ x.icon }}</span><span class="pt">{{ x.text }}</span><UiIcon v-if="x.to" name="chevron" :size="14" class="pc" />
            </component>
          </li>
        </ul>
        <p v-if="!pulse.length" class="okmsg">Ma'lumot yig'ilmoqda — birinchi savdodan keyin shu yerda xulosalar chiqadi.</p>
        <div class="qa">
          <RouterLink v-for="q in quick.slice(0, 4)" :key="q.to" :to="q.to" class="qb" :class="{ main: q.main }"><UiIcon :name="q.icon" :size="16" />{{ q.label }}</RouterLink>
        </div>
      </section>
    </div>

    <!-- KO'RSATKICHLAR -->
    <section v-if="tiles.length" class="tiles">
      <component :is="k.route ? RouterLink : 'div'" v-for="(k, i) in tiles" :key="k.key" :to="k.route" class="tile" :style="{ '--tc': `var(${TILE[k.key] || '--accent'})`, '--i': i }">
        <div class="t-h"><span class="t-i"><UiIcon :name="k.icon || 'chart'" :size="16" /></span><span class="t-l">{{ k.label }}</span></div>
        <b class="t-v">{{ kval(k) }}<small v-if="k.money && !kval(k).includes('mln') && !kval(k).includes('mlrd')"> so'm</small></b>
        <svg v-if="spark(k.spark)" class="t-sp" viewBox="0 0 120 34" preserveAspectRatio="none" aria-hidden="true">
          <defs><linearGradient :id="`tg${k.key}`" x1="0" y1="0" x2="0" y2="1"><stop offset="0" :style="{ stopColor: `var(${TILE[k.key] || '--accent'})`, stopOpacity: .24 }" /><stop offset="1" :style="{ stopColor: `var(${TILE[k.key] || '--accent'})`, stopOpacity: 0 }" /></linearGradient></defs>
          <path :d="spark(k.spark)!.area" :fill="`url(#tg${k.key})`" />
          <path :d="spark(k.spark)!.line" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" class="t-ln" pathLength="1" />
        </svg>
        <div class="t-r"><small class="t-n" :title="k.prev != null ? `${k.prev_label}: ${k.money ? short(k.prev) : k.prev}` : k.norm">{{ k.prev != null ? `${k.prev_label}: ${k.money ? short(k.prev) : k.prev}` : k.norm }}<template v-if="k.norm && k.prev == null && k.ok != null"> {{ k.ok ? '✓' : '⚠' }}</template></small>
          <span v-if="k.delta != null" class="dp sm" :class="kgood(k) ? 'good' : 'bad'">{{ k.delta > 0 ? '↑' : k.delta < 0 ? '↓' : '→' }} {{ kdelta(k) }}</span></div>
      </component>
    </section>

    <!-- 1-QATOR: kanallar · holat · top -->
    <div class="grid g3">
      <section v-if="D.channels" class="card">
        <header class="ch"><h3>Savdo kanallari</h3><small>{{ D.period.label }}</small></header>
        <div class="stack" role="img" :aria-label="D.channels.map((c: any) => `${c.label} ${c.share}%`).join(', ')">
          <i v-for="c in D.channels" :key="c.key" :style="{ flexGrow: c.share || 0.0001, background: CH_COLOR[c.key] }"></i>
        </div>
        <ul class="chl">
          <li v-for="c in D.channels" :key="c.key" :class="{ dim: !c.revenue }">
            <span class="chi" :style="{ color: CH_COLOR[c.key] }"><UiIcon :name="CH_ICON[c.key]" :size="16" /></span>
            <span class="chn"><b>{{ c.label }}</b><small>{{ c.orders }} ta buyurtma</small></span>
            <span class="chv"><b>{{ short(c.revenue) }}</b><small>{{ String(c.share).replace('.', ',') }}%</small></span>
          </li>
        </ul>
      </section>

      <section v-if="D.status" class="card">
        <header class="ch"><h3>Buyurtmalar holati</h3><RouterLink v-if="a.hasModule('kds')" to="/kds" class="lnk">Oshxona →</RouterLink></header>
        <div class="dn">
          <svg viewBox="0 0 140 140" width="148" height="148" role="img" :aria-label="`Jami ${donut.total} buyurtma`">
            <circle cx="70" cy="70" :r="donut.R" fill="none" stroke="var(--surface-3)" stroke-width="14" />
            <circle v-for="sg in donut.segs" :key="sg.key + period" cx="70" cy="70" :r="donut.R" fill="none" :stroke="ST_COLOR[sg.key]" class="seg-c"
                    :stroke-width="hoverSeg === sg.key ? 19 : 14" :stroke-dasharray="`${sg.len} ${donut.C}`" :stroke-dashoffset="sg.off" stroke-linecap="butt"
                    :style="{ '--len': sg.len, '--C': donut.C }" transform="rotate(-90 70 70)" @mouseenter="hoverSeg = sg.key" @mouseleave="hoverSeg = null"><title>{{ sg.label }}: {{ sg.value }} ({{ sg.share }}%)</title></circle>
            <text x="70" y="70" text-anchor="middle" class="dt">{{ donut.total }}</text><text x="70" y="88" text-anchor="middle" class="ds">buyurtma</text>
          </svg>
          <ul class="lg">
            <li v-for="it in D.status.items" :key="it.key" :class="{ dim: !it.value, hl: hoverSeg === it.key }" @mouseenter="hoverSeg = it.key" @mouseleave="hoverSeg = null">
              <i :style="{ background: ST_COLOR[it.key] }"></i><span>{{ it.label }}</span><b>{{ it.value }}</b>
            </li>
          </ul>
        </div>
      </section>

      <section v-if="D.top" class="card">
        <header class="ch"><h3>Eng ko'p sotilganlar</h3><RouterLink to="/reports?tab=menu" class="lnk">Barchasi →</RouterLink></header>
        <ol class="top5">
          <li v-for="(p, i) in D.top" :key="p.name" :style="{ '--i': i }">
            <span class="th"><img v-if="p.image" :src="p.image" alt="" loading="lazy" referrerpolicy="no-referrer" @error="p.image = null" /><span v-else>{{ p.name.slice(0, 1) }}</span><em>{{ i + 1 }}</em></span>
            <span class="tn"><b>{{ p.name }}</b><span class="bar"><i :style="{ '--w': p.qty / D.top[0].qty }"></i></span></span>
            <span class="tq"><b>{{ p.qty }}</b><small>{{ String(p.share).replace('.', ',') }}%</small></span>
          </li>
        </ol>
        <UiEmpty v-if="!D.top.length" title="Hali sotuv yo'q" />
      </section>
    </div>

    <!-- 2-QATOR: filiallar · ombor · so'nggi buyurtmalar -->
    <div class="grid g3">
      <section v-if="D.branches" class="card">
        <header class="ch"><h3>Filiallar</h3><RouterLink to="/branches" class="lnk">Barchasi →</RouterLink></header>
        <ul class="brl">
          <li v-for="(b, i) in D.branches" :key="b.id" :style="{ '--i': i }" :class="{ on: String(b.id) === branch }" @click="ui.setBranch(b.id)">
            <div class="br-h"><b><UiIcon name="store" :size="14" /> {{ b.name }}</b><span>{{ short(b.revenue) }}</span></div>
            <div class="bar lg2"><i :style="{ '--w': b.revenue / brMax }"></i></div>
            <div class="br-f"><small>{{ b.orders }} ta chek</small><span class="st" :class="BST[b.state][1]" :title="BST[b.state][0]"><i></i>Food cost {{ String(b.food_cost).replace('.', ',') }}%</span></div>
          </li>
        </ul>
      </section>

      <section v-if="D.stock" class="card">
        <header class="ch"><h3>Omborda kam qolgan</h3><RouterLink to="/inventory?tab=stock" class="lnk">Barchasi →</RouterLink></header>
        <p class="cs">{{ D.stock.count ? `${D.stock.count} ta xomashyo buyurtma qilinishi kerak` : 'Hammasi yetarli' }}</p>
        <ul class="stk">
          <li v-for="(s, i) in D.stock.items" :key="s.id" :style="{ '--i': i }">
            <span class="sn"><b>{{ s.name }}</b><span class="bar"><i :class="s.level" :style="{ '--w': Math.min(1, s.ratio * 0.66) }"></i></span></span>
            <span class="sq">{{ +s.stock.toFixed(2) }} {{ s.unit }}<small>min {{ +s.min.toFixed(1) }}</small></span>
            <span class="st" :class="LV[s.level][1]"><i></i>{{ LV[s.level][0] }}</span>
          </li>
        </ul>
        <p v-if="!D.stock.items.length" class="okmsg">✓ Hamma xomashyo yetarli</p>
      </section>

      <section v-if="D.recent" class="card">
        <header class="ch"><h3><span v-if="period === 'today'" class="pdot"></span>So'nggi buyurtmalar</h3><RouterLink to="/pos" class="lnk">Kassa →</RouterLink></header>
        <ul class="feed">
          <li v-for="(o, i) in D.recent" :key="o.id" :style="{ '--i': i }">
            <span class="fn"><b>#{{ o.number }}</b><small>{{ o.time }}</small></span>
            <span class="fw">{{ o.where }}</span>
            <span class="fs"><b>{{ money(o.total) }}</b><UiChip :tone="RC[o.status]">{{ o.status_label }}</UiChip></span>
          </li>
        </ul>
        <UiEmpty v-if="!D.recent.length" title="Buyurtma yo'q" />
      </section>
    </div>

    <!-- 3-QATOR: tezkor amallar · vazifalar · faoliyat -->
    <div class="grid g3">
      <section class="card">
        <header class="ch"><h3>Tezkor amallar</h3></header>
        <div class="qgrid">
          <RouterLink v-for="q in quick" :key="q.to" :to="q.to" class="qg" :class="{ main: q.main }"><span><UiIcon :name="q.icon" :size="20" /></span>{{ q.label }}</RouterLink>
        </div>
      </section>

      <section v-if="D.tasks" class="card">
        <header class="ch"><h3>Bugungi vazifalar</h3><RouterLink to="/tasks" class="lnk">Barchasi →</RouterLink></header>
        <p class="cs">{{ D.tasks.open }} ta ochiq<template v-if="D.tasks.overdue"> · <b class="late">{{ D.tasks.overdue }} ta kechikkan</b></template></p>
        <ul class="tk">
          <li v-for="tk in D.tasks.items" :key="tk.id" @click="router.push(`/tasks?open=${tk.id}`)">
            <span class="cb" :class="{ on: tk.done }"><UiIcon v-if="tk.done" name="check" :size="12" /></span>
            <span class="tt" :class="{ done: tk.done }">{{ tk.title }}<small v-if="tk.assignee">{{ tk.assignee }}</small></span>
            <span class="tm" :class="{ late: tk.overdue }">{{ tk.overdue ? '⚠ ' : '' }}{{ tk.time }}</span>
          </li>
        </ul>
        <p v-if="!D.tasks.items.length" class="okmsg">✓ Bugunga vazifa qolmadi</p>
      </section>

      <section class="card">
        <header class="ch"><h3>So'nggi faoliyat</h3></header>
        <ul class="act">
          <li v-for="(e, i) in D.activity" :key="i">
            <UiAvatar :name="e.who" :size="30" />
            <span class="at"><b>{{ e.who }}</b><small>{{ e.text }}</small></span>
            <span class="tm">{{ e.at ? ago(e.at) : '' }}</span>
          </li>
        </ul>
        <UiEmpty v-if="!D.activity.length" title="Hali faoliyat yo'q" />
      </section>
    </div>
  </div>
  <div v-else class="db sk" aria-busy="true"><i class="s1"></i><i class="s2"></i><i class="s3"></i><i class="s4"></i></div>
</template>

<style scoped>
.db { display: flex; flex-direction: column; gap: 18px; transition: opacity .25s; } .db.busy { opacity: .75; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; min-width: 0; box-shadow: var(--shadow-s);
  animation: up .7s cubic-bezier(.2,.8,.2,1) both; }
@keyframes up { from { opacity: 0; transform: translateY(12px); } }
.grid { display: grid; gap: 16px; align-items: stretch; }
.g-main { grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); }
.g3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.ch { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.ch h3 { margin: 0; font-size: 15px; font-weight: 700; letter-spacing: -.01em; display: flex; align-items: center; gap: 8px; }
.ch small { font: 600 11px var(--font-mono); color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.lnk { color: var(--accent); font-weight: 700; font-size: var(--fs-s); text-decoration: none; white-space: nowrap; } .lnk:hover { text-decoration: underline; text-underline-offset: 3px; }
.cs { margin: -8px 0 0; font-size: var(--fs-s); color: var(--muted); } .cs .late { color: var(--danger); }
.okmsg { margin: 0; color: var(--ok); font-weight: 700; font-size: var(--fs-s); }
.pdot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 0 color-mix(in srgb, var(--ok) 60%, transparent); animation: ping 2s infinite; flex-shrink: 0; }
@keyframes ping { 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }

/* sarlavha */
.hd { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.eyebrow { display: inline-flex; align-items: center; gap: 8px; font: 600 11px var(--font-mono); letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.live { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); } .live.on { background: var(--ok); animation: ping 2s infinite; }
.hi h1 { margin: 8px 0 6px; font: 600 clamp(24px, 2.4vw, 32px)/1.1 var(--font-brand); letter-spacing: -.03em; }
.grad { background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent; }
.hi p { margin: 0; color: var(--ink-2); font-size: var(--fs-b); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.wx { display: inline-flex; align-items: center; gap: 3px; padding: 3px 10px; border-radius: 99px; background: var(--surface); border: 1px solid var(--line); color: var(--ink-2); text-decoration: none; font-weight: 700; font-size: var(--fs-xs); white-space: nowrap; }
.wx small { color: var(--muted); font-weight: 600; } .wx:hover { border-color: var(--accent); }
.seg { position: relative; display: inline-flex; gap: 2px; padding: 4px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line); box-shadow: var(--shadow-s); max-width: 100%; overflow-x: auto; scrollbar-width: none; }
.seg::-webkit-scrollbar { display: none; }
.seg .pill { position: absolute; top: 4px; bottom: 4px; left: 0; border-radius: 10px; background: var(--grad); box-shadow: 0 8px 18px -8px var(--accent); transition: transform .5s cubic-bezier(.2,.8,.2,1), width .5s cubic-bezier(.2,.8,.2,1); }
.seg button { position: relative; z-index: 1; border: 0; background: transparent; padding: 0 14px; min-height: 34px; border-radius: 10px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; white-space: nowrap; transition: color .3s; }
.seg button:hover { color: var(--ink); } .seg button.on { color: #fff; }

.setup { display: flex; align-items: center; gap: 10px; padding: 11px 14px; border-radius: 14px; background: var(--warn-tint); color: var(--warn-ink); text-decoration: none; font-size: var(--fs-s); flex-wrap: wrap; border: 1px solid color-mix(in srgb, var(--warn) 25%, transparent); }
.setup.req { background: var(--accent-tint); color: var(--accent); border-color: color-mix(in srgb, var(--accent) 25%, transparent); }
.sp-ring { width: 18px; height: 18px; border-radius: 50%; background: conic-gradient(currentColor calc(var(--p) * 360deg), color-mix(in srgb, currentColor 22%, transparent) 0); -webkit-mask: radial-gradient(circle, transparent 5px, #000 6px); mask: radial-gradient(circle, transparent 5px, #000 6px); }

/* bo'limlar */
.secs { display: grid; grid-template-columns: repeat(var(--cols, 5), minmax(0, 1fr)); gap: 10px; }
@media (max-width: 1240px) { .secs { grid-template-columns: repeat(auto-fill, minmax(176px, 1fr)); } }
.sec { position: relative; display: flex; align-items: center; gap: 11px; padding: 11px 12px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line); text-decoration: none; color: var(--ink); min-width: 0; overflow: hidden;
  transition: transform .3s cubic-bezier(.2,.8,.2,1), border-color .3s, box-shadow .3s; animation: up .6s calc(var(--i) * 35ms) cubic-bezier(.2,.8,.2,1) both; }
.sec::after { content: ''; position: absolute; inset: auto -30% -70% auto; width: 70%; height: 100%; background: radial-gradient(closest-side, color-mix(in srgb, var(--sc) 22%, transparent), transparent); opacity: 0; transition: opacity .4s; pointer-events: none; }
.sec:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--sc) 55%, var(--line)); box-shadow: var(--shadow); } .sec:hover::after { opacity: 1; }
.sec-i { width: 36px; height: 36px; border-radius: 11px; display: grid; place-items: center; flex-shrink: 0; color: var(--sc); background: color-mix(in srgb, var(--sc) 14%, transparent); }
.sec-x { display: flex; flex-direction: column; min-width: 0; } .sec-x b { font-size: 13px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sec-x small { font-size: 11.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sec-x small strong { color: var(--ink); } .sec-x small.bad strong { color: var(--danger); } .sec-x small.warn strong { color: var(--warn); }

/* asosiy grafik */
.hero { gap: 10px; }
.hero-h { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.lbl { font: 600 11px var(--font-mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.big { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin: 6px 0 2px; }
.big b { font: 600 clamp(28px, 3vw, 40px)/1 var(--font-brand); letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
.big small { font-size: 15px; font-weight: 700; color: var(--muted); }
.sub { font-size: var(--fs-s); color: var(--muted); }
.dp { display: inline-flex; align-items: center; gap: 3px; padding: 3px 9px; border-radius: 99px; font-size: 12.5px; font-weight: 800; white-space: nowrap; align-self: center; }
.dp.good { color: var(--ok); background: color-mix(in srgb, var(--ok) 13%, transparent); } .dp.bad { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); }
.dp.sm { padding: 2px 7px; font-size: 11px; flex-shrink: 0; }
.t-r { display: flex; align-items: center; justify-content: space-between; gap: 6px; min-width: 0; min-height: 21px; }
.hero-c { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.mini { display: inline-flex; padding: 3px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line-2); }
.mini button { border: 0; background: transparent; padding: 0 11px; min-height: 28px; border-radius: 8px; font: inherit; font-size: var(--fs-xs); font-weight: 700; color: var(--muted); cursor: pointer; transition: background-color .25s, color .25s; }
.mini button.on { background: var(--surface); color: var(--ink); box-shadow: var(--shadow-s); }
.legend { display: flex; gap: 14px; font-size: var(--fs-xs); color: var(--muted); font-weight: 600; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 16px; height: 0; border-top: 2.5px solid var(--accent); border-radius: 2px; } .legend i.l2 { border-top: 2px dashed var(--muted); }

/* puls */
.pulse { background: linear-gradient(160deg, color-mix(in srgb, var(--accent) 7%, var(--surface)), var(--surface) 55%); }
.pulse ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.pulse li { animation: up .55s calc(.15s + var(--i) * 70ms) cubic-bezier(.2,.8,.2,1) both; }
.pl { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 11px; color: var(--ink); text-decoration: none; background: color-mix(in srgb, var(--surface-2) 70%, transparent); border: 1px solid var(--line-2); transition: border-color .2s, transform .2s; }
a.pl:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); transform: translateX(2px); }
.pi { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; flex-shrink: 0; font-size: 13px; font-weight: 800; }
.ok .pi { background: color-mix(in srgb, var(--ok) 15%, transparent); color: var(--ok); } .bad .pi { background: color-mix(in srgb, var(--danger) 13%, transparent); color: var(--danger); }
.warn .pi { background: color-mix(in srgb, var(--warn) 14%, transparent); color: var(--warn); } .info .pi { background: color-mix(in srgb, var(--accent) 13%, transparent); color: var(--accent); }
.pt { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; line-height: 1.35; } .pc { color: var(--muted); transform: rotate(-90deg); flex-shrink: 0; }
.qa { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: auto; }
.qb { display: flex; align-items: center; gap: 7px; padding: 9px 10px; border-radius: 11px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); text-decoration: none; font-size: 12.5px; font-weight: 700; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: border-color .2s; }
.qb :deep(svg) { color: var(--accent); flex-shrink: 0; } .qb:hover { border-color: var(--accent); }
.qb.main { background: var(--grad); color: #fff; border-color: transparent; box-shadow: 0 8px 18px -10px var(--accent); } .qb.main :deep(svg) { color: #fff; }

/* ko'rsatkichlar */
.tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.tile { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 14px 14px 12px; border-radius: var(--radius-l); background: var(--surface); border: 1px solid var(--line); color: var(--ink); text-decoration: none; min-width: 0; overflow: hidden;
  box-shadow: var(--shadow-s); transition: transform .3s cubic-bezier(.2,.8,.2,1), border-color .3s, box-shadow .3s; animation: up .6s calc(.1s + var(--i) * 60ms) cubic-bezier(.2,.8,.2,1) both; }
a.tile:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--tc) 50%, var(--line)); box-shadow: var(--shadow); }
.t-h { display: flex; align-items: center; gap: 8px; min-width: 0; }
.t-i { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; color: var(--tc); background: color-mix(in srgb, var(--tc) 14%, transparent); flex-shrink: 0; }
.t-l { font-size: 12.5px; font-weight: 700; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.t-v { font: 600 22px/1.15 var(--font-brand); letter-spacing: -.03em; min-width: 0; margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.t-v small { font: 700 12px var(--font); color: var(--muted); letter-spacing: 0; }
.t-sp { width: 100%; height: 34px; color: var(--tc); display: block; margin: 2px 0 0; }
.t-ln { stroke-dasharray: 1; stroke-dashoffset: 1; animation: draw 1.4s .3s cubic-bezier(.33,1,.68,1) forwards; }
@keyframes draw { to { stroke-dashoffset: 0; } }
.t-n { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* kanallar */
.stack { display: flex; gap: 3px; height: 12px; border-radius: 99px; overflow: hidden; }
.stack i { flex-basis: 0; min-width: 2px; border-radius: 3px; transform-origin: left; animation: sx .9s .2s cubic-bezier(.2,.8,.2,1) both; }
@keyframes sx { from { transform: scaleX(0); } }
.chl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.chl li { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 9px 0; border-bottom: 1px solid var(--line-2); } .chl li:last-child { border-bottom: 0; }
.chl li.dim { opacity: .55; }
.chi { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: color-mix(in srgb, currentColor 13%, transparent); }
.chn, .chv { display: flex; flex-direction: column; min-width: 0; } .chn b { font-size: 13.5px; } .chn small, .chv small { font-size: 11.5px; color: var(--muted); }
.chv { align-items: flex-end; } .chv b { font-size: 13.5px; font-variant-numeric: tabular-nums; }

/* holat — donut */
.dn { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; justify-content: center; flex: 1; }
.seg-c { transition: stroke-width .2s; cursor: pointer; animation: arc 1.1s cubic-bezier(.2,.8,.2,1) both; }
@keyframes arc { from { stroke-dasharray: 0 var(--C); } }
.dt { font: 600 26px var(--font-brand); fill: var(--ink); letter-spacing: -.03em; } .ds { font-size: 11px; fill: var(--muted); }
.lg { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 150px; }
.lg li { display: grid; grid-template-columns: 10px 1fr auto; gap: 9px; align-items: center; font-size: 13px; padding: 5px 8px; border-radius: 8px; transition: background-color .2s; }
.lg li.hl { background: var(--surface-2); } .lg li.dim { opacity: .45; }
.lg i { width: 10px; height: 10px; border-radius: 3px; } .lg b { font-variant-numeric: tabular-nums; }

/* top taomlar, ombor, filiallar — umumiy chiziq */
.bar { height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; display: block; }
.bar i { display: block; height: 100%; width: 100%; border-radius: 99px; background: var(--grad); transform-origin: left; transform: scaleX(var(--w, 0)); animation: bw 1.1s calc(.2s + var(--i, 0) * 80ms) cubic-bezier(.2,.8,.2,1) both; }
@keyframes bw { from { transform: scaleX(0); } }
.top5 { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 11px; }
.top5 li { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; gap: 12px; align-items: center; }
.th { position: relative; width: 42px; height: 42px; border-radius: 12px; background: var(--surface-3); display: grid; place-items: center; font-weight: 800; color: var(--muted); }
.th img { width: 100%; height: 100%; object-fit: cover; border-radius: inherit; }
.th em { position: absolute; top: -5px; left: -5px; min-width: 18px; height: 18px; border-radius: 99px; display: grid; place-items: center; font: 700 10px var(--font-mono); font-style: normal; background: var(--surface); border: 1px solid var(--line); color: var(--ink-2); }
.top5 li:first-child .th em { background: var(--grad); color: #fff; border-color: transparent; }
.tn { display: flex; flex-direction: column; gap: 6px; min-width: 0; } .tn b { font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tq { display: flex; flex-direction: column; align-items: flex-end; } .tq b { font-variant-numeric: tabular-nums; } .tq small { color: var(--muted); font-size: var(--fs-xs); }
.brl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.brl li { display: flex; flex-direction: column; gap: 7px; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--line-2); cursor: pointer; transition: border-color .2s, background-color .2s; }
.brl li:hover { border-color: color-mix(in srgb, var(--accent) 40%, var(--line)); } .brl li.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 6%, transparent); }
.br-h, .br-f { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.br-h b { display: inline-flex; align-items: center; gap: 6px; font-size: 13.5px; min-width: 0; } .br-h span { font-weight: 800; font-variant-numeric: tabular-nums; font-size: 13.5px; }
.br-f small { color: var(--muted); font-size: 11.5px; } .bar.lg2 { height: 7px; }
.st { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 700; white-space: nowrap; }
.st i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.st.ok { color: var(--ok); } .st.warn { color: var(--warn); } .st.danger { color: var(--danger); } .st.muted, .st.neutral { color: var(--muted); }
.stk { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.stk li { display: grid; grid-template-columns: minmax(0, 1fr) auto 84px; gap: 10px; align-items: center; }
.sn { display: flex; flex-direction: column; gap: 6px; min-width: 0; } .sn b { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar i.critical { background: var(--danger); } .bar i.low { background: var(--warn); } .bar i.watch { background: var(--series-mute); }
.sq { font-size: 12.5px; font-weight: 700; text-align: right; display: flex; flex-direction: column; font-variant-numeric: tabular-nums; } .sq small { color: var(--muted); font-weight: 500; font-size: var(--fs-xs); }
.feed { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.feed li { display: grid; grid-template-columns: 62px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line-2); animation: up .5s calc(var(--i) * 50ms) cubic-bezier(.2,.8,.2,1) both; } .feed li:last-child { border-bottom: 0; }
.fn { display: flex; flex-direction: column; } .fn b { font: 700 12.5px var(--font-mono); } .fn small { color: var(--muted); font-size: 11px; font-family: var(--font-mono); }
.fw { font-size: 13px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fs { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; } .fs b { font-size: 13px; font-variant-numeric: tabular-nums; }

/* tezkor amallar, vazifalar, faoliyat */
.qgrid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.qg { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 86px; padding: 10px 6px; border-radius: 14px; background: var(--surface-2); border: 1px solid var(--line-2); color: var(--ink); text-decoration: none; font-weight: 700; font-size: 11.5px; text-align: center; line-height: 1.2; transition: border-color .2s, transform .25s cubic-bezier(.2,.8,.2,1); }
.qg span { width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; background: var(--surface); color: var(--accent); box-shadow: var(--shadow-s); }
.qg:hover { border-color: var(--accent); transform: translateY(-2px); }
.qg.main { background: var(--grad); color: #fff; border-color: transparent; } .qg.main span { background: rgba(255, 255, 255, .18); color: #fff; box-shadow: none; }
.tk, .act { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.tk li { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-bottom: 1px solid var(--line-2); border-radius: 8px; cursor: pointer; } .tk li:last-child { border-bottom: 0; }
.tk li:hover { background: var(--surface-2); }
.cb { width: 20px; height: 20px; border-radius: 7px; border: 2px solid var(--line); display: grid; place-items: center; color: #fff; flex-shrink: 0; } .cb.on { background: var(--ok); border-color: var(--ok); }
.tt { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; display: flex; flex-direction: column; } .tt small { color: var(--muted); font-weight: 500; font-size: var(--fs-xs); }
.tt.done { text-decoration: line-through; color: var(--muted); }
.tm { font: 500 11px var(--font-mono); color: var(--muted); white-space: nowrap; } .tm.late { color: var(--danger); font-weight: 700; }
.act li { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line-2); } .act li:last-child { border-bottom: 0; }
.at { flex: 1; min-width: 0; display: flex; flex-direction: column; } .at b { font-size: 13px; } .at small { color: var(--muted); font-size: var(--fs-xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* bayram */
.hol { display: flex; align-items: center; gap: 12px; padding: 11px 14px; border-radius: 14px; text-decoration: none; color: var(--ink);
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 14%, var(--surface)), var(--surface)); border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--line)); }
.hol-i { font-size: 24px; } .hol-t { flex: 1; display: flex; flex-direction: column; min-width: 0; } .hol-t small { color: var(--ink-2); font-size: var(--fs-xs); }
.prep { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap: 12px; }
.pc-todo { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.pc-h { font-size: var(--fs-xs); font-weight: 800; color: var(--ink-2); margin-right: 2px; }
.pc-todo a { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 99px; background: var(--surface); border: 1px solid var(--line); color: var(--ink); text-decoration: none; font-size: var(--fs-xs); font-weight: 700; white-space: nowrap; }
.pc-todo a:hover { border-color: var(--accent); } .pc-todo a.done { color: var(--muted); } .pc-todo a.done .tt { text-decoration: line-through; }
.pc-todo .ti { font-size: 14px; } .pc-todo a.pc-l { margin-left: auto; background: transparent; border-color: transparent; color: var(--accent); }

/* yuklanish skeleti */
.sk { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.sk i { height: 120px; border-radius: var(--radius-l); background: linear-gradient(90deg, var(--surface) 30%, var(--surface-2) 50%, var(--surface) 70%) 0 0 / 300% 100%; border: 1px solid var(--line); animation: shim 1.4s linear infinite; }
.sk .s1 { grid-column: 1 / -1; height: 70px; } .sk .s4 { grid-column: 1 / -1; height: 280px; }
@keyframes shim { to { background-position: -300% 0; } }

@media (max-width: 1400px) {
  .tiles { grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; } .t-v { font-size: 19px; }
}
@media (max-width: 1240px) {
  .g-main { grid-template-columns: 1fr; } .pulse ul { display: grid; grid-template-columns: 1fr 1fr; } .qa { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .tiles { grid-template-columns: repeat(6, minmax(0, 1fr)); } .tile { grid-column: span 2; } .tile:nth-child(n+4) { grid-column: span 3; }
  .g3 { grid-template-columns: 1fr 1fr; } .g3 > :first-child { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .db { gap: 14px; }
  .hd { align-items: stretch; } .seg { width: 100%; } .seg button { flex: 1; padding: 0 8px; }
  .secs { grid-template-columns: 1fr 1fr; gap: 8px; } .sec { padding: 10px; } .sec-i { width: 32px; height: 32px; } .sec-x b { white-space: normal; line-height: 1.2; }
  .card { padding: 14px; }
  .hero-c { align-items: flex-start; width: 100%; flex-direction: row; justify-content: space-between; flex-wrap: wrap; }
  .pulse ul { grid-template-columns: 1fr; } .qa { grid-template-columns: 1fr 1fr; }
  .tiles { grid-template-columns: 1fr 1fr; } .tile, .tile:nth-child(n+4) { grid-column: auto; } .tile:last-child:nth-child(odd) { grid-column: 1 / -1; } .t-v { font-size: 18px; }
  .g3 { grid-template-columns: 1fr; } .g3 > :first-child { grid-column: auto; }
  .qgrid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; } .qg { min-height: 76px; font-size: 10.5px; }
  .pc-h { width: 100%; } .pc-todo a.pc-l { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) { .card, .sec, .tile, .feed li, .pulse li { animation: none; } }
</style>
