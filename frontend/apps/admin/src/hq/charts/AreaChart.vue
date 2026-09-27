<script setup lang="ts">
/**
 * Zamonaviy grafik (bitta qator): ustunli (bars) yoki silliq chiziqli (area).
 * Kenglik konteynerdan o'lchanadi (ResizeObserver) — matn cho'zilmaydi, telefonda ham aniq.
 * Sichqoncha yoki barmoq bilan — eng yaqin nuqta va qiymat ko'rsatiladi.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { big } from '../fmt'

const props = withDefaults(defineProps<{ points: { label: string; value: number }[]; height?: number; money?: boolean; bars?: boolean; every?: number; color?: string; unit?: string }>(),
  { height: 220, money: true, color: '#2563EB', unit: '' })

const box = ref<HTMLElement | null>(null)
const W = ref(640)
let ro: ResizeObserver | null = null
onMounted(() => {
  if (!box.value) return
  W.value = Math.max(260, box.value.clientWidth)
  ro = new ResizeObserver(([e]) => { W.value = Math.max(260, Math.round(e.contentRect.width)) })
  ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())

const uid = `g${Math.random().toString(36).slice(2, 8)}`
const hover = ref<number | null>(null)
const short = (v: number) => props.money ? big(v).replace(' mlrd', 'B').replace(' mln', 'M').replace(' ming', 'k') : (Math.abs(v) >= 1000 ? `${+(v / 1000).toFixed(1)}k` : String(+v.toFixed(1)))

const g = computed(() => {
  const H = props.height, n = props.points.length, w = W.value
  const PL = 44, PR = 8, PT = 12, PB = 26
  const max0 = Math.max(1, ...props.points.map(p => p.value))
  const p10 = Math.pow(10, Math.floor(Math.log10(max0 / 4 || 1)))
  const st = [1, 2, 2.5, 5, 10].map(k => k * p10).find(k => k * 4 >= max0) ?? p10 * 10
  const max = st * 4
  const iw = w - PL - PR, ih = H - PT - PB
  const bw = iw / Math.max(1, n)
  const x = (i: number) => props.bars ? PL + i * bw + bw / 2 : PL + (n <= 1 ? iw / 2 : (i * iw) / (n - 1))
  const y = (v: number) => PT + ih - (ih * Math.max(0, v)) / max
  const pts = props.points.map((p, i) => [x(i), y(p.value)] as [number, number])
  // silliq egri chiziq (monotonga yaqin, Catmull-Rom → Bezier)
  let line = ''
  pts.forEach((p, i) => {
    if (!i) { line = `M${p[0]},${p[1]}`; return }
    const p0 = pts[i - 2] ?? pts[i - 1], p1 = pts[i - 1], p3 = pts[i + 1] ?? p
    const t = 0.18
    const c1 = [p1[0] + (p[0] - p0[0]) * t, Math.min(PT + ih, p1[1] + (p[1] - p0[1]) * t)]
    const c2 = [p[0] - (p3[0] - p1[0]) * t, Math.min(PT + ih, p[1] - (p3[1] - p1[1]) * t)]
    line += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p[0].toFixed(1)},${p[1].toFixed(1)}`
  })
  const area = n ? `${line} L${pts[n - 1][0]},${PT + ih} L${pts[0][0]},${PT + ih} Z` : ''
  const maxLabels = Math.max(2, Math.floor(iw / 64))
  const every = props.every ?? Math.max(1, Math.ceil(n / maxLabels))
  const barW = Math.max(3, Math.min(42, bw * 0.62))
  return { H, w, PL, PT, ih, pts, line, area, bw, barW, every, base: PT + ih, ticks: [0, 1, 2, 3, 4].map(k => ({ v: st * k, y: y(st * k) })) }
})

function onMove(e: PointerEvent) {
  const svg = e.currentTarget as SVGElement
  const r = svg.getBoundingClientRect()
  const px = ((e.clientX - r.left) / r.width) * g.value.w
  let best = 0, d = Infinity
  g.value.pts.forEach((p, i) => { const dd = Math.abs(p[0] - px); if (dd < d) { d = dd; best = i } })
  hover.value = g.value.pts.length ? best : null
}
const total = computed(() => props.points.reduce((a, p) => a + p.value, 0))
</script>

<template>
  <div ref="box" class="ac" @mouseleave="hover = null">
    <svg :viewBox="`0 0 ${g.w} ${g.H}`" :width="g.w" :height="g.H" role="img" :aria-label="`Grafik, jami ${short(total)}`"
         @pointermove="onMove" @pointerdown="onMove" @pointerleave="hover = null">
      <defs>
        <linearGradient :id="`${uid}a`" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :style="{ stopColor: color, stopOpacity: .28 }" /><stop offset="100%" :style="{ stopColor: color, stopOpacity: 0 }" />
        </linearGradient>
        <linearGradient :id="`${uid}b`" gradientUnits="userSpaceOnUse" x1="0" :y1="g.PT" x2="0" :y2="g.base">
          <stop offset="0%" :style="{ stopColor: color }" /><stop offset="100%" :style="{ stopColor: `color-mix(in srgb, ${color} 50%, var(--surface))` }" />
        </linearGradient>
      </defs>
      <g v-for="t in g.ticks" :key="t.v">
        <line :x1="g.PL" :x2="g.w - 8" :y1="t.y" :y2="t.y" class="grid" :class="{ zero: t.v === 0 }" />
        <text :x="g.PL - 8" :y="t.y + 4" text-anchor="end" class="ax">{{ short(t.v) }}</text>
      </g>
      <template v-if="bars">
        <rect v-if="hover !== null" :x="g.pts[hover][0] - g.bw / 2 + 2" :y="g.PT" :width="g.bw - 4" :height="g.ih" rx="8" class="hl" />
        <g v-for="(p, i) in g.pts" :key="i" class="bar" :opacity="hover === null || hover === i ? 1 : 0.45">
          <template v-if="g.base - p[1] > 0.5">
            <rect :x="p[0] - g.barW / 2" :y="p[1]" :width="g.barW" :height="g.base - p[1]" :rx="Math.min(6, g.barW / 2)" :fill="`url(#${uid}b)`" />
            <rect :x="p[0] - g.barW / 2" :y="Math.max(p[1], g.base - 6)" :width="g.barW" :height="Math.min(6, g.base - p[1])" :fill="`url(#${uid}b)`" />
          </template>
        </g>
      </template>
      <template v-else>
        <path :d="g.area" :fill="`url(#${uid}a)`" />
        <path :d="g.line" fill="none" :style="{ stroke: color }" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        <template v-if="hover !== null">
          <line :x1="g.pts[hover][0]" :x2="g.pts[hover][0]" :y1="g.PT" :y2="g.base" class="cross" />
          <circle :cx="g.pts[hover][0]" :cy="g.pts[hover][1]" r="5.5" :style="{ fill: color, stroke: 'var(--surface)' }" stroke-width="2.5" />
        </template>
      </template>
      <text v-for="(p, i) in g.pts" v-show="i % g.every === 0" :key="`l${i}`" :x="p[0]" :y="g.H - 6" text-anchor="middle" class="ax">{{ points[i].label }}</text>
    </svg>
    <div v-if="hover !== null && g.pts[hover]" class="tip" :style="{ left: `${Math.min(Math.max((g.pts[hover][0] / g.w) * 100, 12), 88)}%`, top: `${(Math.min(g.pts[hover][1], g.base - 10) / g.H) * 100}%` }">
      <span>{{ points[hover].label }}</span><b>{{ money ? big(points[hover].value) + " so'm" : points[hover].value + (unit ? ' ' + unit : '') }}</b>
    </div>
  </div>
</template>

<style scoped>
.ac { position: relative; width: 100%; min-width: 0; touch-action: pan-y; }
svg { display: block; width: 100%; height: auto; overflow: visible; user-select: none; }
.ax { font-family: var(--font); font-size: 11px; font-weight: 600; fill: var(--muted); font-variant-numeric: tabular-nums; }
.grid { stroke: var(--line-2); stroke-dasharray: 3 4; } .grid.zero { stroke: var(--line); stroke-dasharray: none; }
.hl { fill: var(--surface-3); opacity: .7; }
.cross { stroke: var(--line); stroke-dasharray: 3 3; }
.bar { transition: opacity .15s; }
.tip { position: absolute; transform: translate(-50%, calc(-100% - 12px)); background: var(--ink); color: var(--surface); padding: 7px 11px; border-radius: 10px;
  font-size: 12px; display: flex; flex-direction: column; gap: 1px; pointer-events: none; white-space: nowrap; box-shadow: 0 8px 20px rgba(0, 0, 0, .18); }
.tip span { opacity: .7; font-weight: 600; } .tip b { font-size: 14px; font-variant-numeric: tabular-nums; }
</style>
