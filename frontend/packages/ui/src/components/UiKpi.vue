<script setup lang="ts">
/** clickable — karta tugmaga aylanadi (bosilsa filtr/sahifa), on — tanlangan holat (admin'dagi global .kpi-click uslubi) */
defineProps<{ label: string; value: string | number; note?: string; tone?: 'ok' | 'warn' | 'danger' | 'muted'; inverted?: boolean; clickable?: boolean; on?: boolean }>()
</script>
<template>
  <component :is="clickable ? 'button' : 'div'" :type="clickable ? 'button' : undefined" class="kpi" :class="{ inv: inverted, 'kpi-click': clickable, on }">
    <span class="l">{{ label }}</span>
    <span class="v">{{ value }}</span>
    <span v-if="note" class="n" :class="tone ?? 'muted'">{{ note }}</span>
  </component>
</template>
<style scoped>
.kpi { display: flex; flex-direction: column; gap: 4px; padding: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); min-width: 0; }
.kpi.inv { background: var(--ink); color: var(--ink-inv); border-color: transparent; }
.l { font-size: var(--fs-s); color: var(--muted); font-weight: 600; }
.kpi.inv .l { color: var(--surface-3); }
.v { font-family: var(--font-display); font-size: var(--fs-2xl); font-weight: 800; letter-spacing: -.02em; line-height: 1.1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 600px) { .kpi { padding: 12px; } .v { font-size: var(--fs-xl); } }
.n { font-size: var(--fs-s); font-weight: 700; }
.n.ok { color: var(--ok); } .n.warn { color: var(--warn); } .n.danger { color: var(--danger); } .n.muted { color: var(--muted); font-weight: 600; }
.kpi.inv .n.muted { color: var(--surface-3); }
</style>
