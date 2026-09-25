<script setup lang="ts">
/**
 * Xodimlar: ro'yxat + karta (lavozim, maosh sharti, rol, vazifalari, davomati, oyliklari) ·
 * smena jadvali (hafta) · davomat (keldi/ketdi) · oylik (hisoblash → tasdiqlash → to'lash).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth()
type Tab = 'employees' | 'schedule' | 'attendance' | 'payroll'
const tab = ref<Tab>('employees')
const meta = ref<any>(null)
const employees = ref<any[]>([])
const card = ref<any>(null)
const drawer = ref(false)
const form = ref<any>(null)
const q = ref('')
const canEdit = computed(() => a.can('hr.edit'))

const SAL: Record<string, string> = { monthly: 'oylik', hourly: 'soat', shift: 'smena', percent: '% savdo' }
const ROLE_TONE: Record<string, any> = { owner: 'accent', manager: 'info', cashier: 'ok', cook: 'warn' }

async function load() {
  meta.value = await api.get('/hr/meta')
  employees.value = await api.get('/hr/employees', { q: q.value || undefined })
}
onMounted(load)

async function openCard(e: any) { card.value = await api.get(`/hr/employees/${e.id}/card`) }
function openForm(e?: any) {
  form.value = e ? { ...e, hire_date: e.hire_date, telegram_id: e.telegram_id ?? null } : {
    full_name: '', phone: '+998', role_code: 'cashier', branch_id: meta.value?.branches[0]?.id ?? null, position_id: null,
    salary_type: 'monthly', rate: 0, pinfl: '', passport: '', card_number: '', emergency_phone: '', note: '', is_active: true, telegram_id: null,
  }
  drawer.value = true
}
function onPosition(v: string) {
  form.value.position_id = v ? Number(v) : null
  const p = meta.value.positions.find((x: any) => x.id === Number(v))
  if (p) { form.value.salary_type = p.default_salary_type; form.value.rate = p.default_rate }
}
async function save() {
  const b = { ...form.value, rate: Number(form.value.rate), branch_id: form.value.branch_id ? Number(form.value.branch_id) : null, position_id: form.value.position_id ? Number(form.value.position_id) : null }
  try {
    form.value.id ? await api.put(`/hr/employees/${form.value.id}`, b) : await api.post('/hr/employees', b)
    drawer.value = false; await load(); if (card.value) card.value = await api.get(`/hr/employees/${card.value.employee.id}/card`); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- jadval
const weekStart = ref(monday(new Date()))
function monday(d: Date) { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x }
const days = computed(() => Array.from({ length: 7 }, (_, i) => { const d = new Date(weekStart.value); d.setDate(d.getDate() + i); return d }))
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const shifts = ref<any[]>([])
async function loadShifts() { shifts.value = await api.get('/hr/shifts', { start: iso(days.value[0]), end: iso(days.value[6]) }) }
watch([tab, weekStart], () => { if (tab.value === 'schedule') loadShifts(); if (tab.value === 'attendance') loadAtt(); if (tab.value === 'payroll') loadPayroll() })
const shiftOf = (eid: number, d: Date) => shifts.value.find(s => s.employee_id === eid && s.date === iso(d))
async function toggleShift(e: any, d: Date) {
  if (!canEdit.value) return
  const s = shiftOf(e.id, d)
  if (s) { await api.del(`/hr/shifts/${s.id}`) } else {
    const p = prompt('Smena vaqti (09:00-18:00):', '09:00-18:00'); if (!p) return
    const [st, en] = p.split('-').map(x => x.trim())
    await api.post('/hr/shifts', { employee_id: e.id, date: iso(d), start: st, end: en, branch_id: e.branch_id })
  }
  await loadShifts()
}
async function copyWeek() {
  const prev = new Date(weekStart.value); prev.setDate(prev.getDate() - 7)
  const r = await api.post(`/hr/shifts/copy-week?from_start=${iso(prev)}&to_start=${iso(weekStart.value)}`)
  toast(`${r.copied} smena nusxalandi`); await loadShifts()
}
const shiftWeek = (n: number) => { const d = new Date(weekStart.value); d.setDate(d.getDate() + 7 * n); weekStart.value = d }

// ---- davomat
const att = ref<any[]>([])
async function loadAtt() { att.value = await api.get('/hr/attendance', { day: iso(new Date()) }) }
async function checkIn(e: any) { try { await api.post(`/hr/attendance/check-in?employee_id=${e.id}`); await loadAtt(); await load(); toast('Keldi ✓') } catch (x: any) { toast(x.detail ?? 'Xato', 'danger') } }
async function checkOut(e: any) { try { await api.post(`/hr/attendance/check-out?employee_id=${e.id}`); await loadAtt(); await load(); toast('Ketdi ✓') } catch (x: any) { toast(x.detail ?? 'Xato', 'danger') } }

// ---- oylik
const period = ref(new Date().toISOString().slice(0, 7))
const payroll = ref<any[]>([])
async function loadPayroll() { payroll.value = await api.get('/hr/payroll', { period: period.value + '-01' }) }
async function compute() { payroll.value = await api.post(`/hr/payroll/compute?period=${period.value}-01`); toast('Hisoblandi') }
async function patchSlip(s: any, k: string, v: any) { const r = await api.patch(`/hr/payroll/${s.id}`, { [k]: Number(v) }); Object.assign(s, r) }
async function setStatus(s: any, st: string) { try { Object.assign(s, await api.post(`/hr/payroll/${s.id}/status?status=${st}`)) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
const payrollTotal = computed(() => payroll.value.reduce((x, s) => x + s.total, 0))
const fmtT = (s: string) => new Date(s).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' })
const fmtD = (s: string) => new Date(s).toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit', year: 'numeric' })
</script>

<template>
  <div class="hr">
    <div v-if="meta" class="kpis">
      <div class="kpi"><b>{{ meta.summary.employees }}</b><span>Xodim</span></div>
      <div class="kpi"><b>{{ meta.summary.on_shift }}</b><span>Hozir smenada</span></div>
      <div class="kpi"><b>{{ meta.summary.today_planned }}</b><span>Bugun rejada</span></div>
      <div class="kpi"><b>{{ money(meta.summary.payroll_month) }}</b><span>Shu oy oylik fondi</span></div>
    </div>
    <nav class="tabs">
      <button :class="{ on: tab === 'employees' }" @click="tab = 'employees'"><UiIcon name="users" :size="15" /> Xodimlar</button>
      <button :class="{ on: tab === 'schedule' }" @click="tab = 'schedule'"><UiIcon name="calendar" :size="15" /> Smena jadvali</button>
      <button :class="{ on: tab === 'attendance' }" @click="tab = 'attendance'"><UiIcon name="clock" :size="15" /> Davomat</button>
      <button v-if="a.can('hr.payroll')" :class="{ on: tab === 'payroll' }" @click="tab = 'payroll'"><UiIcon name="receipt" :size="15" /> Oylik</button>
    </nav>

    <!-- XODIMLAR -->
    <div v-if="tab === 'employees'" class="split">
      <div class="lst-wrap">
        <div class="bar"><UiInput v-model="q" placeholder="Ism yoki telefon" @keydown.enter="load()" /><UiButton v-if="canEdit" variant="brand" @click="openForm()"><UiIcon name="plus" :size="15" /> Xodim</UiButton></div>
        <div class="lst">
          <button v-for="e in employees" :key="e.id" class="emp" :class="{ sel: card?.employee.id === e.id }" @click="openCard(e)">
            <UiAvatar :name="e.full_name" :src="e.avatar" :online="e.on_shift" />
            <span class="nm"><b>{{ e.full_name }}</b><small>{{ e.position_name ?? '—' }} · {{ e.branch_name ?? '' }}</small></span>
            <UiChip :tone="ROLE_TONE[e.role_code] ?? 'neutral'">{{ e.role_name }}</UiChip>
            <span class="sal">{{ money(e.rate) }}<small>/{{ SAL[e.salary_type] }}</small></span>
            <span class="tk" :class="{ warn: e.tasks.overdue }"><UiIcon name="check" :size="12" /> {{ e.tasks.open ?? 0 }}<i v-if="e.tasks.overdue"> · {{ e.tasks.overdue }} kechikkan</i></span>
          </button>
          <UiEmpty v-if="!employees.length" title="Xodim yo'q" text="«Xodim» tugmasi bilan qo'shing — telefon raqami bilan kiradi." />
        </div>
      </div>

      <aside v-if="card" class="card">
        <header><UiAvatar :name="card.employee.full_name" :src="card.employee.avatar" :size="52" />
          <div><h3>{{ card.employee.full_name }}</h3><p>{{ card.employee.position_name ?? '—' }} · {{ card.employee.role_name }} · {{ card.employee.phone }}</p></div>
          <UiButton v-if="canEdit" size="s" variant="secondary" @click="openForm(card.employee)"><UiIcon name="edit" :size="14" /></UiButton>
          <button class="x" @click="card = null"><UiIcon name="x" /></button></header>
        <div class="stats">
          <div><span>Maosh</span><b>{{ money(card.employee.rate) }}<small>/{{ SAL[card.employee.salary_type] }}</small></b></div>
          <div><span>Shu oy davomat</span><b>{{ card.attendance_month.days }} kun · {{ card.attendance_month.hours }} s</b></div>
          <div><span>Kechikish</span><b :class="{ danger: card.attendance_month.late }">{{ card.attendance_month.late }} marta</b></div>
          <div><span>Ishga kirgan</span><b>{{ fmtD(card.employee.hire_date) }}</b></div>
        </div>
        <div class="acts">
          <UiButton v-if="!card.employee.on_shift" size="s" @click="checkIn(card.employee)"><UiIcon name="clock" :size="14" /> Keldi</UiButton>
          <UiButton v-else size="s" variant="secondary" @click="checkOut(card.employee)">Ketdi</UiButton>
          <UiChip v-if="card.employee.telegram_id" tone="ok">Telegram ulangan</UiChip><UiChip v-else tone="neutral">Telegram: botga /start → telefon</UiChip>
        </div>
        <h4>Vazifalari <small>{{ card.tasks.length }}</small></h4>
        <ul class="tl">
          <li v-for="t in card.tasks" :key="t.id"><RouterLink :to="`/tasks`">#{{ t.number }}</RouterLink> {{ t.title }}
            <UiChip :tone="t.status === 'done' ? 'ok' : t.is_overdue ? 'danger' : t.status === 'review' ? 'info' : 'warn'">{{ t.is_overdue ? 'kechikkan' : ({ backlog: 'yangi', active: 'jarayonda', review: 'tekshiruvda', done: 'bajarildi' } as Record<string, string>)[t.status] }}</UiChip></li>
          <li v-if="!card.tasks.length" class="mut">Vazifa yo'q</li>
        </ul>
        <h4>Bu hafta smenalari</h4>
        <div class="chips"><UiChip v-for="s in card.shifts_week" :key="s.id" tone="neutral">{{ s.date.slice(5) }} · {{ s.start }}–{{ s.end }}</UiChip><span v-if="!card.shifts_week.length" class="mut">Rejalashtirilmagan</span></div>
        <h4>Oyliklar</h4>
        <div v-for="p in card.payslips" :key="p.id" class="slip"><span>{{ p.period.slice(0, 7) }}</span><b>{{ money(p.total) }}</b><UiChip :tone="p.status === 'paid' ? 'ok' : p.status === 'approved' ? 'info' : 'neutral'">{{ ({ draft: 'qoralama', approved: 'tasdiqlangan', paid: 'to\'langan' } as Record<string, string>)[p.status] }}</UiChip></div>
      </aside>
      <UiEmpty v-else title="Xodimni tanlang" text="Karta: maosh, davomat, vazifalar, oyliklar — bir joyda." />
    </div>

    <!-- JADVAL -->
    <div v-else-if="tab === 'schedule'" class="sched">
      <div class="bar"><UiButton size="s" variant="ghost" @click="shiftWeek(-1)">‹</UiButton><b>{{ days[0].toLocaleDateString('uz-UZ', { day: '2-digit', month: 'short' }) }} — {{ days[6].toLocaleDateString('uz-UZ', { day: '2-digit', month: 'short' }) }}</b><UiButton size="s" variant="ghost" @click="shiftWeek(1)">›</UiButton>
        <div class="sp"></div><UiButton v-if="canEdit" size="s" variant="secondary" @click="copyWeek()"><UiIcon name="repeat" :size="14" /> O'tgan haftadan nusxa</UiButton></div>
      <div class="grid"><div class="gh">Xodim</div><div v-for="d in days" :key="d.toDateString()" class="gh" :class="{ today: d.toDateString() === new Date().toDateString() }">{{ d.toLocaleDateString('uz-UZ', { weekday: 'short' }) }}<br /><small>{{ d.getDate() }}</small></div>
        <template v-for="e in employees" :key="e.id">
          <div class="gn"><b>{{ e.full_name }}</b><small>{{ e.position_name }}</small></div>
          <button v-for="d in days" :key="d.toDateString()" class="gc" :class="{ has: shiftOf(e.id, d) }" @click="toggleShift(e, d)">
            <span v-if="shiftOf(e.id, d)">{{ shiftOf(e.id, d).start }}–{{ shiftOf(e.id, d).end }}</span><span v-else class="mut">+</span>
          </button>
        </template>
      </div>
      <p class="hint">Katakni bosing — smena qo'shiladi/olinadi. Xodim Telegram botda /keldim /ketdim yozsa, davomat o'zi yoziladi.</p>
    </div>

    <!-- DAVOMAT -->
    <div v-else-if="tab === 'attendance'" class="att">
      <div class="lst">
        <div v-for="e in employees" :key="e.id" class="a-row">
          <UiAvatar :name="e.full_name" :src="e.avatar" :online="e.on_shift" />
          <span class="nm"><b>{{ e.full_name }}</b><small>{{ e.position_name }}</small></span>
          <span v-if="att.find(x => x.employee_id === e.id)" class="mut">keldi {{ fmtT(att.find(x => x.employee_id === e.id).check_in) }}<template v-if="att.find(x => x.employee_id === e.id).check_out"> · ketdi {{ fmtT(att.find(x => x.employee_id === e.id).check_out) }} · {{ att.find(x => x.employee_id === e.id).hours }} s</template>
            <UiChip v-if="att.find(x => x.employee_id === e.id).late_minutes" tone="danger">{{ att.find(x => x.employee_id === e.id).late_minutes }} daq kech</UiChip></span>
          <span v-else class="mut">bugun kelmagan</span>
          <span class="sp"></span>
          <UiButton v-if="!e.on_shift" size="s" @click="checkIn(e)">Keldi</UiButton>
          <UiButton v-else size="s" variant="secondary" @click="checkOut(e)">Ketdi</UiButton>
        </div>
      </div>
    </div>

    <!-- OYLIK -->
    <div v-else class="pay">
      <div class="bar"><input v-model="period" type="month" class="month" @change="loadPayroll()" /><UiButton size="s" variant="secondary" @click="compute()"><UiIcon name="repeat" :size="14" /> Hisoblash</UiButton><div class="sp"></div><b class="tot">Jami: {{ money(payrollTotal) }}</b></div>
      <div class="lst">
        <div class="p-h"><span>Xodim</span><span>Tur</span><span>Stavka</span><span>Soat / smena</span><span>Baza</span><span>Bonus</span><span>Jarima</span><span>Avans</span><span>Jami</span><span>Holat</span></div>
        <div v-for="s in payroll" :key="s.id" class="p-r">
          <span class="nm"><b>{{ s.employee_name }}</b><small>{{ s.position }}</small></span>
          <span class="mut">{{ SAL[s.salary_type] }}</span>
          <span>{{ money(s.rate) }}</span>
          <span class="mut">{{ s.hours }} s / {{ s.shifts }}</span>
          <span>{{ money(s.base) }}</span>
          <span><input :value="s.bonus" type="number" :disabled="s.status === 'paid'" @change="patchSlip(s, 'bonus', ($event.target as HTMLInputElement).value)" /></span>
          <span><input :value="s.penalty" type="number" :disabled="s.status === 'paid'" @change="patchSlip(s, 'penalty', ($event.target as HTMLInputElement).value)" /></span>
          <span><input :value="s.advance" type="number" :disabled="s.status === 'paid'" @change="patchSlip(s, 'advance', ($event.target as HTMLInputElement).value)" /></span>
          <span><b>{{ money(s.total) }}</b></span>
          <span class="st">
            <UiChip :tone="s.status === 'paid' ? 'ok' : s.status === 'approved' ? 'info' : 'neutral'">{{ ({ draft: 'qoralama', approved: 'tasdiq', paid: 'to\'landi' } as Record<string, string>)[s.status] }}</UiChip>
            <UiButton v-if="s.status === 'draft'" size="s" variant="ghost" @click="setStatus(s, 'approved')">Tasdiq</UiButton>
            <UiButton v-else-if="s.status === 'approved'" size="s" variant="ghost" @click="setStatus(s, 'paid')">To'landi</UiButton>
          </span>
        </div>
        <UiEmpty v-if="!payroll.length" title="Bu oy uchun hisob yo'q" text="«Hisoblash» — davomat va stavkalardan qoralama tuziladi." />
      </div>
      <p class="hint">Oylik P&L hisobotida «Mehnat» qatoriga tushadi. Baza: oylik = stavka · soatbay = stavka × soat · smenabay = stavka × smena · % = savdo × foiz.</p>
    </div>

    <UiDrawer :open="drawer" :title="form?.id ? 'Xodim kartasi' : 'Yangi xodim'" width="560px" @close="drawer = false">
      <template v-if="form && meta">
        <div class="grid2">
          <UiInput v-model="form.full_name" label="F.I.O." /><UiInput v-model="form.phone" label="Telefon (login)" :disabled="!!form.id" />
          <UiSelect v-model="form.role_code" label="Rol (ruxsatlar)" :options="meta.roles.map((r: any) => ({ value: r.code, label: r.name }))" />
          <UiSelect :model-value="String(form.position_id ?? '')" label="Lavozim" :options="[{ value: '', label: '—' }, ...meta.positions.map((p: any) => ({ value: String(p.id), label: p.name }))]" @update:model-value="onPosition" />
          <UiSelect :model-value="String(form.branch_id ?? '')" label="Filial" :options="meta.branches.map((b: any) => ({ value: String(b.id), label: b.name }))" @update:model-value="v => form.branch_id = Number(v)" />
          <label class="fl"><span>Ishga kirgan sana</span><input v-model="form.hire_date" type="date" /></label>
          <UiSelect v-model="form.salary_type" label="Maosh turi" :options="meta.salary_types.map((s: any) => ({ value: s.code, label: s.label }))" />
          <UiInput v-model="form.rate" type="number" :label="form.salary_type === 'percent' ? 'Foiz × 100 (2.5% = 250)' : 'Stavka (so\'m)'" />
          <UiInput v-model="form.card_number" label="Karta raqami (oylik)" /><UiInput v-model="form.pinfl" label="PINFL" />
          <UiInput v-model="form.passport" label="Pasport" /><UiInput v-model="form.emergency_phone" label="Favqulodda aloqa" />
        </div>
        <UiInput v-model="form.note" label="Izoh" />
        <label class="fl chk"><input v-model="form.is_active" type="checkbox" /> Faol xodim (o'chirilsa — ishdan bo'shagan sana yoziladi)</label>
      </template>
      <template #footer><UiButton variant="ghost" @click="drawer = false">Bekor</UiButton><UiButton variant="brand" @click="save()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.hr { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px 14px; display: flex; flex-direction: column; }
.kpi b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; } .kpi span { font-size: var(--fs-xs); color: var(--muted); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 9px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.split { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; align-items: start; }
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.lst { display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); overflow: hidden; }
.emp { display: grid; grid-template-columns: 36px 1.6fr auto 1fr 1fr; gap: 10px; align-items: center; padding: 10px 14px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; cursor: pointer; }
.emp:hover, .emp.sel { background: var(--accent-tint); }
.ava { width: 34px; height: 34px; border-radius: 10px; background: var(--surface-3); color: var(--ink-2); display: grid; place-items: center; font-size: 11px; font-weight: 800; position: relative; }
.ava.on::after { content: ''; position: absolute; right: -2px; bottom: -2px; width: 10px; height: 10px; border-radius: 50%; background: var(--ok); border: 2px solid var(--surface); }
.ava.big { width: 48px; height: 48px; font-size: 15px; }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { color: var(--muted); font-size: var(--fs-xs); }
.sal { font-size: var(--fs-s); } .sal small { color: var(--muted); }
.tk { font-size: var(--fs-xs); color: var(--muted); display: inline-flex; align-items: center; gap: 4px; } .tk.warn { color: var(--danger); } .tk i { font-style: normal; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 14px; display: flex; flex-direction: column; gap: 10px; position: sticky; top: calc(var(--topbar-h) + var(--gutter)); }
.card header { display: flex; gap: 10px; align-items: center; } .card h3 { margin: 0; font-family: var(--font-display); } .card p { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.card header > div { flex: 1; } .x { border: 0; background: transparent; cursor: pointer; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; } .stats div { background: var(--surface-2); border-radius: var(--radius); padding: 8px 10px; display: flex; flex-direction: column; }
.stats span { font-size: var(--fs-xs); color: var(--muted); } .stats b { font-size: var(--fs-b); } .stats small { color: var(--muted); font-weight: 600; }
.acts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.card h4 { margin: 6px 0 0; font-size: var(--fs-s); } .card h4 small { color: var(--muted); }
.tl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); } .tl li { display: flex; gap: 6px; align-items: center; }
.chips { display: flex; gap: 4px; flex-wrap: wrap; }
.slip { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; font-size: var(--fs-s); align-items: center; }
.mut { color: var(--muted); font-size: var(--fs-xs); } .danger { color: var(--danger); }
.grid { display: grid; grid-template-columns: 180px repeat(7, 1fr); gap: 4px; }
.gh { font-size: var(--fs-xs); font-weight: 800; color: var(--muted); text-align: center; padding: 6px; } .gh.today { color: var(--accent); }
.gn { display: flex; flex-direction: column; padding: 6px; font-size: var(--fs-s); } .gn small { color: var(--muted); font-size: 10px; }
.gc { min-height: 44px; border: 1px dashed var(--line); border-radius: var(--radius-s); background: var(--surface); cursor: pointer; font-size: 11px; font-weight: 700; }
.gc.has { background: var(--accent-tint); color: var(--accent); border-style: solid; border-color: var(--accent); }
.hint { color: var(--muted); font-size: var(--fs-xs); margin: 8px 0 0; }
.a-row { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.month { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; min-height: var(--touch); }
.tot { font-family: var(--font-display); font-size: var(--fs-l); }
.p-h, .p-r { display: grid; grid-template-columns: 1.6fr .7fr 1fr .9fr 1fr .8fr .8fr .8fr 1fr 1.4fr; gap: 6px; align-items: center; padding: 8px 12px; font-size: var(--fs-s); }
.p-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); } .p-r { border-top: 1px solid var(--line-2); }
.p-r input { width: 100%; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 4px 6px; font-size: var(--fs-s); }
.st { display: flex; gap: 4px; align-items: center; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fl { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.fl input[type=date] { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; min-height: var(--touch); background: var(--surface); }
.fl.chk { flex-direction: row; align-items: center; gap: 8px; margin-top: 8px; }
@media (max-width: 1100px) { .split { grid-template-columns: 1fr; } .card { position: static; } .kpis { grid-template-columns: 1fr 1fr; } .grid { grid-template-columns: 120px repeat(7, 1fr); } }
@media (max-width: 600px) { .emp { grid-template-columns: 36px 1fr; } .emp > :nth-child(n+3) { display: none; } .p-h { display: none; } .p-r { grid-template-columns: 1fr 1fr; } .grid2 { grid-template-columns: 1fr; } .grid { grid-template-columns: 90px repeat(7, 1fr); font-size: 10px; } }
</style>
