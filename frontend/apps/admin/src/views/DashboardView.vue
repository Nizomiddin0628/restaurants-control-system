<script setup lang="ts">
/** Boshqaruv paneli: bugungi KPI + ishga tushirish ro'yxati + tezkor bo'limlar (foydalanuvchi ruxsatiga qarab). */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiCard, UiKpi, UiIcon, UiChip, money, t } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

type Summary = { tenant: { name: string; preset: string; trial_ends_at: string | null }; kpis: { key: string; label: string; value: string | number; money?: boolean; delta?: number | null; hint?: string; warn?: boolean; route?: string }[]; checklist: { key: string; label: string; done: boolean; route: string }[]; enabled_modules: string[] }
const s = ref<Summary | null>(null)
onMounted(async () => { s.value = await api.get<Summary>('/dashboard/summary') })
const a = useAuth(), ui = useUi()
/** Tezkor bo'limlar — yoqilgan modullar menyusidan (dashboard'ning o'zidan tashqari) */
const quick = computed(() => (a.me?.nav ?? []).filter(n => n.route !== '/').slice(0, 8))
const doneCount = computed(() => s.value?.checklist.filter(c => c.done).length ?? 0)
</script>
<template>
  <div v-if="s" class="dash">
    <div class="kpis">
      <UiKpi v-for="(k, i) in s.kpis" :key="k.key" :label="k.label" :value="k.money ? money(Number(k.value)) : k.value"
             :note="k.delta != null ? `${k.delta > 0 ? '▲' : k.delta < 0 ? '▼' : '•'} ${Math.abs(k.delta)}% ${k.hint ? '· ' + k.hint : ''}` : k.hint"
             :tone="k.warn ? 'danger' : k.delta != null ? (k.delta >= 0 ? 'ok' : 'danger') : 'muted'" :inverted="i === 0 && k.money === true" />
    </div>
    <div class="two">
      <UiCard title="Ishga tushirish ro'yxati" :subtitle="`${doneCount} / ${s.checklist.length} tayyor — hammasi tayyor bo'lsa sayt va taomnoma mijozlarga ko'rinadi`">
        <RouterLink v-for="c in s.checklist" :key="c.key" :to="c.route" class="chk" :class="{ done: c.done }">
          <span class="mark"><UiIcon v-if="c.done" name="check" :size="14" /></span>
          <span>{{ c.label }}</span>
          <UiChip :tone="c.done ? 'ok' : 'warn'" style="margin-left:auto">{{ c.done ? 'tayyor' : 'kutilmoqda' }}</UiChip>
        </RouterLink>
      </UiCard>
      <UiCard title="Tezkor bo'limlar" subtitle="Eng ko'p ishlatiladigan joylar — bir bosishda">
        <div class="quick">
          <RouterLink v-for="n in quick" :key="n.route" :to="n.route" class="q">
            <span class="qi"><UiIcon :name="n.icon" :size="20" /></span><span>{{ t(n.label, ui.lang) }}</span>
          </RouterLink>
        </div>
      </UiCard>
    </div>
  </div>
</template>
<style scoped>
.dash { display: flex; flex-direction: column; gap: 16px; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 1024px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.two { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 1025px) { .two { grid-template-columns: 1.2fr 1fr; } }
.chk { display: flex; align-items: center; gap: 10px; min-height: var(--touch); padding: 6px 8px; border-radius: var(--radius); text-decoration: none; color: var(--ink); font-weight: 600; }
.chk:hover { background: var(--surface-2); }
.mark { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--line); display: grid; place-items: center; color: #fff; flex-shrink: 0; }
.done .mark { background: var(--ok); border-color: var(--ok); }
.quick { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.q { display: flex; align-items: center; gap: 10px; min-height: 56px; padding: 8px 12px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--ink); text-decoration: none; font-weight: 700; font-size: var(--fs-m); }
.q:hover { border-color: var(--accent); background: var(--accent-tint); }
.qi { width: 36px; height: 36px; border-radius: 10px; background: var(--surface-3); color: var(--accent); display: grid; place-items: center; flex-shrink: 0; }
</style>
