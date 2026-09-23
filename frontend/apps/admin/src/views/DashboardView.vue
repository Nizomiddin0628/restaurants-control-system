<script setup lang="ts">
/** Bosqich 1 dashboard: sozlash holati + KPI. Konstruktor (sudrash) 7-bosqichda shu sahifaga qo'shiladi. */
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiCard, UiKpi, UiIcon, UiChip, money } from '@restopos/ui'

type Summary = { tenant: { name: string; preset: string; trial_ends_at: string | null }; kpis: { key: string; label: string; value: string | number; money?: boolean; delta?: number | null; hint?: string; warn?: boolean; route?: string }[]; checklist: { key: string; label: string; done: boolean; route: string }[]; enabled_modules: string[] }
const s = ref<Summary | null>(null)
onMounted(async () => { s.value = await api.get<Summary>('/dashboard/summary') })
</script>
<template>
  <div v-if="s" class="dash">
    <div class="kpis">
      <UiKpi v-for="(k, i) in s.kpis" :key="k.key" :label="k.label" :value="k.money ? money(Number(k.value)) : k.value"
             :note="k.delta != null ? `${k.delta > 0 ? '▲' : k.delta < 0 ? '▼' : '•'} ${Math.abs(k.delta)}% ${k.hint ? '· ' + k.hint : ''}` : k.hint"
             :tone="k.warn ? 'danger' : k.delta != null ? (k.delta >= 0 ? 'ok' : 'danger') : 'muted'" :inverted="i === 0 && k.money === true" />
    </div>
    <div class="two">
      <UiCard title="Ishga tushirish ro'yxati" subtitle="Hammasi tayyor bo'lsa sayt va taomnoma mijozlarga ko'rinadi">
        <RouterLink v-for="c in s.checklist" :key="c.key" :to="c.route" class="chk" :class="{ done: c.done }">
          <span class="mark"><UiIcon v-if="c.done" name="check" :size="14" /></span>
          <span>{{ c.label }}</span>
          <UiChip :tone="c.done ? 'ok' : 'warn'" style="margin-left:auto">{{ c.done ? 'tayyor' : 'kutilmoqda' }}</UiChip>
        </RouterLink>
      </UiCard>
      <UiCard title="Keyingi bosqichlar" subtitle="Reja bo'yicha modullar shu tartibda qo'shiladi">
        <ol class="steps">
          <li><b>Kassa (POS) + fiskal + to'lov</b><span>offline, Sunmi, UzQR, Payme/Click</span></li>
          <li><b>Oshxona ekrani (KDS) + TV</b><span>stansiyalar, navbat taxtasi</span></li>
          <li><b>Telegram bot + Mini App</b><span>buyurtma, bonus karta, kuzatuv</span></li>
          <li><b>Dashboard konstruktori</b><span>vidjetlarni sudrab joylashtirish</span></li>
          <li><b>Ombor · HR · O'qitish · Marketing · Yetkazish</b><span>modul sifatida yoqiladi</span></li>
        </ol>
      </UiCard>
    </div>
  </div>
</template>
<style scoped>
.dash { display: flex; flex-direction: column; gap: 16px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.two { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 1025px) { .two { grid-template-columns: 1.2fr 1fr; } }
.chk { display: flex; align-items: center; gap: 10px; min-height: var(--touch); padding: 6px 8px; border-radius: var(--radius); text-decoration: none; color: var(--ink); font-weight: 600; }
.chk:hover { background: var(--surface-2); }
.mark { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--line); display: grid; place-items: center; color: #fff; flex-shrink: 0; }
.done .mark { background: var(--ok); border-color: var(--ok); }
.steps { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; }
.steps li b { display: block; } .steps li span { font-size: var(--fs-s); color: var(--muted); }
</style>
