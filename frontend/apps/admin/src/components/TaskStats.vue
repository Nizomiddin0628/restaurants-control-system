<script setup lang="ts">
/**
 * Doska statistikasi: KPI plitkalar + holatlar donuti + bo'limlar/ustuvorlik bo'yicha ustunchalar.
 * Ranglar: holat palitrasi (tokens.css `--chart-*`, CVD tekshiruvidan o'tgan), bo'limlar — bitta rang
 * (uzunlik ma'noni tashiydi, nomi yonida yozilgan). Rang hech qayerda yolg'iz ma'no tashimaydi.
 */
import { computed } from 'vue'
import { UiCard, UiIcon, t } from '@restopos/ui'
import type { TaskStats } from '@restopos/api'
import { useUi } from '@/stores/ui'

const props = defineProps<{ stats: TaskStats | null; active?: string }>()
/** KPI kartasi bosilsa — vazifalar taxtasi shu holatga o'tadi (ustun yoki «kechikkan» filtri) */
const emit = defineEmits<{ (e: 'pick', k: 'all' | 'active' | 'review' | 'done' | 'overdue'): void }>()
const ui = useUi()

const KIND_VAR: Record<string, string> = { backlog: '--chart-new', active: '--chart-active', review: '--chart-review', done: '--chart-done', cancelled: '--chart-cancel' }
const PRIO = [
  { code: 'urgent', label: 'Shoshilinch', color: 'var(--danger)' },
  { code: 'high', label: 'Muhim', color: 'var(--warn)' },
  { code: 'normal', label: "O'rta", color: 'var(--info)' },
  { code: 'low', label: 'Past', color: 'var(--muted)' },
]

const donut = computed(() => {
  const s = props.stats
  if (!s) return { total: 0, arcs: [] as any[] }
  const items = s.by_column.filter(c => c.count > 0)
  const total = items.reduce((a, b) => a + b.count, 0)
  const R = 54, C = 2 * Math.PI * R
  let acc = 0
  const arcs = items.map(c => {
    const frac = total ? c.count / total : 0
    // 2px bo'shliq: qo'shni bo'laklar tutashmaydi (ustma-ust tushib ketmasin)
    const len = Math.max(0, frac * C - 3)
    const arc = { ...c, len, gap: C - len, offset: -acc * C, color: `var(${KIND_VAR[c.kind] ?? '--chart-bar'})`, pct: Math.round(frac * 100) }
    acc += frac
    return arc
  })
  return { total, arcs, C }
})

const departments = computed(() => {
  const list = props.stats?.by_department ?? []
  const max = Math.max(1, ...list.map(d => d.count))
  return list.map(d => ({ name: t(d.name as any, ui.lang), count: d.count, pct: Math.round(100 * d.count / max) }))
})

const priorities = computed(() => {
  const by = props.stats?.by_priority ?? {}
  const max = Math.max(1, ...Object.values(by))
  return PRIO.map(p => ({ ...p, count: by[p.code] ?? 0, pct: Math.round(100 * (by[p.code] ?? 0) / max) }))
})
</script>

<template>
  <div v-if="stats" class="wrap">
    <div class="kpis">
      <button type="button" class="kpi kpi-click" :class="{ on: active === 'all' }" @click="emit('pick', 'all')"><span class="k-ic ok"><UiIcon name="list" :size="18" /></span><div><b>{{ stats.total }}</b><span>Jami vazifa</span></div></button>
      <button type="button" class="kpi kpi-click" :class="{ on: active === 'active' }" @click="emit('pick', 'active')"><span class="k-ic run"><UiIcon name="clock" :size="18" /></span><div><b>{{ stats.in_progress }}</b><span>Jarayonda</span></div></button>
      <button type="button" class="kpi kpi-click" :class="{ on: active === 'review' }" @click="emit('pick', 'review')"><span class="k-ic rev"><UiIcon name="eye" :size="18" /></span><div><b>{{ stats.review }}</b><span>Tekshiruvda</span></div></button>
      <button type="button" class="kpi kpi-click" :class="{ on: active === 'done' }" @click="emit('pick', 'done')"><span class="k-ic done"><UiIcon name="check" :size="18" /></span><div><b>{{ stats.done }}</b><span>Bajarildi</span></div></button>
      <button type="button" class="kpi kpi-click" :class="{ warn: stats.overdue > 0, on: active === 'overdue' }" @click="emit('pick', 'overdue')"><span class="k-ic late"><UiIcon name="alert" :size="18" /></span><div><b>{{ stats.overdue }}</b><span>Kechikkan</span></div></button>
      <div class="kpi"><span class="k-ic avg"><UiIcon name="chart" :size="18" /></span><div><b>{{ stats.avg_hours_to_done ?? '—' }}<i v-if="stats.avg_hours_to_done"> soat</i></b><span>O'rtacha bajarish</span></div></div>
    </div>

    <div class="charts">
      <UiCard title="Holatlar bo'yicha">
        <div class="donut-row">
          <svg class="donut" viewBox="0 0 140 140" role="img" aria-label="Vazifalar holati">
            <circle cx="70" cy="70" r="54" fill="none" stroke="var(--chart-grid)" stroke-width="16" />
            <circle v-for="a in donut.arcs" :key="a.code" cx="70" cy="70" r="54" fill="none" :stroke="a.color"
                    stroke-width="16" :stroke-dasharray="`${a.len} ${a.gap}`" :stroke-dashoffset="a.offset"
                    transform="rotate(-90 70 70)" stroke-linecap="butt">
              <title>{{ t(a.name as any, ui.lang) }}: {{ a.count }} ({{ a.pct }}%)</title>
            </circle>
            <text x="70" y="66" text-anchor="middle" class="d-num">{{ donut.total }}</text>
            <text x="70" y="84" text-anchor="middle" class="d-lbl">vazifa</text>
          </svg>
          <ul class="legend">
            <li v-for="a in donut.arcs" :key="a.code">
              <span class="dot" :style="{ background: a.color }"></span>
              <span class="nm">{{ t(a.name as any, ui.lang) }}</span>
              <b>{{ a.count }}</b><i>{{ a.pct }}%</i>
            </li>
          </ul>
        </div>
      </UiCard>

      <UiCard title="Bo'limlar bo'yicha">
        <ul class="bars">
          <li v-for="d in departments" :key="d.name">
            <span class="nm">{{ d.name }}</span>
            <span class="track"><span class="fill" :style="{ width: d.pct + '%' }"></span></span>
            <b>{{ d.count }}</b>
          </li>
          <li v-if="!departments.length" class="muted">Ma'lumot yo'q</li>
        </ul>
      </UiCard>

      <UiCard title="Ustuvorlik bo'yicha">
        <ul class="bars">
          <li v-for="p in priorities" :key="p.code">
            <span class="nm"><span class="dot" :style="{ background: p.color }"></span>{{ p.label }}</span>
            <span class="track"><span class="fill" :style="{ width: p.pct + '%', background: p.color }"></span></span>
            <b>{{ p.count }}</b>
          </li>
        </ul>
        <p class="note"><UiIcon name="repeat" :size="14" /> Qaytarilgan ishlar: <b>{{ stats.rework_rate }}%</b> — sifat ko'rsatkichi</p>
      </UiCard>
    </div>
  </div>
</template>

<style scoped>
.wrap { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.kpi { display: flex; align-items: center; gap: 10px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px 14px; }
.kpi.warn { border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); }
.kpi b { display: block; font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; line-height: 1.15; }
.kpi b i { font-size: var(--fs-s); font-weight: 600; font-style: normal; color: var(--muted); }
.kpi span:last-child, .kpi div span { font-size: var(--fs-xs); color: var(--muted); }
.k-ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; flex-shrink: 0; }
.k-ic.ok { background: var(--surface-3); color: var(--ink-2); }
.k-ic.run { background: var(--warn-tint); color: var(--warn-ink); }
.k-ic.rev { background: var(--info-tint); color: var(--info); }
.k-ic.done { background: var(--ok-tint); color: var(--ok); }
.k-ic.late { background: var(--danger-tint); color: var(--danger); }
.k-ic.avg { background: var(--accent-tint); color: var(--accent); }
.charts { display: grid; grid-template-columns: 1.1fr 1fr 1fr; gap: 12px; }
.donut-row { display: flex; align-items: center; gap: 16px; }
.donut { width: 140px; height: 140px; flex-shrink: 0; }
.d-num { font-family: var(--font-display); font-size: 26px; font-weight: 800; fill: var(--ink); }
.d-lbl { font-size: 11px; fill: var(--muted); }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; flex: 1; min-width: 0; }
.legend li { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); }
.legend .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
.legend b { font-weight: 800; }
.legend i { font-style: normal; color: var(--muted); font-size: var(--fs-xs); width: 34px; text-align: right; }
.dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; display: inline-block; }
.bars { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 9px; }
.bars li { display: grid; grid-template-columns: 96px 1fr 28px; align-items: center; gap: 8px; font-size: var(--fs-s); }
.bars .nm { display: flex; align-items: center; gap: 6px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { height: 8px; background: var(--surface-3); border-radius: 4px; overflow: hidden; }
.fill { display: block; height: 100%; background: var(--chart-bar); border-radius: 4px; }
.bars b { text-align: right; font-weight: 800; }
.bars .muted { color: var(--muted); display: block; }
.note { margin: 12px 0 0; font-size: var(--fs-xs); color: var(--muted); display: flex; align-items: center; gap: 6px; }
@media (max-width: 1400px) { .kpis { grid-template-columns: repeat(3, 1fr); } .charts { grid-template-columns: 1fr 1fr; } }
@media (max-width: 900px) { .charts { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .kpis { grid-template-columns: repeat(2, 1fr); } .donut-row { flex-direction: column; align-items: flex-start; } }
</style>
