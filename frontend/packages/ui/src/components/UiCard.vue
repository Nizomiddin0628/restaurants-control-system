<script setup lang="ts">
// padded: Vue boolean prop'ni yo'q bo'lsa `false` qiladi — shuning uchun standartni aniq `true` qilamiz
withDefaults(defineProps<{ title?: string; subtitle?: string; padded?: boolean; inverted?: boolean }>(), { padded: true })
</script>
<template>
  <section class="ui-card" :class="{ inv: inverted, pad: padded }">
    <header v-if="title || $slots.actions" class="hd">
      <div><h3 v-if="title" class="t">{{ title }}</h3><p v-if="subtitle" class="s">{{ subtitle }}</p></div>
      <div class="act"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>
<style scoped>
.ui-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); display: flex; flex-direction: column; gap: 14px; min-width: 0; box-shadow: var(--shadow-s); }
.ui-card.pad { padding: var(--space-5) var(--space-5); }
.ui-card:not(.pad) > .hd { padding: var(--space-4) var(--space-5) 0; }
@media (max-width: 600px) { .ui-card.pad { padding: var(--space-4); } .ui-card:not(.pad) > .hd { padding: var(--space-4) var(--space-4) 0; } }
.ui-card.inv { background: linear-gradient(135deg, #0B1630, #0E2350); color: #EAF1FF; border-color: transparent; }
.hd { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.t { margin: 0; font-size: var(--fs-l); font-weight: 700; letter-spacing: -.01em; }
.s { margin: 4px 0 0; font-size: var(--fs-s); color: var(--muted); }
/* .ui-card.inv — sahifa ildizidagi boshqa .inv klassi bilan to'qnashmasin */
.ui-card.inv .s { color: #9FB2D6; }
.act { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
