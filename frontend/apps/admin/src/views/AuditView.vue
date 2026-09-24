<script setup lang="ts">
/** O'zgarishlar tarixi: kim, qachon, nimani o'zgartirdi — odam tushunadigan tilda. */
import { onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiCard, UiChip, UiEmpty } from '@restopos/ui'

const rows = ref<any[]>([])
const loaded = ref(false)
onMounted(async () => { rows.value = await api.get('/audit', { limit: 100 }); loaded.value = true })

const ACT: Record<string, [string, 'ok' | 'info' | 'danger' | 'warn' | 'accent' | 'neutral']> = {
  create: ["qo'shdi", 'ok'], update: ["o'zgartirdi", 'info'], delete: ["o'chirdi", 'danger'], deactivate: ["o'chirdi", 'danger'],
  archive: ['arxivladi', 'warn'], publish: ["e'lon qildi", 'accent'], modules: ['modullarni o\'zgartirdi', 'accent'], new_version: ['yangi versiya', 'accent'],
}
const MODEL: Record<string, string> = {
  Product: 'Taom', Category: 'Kategoriya', Branch: 'Filial', User: 'Foydalanuvchi', Role: 'Rol', Tenant: 'Restoran sozlamalari',
  Task: 'Vazifa', Course: 'Kurs', Lesson: 'Dars', Assignment: 'Topshiriq', Standard: 'Standart', Employee: 'Xodim',
  Ingredient: 'Xomashyo', Recipe: 'Tex-karta', Expense: 'Chiqim', Order: 'Buyurtma', Table: 'Stol', Reservation: 'Bron',
}
const when = (s: string) => new Date(s).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <UiCard title="O'zgarishlar tarixi" subtitle="Kim, qachon, nimani o'zgartirdi — har bir o'zgarish yozib boriladi">
    <div class="log">
      <div v-for="r in rows" :key="r.id" class="r">
        <span class="t">{{ when(r.at) }}</span>
        <b class="who">{{ r.actor ?? 'Tizim' }}</b>
        <UiChip :tone="(ACT[r.action] ?? [r.action, 'neutral'])[1]">{{ (ACT[r.action] ?? [r.action])[0] }}</UiChip>
        <span class="what">{{ MODEL[r.model] ?? r.model }}<small v-if="r.object_id"> #{{ r.object_id.slice(0, 8) }}</small></span>
      </div>
    </div>
    <UiEmpty v-if="loaded && !rows.length" title="Hali o'zgarish yo'q" text="Taom, narx, xodim yoki sozlama o'zgartirilganda shu yerda ko'rinadi." />
  </UiCard>
</template>

<style scoped>
.log { display: flex; flex-direction: column; }
.r { display: grid; grid-template-columns: 110px minmax(120px, 200px) auto 1fr; gap: 10px; align-items: center; padding: 10px 0; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.t { color: var(--muted); font-variant-numeric: tabular-nums; }
.who { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.what small { color: var(--muted); }
@media (max-width: 600px) { .r { grid-template-columns: 1fr auto; } .t { grid-column: 1 / -1; font-size: var(--fs-xs); } .what { grid-column: 1 / -1; } }
</style>
