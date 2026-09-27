<script setup lang="ts">
/**
 * Zal va stollar — ofitsiant uchun xarita: stol rangiga qarab holat ko'rinadi.
 * Yashil — bo'sh, qizil — band, sariq — hisob so'raldi, kulrang — tozalash kerak, ko'k — bron.
 * Egasi «Tartiblash» rejimida stollarni sichqoncha bilan surib joylashtiradi.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter()
const meta = ref<any>(null)
const board = ref<any>({ tables: [], counts: {}, guests: 0 })
const stats = ref<any>(null)
const sessions = ref<any[]>([])
const zoneId = ref(0)
const edit = ref(false)
const picked = ref<any>(null)
const formOpen = ref(false)
const form = ref<any>(null)
const zoneOpen = ref(false)
const zoneForm = ref<any>(null)
const moveOpen = ref(false)
const guests = ref(2)
let timer: any = null

const STATUS: Record<string, { label: string; tone: any }> = {
  free: { label: "Bo'sh", tone: 'ok' },
  occupied: { label: 'Band', tone: 'danger' },
  bill: { label: "Hisob so'raldi", tone: 'warn' },
  dirty: { label: 'Tozalash kerak', tone: 'neutral' },
  reserved: { label: 'Bron', tone: 'info' },
  off: { label: 'Ishlatilmaydi', tone: 'neutral' },
}
const hhmm = (s: string) => new Date(s).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' })

async function loadMeta() {
  meta.value = await api.get('/tables/meta')
  guests.value = meta.value.settings.default_guests
  if (!zoneId.value && meta.value.zones.length > 1) zoneId.value = meta.value.zones[0].id
}
async function load() {
  board.value = await api.get('/tables/board', { zone_id: zoneId.value || undefined })
  stats.value = await api.get('/tables/stats')
  sessions.value = await api.get('/tables/sessions')
  if (picked.value) picked.value = board.value.tables.find((t: any) => t.id === picked.value.id) ?? null
}
onMounted(async () => { await loadMeta(); await load(); timer = setInterval(() => { if (!edit.value) load() }, 10000) })
onUnmounted(() => clearInterval(timer))

const zoneOptions = computed(() => [{ value: '0', label: 'Barcha zallar' },
  ...(meta.value?.zones ?? []).map((z: any) => ({ value: String(z.id), label: `${z.name} (${z.tables_count})` }))])
const shown = computed<any[]>(() => board.value.tables)
/** KPI kartalar: «band» — xaritada faqat band stollar ajralib turadi; qolganlari — bugungi o'tirishlar jadvaliga */
const hl = ref<'' | 'busy'>('')
const sesEl = ref<HTMLElement | null>(null)
function kpiGo(k: 'busy' | 'ses') {
  if (k === 'busy') { hl.value = hl.value === 'busy' ? '' : 'busy'; mapEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
  else sesEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const longSit = computed(() => meta.value?.settings.long_sit_minutes ?? 90)
const canServe = computed(() => !!meta.value?.can.serve && a.can('tables.serve'))
const freeForMove = computed(() => shown.value.filter(t => t.status === 'free' && t.id !== picked.value?.id))

function pick(t: any) { if (!edit.value) { picked.value = t; moveOpen.value = false; guests.value = Math.min(t.seats, meta.value?.settings.default_guests ?? 2) } }

async function act(fn: () => Promise<any>, ok = 'Bajarildi') {
  try { await fn(); await load(); toast(ok) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const openTable = (t: any) => act(() => api.post(`/tables/${t.id}/open`, { guests: guests.value }), 'Stol ochildi')
const askBill = (t: any) => act(() => api.post(`/tables/${t.id}/bill`), "Hisob so'raldi")
const closeTable = (t: any) => act(() => api.post(`/tables/${t.id}/close`), "Stol bo'shadi")
const cleanTable = (t: any) => act(() => api.post(`/tables/${t.id}/clean`), 'Tozalandi')
async function moveTo(target: any) {
  await act(() => api.post(`/tables/${picked.value.id}/move`, { target_id: target.id }), "Ko'chirildi")
  moveOpen.value = false
}
function toPos(t: any) { router.push({ name: 'pos', query: { table: t.number } }) }

const mapEl = ref<HTMLElement | null>(null)
let dragging: any = null
function down(e: PointerEvent, t: any) {
  if (!edit.value) return
  dragging = t
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}
function drag(e: PointerEvent) {
  if (!dragging || !mapEl.value) return
  const r = mapEl.value.getBoundingClientRect()
  dragging.x = Math.max(0, Math.min(94, ((e.clientX - r.left) / r.width) * 100 - 3))
  dragging.y = Math.max(0, Math.min(90, ((e.clientY - r.top) / r.height) * 100 - 5))
}
function up() { dragging = null }
async function saveLayout() {
  try {
    await api.post('/tables/layout', { tables: shown.value.map(t => ({ id: t.id, x: t.x, y: t.y })) })
    edit.value = false
    toast('Zal tartibi saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

function openForm(t?: any) {
  form.value = t
    ? { ...t }
    : { number: '', zone_id: zoneId.value || meta.value?.zones?.[0]?.id || null, seats: 4, shape: 'square', x: 10, y: 10, size: 1, is_active: true, note: '' }
  formOpen.value = true
}
async function saveTable() {
  const d = form.value
  const body = {
    number: String(d.number), zone_id: d.zone_id ? Number(d.zone_id) : null, branch_id: d.branch_id ?? null,
    seats: Number(d.seats) || 1, shape: d.shape, x: d.x, y: d.y, size: Number(d.size) || 1,
    is_active: d.is_active, note: d.note ?? '',
  }
  if (!body.number) return toast('Stol raqamini yozing', 'danger')
  try {
    d.id ? await api.put(`/tables/${d.id}`, body) : await api.post('/tables', body)
    formOpen.value = false; picked.value = null
    await loadMeta(); await load(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delTable(t: any) {
  if (!confirm(`«${t.number}» stoli o'chirilsinmi?`)) return
  try {
    await api.del(`/tables/${t.id}`)
    picked.value = null; formOpen.value = false
    await loadMeta(); await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function bulkAdd() {
  const n = Number(prompt("Nechta stol qo'shilsin?", '10') ?? 0)
  if (!n) return
  const z = zoneId.value || meta.value?.zones?.[0]?.id || ''
  await act(() => api.post(`/tables/bulk?count=${n}&zone_id=${z}`), `${n} ta stol qo'shildi`)
  await loadMeta()
}
function openZone(z?: any) { zoneForm.value = z ? { ...z } : { name: '', color: '#0F6E63', is_active: true }; zoneOpen.value = true }
async function saveZone() {
  const z = zoneForm.value
  try {
    z.id ? await api.put(`/tables/zones/${z.id}`, z) : await api.post('/tables/zones', z)
    zoneOpen.value = false; await loadMeta(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delZone(z: any) {
  if (!confirm(`«${z.name}» zali o'chirilsinmi?`)) return
  try { await api.del(`/tables/zones/${z.id}`); await loadMeta() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div class="floor">
    <header class="bar">
      <UiSelect :model-value="String(zoneId)" :options="zoneOptions" @update:model-value="v => { zoneId = Number(v); load() }" />
      <div class="legend">
        <span v-for="(v, k) in STATUS" :key="k" class="lg" :class="k"><i></i>{{ v.label }}
          <b v-if="board.counts[k]">{{ board.counts[k] }}</b></span>
      </div>
      <div class="sp"></div>
      <template v-if="meta?.can.admin">
        <UiButton size="s" variant="secondary" @click="openForm()"><UiIcon name="plus" :size="14" /> Stol</UiButton>
        <UiButton size="s" variant="secondary" @click="bulkAdd()">Ko'p stol</UiButton>
        <UiButton size="s" :variant="edit ? 'brand' : 'secondary'" @click="edit ? saveLayout() : (edit = true)">
          <UiIcon name="columns" :size="14" /> {{ edit ? 'Tartibni saqlash' : 'Tartiblash' }}</UiButton>
      </template>
    </header>

    <div class="kpis">
      <button type="button" class="k kpi-click" :class="{ on: hl === 'busy' }" @click="kpiGo('busy')"><span>Band stollar</span><b>{{ board.counts.occupied ?? 0 }} / {{ board.tables.length }}</b></button>
      <button type="button" class="k kpi-click" :class="{ on: hl === 'busy' }" @click="kpiGo('busy')"><span>Hozir mehmon</span><b>{{ board.guests }}</b></button>
      <button type="button" class="k kpi-click" @click="kpiGo('ses')"><span>Bugun o'tirish</span><b>{{ stats?.sessions ?? 0 }}</b></button>
      <button type="button" class="k kpi-click" @click="kpiGo('ses')"><span>O'rtacha o'tirish</span><b>{{ stats?.avg_minutes ?? '—' }}<small> daq</small></b></button>
      <button type="button" class="k kpi-click" @click="kpiGo('ses')"><span>Stol aylanishi</span><b>{{ stats?.turnover ?? 0 }}<small>×</small></b></button>
      <button type="button" class="k kpi-click" @click="kpiGo('ses')"><span>O'rtacha chek</span><b>{{ money(stats?.avg_check ?? 0) }}</b></button>
    </div>

    <p v-if="edit" class="tip"><UiIcon name="alert" :size="14" /> Stollarni bosib turib suring — xarita zalingizga o'xshasin. Tugatgach «Tartibni saqlash» tugmasini bosing.</p>

    <div ref="mapEl" class="map" :class="{ edit }" @pointermove="drag" @pointerup="up" @pointerleave="up">
      <button v-for="t in shown" :key="t.id" class="tb" :class="[t.status, 's' + t.size, t.shape, { sel: picked?.id === t.id, dim: hl === 'busy' && !t.session }]"
              :style="{ left: t.x + '%', top: t.y + '%' }" @pointerdown="down($event, t)" @click="pick(t)">
        <b class="no">{{ t.number }}</b>
        <span class="seats"><UiIcon name="users" :size="11" />{{ t.seats }}</span>
        <span v-if="t.session" class="mins" :class="{ long: t.session.minutes > longSit }">{{ t.session.minutes }}′</span>
        <span v-if="t.session?.order_total" class="sum">{{ money(t.session.order_total) }}</span>
        <span v-else-if="t.reservation" class="res">{{ hhmm(t.reservation.at) }}</span>
      </button>
      <UiEmpty v-if="!shown.length" title="Bu zalda stol yo'q" />
    </div>

    <div ref="sesEl" class="ses-anchor"></div>
    <UiCard v-if="sessions.length" title="Bugungi o'tirishlar" subtitle="Qaysi stol, nechta mehmon, qancha vaqt va qancha summa">
      <div class="tbl">
        <table>
          <thead><tr><th>Stol</th><th>Mehmon</th><th>Ofitsiant</th><th>Ochildi</th><th>Daqiqa</th><th>Chek</th></tr></thead>
          <tbody>
            <tr v-for="s in sessions" :key="s.id">
              <td><b>{{ s.table }}</b></td><td>{{ s.guests }}</td><td>{{ s.waiter ?? '—' }}</td>
              <td>{{ hhmm(s.opened_at) }}</td><td>{{ s.minutes }}</td>
              <td>{{ s.total ? money(s.total) : (s.closed ? '—' : 'davom etmoqda') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <UiDrawer :open="!!picked" :title="picked ? `Stol ${picked.number}` : ''" width="460px" @close="picked = null">
      <template v-if="picked">
        <div class="row">
          <UiChip :tone="STATUS[picked.status].tone">{{ STATUS[picked.status].label }}</UiChip>
          <UiChip tone="neutral">{{ picked.seats }} o'rin</UiChip>
          <UiChip v-if="picked.session" tone="accent">{{ picked.session.minutes }} daqiqa</UiChip>
        </div>

        <div v-if="picked.session" class="sess">
          <p><span>Mehmon</span><b>{{ picked.session.guests }}</b></p>
          <p v-if="picked.session.waiter"><span>Ofitsiant</span><b>{{ picked.session.waiter }}</b></p>
          <p v-if="picked.session.order_number"><span>Buyurtma</span><b>#{{ picked.session.order_number }} — {{ money(picked.session.order_total) }}</b></p>
          <p v-if="picked.session.note"><span>Izoh</span><b>{{ picked.session.note }}</b></p>
        </div>
        <div v-else-if="picked.reservation" class="sess">
          <p><span>Bron</span><b>{{ picked.reservation.name }} · {{ picked.reservation.guests }} kishi</b></p>
          <p><span>Vaqti</span><b>{{ hhmm(picked.reservation.at) }}</b></p>
          <p v-if="picked.reservation.phone"><span>Telefon</span><b>{{ picked.reservation.phone }}</b></p>
        </div>

        <div v-if="!picked.session && canServe" class="guests">
          <span class="lbl">Nechta mehmon?</span>
          <div class="gbtns">
            <button v-for="n in Math.max(picked.seats, 6)" :key="n" :class="{ on: guests === n }" @click="guests = n">{{ n }}</button>
          </div>
        </div>

        <div class="acts">
          <UiButton v-if="canServe && !picked.session" variant="brand" size="l" block @click="openTable(picked)">Stolni ochish</UiButton>
          <UiButton v-if="canServe && picked.session" variant="brand" size="l" block @click="toPos(picked)"><UiIcon name="plus" :size="15" /> Buyurtma qo'shish</UiButton>
          <UiButton v-if="canServe && picked.session && !picked.session.bill_asked" variant="secondary" block @click="askBill(picked)">Hisob so'raldi</UiButton>
          <UiButton v-if="canServe && picked.session" variant="secondary" block @click="moveOpen = !moveOpen">Boshqa stolga ko'chirish</UiButton>
          <UiButton v-if="canServe && picked.session" variant="secondary" block @click="closeTable(picked)">Mehmonlar ketdi</UiButton>
          <UiButton v-if="canServe && picked.status === 'dirty'" variant="brand" block @click="cleanTable(picked)">Tozalandi</UiButton>
          <UiButton v-if="meta?.can.admin" variant="ghost" block @click="openForm(picked)"><UiIcon name="edit" :size="14" /> Stolni tahrirlash</UiButton>
        </div>

        <div v-if="moveOpen" class="movelist">
          <span class="lbl">Qaysi stolga ko'chiramiz?</span>
          <div class="gbtns">
            <button v-for="t in freeForMove" :key="t.id" @click="moveTo(t)">{{ t.number }}</button>
          </div>
          <p v-if="!freeForMove.length" class="hint">Hozir bo'sh stol yo'q.</p>
        </div>
      </template>
    </UiDrawer>

    <UiDrawer :open="formOpen" :title="form?.id ? 'Stolni tahrirlash' : 'Yangi stol'" width="460px" @close="formOpen = false">
      <template v-if="form">
        <div class="fields">
          <UiInput v-model="form.number" label="Raqami yoki nomi" placeholder="12 yoki VIP-1" />
          <UiInput v-model="form.seats" label="Nechta o'rin" type="number" />
          <UiSelect v-model="form.zone_id" label="Zal" :options="(meta?.zones ?? []).map((z: any) => ({ value: z.id, label: z.name }))" />
          <UiSelect v-model="form.shape" label="Shakli" :options="[{ value: 'square', label: 'To`rtburchak' }, { value: 'round', label: 'Dumaloq' }, { value: 'long', label: 'Uzun' }]" />
          <UiSelect v-model="form.size" label="Xaritadagi o'lchami" :options="[{ value: 1, label: 'Kichik' }, { value: 2, label: 'O`rta' }, { value: 3, label: 'Katta' }]" />
          <UiInput v-model="form.note" label="Izoh" placeholder="deraza yonida" />
        </div>
        <label class="chk"><input v-model="form.is_active" type="checkbox" /> Ishlatiladi</label>
        <div v-if="meta?.zones?.length" class="zones">
          <span class="lbl">Zallar</span>
          <div v-for="z in meta.zones" :key="z.id" class="zrow">
            <span class="dot" :style="{ background: z.color }"></span><b>{{ z.name }}</b><span class="cnt">{{ z.tables_count }}</span>
            <span class="sp"></span>
            <UiButton size="s" variant="ghost" @click="openZone(z)"><UiIcon name="edit" :size="13" /></UiButton>
            <UiButton size="s" variant="ghost" @click="delZone(z)"><UiIcon name="trash" :size="13" /></UiButton>
          </div>
          <UiButton size="s" variant="secondary" @click="openZone()"><UiIcon name="plus" :size="13" /> Zal qo'shish</UiButton>
        </div>
      </template>
      <template #footer>
        <UiButton v-if="form?.id" variant="ghost" @click="delTable(form)">O'chirish</UiButton>
        <UiButton variant="brand" @click="saveTable()">Saqlash</UiButton>
      </template>
    </UiDrawer>

    <UiDrawer :open="zoneOpen" :title="zoneForm?.id ? 'Zal' : 'Yangi zal'" width="400px" @close="zoneOpen = false">
      <template v-if="zoneForm">
        <UiInput v-model="zoneForm.name" label="Nomi" placeholder="Terrassa" />
        <label class="fl"><span>Rang</span><input v-model="zoneForm.color" type="color" /></label>
      </template>
      <template #footer><UiButton variant="ghost" @click="zoneOpen = false">Yopish</UiButton><UiButton variant="brand" @click="saveZone()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.floor { display: flex; flex-direction: column; gap: 12px; }
.bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.legend { display: flex; gap: 10px; flex-wrap: wrap; }
.lg { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-xs); font-weight: 700; color: var(--muted); }
.lg i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.lg.free i { background: var(--ok); } .lg.occupied i { background: var(--danger); } .lg.bill i { background: var(--warn); }
.lg.dirty i { background: var(--line); } .lg.reserved i { background: var(--info); } .lg.off i { background: var(--surface-3); }
.lg b { color: var(--ink); }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.k { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.k span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.tb.dim { opacity: .28; filter: grayscale(.6); } .ses-anchor { scroll-margin-top: calc(var(--topbar-h) + 12px); height: 0; margin: 0 0 -1px; }
.k b { font-family: var(--font-display); font-size: var(--fs-l); } .k small { font-size: var(--fs-xs); color: var(--muted); }
.tip { margin: 0; font-size: var(--fs-s); color: var(--warn-ink); display: flex; gap: 6px; align-items: center; }
.map { position: relative; min-height: 460px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-l);
       background-image: radial-gradient(var(--line-2) 1px, transparent 1px); background-size: 24px 24px; overflow: hidden; }
.map.edit { outline: 2px dashed var(--accent); outline-offset: -4px; }
.tb { position: absolute; width: 74px; height: 66px; border-radius: var(--radius); border: 2px solid transparent; background: var(--surface);
      display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px; cursor: pointer; padding: 2px;
      box-shadow: var(--shadow-1); touch-action: none; }
.tb.s2 { width: 96px; height: 74px; } .tb.s3 { width: 124px; height: 82px; }
.tb.round { border-radius: 50%; } .tb.long { border-radius: 10px; }
.tb.free { background: var(--ok-tint); border-color: var(--ok); }
.tb.occupied { background: var(--danger-tint); border-color: var(--danger); }
.tb.bill { background: var(--warn-tint); border-color: var(--warn); }
.tb.dirty { background: var(--surface-3); border-color: var(--line); }
.tb.reserved { background: var(--info-tint); border-color: var(--info); }
.tb.off { opacity: .45; border-style: dashed; }
.tb.sel { outline: 3px solid var(--accent); }
.no { font-family: var(--font-display); font-size: var(--fs-l); line-height: 1; }
.seats { font-size: 10px; color: var(--muted); display: inline-flex; align-items: center; gap: 2px; }
.mins { font-size: 11px; font-weight: 800; } .mins.long { color: var(--danger); }
.sum { font-size: 10px; font-weight: 700; color: var(--muted); }
.res { font-size: 10px; font-weight: 800; color: var(--info); }
.tbl { overflow: auto; }
.tbl table { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
.tbl th { text-align: left; color: var(--muted); font-size: var(--fs-xs); padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.tbl td { padding: 7px 8px; border-bottom: 1px solid var(--line-2); }
.row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.sess { background: var(--surface-2); border-radius: var(--radius); padding: 10px 12px; margin-bottom: 12px; }
.sess p { display: flex; justify-content: space-between; gap: 10px; margin: 4px 0; font-size: var(--fs-s); }
.sess span { color: var(--muted); }
.guests { margin-bottom: 12px; }
.lbl { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; margin: 0 0 6px; display: block; }
.gbtns { display: flex; gap: 6px; flex-wrap: wrap; }
.gbtns button { min-width: 44px; min-height: 44px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); font-weight: 800; cursor: pointer; }
.gbtns button.on { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); }
.acts { display: flex; flex-direction: column; gap: 8px; }
.movelist { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
.hint { font-size: var(--fs-xs); color: var(--muted); }
.fields { display: flex; flex-direction: column; gap: 10px; }
.chk { display: flex; gap: 8px; align-items: center; font-size: var(--fs-s); margin: 12px 0; }
.fl { display: flex; flex-direction: column; gap: 4px; margin: 10px 0; } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.zones { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 10px; }
.zrow { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); padding: 4px 0; }
.dot { width: 10px; height: 10px; border-radius: 3px; }
.cnt { background: var(--surface-3); border-radius: 999px; padding: 0 8px; font-size: var(--fs-xs); font-weight: 800; }
@media (max-width: 900px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
  .map { min-height: 380px; }
  .tb { width: 62px; height: 56px; } .tb.s2 { width: 78px; height: 62px; } .tb.s3 { width: 96px; height: 68px; }
}
</style>
