<script setup lang="ts">
defineProps<{ title: string; text?: string }>()
</script>
<template>
  <div class="empty"><h3>{{ title }}</h3><p v-if="text">{{ text }}</p><div class="a"><slot /></div></div>
</template>
<style scoped>
.empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; padding: 40px 20px; border: 1px dashed var(--line); border-radius: var(--radius-l); color: var(--muted); }
h3 { margin: 0; color: var(--ink); font-size: var(--fs-l); } p { margin: 0; max-width: 420px; } .a { display: flex; gap: 8px; margin-top: 8px; }
</style>
