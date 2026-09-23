<script setup lang="ts">
defineProps<{ title?: string; subtitle?: string; padded?: boolean; inverted?: boolean }>()
</script>
<template>
  <section class="ui-card" :class="{ inv: inverted, pad: padded !== false }">
    <header v-if="title || $slots.actions" class="hd">
      <div><h3 v-if="title" class="t">{{ title }}</h3><p v-if="subtitle" class="s">{{ subtitle }}</p></div>
      <div class="act"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>
<style scoped>
.ui-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.ui-card.pad { padding: var(--space-5) var(--space-5); }
.ui-card.inv { background: var(--ink); color: var(--ink-inv); border-color: transparent; }
.hd { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.t { margin: 0; font-size: var(--fs-l); font-weight: 800; }
.s { margin: 4px 0 0; font-size: var(--fs-s); color: var(--muted); }
.inv .s { color: var(--surface-3); }
.act { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
