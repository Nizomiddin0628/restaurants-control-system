<script setup lang="ts">
/**
 * Tashkiliy tuzilma: rahbar → direktorlar → har filial → menejer → smena → xodimlar.
 * Kompyuterda — daraxt (kattalashtirish, sudrab tashlash), telefonda — ochiladigan ro'yxat. Chop etish / PDF.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiDrawer, UiEmpty, UiIcon, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import OrgNode from '@/components/ops/OrgNode.vue'
import PositionEditor from '@/components/ops/PositionEditor.vue'
import DepartmentsDrawer from '@/components/ops/DepartmentsDrawer.vue'

const a = useAuth(), router = useRouter()
const T = ref<any>(null)
const meta = ref<any>(null)
const canEdit = computed(() => a.can('ops.edit'))
const phone = window.matchMedia('(max-width: 720px)').matches
const mode = ref<'tree' | 'list'>(phone ? 'list' : 'tree')
const zoom = ref(1)
const sel = ref<any>(null)
const detail = ref<any>(null)
const editor = ref(false)
const edValue = ref<any>(null)
const depts = ref(false)
const busy = ref(false)
/** Filiallar boshida yig'iq — daraxt ekranga sig'adi; «Hammasini ochish» bilan to'liq ko'rinadi */
const allOpen = ref(false)
const treeKey = ref(0)
const hlShort = ref(false)
function toggleAll() { allOpen.value = !allOpen.value; treeKey.value++; fit() }
/** Tepadagi ko'rsatkichlar: bosilsa — bo'limlar oynasi, lavozimlar, xodimlar yoki bo'sh o'rinlar ajratiladi */
function kpiGo(k: 'dept' | 'pos' | 'emp' | 'short') {
  if (k === 'dept') depts.value = true
  else if (k === 'pos') router.push('/positions')
  else if (k === 'emp') router.push('/hr')
  else { hlShort.value = !hlShort.value; if (hlShort.value && !allOpen.value) toggleAll() }
}

const chartEl = ref<HTMLElement | null>(null), rootEl = ref<HTMLElement | null>(null)
async function load() {
  ;[T.value, meta.value] = await Promise.all([api.get('/ops/tree'), api.get('/ops/meta')])
}
/** Daraxt ekranga sig'sin: eni va bo'yiga qarab kichraytiriladi (kamida 45%) va o'rtaga suriladi. */
async function fit() {
  await nextTick()
  const c = chartEl.value, r = rootEl.value
  if (!c || !r) return
  zoom.value = 1
  await nextTick()
  const w = r.scrollWidth, h = r.scrollHeight
  const k = Math.min(1, (c.clientWidth - 40) / w, Math.max(0.6, (c.clientHeight - 40) / h))
  zoom.value = Math.max(0.45, Math.floor(k * 20) / 20)
  await nextTick()
  c.scrollLeft = (c.scrollWidth - c.clientWidth) / 2
  c.scrollTop = 0
}
const zoomBy = (d: number) => { zoom.value = Math.min(1.5, Math.max(0.4, +(zoom.value + d).toFixed(2))) }
/** Sichqoncha bilan bo'sh joydan ushlab surish (pan) va Ctrl + g'ildirak bilan zoom */
let pan: { x: number; y: number; l: number; t: number } | null = null
function panStart(e: PointerEvent) {
  const c = chartEl.value
  if (!c || e.pointerType !== 'mouse' || (e.target as HTMLElement).closest('.card, .sc, .br, button')) return
  pan = { x: e.clientX, y: e.clientY, l: c.scrollLeft, t: c.scrollTop }
  c.setPointerCapture(e.pointerId); c.classList.add('grab')
}
function panMove(e: PointerEvent) { const c = chartEl.value; if (!pan || !c) return; c.scrollLeft = pan.l - (e.clientX - pan.x); c.scrollTop = pan.t - (e.clientY - pan.y) }
function panEnd() { pan = null; chartEl.value?.classList.remove('grab') }
function onWheel(e: WheelEvent) { if (!e.ctrlKey) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? 0.1 : -0.1) }
onMounted(async () => { await load(); fit() })
watch(mode, (m) => { if (m === 'tree') fit() })

async function pick(n: any) {
  sel.value = n
  detail.value = await api.get(`/ops/positions/${n.id}`)
}
async function onMove(v: { id: number; to: number }) {
  const from = meta.value.positions.find((p: any) => p.id === v.id)?.name, to = meta.value.positions.find((p: any) => p.id === v.to)?.name
  if (!confirm(`«${from}» endi «${to}» ga bo'ysunsinmi?`)) return
  try { await api.post(`/ops/positions/${v.id}/move`, { reports_to_id: v.to }); toast('Tuzilma yangilandi'); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function useTemplate() {
  busy.value = true
  try { const r = await api.post('/ops/template'); toast(`Tayyor: ${r.departments} bo'lim, ${r.positions} yangi lavozim`); await load(); fit() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
function newPos() { edValue.value = null; editor.value = true }
function editPos() { edValue.value = detail.value; editor.value = true }
async function onSaved(p: any) { editor.value = false; await load(); if (p?.id) { detail.value = p } }
async function onDeleted() { editor.value = false; detail.value = null; sel.value = null; await load() }
const S = computed(() => T.value?.stats)
function doPrint() { window.print() }
const hasTree = computed(() => (T.value?.roots?.length ?? 0) > 0)
</script>

<template>
  <div v-if="T && meta" class="org">
    <!-- tepa: statistika va amallar -->
    <div class="top">
      <div class="st">
        <button type="button" class="kpi-click" :disabled="!canEdit" @click="kpiGo('dept')"><span class="st-i">🗂️</span><b>{{ S.departments }}</b><span>bo'lim</span></button>
        <button type="button" class="kpi-click" @click="kpiGo('pos')"><span class="st-i">🧩</span><b>{{ S.positions }}</b><span>lavozim</span></button>
        <button type="button" class="kpi-click" @click="kpiGo('emp')"><span class="st-i">👥</span><b>{{ S.employees }}</b><span>xodim</span></button>
        <button type="button" class="kpi-click" :class="{ warn: S.short, on: hlShort }" @click="kpiGo('short')"><span class="st-i">🪑</span><b>{{ S.short }}</b><span>bo'sh o'rin · shtat {{ S.headcount }}</span></button>
      </div>
      <div class="ac">
        <div v-if="!phone" class="seg" role="tablist" aria-label="Ko'rinish">
          <button type="button" :class="{ on: mode === 'tree' }" @click="mode = 'tree'">Daraxt</button>
          <button type="button" :class="{ on: mode === 'list' }" @click="mode = 'list'">Ro'yxat</button>
        </div>
        <UiButton v-if="mode === 'tree' && hasTree" variant="ghost" size="s" @click="toggleAll()"><UiIcon name="columns" :size="14" /> {{ allOpen ? 'Filiallarni yig\'ish' : 'Hammasini ochish' }}</UiButton>
        <UiButton v-if="canEdit" variant="ghost" size="s" @click="depts = true"><UiIcon name="columns" :size="14" /> Bo'limlar</UiButton>
        <UiButton variant="ghost" size="s" @click="doPrint()"><UiIcon name="receipt" :size="14" /> Chop etish</UiButton>
        <UiButton v-if="canEdit" variant="brand" size="s" @click="newPos()"><UiIcon name="plus" :size="14" /> Lavozim</UiButton>
      </div>
    </div>

    <!-- bo'sh holat: bir bosishda tayyor tuzilma -->
    <UiCard v-if="!meta.has_structure && canEdit" class="hero">
      <div class="hero-in">
        <span class="hero-i">🏢</span>
        <div>
          <h2>Tuzilmani 1 bosishda yarating</h2>
          <p>Restoran uchun tayyor shablon: 9 bo'lim va 17 lavozim (Rahbar, Operatsion direktor, Filial menejeri, Smena menejeri, Oshpaz, Kassir, Ofitsiant…). Har lavozimning maqsadi va asosiy vazifalari yozilgan. Mavjud lavozimlaringiz saqlanadi, keyin xohlaganingizcha o'zgartirasiz.</p>
          <div class="hero-b"><UiButton variant="brand" :loading="busy" @click="useTemplate()">Tayyor shablonni qo'yish</UiButton><UiButton variant="ghost" @click="newPos()">O'zim yarataman</UiButton></div>
        </div>
      </div>
    </UiCard>

    <p v-if="hlShort" class="flt">🪑 Bo'sh o'rinli lavozimlar ajratilgan — {{ S.short }} o'rin to'ldirilishi kerak · <button type="button" @click="hlShort = false">bekor qilish ✕</button></p>
    <div class="body">
      <UiCard :padded="false" class="chart-card">
        <div v-if="mode === 'tree' && hasTree" class="zoom no-print">
          <button type="button" aria-label="Kattalashtirish" title="Kattalashtirish" @click="zoomBy(0.1)">+</button>
          <span class="zv">{{ Math.round(zoom * 100) }}%</span>
          <button type="button" aria-label="Kichraytirish" title="Kichraytirish" @click="zoomBy(-0.1)">−</button>
          <button type="button" aria-label="Ekranga moslash" title="Ekranga moslash" @click="fit()">⤢</button>
        </div>
        <div v-if="hasTree && mode === 'tree'" ref="chartEl" class="chart" :class="{ hls: hlShort }" @pointerdown="panStart" @pointermove="panMove" @pointerup="panEnd" @pointercancel="panEnd" @wheel="onWheel">
          <ul ref="rootEl" :key="treeKey" class="root" :style="{ zoom }">
            <OrgNode v-for="r in T.roots" :key="`${r.type}${r.id}`" :n="r" mode="tree" :selected="sel?.id" :can-edit="canEdit" :collapse="!allOpen && S.branches > 1" @pick="pick" @move="onMove" @toggle="fit()" />
          </ul>
        </div>
        <ul v-else-if="hasTree" class="list">
          <OrgNode v-for="r in T.roots" :key="`${r.type}${r.id}`" :n="r" mode="list" :selected="sel?.id" @pick="pick" @move="onMove" />
        </ul>
        <UiEmpty v-else title="Hali lavozim yo'q" text="«Lavozim» tugmasi bilan qo'shing yoki tayyor shablonni qo'ying." />
        <p v-if="mode === 'tree' && hasTree" class="hint no-print">💡 Filialni bosing — ichi ochiladi. Bo'sh joydan ushlab suring, Ctrl + g'ildirak — kattalashtirish.<template v-if="canEdit"> Lavozimni boshqasining ustiga sudrab tashlasangiz — unga bo'ysunadigan bo'ladi.</template></p>
      </UiCard>

      <!-- tanlangan lavozim: qisqa kartochka -->
    </div>
    <UiDrawer :open="!!detail" :title="detail?.name ?? ''" width="560px" @close="detail = null; sel = null">
      <div v-if="detail" class="pd">
        <div class="pd-h" :style="{ '--c': detail.department?.color ?? 'var(--line)' }">
          <span class="pd-i">{{ detail.icon }}</span>
          <div><b>{{ detail.name }}</b><small>{{ detail.department ? `${detail.department.icon} ${detail.department.name}` : 'Bo\'limsiz' }} · {{ detail.level_label }}</small></div>
        </div>
        <p v-if="detail.purpose" class="pd-p">{{ detail.purpose }}</p>
        <dl class="pd-dl">
          <dt>Rahbari</dt><dd>{{ detail.reports_to?.name ?? '—' }}</dd>
          <dt>Qo'l ostida</dt><dd>{{ detail.subordinates.map((s: any) => s.name).join(', ') || '—' }}</dd>
          <dt>Qayerda</dt><dd>{{ detail.scope_label }}</dd>
          <dt>Xodimlar</dt><dd>{{ detail.employees.length }}<template v-if="detail.headcount"> / shtat {{ detail.headcount }}{{ detail.scope === 'branch' ? ' har filialda' : '' }}</template></dd>
        </dl>
        <div class="pd-c">
          <div><b>{{ detail.counts.responsibilities }}</b><span>vazifa</span></div>
          <div><b>{{ detail.counts.courses }}</b><span>kurs</span></div>
          <div><b>{{ detail.counts.standards }}</b><span>standart</span></div>
          <div><b>{{ detail.kpi.avg ?? '—' }}</b><span>KPI</span></div>
        </div>
        <ul v-if="detail.employees.length" class="pd-e">
          <li v-for="e in detail.employees.slice(0, 6)" :key="e.id"><UiAvatar :name="e.name" :src="e.avatar" :size="28" /><span>{{ e.name }}<small>{{ e.branch ?? '' }}</small></span></li>
        </ul>
        <div class="pd-b">
          <RouterLink :to="`/positions?id=${detail.id}`" class="lnk">To'liq lavozim kartasi →</RouterLink>
          <UiButton v-if="canEdit" size="s" variant="ghost" @click="editPos()"><UiIcon name="edit" :size="14" /> Tahrirlash</UiButton>
        </div>
      </div>
    </UiDrawer>

    <PositionEditor :open="editor" :value="edValue" :meta="meta" @close="editor = false" @saved="onSaved" @deleted="onDeleted" />
    <DepartmentsDrawer :open="depts" :departments="meta.departments" @close="depts = false" @changed="load()" />
  </div>
</template>

<style scoped>
.org { display: flex; flex-direction: column; gap: 14px; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.st { display: flex; gap: 10px; flex-wrap: wrap; }
.st button { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 10px 30px 10px 12px; display: flex; align-items: center; gap: 8px; min-height: 48px; }
.st button:disabled { cursor: default; } .st-i { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-2); font-size: 16px; }
.st b { font-family: var(--font-display); font-size: var(--fs-l); font-variant-numeric: tabular-nums; } .st span:last-child { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.st .warn { border-color: color-mix(in srgb, var(--warn) 50%, var(--line)); background: var(--warn-tint); }
.flt { margin: 0; padding: 8px 12px; border-radius: 12px; background: var(--warn-tint); font-size: var(--fs-s); } .flt button { border: 0; background: none; color: var(--accent); font: inherit; font-weight: 700; cursor: pointer; }
.ac { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.seg { display: inline-flex; background: var(--surface-3); border-radius: 10px; padding: 3px; }
.seg button { border: 0; background: transparent; padding: 0 12px; min-height: 32px; border-radius: 8px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; }
.seg button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.hero-in { display: flex; gap: 16px; align-items: flex-start; } .hero-i { font-size: 44px; }
.hero h2 { margin: 0 0 6px; font-family: var(--font-display); } .hero p { margin: 0; color: var(--ink-2); max-width: 760px; }
.hero-b { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-items: start; }
.chart-card { position: relative; min-width: 0; }
.chart { overflow: auto; padding: 28px 16px 36px; height: max(460px, calc(100dvh - 250px)); cursor: grab; border-radius: var(--radius-l) var(--radius-l) 0 0;
  background: radial-gradient(circle, color-mix(in srgb, var(--ink) 9%, transparent) 1px, transparent 1.2px) 0 0 / 18px 18px, var(--surface); }
.chart.grab { cursor: grabbing; user-select: none; }
.chart.hls :deep(.card:not(.short)), .chart.hls :deep(.sc:not(.short)) { opacity: .3; }
.root { list-style: none; margin: 0 auto; padding: 0; display: flex; justify-content: center; width: max-content; min-width: 100%; }
.zoom { position: absolute; top: 12px; right: 12px; z-index: 2; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 4px; border-radius: 12px;
  background: color-mix(in srgb, var(--surface) 92%, transparent); border: 1px solid var(--line); box-shadow: 0 6px 18px -10px rgba(0, 0, 0, .3); }
.zoom button { width: 34px; height: 34px; border: 0; border-radius: 8px; background: transparent; color: var(--ink); font-weight: 800; cursor: pointer; font-size: 16px; }
.zoom button:hover { background: var(--surface-2); } .zv { font-size: 10px; font-weight: 800; color: var(--muted); font-variant-numeric: tabular-nums; }
.list { list-style: none; margin: 0; padding: 0; }
.hint { margin: 0; padding: 8px 14px 12px; font-size: var(--fs-xs); color: var(--muted); }
.pd { display: flex; flex-direction: column; gap: 14px; }
.pd-h { display: flex; gap: 12px; align-items: center; border-left: 4px solid var(--c); padding-left: 10px; }
.pd-i { font-size: 30px; } .pd-h div { flex: 1; display: flex; flex-direction: column; min-width: 0; } .pd-h b { font-family: var(--font-display); font-size: var(--fs-l); } .pd-h small { color: var(--muted); font-size: var(--fs-xs); }
.x { border: 0; background: transparent; cursor: pointer; color: var(--muted); }
.pd-p { margin: 0; font-size: var(--fs-s); color: var(--ink-2); background: var(--surface-2); padding: 10px 12px; border-radius: 10px; }
.pd-dl { display: grid; grid-template-columns: 96px 1fr; gap: 6px 10px; margin: 0; font-size: var(--fs-s); } .pd-dl dt { color: var(--muted); } .pd-dl dd { margin: 0; font-weight: 600; }
.pd-c { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.pd-c div { background: var(--surface-2); border-radius: 10px; padding: 8px 4px; display: flex; flex-direction: column; align-items: center; }
.pd-c b { font-family: var(--font-display); font-size: var(--fs-l); } .pd-c span { font-size: 11px; color: var(--muted); }
.pd-e { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.pd-e li { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); } .pd-e span { display: flex; flex-direction: column; } .pd-e small { color: var(--muted); font-size: 11px; }
.pd-b { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.lnk { color: var(--accent); font-weight: 800; text-decoration: none; font-size: var(--fs-s); }
@media (max-width: 720px) {
  .st { display: grid; grid-template-columns: 1fr 1fr; width: 100%; gap: 8px; } .st button { padding: 8px 26px 8px 10px; min-height: 44px; } .st-i { display: none; }
  .ac { width: 100%; } .ac > * { flex: 1 1 auto; } .hero-in { flex-direction: column; }
}
@media print { .ac, .no-print, .top .ac, .st { display: none !important; } .chart { height: auto; max-height: none; overflow: visible; background: none; } }
</style>
