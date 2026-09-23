<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiCard, UiChip } from '@restopos/ui'
const rows = ref<any[]>([])
onMounted(async () => { rows.value = await api.get('/audit', { limit: 100 }) })
</script>
<template>
  <UiCard title="O'zgarishlar tarixi" subtitle="Kim, qachon, nima — har o'zgarish yoziladi (undo uchun asos)">
    <div class="log"><div v-for="r in rows" :key="r.id" class="r"><span class="t">{{ new Date(r.at).toLocaleString('uz-UZ') }}</span><UiChip tone="accent">{{ r.action }}</UiChip><b>{{ r.model }}</b><span class="muted">#{{ r.object_id }} · {{ r.actor ?? 'tizim' }}</span></div></div>
  </UiCard>
</template>
<style scoped>.log { display: flex; flex-direction: column; } .r { display: flex; gap: 10px; align-items: center; padding: 8px 0; border-top: 1px solid var(--line-2); font-size: var(--fs-s); flex-wrap: wrap; } .t { color: var(--muted); min-width: 140px; } .muted { color: var(--muted); }</style>
