<script setup lang="ts">
/** Bo'lim dashboardi vidjeti: grafik (ustun/chiziq), reyting, ro'yxat, donut yoki jadval — bitta umumiy karta. */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AreaChart from '@/hq/charts/AreaChart.vue'
import Donut from '@/hq/charts/Donut.vue'

const props = defineProps<{ w: any; color: string }>()
const max = computed(() => Math.max(1, ...((props.w.rows ?? []).map((r: any) => Number(r.value) || 0))))
const unit = computed(() => (props.w.title?.includes('%') ? '%' : ''))
</script>

<template>
  <article class="dw" :class="{ wide: w.wide }" :style="{ '--sc': color }">
    <header>
      <div><h3>{{ w.title }}</h3><small v-if="w.sub">{{ w.sub }}</small></div>
      <RouterLink v-if="w.route" :to="w.route" class="more">Batafsil ›</RouterLink>
    </header>

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
.dw { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 16px; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.dw.wide { grid-column: 1 / -1; }
header { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
h3 { margin: 0; font-size: var(--fs-m); } header small { color: var(--muted); font-size: var(--fs-xs); }
.more { color: var(--sc); font-weight: 700; font-size: var(--fs-s); text-decoration: none; white-space: nowrap; }
.rank, .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.rank li { display: grid; grid-template-columns: 22px minmax(0, 1.2fr) minmax(60px, 1fr) auto; gap: 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); }
.rank li:last-child { border-bottom: 0; }
.n { width: 22px; height: 22px; border-radius: 7px; background: var(--surface-2); display: grid; place-items: center; font-size: 11px; font-weight: 800; color: var(--muted); }
.t { display: flex; flex-direction: column; min-width: 0; } .t b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; } .t small { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 8px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: var(--sc); border-radius: 99px; opacity: .8; }
.v { white-space: nowrap; font-variant-numeric: tabular-nums; }
.list li { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 9px 10px; border-radius: 10px; font-size: var(--fs-s); border-left: 3px solid transparent; }
.list li:nth-child(odd) { background: var(--surface-2); }
.list li.bad { border-left-color: var(--danger); } .list li.warn { border-left-color: #F59E0B; } .list li.ok { border-left-color: var(--ok); }
.list li.bad .r b { color: var(--danger); }
.r { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex-shrink: 0; } .r b { white-space: nowrap; font-variant-numeric: tabular-nums; }
.bd { font-style: normal; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 99px; background: var(--surface-3); color: var(--ink-2); white-space: nowrap; }
.bad .bd { background: var(--danger-tint); color: var(--danger); } .warn .bd { background: #FEF3C7; color: #92400E; } .ok .bd { background: #DCFCE7; color: #166534; }
.empty { justify-content: center !important; color: var(--muted); padding: 18px !important; background: transparent !important; }
.tbl { overflow-x: auto; } table { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
th { text-align: left; font-size: 11px; color: var(--muted); font-weight: 700; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 9px 8px; border-bottom: 1px solid var(--line-2); white-space: nowrap; font-variant-numeric: tabular-nums; } td:first-child { font-weight: 700; white-space: normal; }
tr.last td { font-weight: 800; border-top: 2px solid var(--line); border-bottom: 0; }
@media (max-width: 640px) { .dw { padding: 12px; } .rank li { grid-template-columns: 20px minmax(0, 1fr) auto; } .rank .bar { display: none; } }
</style>
