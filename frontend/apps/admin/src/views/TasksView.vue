<script setup lang="ts">
/**
 * Vazifalar va muammolar — boshqaruv markazi.
 * Ko'rinishlar: Kanban (sudrab ko'chirish) · Ro'yxat · Kalendar · Mening vazifalarim · Muammolar · Arxiv.
 * Zanjir: muammo (foto) → vazifa → bajaruvchi → dalil → nazoratchi tasdig'i. Qoidalar backendda (services.py).
 */
import { computed, onMounted, ref, watch } from 'vue'
import draggable from 'vuedraggable'
import { api, type Task, type TaskCard, type TaskColumn, type TaskMeta, type TaskStats } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, t, toast } from '@restopos/ui'
import TaskDetail from '@/components/TaskDetail.vue'
import TaskStatsPanel from '@/components/TaskStats.vue'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
type Tab = 'kanban' | 'list' | 'calendar' | 'mine' | 'issues' | 'archive'
const tab = ref<Tab>('kanban')
const meta = ref<TaskMeta | null>(null)
const columns = ref<(TaskColumn & { tasks: TaskCard[] })[]>([])
const stats = ref<TaskStats | null>(null)
const listRows = ref<TaskCard[]>([])
const selected = ref<Task | null>(null)
const loading = ref(false)
const showStats = ref(true)

const f = ref({ branch_id: '', department_id: '', priority: '', assignee_id: '', q: '', overdue: false })
const query = computed(() => ({
  branch_id: f.value.branch_id || undefined,
  department_id: f.value.department_id || undefined,
  priority: f.value.priority || undefined,
  assignee_id: f.value.assignee_id || undefined,
  q: f.value.q || undefined,
  overdue: f.value.overdue || undefined,
  mine: tab.value === 'mine' || undefined,
  source: tab.value === 'issues' ? 'issue' : undefined,
  archived: tab.value === 'archive' || undefined,
}))

// yangi vazifa formasi
const drawer = ref(false)
const form = ref<any>(null)
const saving = ref(false)

const PRIO: Record<string, { label: string; tone: any }> = {
  urgent: { label: 'Shoshilinch', tone: 'danger' }, high: { label: 'Muhim', tone: 'warn' },
  normal: { label: "O'rta", tone: 'info' }, low: { label: 'Past', tone: 'neutral' },
}
const KIND_VAR: Record<string, string> = { backlog: '--chart-new', active: '--chart-active', review: '--chart-review', done: '--chart-done', cancelled: '--chart-cancel' }
const TABS: { code: Tab; label: string; icon: string }[] = [
  { code: 'kanban', label: 'Kanban', icon: 'columns' },
  { code: 'list', label: "Ro'yxat", icon: 'list' },
  { code: 'calendar', label: 'Kalendar', icon: 'calendar' },
  { code: 'mine', label: 'Mening vazifalarim', icon: 'users' },
  { code: 'issues', label: 'Muammolar', icon: 'alert' },
  { code: 'archive', label: 'Arxiv', icon: 'archive' },
]

const branchOptions = computed(() => [{ value: '', label: 'Barcha filiallar' }, ...(meta.value?.branches ?? []).map(b => ({ value: String(b.id), label: b.name }))])
const depOptions = computed(() => [{ value: '', label: "Barcha bo'limlar" }, ...(meta.value?.departments ?? []).map(d => ({ value: String(d.id), label: t(d.name as any, ui.lang) }))])
const prioOptions = computed(() => [{ value: '', label: 'Barcha ustuvorliklar' }, ...Object.entries(PRIO).map(([k, v]) => ({ value: k, label: v.label }))])
const userOptions = computed(() => [{ value: '', label: 'Barcha bajaruvchilar' }, ...(meta.value?.users ?? []).map(u => ({ value: u.id, label: u.full_name || u.phone }))])
const issuesCount = computed(() => columns.value.flatMap(c => c.tasks).filter(t2 => t2.source === 'issue').length)

async function loadMeta() { meta.value = await api.get('/tasks/meta') }

async function loadBoard() {
  loading.value = true
  try {
    const d = await api.get<{ columns: any[]; stats: TaskStats }>('/tasks/board', query.value)
    columns.value = d.columns
    stats.value = d.stats
  } finally { loading.value = false }
}

async function loadList() {
  loading.value = true
  try {
    const d = await api.get<{ items: TaskCard[] }>('/tasks/tasks', { ...query.value, page_size: 200, ordering: 'due_at' })
    listRows.value = d.items
    stats.value = await api.get('/tasks/stats', { branch_id: query.value.branch_id, department_id: query.value.department_id })
  } finally { loading.value = false }
}

async function reload() { tab.value === 'kanban' ? await loadBoard() : await loadList() }
onMounted(async () => { await loadMeta(); await reload() })
watch([tab, () => ({ ...f.value })], reload, { deep: true })

async function open(id: number) { selected.value = await api.get<Task>(`/tasks/tasks/${id}`) }

function onChanged(task: Task) {
  selected.value = task
  reload()
}

async function onDrop(col: TaskColumn & { tasks: TaskCard[] }, evt: any) {
  const moved = evt?.added?.element as TaskCard | undefined
  if (!moved) {
    // shu ustun ichida tartib o'zgardi
    const idx = col.tasks.findIndex(x => x.id === evt?.moved?.element?.id)
    if (idx >= 0) await api.post(`/tasks/tasks/${col.tasks[idx].id}/move`, { column_id: col.id, position: idx })
    return
  }
  const position = col.tasks.findIndex(x => x.id === moved.id)
  try {
    await api.post(`/tasks/tasks/${moved.id}/move`, { column_id: col.id, position })
    toast(`#${moved.number} → ${t(col.name as any, ui.lang)}`)
    if (selected.value?.id === moved.id) await open(moved.id)
  } catch (e: any) {
    toast(e.detail ?? 'Ko\'chirib bo\'lmadi', 'danger')
  } finally { await loadBoard() }
}

function openNew(columnId?: number) {
  form.value = {
    title: '', description: '', column_id: columnId ?? columns.value[0]?.id ?? null,
    branch_id: meta.value?.branches[0]?.id ?? null, category_id: null, department_id: null,
    assignee_id: '', supervisor_id: '', priority: 'normal', due_at: '', location: '', estimated_cost: 0, source: 'manual',
  }
  drawer.value = true
}

function onCategory(id: string) {
  const c = meta.value?.categories.find(x => x.id === Number(id))
  form.value.category_id = id ? Number(id) : null
  if (c) {
    form.value.priority = c.default_priority
    form.value.department_id = c.department_id
    if (!form.value.due_at) {
      const due = new Date(Date.now() + c.sla_hours * 3600_000)
      form.value.due_at = new Date(due.getTime() - due.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    }
  }
}

async function save() {
  if (!form.value.title.trim()) { toast('Sarlavhani yozing', 'danger'); return }
  saving.value = true
  try {
    const body = { ...form.value, assignee_id: form.value.assignee_id || null, supervisor_id: form.value.supervisor_id || null,
                   due_at: form.value.due_at || null }
    const t2 = await api.post<Task>('/tasks/tasks', body)
    drawer.value = false
    await reload()
    await open(t2.id)
    toast(`#${t2.number} ochildi`)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}

// kalendar: joriy oy, muddat bo'yicha
const month = ref(new Date())
const calendar = computed(() => {
  const first = new Date(month.value.getFullYear(), month.value.getMonth(), 1)
  const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7))
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start); d.setDate(start.getDate() + i)
    const key = d.toDateString()
    return {
      date: d, day: d.getDate(), other: d.getMonth() !== month.value.getMonth(),
      today: key === new Date().toDateString(),
      items: listRows.value.filter(x => x.due_at && new Date(x.due_at).toDateString() === key),
    }
  })
})
const monthLabel = computed(() => month.value.toLocaleDateString('uz-UZ', { month: 'long', year: 'numeric' }))
const shiftMonth = (n: number) => { const d = new Date(month.value); d.setMonth(d.getMonth() + n); month.value = d }

const fmtDate = (s?: string | null) => s ? new Date(s).toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'
const initials = (n?: string) => (n || '?').split(' ').map(x => x[0]).slice(0, 2).join('').toUpperCase()
</script>

<template>
  <div class="tasks">
    <header class="page-h">
      <div>
        <p>Restoranning barcha operatsion ishlari bitta joyda: ko'ring, nazorat qiling, bajaring.</p>
      </div>
      <div class="page-a">
        <UiButton variant="ghost" size="s" @click="showStats = !showStats"><UiIcon name="chart" :size="15" /> {{ showStats ? 'Statistikani yashirish' : 'Statistika' }}</UiButton>
        <UiButton v-if="meta?.can.create" variant="brand" @click="openNew()"><UiIcon name="plus" :size="16" /> Yangi vazifa</UiButton>
      </div>
    </header>

    <TaskStatsPanel v-if="showStats" :stats="stats" />

    <nav class="tabs">
      <button v-for="tb in TABS" :key="tb.code" :class="{ on: tab === tb.code }" @click="tab = tb.code">
        <UiIcon :name="tb.icon" :size="15" /> {{ tb.label }}
        <span v-if="tb.code === 'issues' && issuesCount" class="badge">{{ issuesCount }}</span>
      </button>
    </nav>

    <div class="filters">
      <UiInput v-model="f.q" placeholder="Vazifa, muammo, joy…" />
      <UiSelect v-model="f.branch_id" :options="branchOptions" />
      <UiSelect v-model="f.department_id" :options="depOptions" />
      <UiSelect v-model="f.priority" :options="prioOptions" />
      <UiSelect v-model="f.assignee_id" :options="userOptions" />
      <button class="chip-btn" :class="{ on: f.overdue }" @click="f.overdue = !f.overdue">
        <UiIcon name="alert" :size="14" /> Kechikkanlar
      </button>
    </div>

    <div class="work">
      <!-- KANBAN -->
      <div v-if="tab === 'kanban'" class="board" :class="{ loading }">
        <section v-for="col in columns" :key="col.id" class="col">
          <header class="col-h" :style="{ '--c': `var(${KIND_VAR[col.kind] ?? '--chart-bar'})` }">
            <span class="cdot"></span>
            <b>{{ t(col.name as any, ui.lang) }}</b>
            <span class="cnt">{{ col.count }}</span>
            <span v-if="col.wip_limit" class="wip" :class="{ over: col.count > col.wip_limit }">max {{ col.wip_limit }}</span>
          </header>
          <draggable v-model="col.tasks" :group="{ name: 'tasks' }" item-key="id" class="cards"
                     :animation="150" ghost-class="ghost" @change="onDrop(col, $event)">
            <template #item="{ element: c }">
              <article class="card" :class="{ sel: selected?.id === c.id, late: c.is_overdue }" @click="open(c.id)">
                <div class="c-top">
                  <span class="c-num">#{{ c.number }}</span>
                  <UiChip :tone="PRIO[c.priority].tone">{{ PRIO[c.priority].label }}</UiChip>
                  <UiIcon v-if="c.source === 'issue'" name="alert" :size="13" class="src" />
                </div>
                <h4>{{ c.title }}</h4>
                <div class="c-meta">
                  <span v-if="c.branch_name"><UiIcon name="store" :size="12" /> {{ c.branch_name }}</span>
                  <span v-if="c.due_at" :class="{ late: c.is_overdue }"><UiIcon name="calendar" :size="12" /> {{ fmtDate(c.due_at) }}</span>
                </div>
                <div class="c-foot">
                  <span class="ava" :title="c.assignee?.full_name">{{ initials(c.assignee?.full_name) }}</span>
                  <span class="who">{{ (c.assignee?.full_name || 'Tayinlanmagan').split(' ')[0] }}</span>
                  <span v-if="c.department" class="dep" :style="{ background: c.department.color + '22', color: c.department.color }">{{ t(c.department.name as any, ui.lang) }}</span>
                  <span class="sp"></span>
                  <span v-if="c.attachments_count" class="mini"><UiIcon name="image" :size="12" />{{ c.attachments_count }}</span>
                  <span v-if="c.comments_count" class="mini"><UiIcon name="bell" :size="12" />{{ c.comments_count }}</span>
                </div>
                <div class="bar" :title="`${c.progress}%`"><span :style="{ width: c.progress + '%' }"></span><i>{{ c.progress }}%</i></div>
              </article>
            </template>
          </draggable>
          <button v-if="meta?.can.create" class="add" @click="openNew(col.id)"><UiIcon name="plus" :size="14" /> Vazifa qo'shish</button>
        </section>
      </div>

      <!-- KALENDAR -->
      <UiCard v-else-if="tab === 'calendar'" :padded="false" class="cal-card">
        <template #actions>
          <div class="cal-nav">
            <UiButton size="s" variant="ghost" @click="shiftMonth(-1)">‹</UiButton>
            <b>{{ monthLabel }}</b>
            <UiButton size="s" variant="ghost" @click="shiftMonth(1)">›</UiButton>
          </div>
        </template>
        <div class="cal">
          <div v-for="d in ['Du','Se','Ch','Pa','Ju','Sh','Ya']" :key="d" class="cal-hd">{{ d }}</div>
          <div v-for="(c, i) in calendar" :key="i" class="cal-d" :class="{ other: c.other, today: c.today }">
            <span class="dn">{{ c.day }}</span>
            <button v-for="it in c.items.slice(0, 3)" :key="it.id" class="cal-i" :class="it.priority" @click="open(it.id)">
              #{{ it.number }} {{ it.title }}
            </button>
            <span v-if="c.items.length > 3" class="more">+{{ c.items.length - 3 }}</span>
          </div>
        </div>
      </UiCard>

      <!-- RO'YXAT / MENING / MUAMMOLAR / ARXIV -->
      <UiCard v-else :padded="false" class="list-card">
        <div class="lst">
          <div class="l-h">
            <span>#</span><span>Vazifa</span><span class="hp">Bo'lim</span><span class="hp">Bajaruvchi</span>
            <span class="hp">Muddat</span><span>Holat</span><span class="hp">Bajarilish</span>
          </div>
          <button v-for="r in listRows" :key="r.id" class="l-r" :class="{ sel: selected?.id === r.id }" @click="open(r.id)">
            <span class="num">#{{ r.number }}</span>
            <span class="ttl"><b>{{ r.title }}</b><UiChip :tone="PRIO[r.priority].tone">{{ PRIO[r.priority].label }}</UiChip></span>
            <span class="hp">{{ r.department ? t(r.department.name as any, ui.lang) : '—' }}</span>
            <span class="hp">{{ r.assignee?.full_name ?? '—' }}</span>
            <span class="hp" :class="{ late: r.is_overdue }">{{ fmtDate(r.due_at) }}</span>
            <span><UiChip :tone="r.status === 'done' ? 'ok' : r.status === 'review' ? 'info' : r.status === 'active' ? 'warn' : 'neutral'">
              {{ { backlog: 'Yangi', active: 'Jarayonda', review: 'Tekshiruvda', done: 'Bajarildi', cancelled: 'Bekor' }[r.status] }}</UiChip></span>
            <span class="hp bar sm"><span :style="{ width: r.progress + '%' }"></span><i>{{ r.progress }}%</i></span>
          </button>
          <UiEmpty v-if="!listRows.length && !loading"
                   :title="tab === 'issues' ? 'Ochiq muammo yo\'q — zo\'r!' : tab === 'archive' ? 'Arxiv bo\'sh' : 'Vazifa topilmadi'"
                   text="Filtrlarni o'zgartiring yoki yangi vazifa oching." />
        </div>
      </UiCard>

      <TaskDetail v-if="selected && meta" :task="selected" :meta="meta"
                  @close="selected = null" @changed="onChanged" @deleted="selected = null; reload()" />
    </div>

    <!-- yangi vazifa / muammo -->
    <UiDrawer :open="drawer" title="Yangi vazifa yoki muammo" width="560px" @close="drawer = false">
      <template v-if="form">
        <UiInput v-model="form.title" label="Nima qilish kerak?" placeholder="Masalan: Zaldagi divanni remont qilish" />
        <label class="fl"><span>Tavsif</span><textarea v-model="form.description" rows="3" placeholder="Qayerda, qanday muammo, nima kerak…"></textarea></label>
        <div class="grid2">
          <UiSelect :model-value="String(form.category_id ?? '')" label="Muammo turi"
                    :options="[{ value: '', label: '— tanlang —' }, ...(meta?.categories ?? []).map(c => ({ value: String(c.id), label: t(c.name as any, ui.lang) }))]"
                    @update:model-value="onCategory" />
          <UiSelect v-model="form.priority" label="Ustuvorlik" :options="Object.entries(PRIO).map(([k, v]) => ({ value: k, label: v.label }))" />
          <UiSelect :model-value="String(form.branch_id ?? '')" label="Filial"
                    :options="(meta?.branches ?? []).map(b => ({ value: String(b.id), label: b.name }))"
                    @update:model-value="v => form.branch_id = Number(v)" />
          <UiInput v-model="form.location" label="Joyi" placeholder="Zal, 3-stol" />
          <UiSelect v-model="form.assignee_id" label="Bajaruvchi"
                    :options="[{ value: '', label: '— keyin tayinlanadi —' }, ...(meta?.users ?? []).map(u => ({ value: u.id, label: u.full_name || u.phone }))]" />
          <UiSelect v-model="form.supervisor_id" label="Nazoratchi"
                    :options="[{ value: '', label: '— bo\'lim boshlig\'i —' }, ...(meta?.users ?? []).map(u => ({ value: u.id, label: u.full_name || u.phone }))]" />
          <label class="fl"><span>Muddat</span><input v-model="form.due_at" type="datetime-local" /></label>
          <UiInput v-model="form.estimated_cost" type="number" label="Taxminiy xarajat" suffix="so'm" />
        </div>
        <p class="tip"><UiIcon name="alert" :size="14" /> Tur tanlansa — muddat, bosqichlar va nazoratchi avtomatik qo'yiladi. Rasmni vazifa ochilgach yuklaysiz.</p>
      </template>
      <template #footer>
        <UiButton variant="ghost" @click="drawer = false">Bekor</UiButton>
        <UiButton variant="brand" :loading="saving" @click="save()">Ochish</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.tasks { display: flex; flex-direction: column; gap: 14px; }
.page-h { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.page-h h2 { margin: 0; font-family: var(--font-display); font-size: var(--fs-2xl); font-weight: 800; letter-spacing: -.02em; }
.page-h p { margin: 2px 0 0; color: var(--muted); font-size: var(--fs-s); }
.page-a { display: flex; gap: 8px; }
.tabs { display: flex; gap: 4px; overflow-x: auto; border-bottom: 1px solid var(--line); }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 9px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.badge { background: var(--danger); color: #fff; border-radius: 999px; font-size: 10px; padding: 1px 6px; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end; }
.filters > * { min-width: 150px; }
.chip-btn { display: inline-flex; align-items: center; gap: 6px; min-height: var(--touch); padding: 0 14px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); font-weight: 700; font-size: var(--fs-s); cursor: pointer; min-width: 0; }
.chip-btn.on { background: var(--danger-tint); color: var(--danger); border-color: var(--danger); }
.work { display: flex; gap: 14px; align-items: flex-start; }
.board { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 6px; flex: 1; min-width: 0; }
.board.loading { opacity: .6; }
.col { flex: 0 0 300px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 10px; display: flex; flex-direction: column; gap: 8px; max-height: calc(100vh - 220px); }
.col-h { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); }
.cdot { width: 10px; height: 10px; border-radius: 3px; background: var(--c); }
.col-h b { font-weight: 800; }
.cnt { background: var(--surface-3); border-radius: 999px; padding: 1px 8px; font-weight: 800; font-size: var(--fs-xs); }
.wip { margin-left: auto; font-size: 10px; color: var(--muted); }
.wip.over { color: var(--danger); font-weight: 800; }
.cards { display: flex; flex-direction: column; gap: 8px; overflow-y: auto; flex: 1; min-height: 40px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 7px; }
.card:hover { border-color: var(--accent); }
.card.sel { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-tint); }
.card.late { border-left: 3px solid var(--danger); }
.ghost { opacity: .4; }
.c-top { display: flex; align-items: center; gap: 6px; }
.c-num { font-size: var(--fs-xs); font-weight: 800; color: var(--muted); }
.src { color: var(--danger); margin-left: auto; }
.card h4 { margin: 0; font-size: var(--fs-s); font-weight: 700; line-height: 1.3; }
.c-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: var(--muted); }
.c-meta span { display: inline-flex; align-items: center; gap: 4px; }
.c-meta .late, .late > .hp, span.late { color: var(--danger); font-weight: 700; }
.c-foot { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.ava { width: 22px; height: 22px; border-radius: 7px; background: var(--accent-tint); color: var(--accent); display: grid; place-items: center; font-size: 9px; font-weight: 800; }
.who { color: var(--ink-2); font-weight: 600; }
.dep { border-radius: 999px; padding: 1px 7px; font-weight: 700; font-size: 10px; }
.sp { flex: 1; }
.mini { display: inline-flex; align-items: center; gap: 2px; color: var(--muted); }
.bar { position: relative; height: 5px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--chart-bar); border-radius: 3px; }
.bar > i { position: absolute; right: 0; top: -14px; font-size: 9px; font-style: normal; color: var(--muted); }
.add { border: 1px dashed var(--line); background: transparent; border-radius: var(--radius); padding: 8px; color: var(--muted); font-weight: 700; font-size: var(--fs-xs); cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; }
.add:hover { border-color: var(--accent); color: var(--accent); }
.list-card, .cal-card { flex: 1; min-width: 0; }
.lst { display: flex; flex-direction: column; }
.l-h, .l-r { display: grid; grid-template-columns: 62px 2.2fr 1fr 1fr 96px 108px 90px; gap: 10px; align-items: center; padding: 9px 14px; text-align: left; }
.l-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.l-r { border: 0; border-top: 1px solid var(--line-2); background: transparent; cursor: pointer; font: inherit; }
.l-r:hover { background: var(--surface-2); }
.l-r.sel { background: var(--accent-tint); }
.l-r .num { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.ttl { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ttl b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-s); }
.bar.sm { height: 6px; }
.cal-nav { display: flex; align-items: center; gap: 8px; font-family: var(--font-display); }
.cal { display: grid; grid-template-columns: repeat(7, 1fr); }
.cal-hd { padding: 8px; font-size: var(--fs-xs); font-weight: 800; color: var(--muted); background: var(--surface-2); text-align: center; }
.cal-d { min-height: 96px; border-top: 1px solid var(--line-2); border-right: 1px solid var(--line-2); padding: 6px; display: flex; flex-direction: column; gap: 3px; }
.cal-d.other { background: var(--surface-2); color: var(--muted); }
.cal-d.today { background: var(--accent-tint); }
.dn { font-size: var(--fs-xs); font-weight: 800; color: var(--muted); }
.cal-i { border: 0; text-align: left; border-radius: 6px; padding: 3px 6px; font-size: 10px; font-weight: 700; cursor: pointer; background: var(--surface-3); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cal-i.urgent, .cal-i.high { background: var(--danger-tint); color: var(--danger); }
.cal-i.normal { background: var(--warn-tint); color: var(--warn-ink); }
.more { font-size: 10px; color: var(--muted); }
.fl { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); font-weight: 600; }
.fl textarea, .fl input { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; background: var(--surface); font: inherit; min-height: var(--touch); }
.fl span { color: var(--muted); font-size: var(--fs-xs); font-weight: 700; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tip { display: flex; gap: 6px; align-items: flex-start; font-size: var(--fs-xs); color: var(--muted); background: var(--surface-2); border-radius: var(--radius); padding: 8px 10px; margin: 0; }
@media (max-width: 1024px) { .work { display: block; } .l-h, .l-r { grid-template-columns: 54px 1fr 100px; } .hp { display: none; } }
@media (max-width: 600px) {
  .col { flex: 0 0 84vw; max-height: none; }
  .filters > * { min-width: 46%; flex: 1; }
  .grid2 { grid-template-columns: 1fr; }
  .cal-d { min-height: 64px; }
}
</style>
