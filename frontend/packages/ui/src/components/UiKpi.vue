<script setup lang="ts">
defineProps<{ label: string; value: string | number; note?: string; tone?: 'ok' | 'warn' | 'danger' | 'muted'; inverted?: boolean }>()
</script>
<template>
  <div class="kpi" :class="{ inv: inverted }">
    <span class="l">{{ label }}</span>
    <span class="v">{{ value }}</span>
    <span v-if="note" class="n" :class="tone ?? 'muted'">{{ note }}</span>
  </div>
</template>
<style scoped>
.kpi { display: flex; flex-direction: column; gap: 4px; padding: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); min-width: 0; }
.kpi.inv { background: var(--ink); color: var(--ink-inv); border-color: transparent; }
.l { font-size: var(--fs-s); color: var(--muted); font-weight: 600; }
.inv .l { color: var(--surface-3); }
.v { font-family: var(--font-display); font-size: var(--fs-2xl); font-weight: 800; letter-spacing: -.02em; line-height: 1.1; }
.n { font-size: var(--fs-s); font-weight: 700; }
.n.ok { color: var(--ok); } .n.warn { color: var(--warn); } .n.danger { color: var(--danger); } .n.muted { color: var(--muted); font-weight: 600; }
.inv .n.muted { color: var(--surface-3); }
</style>
