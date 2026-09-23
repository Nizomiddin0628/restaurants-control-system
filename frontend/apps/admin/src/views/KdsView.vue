<script setup lang="ts">
/**
 * Oshxona ekrani (KDS) — oshpaz uchun: katta kartalar, rang bilan kutish vaqti, bir bosishda holat.
 * Yashil — yangi, sariq — kutmoqda, qizil — kechikdi. Har N soniyada o'zi yangilanadi.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiEmpty, UiIcon, UiSelect, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
const meta = ref<any>(null)
const tickets = ref<any[]>([])
const stats = ref<any>(null)
const stationId = ref<number | null>(null)
const fullscreen = ref(false)
const showServed = ref(false)
const settingsOpen = ref(false)
const stForm = ref<any>(null)
let timer: any = null

const TYPE: Record<string, string> = { dine_in: 'Zalda', takeaway: 'Olib ketish', delivery: 'Yetkazish' }
const COLS = [
  { code: 'new', label: 'Yangi', next: 'cooking', btn: 'Boshlash' },
  { code: 'cooking', label: 'Tayyorlanmoqda', next: 'ready', btn: 'Tayyor' },
  { code: 'ready', label: 'Tayyor', next: 'served', btn: 'Berildi' },
]

async function loadMeta() { meta.value = await api.get('/kds/meta'); if (stationId.value === null) stationId.value = 0 }
async function load() {
  tickets.value = await api.get('/kds/board', { station_id: stationId.value || undefined, include_served: showServed.value || undefined })
  stats.value = await api.get('/kds/stats')
}
onMounted(async () => {
  await loadMeta(); await load()
  timer = setInterval(load, (meta.value?.settings.auto_refresh_seconds ?? 5) * 1000)
})
onUnmounted(() => clearInterval(timer))

const byStatus = (code: string) => tickets.value.filter(x => x.status === code)
function tone(m: number) {
  const s = meta.value?.settings ?? { warn_minutes: 8, late_minutes: 15 }
  return m >= s.late_minutes ? 'late' : m >= s.warn_minutes ? 'warn' : 'ok'
}
async function move(tk: any, status: string) {
  try { Object.assign(tk, await api.post(`/kds/tickets/${tk.id}/status`, { status })); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function toggleItem(it: any, tk: any) {
  try { Object.assign(tk, await api.post(`/kds/items/${it.id}/toggle`)); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function openStation(s?: any) {
  stForm.value = s ? { ...s, name: { ...s.name }, category_ids: [...s.category_ids] }
    : { name: { uz: '', ru: '', en: '' }, color: '#0F6E63', category_ids: [], is_active: true }
  settingsOpen.value = true
}
async function saveStation() {
  try {
    stForm.value.id ? await api.put(`/kds/stations/${stForm.value.id}`, stForm.value) : await api.post('/kds/stations', stForm.value)
    settingsOpen.value = false; await loadMeta(); await load(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delStation(s: any) {
  if (!confirm(`«${t(s.name, ui.lang)}» stansiyasi o'chirilsinmi?`)) return
  try { await api.del(`/kds/stations/${s.id}`); await loadMeta() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function toggleCat(id: number) {
  const i = stForm.value.category_ids.indexOf(id)
  i >= 0 ? stForm.value.category_ids.splice(i, 1) : stForm.value.category_ids.push(id)
}
const stationOptions = computed(() => [{ value: '0', label: 'Barcha stansiyalar' },
  ...(meta.value?.stations ?? []).map((s: any) => ({ value: String(s.id), label: `${t(s.name, ui.lang)} (${s.open_count})` }))])
</script>

<template>
  <div class="kds" :class="{ fs: fullscreen }">
    <header class="bar">
      <UiSelect :model-value="String(stationId ?? 0)" :options="stationOptions" @update:model-value="v => { stationId = Number(v); load() }" />
      <button class="chip-btn" :class="{ on: showServed }" @click="showServed = !showServed; load()">Berilganlar</button>
      <div v-if="stats" class="st">
        <span><b>{{ stats.open }}</b> ochiq</span>
        <span><b>{{ stats.tickets }}</b> bugun</span>
        <span v-if="stats.avg_minutes"><b>{{ stats.avg_minutes }}</b> daq o'rtacha</span>
        <span v-if="stats.late" class="late"><b>{{ stats.late }}</b> kechikkan</span>
      </div>
      <div class="sp"></div>
      <UiButton v-if="meta?.can.admin" size="s" variant="secondary" @click="openStation()"><UiIcon name="plus" :size="14" /> Stansiya</UiButton>
      <UiButton size="s" variant="secondary" @click="fullscreen = !fullscreen"><UiIcon name="tv" :size="14" /> {{ fullscreen ? 'Chiqish' : 'To\'liq ekran' }}</UiButton>
    </header>

    <div class="cols">
      <section v-for="c in COLS" :key="c.code" class="col" :class="c.code">
        <header><b>{{ c.label }}</b><span class="cnt">{{ byStatus(c.code).length }}</span></header>
        <div class="cards">
          <article v-for="tk in byStatus(c.code)" :key="tk.id" class="tk" :class="tone(tk.waiting_minutes)">
            <div class="tk-h">
              <b class="num">#{{ tk.number }}</b>
              <UiChip :tone="tk.order_type === 'delivery' ? 'info' : tk.order_type === 'dine_in' ? 'accent' : 'neutral'">
                {{ TYPE[tk.order_type] }}{{ tk.table_no ? ` · ${tk.table_no}` : '' }}</UiChip>
              <span class="sp"></span>
              <span class="min"><UiIcon name="clock" :size="14" /> {{ tk.waiting_minutes }}′</span>
            </div>
            <span v-if="tk.station_name" class="stn">{{ t(tk.station_name, ui.lang) }}</span>
            <ul class="items">
              <li v-for="it in tk.items" :key="it.id" :class="{ done: it.is_done }" @click="meta?.can.cook && toggleItem(it, tk)">
                <b>{{ it.qty }}×</b> {{ it.name }}
                <small v-if="it.note">— {{ it.note }}</small>
                <small v-for="(m, i) in it.modifiers" :key="i">+ {{ m.name }}</small>
              </li>
            </ul>
            <p v-if="tk.note" class="note"><UiIcon name="alert" :size="13" /> {{ tk.note }}</p>
            <div class="acts">
              <UiButton v-if="meta?.can.cook" size="l" block :variant="c.code === 'ready' ? 'primary' : 'brand'" @click="move(tk, c.next)">{{ c.btn }}</UiButton>
              <UiButton v-if="meta?.can.cook && c.code !== 'new'" size="s" variant="ghost" @click="move(tk, c.code === 'cooking' ? 'new' : 'cooking')">Orqaga</UiButton>
            </div>
          </article>
          <UiEmpty v-if="!byStatus(c.code).length" :title="c.code === 'new' ? 'Yangi buyurtma yo\'q' : '—'" />
        </div>
      </section>
    </div>

    <UiDrawer :open="settingsOpen" :title="stForm?.id ? 'Stansiya' : 'Yangi stansiya'" width="520px" @close="settingsOpen = false">
      <template v-if="stForm">
        <label class="fl"><span>Nomi</span><input v-model="stForm.name.uz" placeholder="Issiq oshxona" /></label>
        <label class="fl"><span>Rang</span><input v-model="stForm.color" type="color" /></label>
        <p class="fl-lbl">Qaysi kategoriyalar shu ekranga tushsin:</p>
        <div class="cats">
          <button v-for="c in meta?.categories ?? []" :key="c.id" class="cat" :class="{ on: stForm.category_ids.includes(c.id) }" @click="toggleCat(c.id)">
            {{ t(c.name, ui.lang) }}</button>
        </div>
        <p class="hint">Hech biri tanlanmasa — bu stansiya faqat boshqa stansiyalarga tegishli bo'lmagan taomlarni oladi.</p>
        <div v-if="meta?.stations?.length" class="exist">
          <p class="fl-lbl">Mavjud stansiyalar:</p>
          <div v-for="s in meta.stations" :key="s.id" class="ex-row">
            <span class="dot" :style="{ background: s.color }"></span><b>{{ t(s.name, ui.lang) }}</b>
            <span class="sp"></span>
            <UiButton size="s" variant="ghost" @click="openStation(s)"><UiIcon name="edit" :size="13" /></UiButton>
            <UiButton size="s" variant="ghost" @click="delStation(s)"><UiIcon name="trash" :size="13" /></UiButton>
          </div>
        </div>
      </template>
      <template #footer><UiButton variant="ghost" @click="settingsOpen = false">Yopish</UiButton><UiButton variant="brand" @click="saveStation()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.kds { display: flex; flex-direction: column; gap: 12px; }
.kds.fs { position: fixed; inset: 0; z-index: 100; background: var(--bg); padding: 14px; overflow: auto; }
.bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.st { display: flex; gap: 14px; font-size: var(--fs-s); color: var(--muted); } .st b { color: var(--ink); font-family: var(--font-display); font-size: var(--fs-l); }
.st .late b { color: var(--danger); }
.chip-btn { min-height: var(--touch); padding: 0 14px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); font-weight: 700; cursor: pointer; }
.chip-btn.on { background: var(--accent-tint); color: var(--accent); border-color: var(--accent); }
.cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; align-items: start; }
.col { background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 10px; }
.col > header { display: flex; align-items: center; gap: 8px; padding-bottom: 8px; }
.cnt { background: var(--surface-3); border-radius: 999px; padding: 1px 9px; font-weight: 800; font-size: var(--fs-xs); }
.cards { display: flex; flex-direction: column; gap: 10px; }
.tk { background: var(--surface); border: 1px solid var(--line); border-left: 5px solid var(--ok); border-radius: var(--radius); padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.tk.warn { border-left-color: var(--warn); } .tk.late { border-left-color: var(--danger); background: var(--danger-tint); }
.tk-h { display: flex; align-items: center; gap: 8px; }
.num { font-family: var(--font-display); font-size: var(--fs-xl); }
.min { font-weight: 800; display: inline-flex; align-items: center; gap: 4px; }
.tk.late .min { color: var(--danger); } .tk.warn .min { color: var(--warn-ink); }
.stn { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.items { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.items li { padding: 6px 8px; border-radius: var(--radius-s); background: var(--surface-2); cursor: pointer; font-size: var(--fs-b); }
.items li.done { text-decoration: line-through; color: var(--muted); background: var(--ok-tint); }
.items small { color: var(--muted); font-size: var(--fs-xs); margin-left: 6px; }
.note { margin: 0; font-size: var(--fs-s); color: var(--warn-ink); display: flex; gap: 6px; align-items: center; }
.acts { display: flex; gap: 6px; align-items: center; }
.acts > :first-child { flex: 1; }
.fl { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.fl input { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; min-height: var(--touch); background: var(--surface); }
.fl-lbl { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; margin: 8px 0 4px; }
.cats { display: flex; gap: 6px; flex-wrap: wrap; }
.cat { border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 6px 12px; font-size: var(--fs-s); font-weight: 700; cursor: pointer; }
.cat.on { background: var(--accent-tint); color: var(--accent); border-color: var(--accent); }
.hint { font-size: var(--fs-xs); color: var(--muted); margin: 8px 0 0; }
.exist { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
.ex-row { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); padding: 4px 0; }
.dot { width: 10px; height: 10px; border-radius: 3px; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
@media (min-width: 1921px) { .num { font-size: var(--fs-2xl); } .items li { font-size: var(--fs-l); } }
</style>