<script setup lang="ts">
defineProps<{ tone?: 'ok' | 'warn' | 'danger' | 'info' | 'neutral' | 'accent' }>()
</script>
<template><span class="chip" :class="tone ?? 'neutral'"><slot /></span></template>
<style scoped>
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px; font-size: var(--fs-xs); font-weight: 700; white-space: nowrap; }
.neutral { background: var(--surface-3); color: var(--ink-2); }
.ok { background: var(--ok-tint); color: var(--ok); } .warn { background: var(--warn-tint); color: var(--warn-ink); }
.danger { background: var(--danger-tint); color: var(--danger); } .info { background: var(--info-tint); color: var(--info); }
.accent { background: var(--accent-tint); color: var(--accent); }
</style>
