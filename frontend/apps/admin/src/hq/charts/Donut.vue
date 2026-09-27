<script setup lang="ts">
/** Ulushlar halqasi: markazda jami, yonida ulushlar (foiz bilan). Bo'lakni bosganda/ustiga kelganda ajralib turadi. */
import { computed, ref } from 'vue'

const props = defineProps<{ items: { key: string; label: string; value: number; color: string }[]; total?: number }>()
const R = 54, C = 2 * Math.PI * R
const hot = ref<string | null>(null)
const segs = computed(() => {
  const tot = props.items.reduce((s, x) => s + x.value, 0)
  const live = props.items.filter(x => x.value > 0)
  const gap = live.length > 1 ? 3 : 0
  let acc = 0
  return { tot, list: live.map(x => { const len = tot ? (C * x.value) / tot : 0; const s = { ...x, len: Math.max(0.5, len - gap), off: -acc }; acc += len; return s }) }
})
const pct = (v: number) => (segs.value.tot ? Math.round((100 * v) / segs.value.tot) : 0)
const center = computed(() => { const h = props.items.find(x => x.key === hot.value); return h ? { v: h.value, l: h.label } : { v: props.total ?? segs.value.tot, l: 'jami' } })
</script>

<template>
  <div class="dn">
    <svg viewBox="0 0 140 140" width="156" height="156" role="img" :aria-label="`Jami ${segs.tot}`">
      <circle cx="70" cy="70" :r="R" fill="none" stroke="var(--surface-3)" stroke-width="14" />
      <circle v-for="s in segs.list" :key="s.key" cx="70" cy="70" :r="R" fill="none" :stroke="s.color" :stroke-width="hot === s.key ? 18 : 14"
              :stroke-dasharray="`${s.len} ${C}`" :stroke-dashoffset="s.off" transform="rotate(-90 70 70)" stroke-linecap="butt" class="seg"
              :opacity="hot && hot !== s.key ? 0.35 : 1" @mouseenter="hot = s.key" @mouseleave="hot = null" @click="hot = hot === s.key ? null : s.key"><title>{{ s.label }}: {{ s.value }}</title></circle>
      <text x="70" y="72" text-anchor="middle" class="t">{{ center.v }}</text>
      <text x="70" y="90" text-anchor="middle" class="l">{{ center.l.length > 14 ? center.l.slice(0, 13) + '…' : center.l }}</text>
    </svg>
    <ul>
      <li v-for="x in items" :key="x.key" :class="{ dim: hot && hot !== x.key }" @mouseenter="hot = x.key" @mouseleave="hot = null">
        <i :style="{ background: x.color }"></i><span class="lb">{{ x.label }}</span><b>{{ x.value }}</b><em>{{ pct(x.value) }}%</em>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.dn { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; justify-content: center; }
.seg { transition: stroke-width .15s, opacity .15s; cursor: pointer; }
.t { font-family: var(--font); font-size: 26px; font-weight: 800; fill: var(--ink); font-variant-numeric: tabular-nums; }
.l { font-family: var(--font); font-size: 10px; font-weight: 700; fill: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; min-width: 160px; flex: 1; max-width: 280px; }
li { display: grid; grid-template-columns: 10px 1fr auto 40px; align-items: center; gap: 8px; font-size: var(--fs-s); padding: 5px 8px; border-radius: 8px; transition: opacity .15s, background .15s; }
li:hover { background: var(--surface-2); } li.dim { opacity: .45; }
li i { width: 10px; height: 10px; border-radius: 3px; } .lb { color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
li b { font-variant-numeric: tabular-nums; } li em { font-style: normal; color: var(--muted); font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; }
</style>
