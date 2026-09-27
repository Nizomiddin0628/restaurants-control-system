<script setup lang="ts">
/**
 * Bo'lim sahifasi = shu bo'limning dashboardi:
 *   sarlavha + davr (bugun / 7 kun / 30 kun) → modullarga tez o'tish → asosiy ko'rsatkichlar → grafiklar va ro'yxatlar;
 *   pastida — «Asosiy sahifaga qaytish». Ma'lumot 60 soniyada yangilanadi.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiEmpty, UiIcon, t } from '@restopos/ui'
import { useUi } from '@/stores/ui'
import { useNav, useSectionStats } from '@/nav/sections'
import DashWidget from '@/components/dash/DashWidget.vue'

const route = useRoute(), router = useRouter(), ui = useUi()
const { sections } = useNav()
const code = computed(() => String(route.params.code))
const S = computed(() => sections.value.find(s => s.code === code.value))
const { stats, load } = useSectionStats()
const kpis = computed(() => stats.value?.[code.value] ?? [])
const days = ref<number>(Number(localStorage.getItem('sec.days')) || 7)
const D = ref<any>(null)
const loading = ref(false)

async function loadDash() {
  loading.value = true
  try { D.value = await api.get(`/dashboard/section/${code.value}`, { days: days.value, ...(ui.branch ? { branch_id: ui.branch } : {}) }) } catch { D.value = { widgets: [] } } finally { loading.value = false }
}
function refresh() { load(true); loadDash() }
let timer: number | undefined
onMounted(() => { refresh(); timer = window.setInterval(() => { if (!document.hidden) refresh() }, 60_000) })
onBeforeUnmount(() => clearInterval(timer))
watch(code, () => { D.value = null; refresh() })
watch(() => ui.branch, () => refresh())
watch(days, (v) => { try { localStorage.setItem('sec.days', String(v)) } catch { /* private */ } loadDash() })
const updated = computed(() => { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` })
</script>

<template>
  <div class="sv">
    <template v-if="S">
      <header class="hd" :style="{ '--sc': S.color }">
        <span class="em">{{ S.emoji }}</span>
        <div class="ht"><h2>{{ S.title }}</h2><p>{{ S.desc }}</p></div>
        <div class="per" role="tablist" aria-label="Davr">
          <button v-for="p in [[1, 'Bugun'], [7, '7 kun'], [30, '30 kun']] as const" :key="p[0]" type="button" :class="{ on: days === p[0] }" @click="days = p[0]">{{ p[1] }}</button>
        </div>
      </header>

      <nav class="go" aria-label="Bo'lim modullari" :style="{ '--sc': S.color }">
        <RouterLink v-for="m in S.items" :key="m.route" :to="m.route" :title="m.desc"><UiIcon :name="m.icon" :size="18" /><span>{{ t(m.label, ui.lang) }}</span></RouterLink>
      </nav>

      <section v-if="kpis.length" class="kpis" :style="{ '--sc': S.color }" aria-label="Asosiy ko'rsatkichlar">
        <RouterLink v-for="k in kpis" :key="k.label" :to="k.route || '/'" class="kpi" :class="k.tone">
          <span class="ki">{{ k.icon }}</span>
          <span class="kt"><small>{{ k.label }}</small><b>{{ k.value }}</b><em>{{ k.hint }}</em></span>
        </RouterLink>
      </section>

      <section v-if="D" class="grid" :class="{ busy: loading }">
        <DashWidget v-for="(w, i) in D.widgets" :key="`${code}-${i}-${w.title}`" :w="w" :color="S.color" />
      </section>
      <div v-else class="skel"><div v-for="i in 4" :key="i"></div></div>
      <UiEmpty v-if="D && !D.widgets.length" title="Bu bo'lim uchun hali ma'lumot yo'q" text="Modullardan foydalanishni boshlang — grafiklar o'zi to'ladi." />

      <footer class="ft">
        <small>Yangilandi: {{ updated }} · har daqiqada o'zi yangilanadi</small>
        <UiButton variant="ghost" @click="router.push('/')"><UiIcon name="home" :size="16" /> Asosiy sahifaga qaytish</UiButton>
      </footer>
    </template>
    <UiEmpty v-else title="Bo'lim topilmadi" text="Bu bo'lim yoqilmagan yoki sizga ruxsat berilmagan.">
      <UiButton variant="brand" @click="router.push('/')">Asosiy sahifa</UiButton>
    </UiEmpty>
  </div>
</template>

<style scoped>
.sv { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; gap: 14px; align-items: center; padding: 14px 18px; border-radius: 18px; background: color-mix(in srgb, var(--sc) 9%, var(--surface)); border: 1px solid color-mix(in srgb, var(--sc) 25%, transparent); }
.em { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; font-size: 28px; background: var(--surface); flex-shrink: 0; }
.ht { flex: 1; min-width: 0; } h2 { margin: 0; font-family: var(--font-display); font-size: 22px; } .ht p { margin: 2px 0 0; color: var(--ink-2); font-size: var(--fs-s); }
.per { display: flex; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 3px; flex-shrink: 0; }
.per button { border: 0; background: transparent; padding: 7px 12px; border-radius: 9px; font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; color: var(--muted); white-space: nowrap; }
.per button.on { background: var(--sc); color: #fff; }
.go { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
.go a { display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line); color: var(--ink); text-decoration: none;
  font-weight: 700; font-size: var(--fs-s); white-space: nowrap; flex-shrink: 0; }
.go a:hover { border-color: var(--sc); color: var(--sc); } .go a :deep(svg) { color: var(--sc); }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.kpi { display: flex; gap: 12px; align-items: center; padding: 14px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line); text-decoration: none; color: var(--ink); min-width: 0; }
.kpi:hover { border-color: var(--sc); }
.ki { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; font-size: 20px; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 12%, transparent); }
.kt { display: flex; flex-direction: column; min-width: 0; } .kt small { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); }
.kt b { font-family: var(--font-display); font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kt em { font-style: normal; font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kpi.ok { border-left: 4px solid var(--ok); } .kpi.warn { border-left: 4px solid #F59E0B; } .kpi.bad { border-left: 4px solid var(--danger); } .kpi.bad b { color: var(--danger); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; transition: opacity .2s; }
.grid.busy { opacity: .6; }
.skel { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; } .skel div { height: 220px; border-radius: 16px; background: var(--surface-2); animation: pl 1.2s infinite alternate; }
@keyframes pl { to { opacity: .5; } }
.ft { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; } .ft small { color: var(--muted); font-size: var(--fs-xs); }
@media (max-width: 900px) { .grid { grid-template-columns: minmax(0, 1fr); } .hd { flex-wrap: wrap; } .per { width: 100%; } .per button { flex: 1; } }
@media (max-width: 640px) {
  .hd { padding: 12px; } .em { width: 44px; height: 44px; font-size: 24px; } h2 { font-size: 19px; }
  .kpis { grid-template-columns: 1fr 1fr; gap: 8px; } .kpi { padding: 10px; gap: 8px; } .ki { width: 32px; height: 32px; font-size: 16px; } .kt b { font-size: 16px; }
  .skel { grid-template-columns: 1fr; } .ft { flex-direction: column-reverse; align-items: stretch; } .ft small { text-align: center; }
}
</style>
