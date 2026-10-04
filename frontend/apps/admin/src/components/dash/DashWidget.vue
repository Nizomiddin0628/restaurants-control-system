<script setup lang="ts">
/** Bo'lim dashboardi vidjeti: grafik (ustun/chiziq), reyting, ro'yxat, donut yoki jadval — bitta umumiy karta. */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AreaChart from '@/hq/charts/AreaChart.vue'
import Donut from '@/hq/charts/Donut.vue'

const props = defineProps<{ w: any; color: string }>()
const max = computed(() => Math.max(1, ...((props.w.rows ?? []).map((r: any) => Number(r.value) || 0))))
const unit = computed(() => (props.w.title?.includes('%') ? '%' : ''))
/** Grafik sarlavhasida jami (pul) yoki o'rtacha (%) — bir qarashda raqam */
const headline = computed(() => {
  if (props.w.type !== 'chart' || !props.w.points?.length) return ''
  const vals = props.w.points.map((p: any) => Number(p.value) || 0)
  if (unit.value) return `${(vals.reduce((a: number, b: number) => a + b, 0) / vals.length).toFixed(1)}%`
  const s = vals.reduce((a: number, b: number) => a + b, 0)
  if (!props.w.money) return String(s)
  return s >= 1e6 ? `${(s / 1e6).toFixed(1).replace('.', ',')} mln` : s.toLocaleString('ru-RU').replace(/,/g, ' ')
})
</script>

<template>
  <article class="dw" :class="{ wide: w.wide }" :style="{ '--sc': color }">
    <header>
      <div class="ht"><h3>{{ w.title }}</h3><small v-if="w.sub">{{ w.sub }}</small></div>
      <RouterLink v-if="w.route" :to="w.route" class="more" :title="`${w.title} — batafsil`">Batafsil <span aria-hidden="true">→</span></RouterLink>
    </header>
    <p v-if="headline" class="hl"><b>{{ headline }}</b><small v-if="w.money"> so'm</small><small v-else-if="unit"> o'rtacha</small><small v-else> jami</small></p>

    <AreaChart v-if="w.type === 'chart'" :points="w.points" :bars="w.kind === 'bars'" :money="w.money" :height="w.wide ? 220 : 190" :color="color" :unit="unit" />

    <Donut v-else-if="w.type === 'donut'" :items="w.items" />

    <ol v-else-if="w.type === 'rank'" class="rank">
      <li v-for="(r, i) in w.rows" :key="i">
        <span class="n">{{ i + 1 }}</span>
        <span class="t"><b>{{ r.label }}</b><small v-if="r.sub">{{ r.sub }}</small></span>
        <span class="bar"><i :style="{ width: `${Math.max(2, (100 * (Number(r.value) || 0)) / max)}%` }"></i></span>
        <b class="v">{{ r.display ?? r.value }}</b>
      </li>
      <li v-if="!w.rows.length" class="empty">Ma'lumot yo'q</li>
    </ol>

    <ul v-else-if="w.type === 'list'" class="list">
      <li v-for="(r, i) in w.rows" :key="i" :class="r.tone">
        <span class="t"><b>{{ r.title }}</b><small v-if="r.sub">{{ r.sub }}</small></span>
        <span class="r"><em v-if="r.badge" class="bd">{{ r.badge }}</em><b v-if="r.right">{{ r.right }}</b></span>
      </li>
      <li v-if="!w.rows.length" class="empty">{{ w.empty || "Ma'lumot yo'q" }}</li>
    </ul>

    <div v-else-if="w.type === 'table'" class="tbl">
      <table>
        <thead><tr><th v-for="c in w.cols" :key="c">{{ c }}</th></tr></thead>
        <tbody><tr v-for="(r, i) in w.rows" :key="i" :class="{ last: i === w.rows.length - 1 && w.title.includes('Foyda') }"><td v-for="(c, j) in r" :key="j">{{ c }}</td></tr></tbody>
      </table>
    </div>
  </article>
</template>

<style scoped>
.dw { background: var(--surface); border: 1px solid var(--line); border-radius: 20px; padding: 18px 18px 14px; display: flex; flex-direction: column; gap: 10px; min-width: 0;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 12px 32px -18px rgba(16, 24, 40, .18); transition: box-shadow .2s, border-color .2s; }
.dw:hover { border-color: color-mix(in srgb, var(--sc) 30%, var(--line)); }
.ht { min-width: 0; }
.hl { margin: -4px 0 0; } .hl b { font-size: 26px; font-weight: 800; letter-spacing: -.02em; font-variant-numeric: tabular-nums; } .hl small { color: var(--muted); font-weight: 600; font-size: var(--fs-s); }
.dw.wide { grid-column: 1 / -1; }
header { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
h3 { margin: 0; font-size: var(--fs-b); font-weight: 800; letter-spacing: -.01em; } header small { color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
.more { color: var(--sc); font-weight: 700; font-size: var(--fs-xs); text-decoration: none; white-space: nowrap; padding: 5px 10px; border-radius: 99px; background: color-mix(in srgb, var(--sc) 10%, transparent); }
.more:hover { background: color-mix(in srgb, var(--sc) 18%, transparent); }
.rank, .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.rank li { display: grid; grid-template-columns: 22px minmax(0, 1.2fr) minmax(60px, 1fr) auto; gap: 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); }
.rank li:last-child { border-bottom: 0; }
.n { width: 22px; height: 22px; border-radius: 7px; background: color-mix(in srgb, var(--sc) 10%, var(--surface-2)); display: grid; place-items: center; font-size: 11px; font-weight: 800; color: var(--muted); }
.t { display: flex; flex-direction: column; min-width: 0; } .t b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; } .t small { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 8px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: linear-gradient(90deg, color-mix(in srgb, var(--sc) 55%, transparent), var(--sc)); border-radius: 99px; }
.v { white-space: nowrap; font-variant-numeric: tabular-nums; }
.list li { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 9px 10px; border-radius: 10px; font-size: var(--fs-s); border-left: 3px solid transparent; }
.list li:nth-child(odd) { background: var(--surface-2); }
.list li.bad { border-left-color: var(--danger); } .list li.warn { border-left-color: #F59E0B; } .list li.ok { border-left-color: var(--ok); }
.list li.bad .r b { color: var(--danger); }
.r { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex-shrink: 0; } .r b { white-space: nowrap; font-variant-numeric: tabular-nums; }
.bd { font-style: normal; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 99px; background: var(--surface-3); color: var(--ink-2); white-space: nowrap; }
.bad .bd { background: var(--danger-tint); color: var(--danger); } .warn .bd { background: var(--warn-tint); color: var(--warn-ink); } .ok .bd { background: var(--ok-tint); color: var(--ok); }
.rank li.empty { display: block; text-align: center; }
.empty { justify-content: center !important; color: var(--muted); padding: 18px !important; background: transparent !important; }
.tbl { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
th { text-align: left; font-size: 11px; color: var(--muted); font-weight: 700; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 9px 8px; border-bottom: 1px solid var(--line-2); white-space: nowrap; font-variant-numeric: tabular-nums; } td:first-child { font-weight: 700; white-space: normal; }
tr.last td { font-weight: 800; border-top: 2px solid var(--line); border-bottom: 0; }
@media (max-width: 640px) { .dw { padding: 12px; } .rank li { grid-template-columns: 20px minmax(0, 1fr) auto; } .rank .bar { display: none; } }
</style>
