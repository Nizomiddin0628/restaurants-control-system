<script setup lang="ts">
/**
 * Modullar: yoqish/o'chirish — yon menyu va API darhol o'zgaradi. Kod o'zgarmaydi.
 * Ikki ro'yxat: "Ishlaydigan modullar" (yoqiladi) va "Rejadagi" (hali yozilmagan — yoqib bo'lmaydi).
 */
import { computed, onMounted, ref } from 'vue'
import { api, type ModuleInfo } from '@restopos/api'
import { UiCard, UiToggle, UiChip, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
const mods = ref<ModuleInfo[]>([]), saving = ref(false)
const ready = computed(() => mods.value.filter(m => m.implemented))
const planned = computed(() => mods.value.filter(m => !m.implemented))
onMounted(async () => { mods.value = await api.get('/modules') })

async function toggle(m: ModuleInfo, on: boolean) {
  // faqat yozilgan modullar saqlanadi — rejadagilari bazani chalkashtirmaydi
  const enabled = mods.value.filter(x => x.implemented && (x.code === m.code ? on : x.enabled)).map(x => x.code)
  saving.value = true
  try {
    await api.put('/modules', { enabled })
    await a.load()
    mods.value = await api.get('/modules')
    toast(on ? `${t(m.name, ui.lang)} yoqildi — chap menyuda paydo bo'ldi` : `${t(m.name, ui.lang)} o'chirildi`)
  } catch (e: any) {
    mods.value = await api.get('/modules')      // xato bo'lsa tugma haqiqiy holatga qaytsin
    toast(e.detail ?? 'Xato', 'danger')
  } finally { saving.value = false }
}
</script>

<template>
  <div class="mods">
    <UiCard title="Ishlaydigan modullar" subtitle="Yoqsangiz — chap menyuda darhol paydo bo'ladi. O'chirsangiz — ma'lumot saqlanadi, faqat yashiriladi.">
      <div class="list">
        <div v-for="m in ready" :key="m.code" class="row">
          <div class="info">
            <b>{{ t(m.name, ui.lang) }}</b>
            <div class="meta">
              <UiChip tone="accent">v{{ m.version }}</UiChip>
              <UiChip v-if="!m.allowed_by_plan" tone="warn">tarifda yo'q</UiChip>
              <span v-if="m.depends.length" class="dep">bog'liq: {{ m.depends.join(', ') }}</span>
            </div>
          </div>
          <UiToggle :model-value="m.enabled" :disabled="saving || !m.allowed_by_plan || !a.can('core.modules.manage')"
                    @update:model-value="toggle(m, $event)" />
        </div>
      </div>
    </UiCard>

    <UiCard title="Rejadagi modullar" subtitle="Bular hali yozilmagan — shuning uchun yoqib bo'lmaydi. Tayyor bo'lgach shu yerda o'zi faollashadi.">
      <div class="list">
        <div v-for="m in planned" :key="m.code" class="row off">
          <div class="info">
            <b>{{ t(m.name, ui.lang) }}</b>
            <div class="meta"><UiChip tone="neutral">{{ m.phase }}-bosqich rejada</UiChip><span class="dep">tez kunda</span></div>
          </div>
          <span class="soon">tayyor emas</span>
        </div>
      </div>
    </UiCard>
  </div>
</template>

<style scoped>
.mods { display: flex; flex-direction: column; gap: 14px; }
.list { display: flex; flex-direction: column; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 4px; border-top: 1px solid var(--line-2); }
.row:first-child { border-top: 0; }
.row.off { opacity: .6; }
.info { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dep { font-size: var(--fs-xs); color: var(--muted); }
.soon { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); border: 1px dashed var(--line); border-radius: 999px; padding: 4px 10px; white-space: nowrap; }
</style>