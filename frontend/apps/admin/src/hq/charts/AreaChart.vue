<script setup lang="ts">
/** Oddiy chiziqli grafik (bitta qator): o'q, to'r, nuqtaga olib borsa — qiymat. Ikki o'qli grafik yo'q. */
import { computed, ref } from 'vue'
import { big } from '../fmt'

const props = withDefaults(defineProps<{ points: { label: string; value: number }[]; height?: number; money?: boolean; bars?: boolean; every?: number; color?: string; unit?: string }>(), { height: 220, money: true, color: '#2563EB', unit: '' })
const W = 640, PL = 48, PB = 24, PT = 10
const hover = ref<number | null>(null)
const g = computed(() => {
  const H = props.height, n = props.points.length
  const max0 = Math.max(1, ...props.points.map(p => p.value))
  const p10 = Math.pow(10, Math.floor(Math.log10(max0 / 4 || 1))), st = [1, 2, 5, 10].map(k => k * p10).find(k => k * 4 >= max0) ?? p10 * 10
  const max = st * 4
  const x = (i: number) => PL + (n <= 1 ? 0 : (i * (W - PL - 10)) / (n - 1))
  const bw = (W - PL - 10) / Math.max(1, n)
  const y = (v: number) => H - PB - ((H - PB - PT) * v) / max
  const pts = props.points.map((p, i) => [props.bars ? PL + i * bw + bw / 2 : x(i), y(p.value)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const area = n ? `${line} L${pts[n - 1][0]},${H - PB} L${pts[0][0]},${H - PB} Z` : ''
  return { H, pts, line, area, bw, ticks: [0, 1, 2, 3, 4].map(k => ({ v: st * k, y: y(st * k) })), every: props.every ?? Math.ceil(n / 8) }
})
</script>

<template>
  <div class="ac" @mouseleave="hover = null">
    <svg :viewBox="`0 0 ${W} ${g.H}`" preserveAspectRatio="none" role="img" aria-label="Grafik" :style="{ height: `${g.H}px` }">
      <g v-for="t in g.ticks" :key="t.v"><line :x1="PL" :x2="W - 6" :y1="t.y" :y2="t.y" stroke="var(--line-2)" /><text :x="PL - 6" :y="t.y + 4" text-anchor="end" class="ax">{{ money ? big(t.v).replace(' mln', 'M').replace(' mlrd', 'B').replace(' ming', 'k') : t.v }}</text></g>
      <template v-if="bars">
        <rect v-for="(p, i) in g.pts" :key="i" :x="p[0] - g.bw * 0.32" :y="p[1]" :width="g.bw * 0.64" :height="g.H - PB - p[1]" rx="3" :fill="color" :opacity="hover === i ? 1 : 0.55" />
      </template>
      <template v-else>
        <path :d="g.area" :fill="color" opacity=".12" /><path :d="g.line" fill="none" :stroke="color" stroke-width="2.5" stroke-linejoin="round" />
        <circle v-for="(p, i) in g.pts" :key="i" :cx="p[0]" :cy="p[1]" :r="hover === i ? 5 : 3" :fill="color" stroke="var(--surface)" stroke-width="2" />
      </template>
      <text v-for="(p, i) in g.pts" v-show="i % g.every === 0" :key="`l${i}`" :x="p[0]" :y="g.H - 6" text-anchor="middle" class="ax">{{ points[i].label }}</text>
      <rect v-for="(p, i) in g.pts" :key="`h${i}`" :x="p[0] - (W - PL) / Math.max(1, g.pts.length) / 2" :y="0" :width="(W - PL) / Math.max(1, g.pts.length)" :height="g.H" fill="transparent" @mouseenter="hover = i" />
    </svg>
    <div v-if="hover !== null" class="tip" :style="{ left: `${(g.pts[hover][0] / W) * 100}%`, top: `${(g.pts[hover][1] / g.H) * 100}%` }">
      <b>{{ points[hover].label }}</b><span>{{ money ? big(points[hover].value) + ' so\'m' : points[hover].value + unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.ac { position: relative; } svg { width: 100%; display: block; } .ax { font-size: 11px; fill: var(--muted); }
.tip { position: absolute; transform: translate(-50%, calc(-100% - 10px)); background: var(--ink); color: var(--surface); padding: 6px 10px; border-radius: 8px; font-size: 12px; display: flex; flex-direction: column; pointer-events: none; white-space: nowrap; }
</style>
