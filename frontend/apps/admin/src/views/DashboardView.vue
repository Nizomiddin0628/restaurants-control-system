<script setup lang="ts">
/**
 * Boshqaruv paneli — menejer bir qarashda ko'radigan hamma narsa:
 * KPI (o'tgan davrga nisbatan) · savdo dinamikasi · buyurtmalar holati · eng ko'p sotilganlar ·
 * filiallar · so'nggi buyurtmalar · ombor ogohlantirishlari · tezkor amallar · bugungi vazifalar · so'nggi faoliyat.
 * Davr (bugun/kecha/7 kun/oy/yil) va filial tanlanadi; har 60 soniyada yangilanadi.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiCard, UiChip, UiEmpty, UiIcon, money } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'
import WeatherStrip from '@/components/forecast/WeatherStrip.vue'
import { useNav } from '@/nav/sections'

const a = useAuth(), router = useRouter()
const { sections, sectionLink } = useNav()
const D = ref<any>(null)
const S = ref<any>(null)
const loading = ref(false)
const period = ref<string>(localStorage.getItem('dash.period') || 'today')
const branch = ref<string>('')
const metric = ref<'revenue' | 'orders'>('revenue')
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
  timer = window.setInterval(() => { if (period.value === 'today' && !document.hidden) load() }, 60000)
})
onBeforeUnmount(() => clearInterval(timer))
watch([period, branch], () => { try { localStorage.setItem('dash.period', period.value) } catch { /* private */ } load() })

const hello = computed(() => { const h = new Date().getHours(); return h < 5 ? 'Xayrli tun' : h < 11 ? 'Xayrli tong' : h < 18 ? 'Xayrli kun' : 'Xayrli kech' })
const setupLeft = computed(() => (S.value?.checklist ?? []).filter((c: any) => !c.done))
const today = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'][new Date().getDay()]
const dateLabel = computed(() => { const d = new Date(); return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}` })

// ---------- KPI
const ICON_BG = ['var(--series-3)', 'var(--series-1)', '#7C5CC4', 'var(--series-2)', '#D0485A', '#1E8FA0']
function kval(k: any) { if (k.money && Math.abs(k.value) >= 10_000_000) return `${(k.value / 1e6).toFixed(1).replace('.', ',')} mln`; return k.money ? money(k.value) : k.percent ? `${k.value}%` : String(k.value) }
function kgood(k: any) { if (k.delta == null) return null; const up = k.delta > 0; return k.lower_is_better ? !up : up }
function kdelta(k: any) { if (k.delta == null) return ''; const v = Math.abs(k.delta); return `${k.delta > 0 ? '+' : k.delta < 0 ? '−' : ''}${v}${k.percent ? ' p.p.' : '%'}` }
function spark(vals: number[] | undefined, w = 72, h = 26) {
  if (!vals || vals.length < 2) return null
  const max = Math.max(...vals), min = Math.min(...vals), r = max - min || 1
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * (w - 4) + 2, h - 3 - ((v - min) / r) * (h - 6)])
  return { d: pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '), last: pts[pts.length - 1] }
}

// ---------- savdo dinamikasi (bitta o'q: savdo YOKI buyurtmalar — ikki o'qli grafik chalg'itadi)
const W = 640, H = 240, PL = 44, PB = 26, PT = 12
const hover = ref<number | null>(null)
const chart = computed(() => {
  const pts = D.value?.series?.points ?? []
  if (!pts.length) return null
  const vals = pts.map((p: any) => p[metric.value])
  const rawMax = Math.max(...vals, 1)
  const step = niceStep(rawMax / 4)
  const max = Math.ceil(rawMax / step) * step
  const bw = (W - PL - 8) / pts.length
  const bars = pts.map((p: any, i: number) => {
    const v = p[metric.value], hh = ((H - PB - PT) * v) / max
    return { x: PL + i * bw + bw * 0.18, w: Math.max(3, bw * 0.64), y: H - PB - hh, h: Math.max(0, hh), p, i }
  })
  const ticks = Array.from({ length: 5 }, (_, k) => ({ v: step * k, y: H - PB - ((H - PB - PT) * step * k) / max }))
  const every = Math.ceil(pts.length / 10)
  return { bars, ticks, every, bw }
})
function niceStep(x: number) { const p = Math.pow(10, Math.floor(Math.log10(x || 1))); const n = x / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p }
function short(v: number) { return metric.value === 'orders' ? String(v) : v >= 1e6 ? `${+(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : String(v) }
const hp = computed(() => (hover.value != null && chart.value ? chart.value.bars[hover.value] : null))
const nowLabel = computed(() => `${String(new Date().getHours()).padStart(2, '0')}:00`)

// ---------- buyurtmalar holati (donut)
const ST_COLOR: Record<string, string> = { done: 'var(--series-1)', cooking: 'var(--series-2)', new: 'var(--series-3)', ready: 'var(--series-4)', cancelled: 'var(--series-mute)' }
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
const F = computed(() => D.value?.forecast)
const accessReq = computed(() => a.can('core.settings.edit') ? (a.me?.tenant.settings as any)?.platform?.access_request ?? null : null)
const fmtD = (x: string) => x.split('-').reverse().join('.')
const branchName = computed(() => D.value?.branches_list.find((b: any) => String(b.id) === branch.value)?.name)
</script>

<template>
  <div v-if="D" class="db" :class="{ busy: loading }">
    <!-- SARLAVHA -->
    <header class="top">
      <div class="hi">
        <h1>{{ hello }}, {{ D.user.first_name || 'hurmatli rahbar' }}! 👋</h1>
        <p>{{ D.tenant.name }} · {{ today }}, {{ dateLabel }}<template v-if="branchName"> · {{ branchName }}</template></p>
      </div>
      <div class="ctl">
        <select v-if="D.branches_list.length > 1" v-model="branch" class="sel" aria-label="Filial">
          <option value="">Barcha filiallar ({{ D.branches_list.length }})</option>
          <option v-for="b in D.branches_list" :key="b.id" :value="String(b.id)">{{ b.name }}</option>
        </select>
        <div class="seg" role="tablist" aria-label="Davr">
          <button v-for="p in D.period.periods" :key="p.code" type="button" role="tab" :aria-selected="period === p.code" :class="{ on: period === p.code }" @click="period = p.code">{{ p.label }}</button>
        </div>
      </div>
    </header>

    <!-- BO'LIMLAR: asosiy sahifadan har bo'limga bir bosishda -->
    <nav class="secs" aria-label="Bo'limlar">
      <RouterLink v-for="sc in sections" :key="sc.code" :to="sectionLink(sc)" class="sec-t" :style="{ '--sc': sc.color }">
        <span class="sec-e">{{ sc.emoji }}</span><span class="sec-x"><b>{{ sc.title }}</b><small>{{ sc.items.length > 1 ? `${sc.items.length} ta modul` : sc.desc.split(',')[0] }}</small></span>
      </RouterLink>
    </nav>

    <RouterLink v-if="accessReq" to="/support" class="setup req">🛟 <b>Platforma yordami panelingizga kirish uchun ruxsat so'rayapti</b> — {{ accessReq.reason }}. Ko'rib chiqish →</RouterLink>
    <RouterLink v-if="setupLeft.length" :to="setupLeft[0].route" class="setup">
      <UiIcon name="alert" :size="16" /> <b>Ishga tushirish: {{ (S?.checklist.length ?? 0) - setupLeft.length }}/{{ S?.checklist.length }} tayyor.</b>
      Keyingi qadam: {{ setupLeft[0].label }} <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" />
    </RouterLink>

    <!-- BAYRAM VA OB-HAVO -->
    <section v-if="F && (F.alerts.length || F.weather.length || F.next)" class="r0" :class="{ solo: !F.weather.length }">
      <div v-if="F.alerts.length" class="alerts">
        <HolidayAlert v-for="al in F.alerts" :key="al.id" :a="al" :compact="F.alerts.length > 1" show-link />
      </div>
      <RouterLink v-else-if="F.next" :to="a.can('forecast.view') ? '/forecast' : '/'" class="nx">
        <span class="nx-i">📅</span>
        <span class="nx-b"><small>Keyingi bayram</small><b>{{ F.next.name.uz }}</b><span>{{ fmtD(F.next.date) }} · {{ F.next.days_left }} kun qoldi · savdo {{ F.next.uplift_percent >= 0 ? '+' : '' }}{{ F.next.uplift_percent }}%</span></span>
        <small class="nx-n">{{ F.next.prep_days }} kun oldin xarid rejasi tayyorlanadi</small>
      </RouterLink>
      <UiCard v-if="F.weather.length" :title="`Ob-havo · ${F.location}`" subtitle="Savdoga ta'siri prognozda hisobga olinadi">
        <template #actions><RouterLink v-if="a.can('forecast.view')" to="/forecast" class="lnk">Batafsil</RouterLink></template>
        <WeatherStrip :days="F.weather" :hints="2" />
      </UiCard>
    </section>

    <!-- KPI -->
    <section v-if="D.kpis.length" class="kpis">
      <component :is="k.route ? RouterLink : 'div'" v-for="(k, i) in D.kpis" :key="k.key" :to="k.route" class="kpi">
        <div class="kh"><span class="ki" :style="{ background: ICON_BG[i % 6] }"><UiIcon :name="k.icon || 'chart'" :size="18" /></span><span class="kl">{{ k.label }}</span></div>
        <b class="kv" :class="{ long: kval(k).length > 8 }" :title="k.money ? money(k.value) + ' so\'m' : ''">{{ kval(k) }}<small v-if="k.money"> so'm</small></b>
        <div class="kf">
          <span v-if="k.delta != null" class="kd" :class="kgood(k) ? 'good' : 'bad'">{{ k.delta > 0 ? '↑' : k.delta < 0 ? '↓' : '→' }} {{ kdelta(k) }}</span>
          <svg v-if="spark(k.spark)" class="sp" width="72" height="26" viewBox="0 0 72 26" aria-hidden="true">
            <path :d="spark(k.spark)!.d" fill="none" stroke="var(--series-mute)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
            <circle :cx="spark(k.spark)!.last[0]" :cy="spark(k.spark)!.last[1]" r="3.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2" />
          </svg>
        </div>
        <small class="kn">{{ k.prev != null ? `${k.prev_label}: ${k.money ? money(k.prev) : k.prev}` : k.norm }}<template v-if="k.norm && k.prev == null && k.ok != null"> {{ k.ok ? '✓' : '⚠' }}</template></small>
      </component>
    </section>

    <!-- 1-QATOR: dinamika · holat · top -->
    <div class="row r1">
      <UiCard v-if="D.series" :title="'Savdo dinamikasi'" :subtitle="`${D.period.label} · ${D.series.unit} bo'yicha${D.series.best ? ' · eng yuqori: ' + D.series.best : ''}`">
        <template #actions>
          <div class="seg sm"><button type="button" :class="{ on: metric === 'revenue' }" @click="metric = 'revenue'">Savdo</button><button type="button" :class="{ on: metric === 'orders' }" @click="metric = 'orders'">Buyurtmalar</button></div>
        </template>
        <div v-if="chart" class="chart" @mouseleave="hover = null">
          <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="`${metric === 'revenue' ? 'Savdo' : 'Buyurtmalar'} dinamikasi`">
            <g v-for="tk in chart.ticks" :key="tk.v"><line :x1="PL" :x2="W - 4" :y1="tk.y" :y2="tk.y" stroke="var(--line-2)" stroke-width="1" /><text :x="PL - 8" :y="tk.y + 4" text-anchor="end" class="ax">{{ short(tk.v) }}</text></g>
            <g v-for="b in chart.bars" :key="b.i">
              <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="4" :fill="(period === 'today' && b.p.label === nowLabel) || hover === b.i ? 'var(--accent)' : 'color-mix(in srgb, var(--accent) 55%, var(--surface))'" />
              <rect :x="PL + b.i * chart.bw" :y="PT" :width="chart.bw" :height="H - PB - PT" fill="transparent" @mouseenter="hover = b.i" @touchstart.passive="hover = b.i" />
              <text v-if="b.i % chart.every === 0" :x="b.x + b.w / 2" :y="H - 8" text-anchor="middle" class="ax">{{ b.p.label }}</text>
            </g>
          </svg>
          <div v-if="hp" class="tip" :style="{ left: `${((hp.x + hp.w / 2) / W) * 100}%`, top: `${(hp.y / H) * 100}%` }">
            <b>{{ hp.p.label }}</b><span>{{ money(hp.p.revenue) }} so'm</span><span>{{ hp.p.orders }} ta buyurtma</span>
          </div>
        </div>
        <UiEmpty v-else title="Bu davrda savdo yo'q" />
      </UiCard>

      <UiCard v-if="D.status" title="Buyurtmalar holati" :subtitle="D.period.label">
        <div class="dn">
          <svg viewBox="0 0 140 140" width="150" height="150" role="img" :aria-label="`Jami ${donut.total} buyurtma`">
            <circle cx="70" cy="70" :r="donut.R" fill="none" stroke="var(--surface-3)" stroke-width="16" />
            <circle v-for="sg in donut.segs" :key="sg.key" cx="70" cy="70" :r="donut.R" fill="none" :stroke="ST_COLOR[sg.key]"
                    :stroke-width="hoverSeg === sg.key ? 20 : 16" :stroke-dasharray="`${sg.len} ${donut.C}`" :stroke-dashoffset="sg.off"
                    transform="rotate(-90 70 70)" @mouseenter="hoverSeg = sg.key" @mouseleave="hoverSeg = null"><title>{{ sg.label }}: {{ sg.value }} ({{ sg.share }}%)</title></circle>
            <text x="70" y="68" text-anchor="middle" class="dt">{{ donut.total }}</text><text x="70" y="86" text-anchor="middle" class="ds">jami</text>
          </svg>
          <ul class="lg">
            <li v-for="it in D.status.items" :key="it.key" :class="{ dim: !it.value, hl: hoverSeg === it.key }" @mouseenter="hoverSeg = it.key" @mouseleave="hoverSeg = null">
              <i :style="{ background: ST_COLOR[it.key] }"></i><span>{{ it.label }}</span><b>{{ it.value }}</b><small>{{ it.share }}%</small>
            </li>
          </ul>
        </div>
        <RouterLink v-if="a.hasModule('kds')" to="/kds" class="more">Oshxona ekrani <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" /></RouterLink>
      </UiCard>

      <UiCard v-if="D.top" title="Eng ko'p sotilganlar" :subtitle="D.period.label">
        <template #actions><RouterLink to="/reports?tab=menu" class="lnk">Barchasi</RouterLink></template>
        <ol class="top5">
          <li v-for="(p, i) in D.top" :key="p.name">
            <span class="n">{{ i + 1 }}</span>
            <span class="th"><img v-if="p.image" :src="p.image" alt="" loading="lazy" referrerpolicy="no-referrer" @error="p.image = null" /><span v-else>{{ p.name.slice(0, 1) }}</span></span>
            <span class="tn"><b>{{ p.name }}</b><span class="bar"><i :style="{ width: `${(p.qty / D.top[0].qty) * 100}%` }"></i></span></span>
            <span class="tq"><b>{{ p.qty }}</b><small>{{ p.share }}%</small></span>
          </li>
        </ol>
        <UiEmpty v-if="!D.top.length" title="Hali sotuv yo'q" />
      </UiCard>
    </div>

    <!-- 2-QATOR: filiallar · so'nggi buyurtmalar · ombor -->
    <div class="row r2">
      <UiCard v-if="D.branches" title="Filiallar ko'rsatkichlari" :subtitle="D.period.label">
        <template #actions><RouterLink to="/branches" class="lnk">Barchasi</RouterLink></template>
        <table class="tb">
          <thead><tr><th>Filial</th><th class="r">Savdo</th><th class="r">Chek</th><th class="r">Food cost</th></tr></thead>
          <tbody>
            <tr v-for="b in D.branches" :key="b.id" class="click" @click="branch = String(b.id)">
              <td class="w"><UiIcon name="store" :size="14" /> {{ b.name }}</td><td class="r">{{ money(b.revenue) }}</td><td class="r">{{ b.orders }}</td>
              <td class="r"><span class="st" :class="BST[b.state][1]" :title="BST[b.state][0]"><i></i>{{ b.food_cost }}%</span></td>
            </tr>
          </tbody>
        </table>
      </UiCard>

      <UiCard v-if="D.recent" title="So'nggi buyurtmalar">
        <template #actions><RouterLink to="/pos" class="lnk">Kassa</RouterLink></template>
        <table class="tb">
          <thead><tr><th>#</th><th>Qayerga</th><th class="r">Summa</th><th>Holat</th></tr></thead>
          <tbody>
            <tr v-for="o in D.recent" :key="o.id"><td class="nt"><b>{{ o.number }}</b><small>{{ o.time }}</small></td><td class="w">{{ o.where }}</td><td class="r">{{ money(o.total) }}</td><td><UiChip :tone="RC[o.status]">{{ o.status_label }}</UiChip></td></tr>
          </tbody>
        </table>
        <UiEmpty v-if="!D.recent.length" title="Buyurtma yo'q" />
      </UiCard>

      <UiCard v-if="D.stock" title="Omborda kam qolgan" :subtitle="D.stock.count ? `${D.stock.count} ta xomashyo buyurtma qilinishi kerak` : 'Hammasi yetarli'">
        <template #actions><RouterLink to="/inventory?tab=stock" class="lnk">Barchasi</RouterLink></template>
        <ul class="stk">
          <li v-for="s in D.stock.items" :key="s.id">
            <span class="sn"><b>{{ s.name }}</b><span class="bar"><i :class="s.level" :style="{ width: `${Math.min(100, s.ratio * 66)}%` }"></i></span></span>
            <span class="sq">{{ +s.stock.toFixed(2) }} {{ s.unit }}<small>min {{ +s.min.toFixed(1) }}</small></span>
            <span class="st" :class="LV[s.level][1]"><i></i>{{ LV[s.level][0] }}</span>
          </li>
        </ul>
        <p v-if="!D.stock.items.length" class="okmsg">✓ Hamma xomashyo yetarli</p>
      </UiCard>
    </div>

    <!-- 3-QATOR: tezkor amallar · vazifalar · faoliyat -->
    <div class="row r3">
      <UiCard title="Tezkor amallar">
        <div class="qa">
          <RouterLink v-for="q in quick" :key="q.to" :to="q.to" class="qb" :class="{ main: q.main }"><span><UiIcon :name="q.icon" :size="20" /></span>{{ q.label }}</RouterLink>
        </div>
      </UiCard>

      <UiCard v-if="D.tasks" title="Bugungi vazifalar" :subtitle="`${D.tasks.open} ta ochiq${D.tasks.overdue ? ` · ${D.tasks.overdue} ta kechikkan` : ''}`">
        <template #actions><RouterLink to="/tasks" class="lnk">Barchasi</RouterLink></template>
        <ul class="tk">
          <li v-for="tk in D.tasks.items" :key="tk.id" class="click" @click="router.push(`/tasks?open=${tk.id}`)">
            <span class="cb" :class="{ on: tk.done }"><UiIcon v-if="tk.done" name="check" :size="12" /></span>
            <span class="tt" :class="{ done: tk.done }">{{ tk.title }}<small v-if="tk.assignee">{{ tk.assignee }}</small></span>
            <span class="tm" :class="{ late: tk.overdue }">{{ tk.overdue ? '⚠ ' : '' }}{{ tk.time }}</span>
          </li>
        </ul>
        <p v-if="!D.tasks.items.length" class="okmsg">✓ Bugunga vazifa qolmadi</p>
      </UiCard>

      <UiCard title="So'nggi faoliyat">
        <ul class="act">
          <li v-for="(e, i) in D.activity" :key="i">
            <UiAvatar :name="e.who" :size="32" />
            <span class="at"><b>{{ e.who }}</b><small>{{ e.text }}</small></span>
            <span class="tm">{{ e.at ? ago(e.at) : '' }}</span>
          </li>
        </ul>
        <UiEmpty v-if="!D.activity.length" title="Hali faoliyat yo'q" />
      </UiCard>
    </div>
  </div>
</template>

<style scoped>
.secs { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
.sec-t { display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line); text-decoration: none; color: var(--ink); min-width: 0; }
.sec-t:hover { border-color: var(--sc); box-shadow: 0 4px 14px rgba(0,0,0,.05); }
.sec-e { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; font-size: 22px; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 13%, transparent); }
.sec-x { display: flex; flex-direction: column; min-width: 0; } .sec-x b { font-size: var(--fs-s); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .sec-x small { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 640px) { .secs { grid-template-columns: 1fr 1fr; gap: 8px; } .sec-t { padding: 10px; } .sec-e { width: 36px; height: 36px; font-size: 19px; } }

.db { display: flex; flex-direction: column; gap: 16px; transition: opacity .2s; } .db.busy { opacity: .72; }
.top { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.hi h1 { margin: 0; font-family: var(--font-display); font-size: 28px; font-weight: 800; letter-spacing: -.02em; }
.hi p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); text-transform: none; }
.ctl { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sel { min-height: 40px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; font-weight: 700; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.seg { display: inline-flex; background: var(--surface-3); border-radius: 10px; padding: 3px; gap: 2px; }
.seg button { border: 0; background: transparent; padding: 0 12px; min-height: 34px; border-radius: 8px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; white-space: nowrap; }
.seg button.on { background: var(--ink); color: var(--surface); }
.seg.sm button { min-height: 28px; padding: 0 10px; font-size: var(--fs-xs); } .seg.sm button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.setup.req { background: #DBE7FF; color: #1E3A8A; }
.setup { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 12px; background: var(--warn-tint); color: var(--warn-ink); text-decoration: none; font-size: var(--fs-s); flex-wrap: wrap; }

.r0 { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 16px; align-items: stretch; } .r0.solo { grid-template-columns: minmax(0, 1fr); }
.r0 > :deep(.ui-card) { min-width: 0; }
.nx { display: flex; flex-direction: column; justify-content: center; gap: 10px; padding: 16px 18px; border-radius: 16px; background: var(--surface); border: 1px solid var(--line); color: var(--ink); text-decoration: none; min-width: 0; }
.nx:hover { border-color: var(--accent); }
.nx-i { font-size: 28px; } .nx-b { display: flex; flex-direction: column; gap: 2px; } .nx-b small, .nx-n { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.nx-b b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; } .nx-b span { font-size: var(--fs-s); color: var(--ink-2); }
.alerts { display: flex; flex-direction: column; gap: 10px; min-width: 0; } .alerts > * { flex: 1; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 14px; display: flex; flex-direction: column; gap: 6px; min-width: 0; color: var(--ink); text-decoration: none; transition: border-color .15s, transform .15s; }
a.kpi:hover { border-color: var(--accent); transform: translateY(-1px); }
.kh { display: flex; align-items: center; gap: 10px; }
.ki { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: #fff; flex-shrink: 0; }
.kl { font-size: var(--fs-s); font-weight: 700; color: var(--ink-2); }
.kv { font-family: var(--font-display); font-size: 22px; font-weight: 800; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kv.long { font-size: 19px; } .kv.long small { display: none; }
.kv small { font-size: 13px; font-weight: 700; color: var(--muted); }
.kf { display: flex; align-items: center; justify-content: space-between; gap: 6px; min-height: 26px; }
.kd { font-size: var(--fs-s); font-weight: 800; white-space: nowrap; } .kd.good { color: var(--ok); } .kd.bad { color: var(--danger); }
.sp { flex-shrink: 0; margin-left: auto; }
.kn { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.row { display: grid; gap: 16px; align-items: stretch; }
.r1 { grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr) minmax(0, 1.05fr); }
.r2, .r3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.row > :deep(.ui-card) { min-width: 0; }
.lnk { color: var(--accent); font-weight: 700; font-size: var(--fs-s); text-decoration: none; white-space: nowrap; }
.more { display: inline-flex; align-items: center; gap: 4px; color: var(--accent); font-weight: 700; font-size: var(--fs-s); text-decoration: none; align-self: flex-start; }

.chart { position: relative; width: 100%; }
.chart svg { width: 100%; height: 240px; display: block; }
.ax { font-size: 11px; fill: var(--muted); font-family: var(--font-body, inherit); }
.tip { position: absolute; transform: translate(-50%, calc(-100% - 8px)); background: var(--ink); color: var(--surface); border-radius: 8px; padding: 6px 10px; font-size: 12px; display: flex; flex-direction: column; pointer-events: none; white-space: nowrap; box-shadow: var(--shadow); }
.tip b { font-size: 12px; }

.dn { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; justify-content: center; }
.dn circle { transition: stroke-width .15s; cursor: pointer; }
.dt { font-family: var(--font-display); font-size: 26px; font-weight: 800; fill: var(--ink); } .ds { font-size: 11px; fill: var(--muted); }
.lg { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 170px; }
.lg li { display: grid; grid-template-columns: 12px 1fr auto 44px; gap: 8px; align-items: center; font-size: var(--fs-s); padding: 3px 6px; border-radius: 6px; }
.lg li.hl { background: var(--surface-2); } .lg li.dim { opacity: .5; }
.lg i { width: 12px; height: 12px; border-radius: 3px; } .lg b { font-variant-numeric: tabular-nums; } .lg small { color: var(--muted); text-align: right; }

.top5 { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.top5 li { display: grid; grid-template-columns: 18px 40px minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.top5 .n { font-weight: 800; color: var(--muted); font-size: var(--fs-s); }
.th { width: 40px; height: 40px; border-radius: 10px; overflow: hidden; background: var(--surface-3); display: grid; place-items: center; font-weight: 800; color: var(--muted); }
.th img { width: 100%; height: 100%; object-fit: cover; }
.tn { display: flex; flex-direction: column; gap: 5px; min-width: 0; } .tn b { font-size: var(--fs-s); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar { height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; display: block; }
.bar i { display: block; height: 100%; border-radius: 99px; background: var(--series-2); }
.tq { display: flex; flex-direction: column; align-items: flex-end; } .tq b { font-variant-numeric: tabular-nums; } .tq small { color: var(--muted); font-size: var(--fs-xs); }

.tb { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
.tb th { text-align: left; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; padding: 6px 6px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.tb td { padding: 9px 6px; border-bottom: 1px solid var(--line-2); white-space: nowrap; font-variant-numeric: tabular-nums; }
.tb tr:last-child td { border-bottom: 0; } .nt b { display: block; } .nt small { color: var(--muted); font-size: var(--fs-xs); } .tb .r { text-align: right; } .tb .w { max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.click { cursor: pointer; } .tb tr.click:hover td { background: var(--surface-2); }
.st { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 700; white-space: nowrap; }
.st i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.st.ok { color: var(--ok); } .st.warn { color: var(--warn-ink); } .st.danger { color: var(--danger); } .st.muted, .st.neutral { color: var(--muted); }

.stk { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.stk li { display: grid; grid-template-columns: minmax(0, 1fr) auto 92px; gap: 10px; align-items: center; }
.sn { display: flex; flex-direction: column; gap: 5px; min-width: 0; } .sn b { font-size: var(--fs-s); }
.bar i.critical { background: var(--danger); } .bar i.low { background: var(--warn); } .bar i.watch { background: var(--series-mute); }
.sq { font-size: var(--fs-s); font-weight: 700; text-align: right; display: flex; flex-direction: column; } .sq small { color: var(--muted); font-weight: 500; font-size: var(--fs-xs); }
.okmsg { margin: 0; color: var(--ok); font-weight: 700; font-size: var(--fs-s); }

.qa { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.qb { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 88px; padding: 10px 6px; border-radius: 14px; background: var(--surface-2); border: 1px solid var(--line-2); color: var(--ink); text-decoration: none; font-weight: 700; font-size: var(--fs-xs); text-align: center; line-height: 1.2; }
.qb span { width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; background: var(--surface); color: var(--accent); }
.qb:hover { border-color: var(--accent); }
.qb.main { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); } .qb.main span { background: color-mix(in srgb, var(--accent-ink) 18%, transparent); color: var(--accent-ink); }

.tk, .act { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.tk li { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--line-2); border-radius: 6px; } .tk li:last-child { border-bottom: 0; }
.tk li:hover { background: var(--surface-2); }
.cb { width: 20px; height: 20px; border-radius: 6px; border: 2px solid var(--line); display: grid; place-items: center; color: #fff; flex-shrink: 0; } .cb.on { background: var(--series-1); border-color: var(--series-1); }
.tt { flex: 1; min-width: 0; font-size: var(--fs-s); font-weight: 600; display: flex; flex-direction: column; } .tt small { color: var(--muted); font-weight: 500; font-size: var(--fs-xs); }
.tt.done { text-decoration: line-through; color: var(--muted); }
.tm { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; } .tm.late { color: var(--danger); font-weight: 700; }
.act li { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line-2); } .act li:last-child { border-bottom: 0; }
.at { flex: 1; min-width: 0; display: flex; flex-direction: column; } .at b { font-size: var(--fs-s); } .at small { color: var(--muted); font-size: var(--fs-xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

@media (max-width: 1400px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .r1 { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .r1 > :first-child { grid-column: 1 / -1; } }
@media (max-width: 1100px) { .r0 { grid-template-columns: minmax(0, 1fr); } .r2, .r3 { grid-template-columns: 1fr 1fr; } .r2 > :first-child, .r3 > :first-child { grid-column: 1 / -1; } }
@media (max-width: 720px) {
  .hi h1 { font-size: 22px; } .ctl { width: 100%; } .seg { width: 100%; overflow-x: auto; } .seg button { flex: 1; padding: 0 8px; } .sel { width: 100%; }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .kv { font-size: 20px; } .kpi { padding: 12px; } .ki { width: 30px; height: 30px; } .sp { display: none; }
  .r1, .r2, .r3 { grid-template-columns: 1fr; } .r1 > :first-child { grid-column: auto; } .r2 > :first-child, .r3 > :first-child { grid-column: auto; }
  .chart svg { height: 200px; } .qa { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; } .qb { min-height: 76px; font-size: 11px; }
}
</style>
