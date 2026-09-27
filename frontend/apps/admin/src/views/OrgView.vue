<script setup lang="ts">
/**
 * Tashkiliy tuzilma: rahbar → direktorlar → har filial → menejer → smena → xodimlar.
 * Kompyuterda — daraxt (kattalashtirish, sudrab tashlash), telefonda — ochiladigan ro'yxat. Chop etish / PDF.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiDrawer, UiEmpty, UiIcon, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import OrgNode from '@/components/ops/OrgNode.vue'
import PositionEditor from '@/components/ops/PositionEditor.vue'
import DepartmentsDrawer from '@/components/ops/DepartmentsDrawer.vue'

const a = useAuth()
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

const chartEl = ref<HTMLElement | null>(null), rootEl = ref<HTMLElement | null>(null)
async function load() {
  ;[T.value, meta.value] = await Promise.all([api.get('/ops/tree'), api.get('/ops/meta')])
}
/** Daraxt ekranga sig'sin: kerak bo'lsa kichraytiriladi va o'rtaga suriladi. */
async function fit() {
  await nextTick()
  const c = chartEl.value, r = rootEl.value
  if (!c || !r) return
  zoom.value = 1
  await nextTick()
  const w = r.scrollWidth
  if (w > c.clientWidth - 32) zoom.value = Math.max(0.75, Math.floor(((c.clientWidth - 32) / w) * 20) / 20)
  await nextTick()
  c.scrollLeft = (c.scrollWidth - c.clientWidth) / 2
}
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
        <div><b>{{ S.departments }}</b><span>bo'lim</span></div>
        <div><b>{{ S.positions }}</b><span>lavozim</span></div>
        <div><b>{{ S.employees }}</b><span>xodim</span></div>
        <div :class="{ warn: S.short }"><b>{{ S.short }}</b><span>bo'sh o'rin (shtat {{ S.headcount }})</span></div>
      </div>
      <div class="ac">
        <div v-if="!phone" class="seg" role="tablist" aria-label="Ko'rinish">
          <button type="button" :class="{ on: mode === 'tree' }" @click="mode = 'tree'">Daraxt</button>
          <button type="button" :class="{ on: mode === 'list' }" @click="mode = 'list'">Ro'yxat</button>
        </div>
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

    <div class="body" :class="{ side: !!detail }">
      <UiCard :padded="false" class="chart-card">
        <div v-if="mode === 'tree' && hasTree" class="zoom no-print">
          <button type="button" aria-label="Kattalashtirish" @click="zoom = Math.min(1.4, +(zoom + 0.1).toFixed(1))">+</button>
          <button type="button" aria-label="Kichraytirish" @click="zoom = Math.max(0.4, +(zoom - 0.1).toFixed(1))">−</button>
          <button type="button" aria-label="Ekranga moslash" title="Ekranga moslash" @click="fit()">⤢</button>
        </div>
        <div v-if="hasTree && mode === 'tree'" ref="chartEl" class="chart">
          <ul ref="rootEl" class="root" :style="{ zoom }">
            <OrgNode v-for="r in T.roots" :key="`${r.type}${r.id}`" :n="r" mode="tree" :selected="sel?.id" :can-edit="canEdit" :collapse="S.branches > 3" @pick="pick" @move="onMove" />
          </ul>
        </div>
        <ul v-else-if="hasTree" class="list">
          <OrgNode v-for="r in T.roots" :key="`${r.type}${r.id}`" :n="r" mode="list" :selected="sel?.id" @pick="pick" @move="onMove" />
        </ul>
        <UiEmpty v-else title="Hali lavozim yo'q" text="«Lavozim» tugmasi bilan qo'shing yoki tayyor shablonni qo'ying." />
        <p v-if="canEdit && mode === 'tree' && hasTree" class="hint no-print">💡 Lavozimni boshqasining ustiga sudrab tashlasangiz — unga bo'ysunadigan bo'ladi.</p>
      </UiCard>

      <!-- tanlangan lavozim: qisqa kartochka -->
      <component :is="phone ? UiDrawer : 'aside'" v-if="detail" :open="true" :title="detail.name" class="pd" @close="detail = null; sel = null">
        <div class="pd-h" :style="{ '--c': detail.department?.color ?? 'var(--line)' }">
          <span class="pd-i">{{ detail.icon }}</span>
          <div><b>{{ detail.name }}</b><small>{{ detail.department ? `${detail.department.icon} ${detail.department.name}` : 'Bo\'limsiz' }} · {{ detail.level_label }}</small></div>
          <button v-if="!phone" type="button" class="x" aria-label="Yopish" @click="detail = null; sel = null"><UiIcon name="x" :size="16" /></button>
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
      </component>
    </div>

    <PositionEditor :open="editor" :value="edValue" :meta="meta" @close="editor = false" @saved="onSaved" @deleted="onDeleted" />
    <DepartmentsDrawer :open="depts" :departments="meta.departments" @close="depts = false" @changed="load()" />
  </div>
</template>

<style scoped>
.org { display: flex; flex-direction: column; gap: 14px; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.st { display: flex; gap: 10px; flex-wrap: wrap; }
.st div { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 8px 14px; display: flex; align-items: baseline; gap: 6px; }
.st b { font-family: var(--font-display); font-size: var(--fs-l); } .st span { font-size: var(--fs-xs); color: var(--muted); }
.st .warn { border-color: color-mix(in srgb, var(--warn) 50%, var(--line)); background: var(--warn-tint); }
.ac { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.seg { display: inline-flex; background: var(--surface-3); border-radius: 10px; padding: 3px; }
.seg button { border: 0; background: transparent; padding: 0 12px; min-height: 32px; border-radius: 8px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; }
.seg button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.hero-in { display: flex; gap: 16px; align-items: flex-start; } .hero-i { font-size: 44px; }
.hero h2 { margin: 0 0 6px; font-family: var(--font-display); } .hero p { margin: 0; color: var(--ink-2); max-width: 760px; }
.hero-b { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-items: start; }
.body.side { grid-template-columns: minmax(0, 1fr) 340px; }
.chart-card { position: relative; min-width: 0; }
.chart { overflow: auto; padding: 24px 16px 32px; min-height: 420px; max-height: calc(100vh - 230px); }
.root { list-style: none; margin: 0 auto; padding: 0; display: flex; justify-content: center; width: max-content; min-width: 100%; }
.zoom { position: absolute; top: 10px; left: 10px; z-index: 2; display: flex; flex-direction: column; gap: 4px; }
.zoom button { width: 34px; height: 34px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); font-weight: 800; cursor: pointer; font-size: 13px; }
.list { list-style: none; margin: 0; padding: 0; }
.hint { margin: 0; padding: 8px 14px 12px; font-size: var(--fs-xs); color: var(--muted); }
.pd { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 16px; display: flex; flex-direction: column; gap: 12px; position: sticky; top: 12px; }
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
@media (max-width: 1100px) { .body.side { grid-template-columns: minmax(0, 1fr) 300px; } }
@media (max-width: 720px) { .body.side { grid-template-columns: minmax(0, 1fr); } .st div { padding: 6px 10px; } .hero-in { flex-direction: column; } }
@media print { .ac, .no-print, .pd, .top .ac { display: none !important; } .chart { max-height: none; overflow: visible; } .body.side { grid-template-columns: 1fr; } }
</style>
