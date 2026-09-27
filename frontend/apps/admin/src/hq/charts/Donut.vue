<script setup lang="ts">
/** Holat donuti: sog'lom / e'tibor / kritik — markazda jami. */
import { computed } from 'vue'

const props = defineProps<{ items: { key: string; label: string; value: number; color: string }[]; total?: number }>()
const R = 52, C = 2 * Math.PI * R
const segs = computed(() => {
  const tot = props.items.reduce((s, x) => s + x.value, 0)
  let acc = 0
  return { tot, list: props.items.filter(x => x.value > 0).map(x => { const len = tot ? (C * x.value) / tot : 0; const s = { ...x, len: Math.max(0, len - (props.items.length > 1 ? 2 : 0)), off: -acc }; acc += len; return s }) }
})
</script>

<template>
  <div class="dn">
    <svg viewBox="0 0 140 140" width="150" height="150" role="img" :aria-label="`Jami ${segs.tot}`">
      <circle cx="70" cy="70" :r="R" fill="none" stroke="var(--surface-3)" stroke-width="16" />
      <circle v-for="s in segs.list" :key="s.key" cx="70" cy="70" :r="R" fill="none" :stroke="s.color" stroke-width="16" :stroke-dasharray="`${s.len} ${C}`" :stroke-dashoffset="s.off" transform="rotate(-90 70 70)"><title>{{ s.label }}: {{ s.value }}</title></circle>
      <text x="70" y="76" text-anchor="middle" class="t">{{ total ?? segs.tot }}</text>
    </svg>
    <ul><li v-for="x in items" :key="x.key"><i :style="{ background: x.color }"></i><b>{{ x.value }}</b><span>{{ x.label }}</span></li></ul>
  </div>
</template>

<style scoped>
.dn { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; justify-content: center; }
.t { font-family: var(--font-display); font-size: 28px; font-weight: 800; fill: var(--ink); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
li { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); } li i { width: 12px; height: 12px; border-radius: 50%; } li b { min-width: 24px; }
</style>
