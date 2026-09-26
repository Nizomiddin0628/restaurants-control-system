<script setup lang="ts">
/** 7 kunlik ob-havo: ikonka, harorat, yog'in ehtimoli, savdoga ta'siri (%) va maslahatlar. */
import { computed } from 'vue'

const props = defineProps<{ days: any[]; hints?: number }>()
const WD = ['Ya', 'Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh']
const n = new Date()
const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
function dayLabel(s: string, i: number) {
  if (i === 0 && s === today) return 'Bugun'
  const d = new Date(s + 'T00:00:00')
  return i === 1 && props.days[0]?.date === today ? 'Ertaga' : `${WD[d.getDay()]} ${String(d.getDate()).padStart(2, '0')}`
}
const shown = computed(() => {
  const out: { date: string; tone: string; text: string }[] = []
  for (const [i, d] of props.days.entries()) for (const h of d.hints ?? []) out.push({ date: dayLabel(d.date, i), ...h })
  return out.slice(0, props.hints ?? 3)
})
</script>

<template>
  <div class="ws">
    <ul class="days">
      <li v-for="(d, i) in days" :key="d.date" :class="{ on: i === 0 }" :title="`${d.label} · yog'in ${d.precip_prob}% · shamol ${d.wind} km/soat`">
        <small>{{ dayLabel(d.date, i) }}</small>
        <span class="e">{{ d.icon }}</span>
        <b>{{ d.t_max }}°</b><span class="mn">{{ d.t_min }}°</span>
        <span class="pp" :class="{ hi: d.precip_prob >= 50 }">💧{{ d.precip_prob }}%</span>
        <span v-if="d.effect" class="ef" :class="d.effect > 0 ? 'up' : 'dn'">{{ d.effect > 0 ? '+' : '' }}{{ d.effect }}%</span>
      </li>
    </ul>
    <ul v-if="shown.length" class="hints">
      <li v-for="(h, i) in shown" :key="i" :class="h.tone"><b>{{ h.date }}:</b> {{ h.text }}</li>
    </ul>
  </div>
</template>

<style scoped>
.ws { display: flex; flex-direction: column; gap: 12px; }
.days { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
.days li { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 2px; border-radius: 12px; background: var(--surface-2); border: 1px solid var(--line-2); min-width: 0; }
.days li.on { background: var(--accent-tint); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }
.days small { font-size: 11px; font-weight: 700; color: var(--muted); white-space: nowrap; }
.e { font-size: 22px; line-height: 1.2; }
.days b { font-family: var(--font-display); font-size: var(--fs-m); font-weight: 800; }
.mn { font-size: var(--fs-xs); color: var(--muted); }
.pp { font-size: 11px; color: var(--muted); white-space: nowrap; } .pp.hi { color: var(--info); font-weight: 700; }
.ef { font-size: 11px; font-weight: 800; padding: 0 6px; border-radius: 99px; } .ef.dn { background: var(--danger-tint); color: var(--danger); } .ef.up { background: var(--ok-tint); color: var(--ok); }
.hints { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.hints li { font-size: var(--fs-s); padding: 8px 10px; border-radius: 10px; background: var(--info-tint); color: var(--ink); line-height: 1.35; }
.hints li.warn { background: var(--warn-tint); }
@media (max-width: 720px) {
  .days { gap: 3px; } .days li { padding: 6px 0; border-radius: 9px; } .e { font-size: 18px; } .days b { font-size: var(--fs-s); }
  .days small, .pp, .ef { font-size: 10px; } .ef { padding: 0 3px; }
}
</style>
