<script setup lang="ts">
/**
 * Bron va navbat — administrator ekrani.
 * Chapda kun bo'yicha bronlar (vaqt bo'yicha tartiblangan), o'ngda navbat (joy yo'q mehmonlar).
 * Bron «O'tirdi» qilinsa — zal xaritasida stol darhol band bo'ladi.
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, toast } from '@restopos/ui'

const meta = ref<any>(null)
const rows = ref<any[]>([])
const wait = ref<any[]>([])
const stats = ref<any>(null)
/** mahalliy sana (UTC emas — Toshkentda tun yarmidan keyin «kecha» bo'lib qolmasin) */
const localIso = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const day = ref(localIso(new Date()))
const filter = ref('')
/** KPI kartalar: bosilsa — ro'yxat shu holat bo'yicha filtrlanadi (yoki navbat kartasiga o'tadi) */
const kf = ref<'' | 'active' | 'seated' | 'no_show'>('')
const KF: Record<string, string> = { active: 'kutilmoqda', seated: "o'tirgan", no_show: 'kelmadi' }
const waitEl = ref<any>(null)
const rowsShown = computed(() => rows.value.filter((r: any) => !kf.value || (kf.value === 'active' ? ['new', 'confirmed'].includes(r.status) : r.status === kf.value)))
function kpiGo(k: '' | 'active' | 'seated' | 'no_show' | 'wait') {
  if (k === 'wait') { (waitEl.value?.$el ?? waitEl.value)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); return }
  if (filter.value) { filter.value = ''; load() }
  kf.value = kf.value === k ? '' : k
}
const search = ref('')
const open = ref(false)
const form = ref<any>(null)
const avail = ref<any>(null)
const waitOpen = ref(false)
const waitForm = ref<any>(null)
const seatFor = ref<any>(null)   // navbatdagi mehmonga stol tanlash

const ST: Record<string, { label: string; tone: any }> = {
  new: { label: 'Yangi', tone: 'info' },
  confirmed: { label: 'Tasdiqlandi', tone: 'accent' },
  seated: { label: "O'tirdi", tone: 'ok' },
  done: { label: 'Tugadi', tone: 'neutral' },
  cancelled: { label: 'Bekor', tone: 'neutral' },
  no_show: { label: 'Kelmadi', tone: 'danger' },
}
const WST: Record<string, { label: string; tone: any }> = {
  waiting: { label: 'Navbatda', tone: 'warn' },
  called: { label: 'Chaqirildi', tone: 'info' },
  seated: { label: "O'tirdi", tone: 'ok' },
  left: { label: 'Ketdi', tone: 'neutral' },
}
const hhmm = (s: string) => new Date(s).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' })

async function load() {
  rows.value = await api.get('/reservations', { date: day.value, status: filter.value || undefined, q: search.value || undefined })
  stats.value = await api.get('/reservations/stats', { date: day.value })
  wait.value = await api.get('/reservations/waitlist')
}
onMounted(async () => { meta.value = await api.get('/reservations/meta'); await load() })

const canManage = computed(() => !!meta.value?.can.manage)
const freeTables = computed(() => (meta.value?.tables ?? []))

function shiftDay(n: number) {
  const d = new Date(`${day.value}T12:00:00`); d.setDate(d.getDate() + n)
  day.value = localIso(d); load()
}

// ---------------------------------------------------------------- bron formasi
function openForm(r?: any) {
  form.value = r
    ? { ...r, date: r.starts_at.slice(0, 10), time: hhmm(r.starts_at) }
    : { guest_name: '', phone: '', guests: 2, table_id: null, date: day.value, time: '19:00', occasion: '', note: '', deposit: 0, source: 'phone', auto_table: true, duration_minutes: meta.value?.settings.default_duration_minutes ?? 90 }
  avail.value = null
  open.value = true
}
function startsAt(): string {
  const [h, m] = String(form.value.time || '19:00').split(':')
  const d = new Date(`${form.value.date}T${(h ?? '19').padStart(2, '0')}:${(m ?? '00').padStart(2, '0')}:00`)
  return d.toISOString()
}
async function checkFree() {
  try {
    avail.value = await api.get('/reservations/availability', { at: startsAt(), guests: form.value.guests, exclude_id: form.value.id })
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function save() {
  const f = form.value
  if (!f.guest_name) return toast('Mehmon ismini yozing', 'danger')
  const body = {
    guest_name: f.guest_name, phone: f.phone ?? '', guests: Number(f.guests) || 1,
    table_id: f.table_id ? Number(f.table_id) : null, starts_at: startsAt(),
    duration_minutes: Number(f.duration_minutes) || 0, source: f.source ?? 'phone',
    note: f.note ?? '', occasion: f.occasion ?? '', deposit: Number(f.deposit) || 0, auto_table: !!f.auto_table,
  }
  try {
    f.id ? await api.put(`/reservations/${f.id}`, body) : await api.post('/reservations', body)
    open.value = false; day.value = f.date; await load(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function setStatus(r: any, status: string, table_id?: number) {
  try { await api.post(`/reservations/${r.id}/status`, { status, table_id: table_id ?? null }); await load(); toast('Yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function remove(r: any) {
  if (!confirm(`${r.guest_name} broni o'chirilsinmi?`)) return
  try { await api.del(`/reservations/${r.id}`); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function markNoShows() {
  try { const r = await api.post('/reservations/mark-no-shows'); await load(); toast(`${r.marked} ta bron «kelmadi» deb belgilandi`) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---------------------------------------------------------------- navbat
function openWait() { waitForm.value = { guest_name: '', phone: '', guests: 2, note: '', quoted_minutes: meta.value?.quote_minutes ?? 15 }; waitOpen.value = true }
async function saveWait() {
  try {
    await api.post('/reservations/waitlist', { ...waitForm.value, guests: Number(waitForm.value.guests) || 1, quoted_minutes: Number(waitForm.value.quoted_minutes) || 0 })
    waitOpen.value = false; await load(); toast('Navbatga yozildi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function waitStatus(w: any, status: string, table_id?: number) {
  try { await api.post(`/reservations/waitlist/${w.id}/status`, { status, table_id: table_id ?? null }); seatFor.value = null; await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div class="res">
    <header class="bar">
      <div class="nav">
        <UiButton size="s" variant="ghost" @click="shiftDay(-1)">‹</UiButton>
        <input v-model="day" type="date" class="date" @change="load()" />
        <UiButton size="s" variant="ghost" @click="shiftDay(1)">›</UiButton>
      </div>
      <UiSelect :model-value="filter" :options="[{ value: '', label: 'Barcha holat' }, ...Object.entries(ST).map(([v, o]) => ({ value: v, label: o.label }))]"
                @update:model-value="v => { filter = v; load() }" />
      <input v-model="search" class="srch" placeholder="Ism yoki telefon…" @keyup.enter="load()" />
      <div class="sp"></div>
      <UiButton v-if="canManage" size="s" variant="secondary" @click="markNoShows()">Kelmaganlarni belgilash</UiButton>
      <UiButton v-if="canManage" size="s" variant="brand" @click="openForm()"><UiIcon name="plus" :size="14" /> Yangi bron</UiButton>
    </header>

    <div class="kpis">
      <button type="button" class="k kpi-click" :class="{ on: !kf && !filter }" @click="kpiGo('')"><span>Bronlar</span><b>{{ stats?.total ?? 0 }}</b></button>
      <button type="button" class="k kpi-click" :class="{ on: kf === 'active' }" @click="kpiGo('active')"><span>Kutilmoqda</span><b>{{ stats?.active ?? 0 }}</b></button>
      <button type="button" class="k kpi-click" :class="{ on: kf === 'seated' }" @click="kpiGo('seated')"><span>O'tirgan</span><b>{{ stats?.seated ?? 0 }}</b></button>
      <button type="button" class="k kpi-click" @click="kpiGo('')"><span>Mehmon</span><b>{{ stats?.guests ?? 0 }}</b></button>
      <button type="button" class="k kpi-click" :class="{ on: kf === 'no_show' }" @click="kpiGo('no_show')"><span>Kelmadi</span><b :class="{ bad: stats?.no_show }">{{ stats?.no_show ?? 0 }}</b></button>
      <button type="button" class="k kpi-click" @click="kpiGo('wait')"><span>Navbatda</span><b>{{ stats?.waitlist ?? 0 }}</b></button>
    </div>

    <div class="cols">
      <UiCard title="Bronlar" subtitle="Kun bo'yicha, vaqt tartibida. Kechikkanlari qizil ko'rinadi.">
        <div class="list">
          <p v-if="kf" class="flt">Filtr: {{ KF[kf] }} — {{ rowsShown.length }} ta · <button type="button" @click="kf = ''">hammasi ✕</button></p>
          <article v-for="r in rowsShown" :key="r.id" class="item" :class="{ late: r.is_late && (r.status === 'new' || r.status === 'confirmed') }">
            <div class="time">
              <b>{{ hhmm(r.starts_at) }}</b>
              <small>{{ r.duration_minutes }} daq</small>
            </div>
            <div class="who">
              <div class="l1"><b>{{ r.guest_name }}</b><UiChip :tone="ST[r.status].tone">{{ ST[r.status].label }}</UiChip>
                <UiChip v-if="r.occasion" tone="accent">{{ r.occasion }}</UiChip></div>
              <div class="l2">
                <span><UiIcon name="users" :size="12" /> {{ r.guests }} kishi</span>
                <span><UiIcon name="sofa" :size="12" /> {{ r.table_no ?? 'stol tanlanmagan' }}</span>
                <span v-if="r.phone"><UiIcon name="bell" :size="12" /> {{ r.phone }}</span>
                <span v-if="r.note" class="note">{{ r.note }}</span>
              </div>
            </div>
            <div v-if="canManage" class="acts">
              <UiButton v-if="r.status === 'new'" size="s" variant="secondary" @click="setStatus(r, 'confirmed')">Tasdiqlash</UiButton>
              <UiButton v-if="r.status === 'new' || r.status === 'confirmed'" size="s" variant="brand" @click="setStatus(r, 'seated')">O'tirdi</UiButton>
              <UiButton v-if="r.status === 'seated'" size="s" variant="secondary" @click="setStatus(r, 'done')">Tugadi</UiButton>
              <UiButton v-if="r.status === 'new' || r.status === 'confirmed'" size="s" variant="ghost" @click="setStatus(r, 'no_show')">Kelmadi</UiButton>
              <UiButton size="s" variant="ghost" @click="openForm(r)"><UiIcon name="edit" :size="13" /></UiButton>
              <UiButton size="s" variant="ghost" @click="remove(r)"><UiIcon name="trash" :size="13" /></UiButton>
            </div>
          </article>
          <UiEmpty v-if="!rowsShown.length" title="Bu kunda bron yo'q" />
        </div>
      </UiCard>

      <UiCard ref="waitEl" title="Navbat" subtitle="Joy bo'shaganda chaqiriladi">
        <template #actions>
          <UiButton v-if="canManage" size="s" variant="secondary" @click="openWait()"><UiIcon name="plus" :size="13" /> Qo'shish</UiButton>
        </template>
        <div class="list">
          <article v-for="w in wait" :key="w.id" class="witem">
            <div class="l1"><b>{{ w.guest_name }}</b><UiChip :tone="WST[w.status].tone">{{ WST[w.status].label }}</UiChip></div>
            <div class="l2">
              <span><UiIcon name="users" :size="12" /> {{ w.guests }}</span>
              <span><UiIcon name="clock" :size="12" /> {{ w.waiting_minutes }} daq kutdi</span>
              <span v-if="w.phone">{{ w.phone }}</span>
            </div>
            <div v-if="canManage" class="acts">
              <UiButton v-if="w.status === 'waiting'" size="s" variant="secondary" @click="waitStatus(w, 'called')">Chaqirish</UiButton>
              <UiButton size="s" variant="brand" @click="seatFor = seatFor?.id === w.id ? null : w">Stolga o'tirg'izish</UiButton>
              <UiButton size="s" variant="ghost" @click="waitStatus(w, 'left')">Ketdi</UiButton>
            </div>
            <div v-if="seatFor?.id === w.id" class="gbtns">
              <button v-for="t in freeTables" :key="t.id" @click="waitStatus(w, 'seated', t.id)">{{ t.number }}<small>{{ t.seats }}</small></button>
            </div>
          </article>
          <UiEmpty v-if="!wait.length" title="Navbat bo'sh" />
        </div>
        <p class="quote">Hozirgi taxminiy kutish: <b>{{ meta?.quote_minutes ?? 0 }} daqiqa</b></p>
      </UiCard>
    </div>

    <!-- bron formasi -->
    <UiDrawer :open="open" :title="form?.id ? 'Bronni tahrirlash' : 'Yangi bron'" width="480px" @close="open = false">
      <template v-if="form">
        <div class="fields">
          <UiInput v-model="form.guest_name" label="Mehmon ismi" placeholder="Akmal Rasulov" />
          <UiInput v-model="form.phone" label="Telefon" placeholder="+998 90 123 45 67" />
          <div class="two">
            <label class="fl"><span>Sana</span><input v-model="form.date" type="date" /></label>
            <label class="fl"><span>Vaqt</span><input v-model="form.time" type="time" /></label>
          </div>
          <div class="two">
            <UiInput v-model="form.guests" label="Nechta mehmon" type="number" />
            <UiInput v-model="form.duration_minutes" label="Davomiyligi (daq)" type="number" />
          </div>
          <UiSelect v-model="form.table_id" label="Stol"
                    :options="[{ value: '', label: 'Tizim o`zi tanlasin' }, ...freeTables.map((t: any) => ({ value: t.id, label: `${t.number} — ${t.seats} o'rin` }))]" />
          <UiSelect v-model="form.source" label="Qayerdan" :options="[{ value: 'phone', label: 'Telefon' }, { value: 'hall', label: 'Zalda' }, { value: 'site', label: 'Sayt' }, { value: 'telegram', label: 'Telegram' }]" />
          <UiInput v-model="form.occasion" label="Sabab" placeholder="tug'ilgan kun" />
          <UiInput v-model="form.deposit" label="Oldindan to'lov (so'm)" type="number" />
          <UiInput v-model="form.note" label="Izoh" placeholder="deraza yonidagi stol so'radi" />
        </div>
        <UiButton size="s" variant="secondary" @click="checkFree()">Shu vaqtda bo'sh stollarni ko'rish</UiButton>
        <div v-if="avail" class="avail">
          <p v-if="avail.free.length" class="hint">Bo'sh: <b v-for="t in avail.free" :key="t.id" class="tchip" @click="form.table_id = t.id">{{ t.number }} ({{ t.seats }})</b></p>
          <p v-else class="hint bad">Bu vaqtda bo'sh stol yo'q.
            <template v-if="avail.suggest_times.length">Taklif: {{ avail.suggest_times.join(', ') }}</template>
          </p>
        </div>
      </template>
      <template #footer>
        <UiButton variant="ghost" @click="open = false">Yopish</UiButton>
        <UiButton variant="brand" @click="save()">Saqlash</UiButton>
      </template>
    </UiDrawer>

    <UiDrawer :open="waitOpen" title="Navbatga yozish" width="420px" @close="waitOpen = false">
      <template v-if="waitForm">
        <div class="fields">
          <UiInput v-model="waitForm.guest_name" label="Ism" placeholder="Oybek" />
          <UiInput v-model="waitForm.phone" label="Telefon" />
          <UiInput v-model="waitForm.guests" label="Nechta mehmon" type="number" />
          <UiInput v-model="waitForm.quoted_minutes" label="Aytilgan kutish (daq)" type="number" />
          <UiInput v-model="waitForm.note" label="Izoh" />
        </div>
      </template>
      <template #footer><UiButton variant="ghost" @click="waitOpen = false">Yopish</UiButton><UiButton variant="brand" @click="saveWait()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.res { display: flex; flex-direction: column; gap: 12px; }
.bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.nav { display: flex; align-items: center; gap: 4px; }
.date, .srch { min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); padding: 0 12px; }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.k { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.k span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.k b { font-family: var(--font-display); font-size: var(--fs-l); } .k b.bad { color: var(--danger); }
.flt { margin: 0 0 4px; font-size: var(--fs-s); color: var(--ink-2); } .flt button { border: 0; background: none; color: var(--accent); font: inherit; font-weight: 700; cursor: pointer; padding: 0; }
.cols { display: grid; grid-template-columns: 1.7fr 1fr; gap: 12px; align-items: start; }
.list { display: flex; flex-direction: column; }
.item { display: flex; gap: 12px; align-items: flex-start; padding: 10px 4px; border-top: 1px solid var(--line-2); }
.item:first-child { border-top: 0; }
.item.late { background: var(--danger-tint); border-radius: var(--radius); }
.time { display: flex; flex-direction: column; align-items: center; min-width: 56px; }
.time b { font-family: var(--font-display); font-size: var(--fs-l); }
.time small { font-size: 10px; color: var(--muted); }
.who { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.l1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.l2 { display: flex; gap: 12px; flex-wrap: wrap; font-size: var(--fs-xs); color: var(--muted); }
.l2 span { display: inline-flex; align-items: center; gap: 4px; }
.l2 .note { font-style: italic; }
.acts { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.witem { display: flex; flex-direction: column; gap: 6px; padding: 10px 4px; border-top: 1px solid var(--line-2); }
.witem:first-child { border-top: 0; }
.gbtns { display: flex; gap: 6px; flex-wrap: wrap; }
.gbtns button { min-width: 44px; min-height: 40px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); font-weight: 800; cursor: pointer; display: inline-flex; flex-direction: column; align-items: center; justify-content: center; }
.gbtns button small { font-size: 9px; color: var(--muted); font-weight: 600; }
.quote { font-size: var(--fs-xs); color: var(--muted); margin: 10px 0 0; }
.fields { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fl { display: flex; flex-direction: column; gap: 6px; }
.fl span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fl input { min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); padding: 0 12px; }
.avail { margin-top: 10px; }
.hint { font-size: var(--fs-s); color: var(--muted); display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.hint.bad { color: var(--danger); }
.tchip { background: var(--ok-tint); color: var(--ok); border-radius: 999px; padding: 3px 10px; font-size: var(--fs-xs); font-weight: 800; cursor: pointer; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 600px) { .kpis { grid-template-columns: repeat(2, 1fr); } .item { flex-wrap: wrap; } }
</style>
