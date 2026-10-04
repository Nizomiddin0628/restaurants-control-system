<script setup lang="ts">
/**
 * Loyihalar: bosh sahifa (KPI, loyiha kartalari, yaqin muddatlar, mening vazifalarim, bildirishnomalar),
 * umumiy kanban, oylik kalendar va bildirishnomalar lentasi.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiEmpty, UiIcon, UiSelect, money } from '@restopos/ui'
import Donut from '@/hq/charts/Donut.vue'
import KanbanBoard from '@/components/projects/KanbanBoard.vue'
import ProgressRing from '@/components/projects/ProgressRing.vue'
import ProjectForm from '@/components/projects/ProjectForm.vue'
import { ACT_ICON, HEALTH_COLOR, HEALTH_TONE, MONTHS, STATUS_TONE, ago, d, dShort, left } from '@/components/projects/pm'

const route = useRoute(), router = useRouter()
type Tab = 'home' | 'kanban' | 'calendar' | 'feed'
const tab = ref<Tab>((route.query.tab as Tab) || 'home')
const M = ref<any>(null), O = ref<any>(null)
const filter = ref<'live' | 'plan' | 'done' | 'all' | 'risk'>(route.query.filter === 'risk' ? 'risk' : 'live'), cat = ref('')
const form = ref(false)
const tasks = ref<any[]>([]), kMine = ref(false), kProject = ref('')
const now = new Date()
const ym = ref({ y: now.getFullYear(), m: now.getMonth() + 1 })
const C = ref<any>(null)
const feed = ref<any[]>([])

async function load() {
  if (tab.value === 'home') O.value = await api.get('/projects/overview')
  if (tab.value === 'kanban') tasks.value = await api.get('/projects/tasks', { mine: kMine.value || undefined, project_id: kProject.value || undefined })
  if (tab.value === 'calendar') C.value = await api.get('/projects/calendar', { month: `${ym.value.y}-${String(ym.value.m).padStart(2, '0')}` })
  if (tab.value === 'feed') feed.value = await api.get('/projects/feed')
}
onMounted(async () => { M.value = await api.get('/projects/meta'); if (tab.value !== 'home') O.value = await api.get('/projects/overview'); await load() })
watch(tab, (t) => { router.replace({ query: { tab: t } }); load() })
watch([kMine, kProject], load)
watch(ym, load, { deep: true })

const list = computed(() => (O.value?.projects ?? []).filter((p: any) =>
  (filter.value === 'all' || (filter.value === 'risk' ? ['active', 'paused', 'plan'].includes(p.status) && ['risk', 'late'].includes(p.health) : filter.value === 'live' ? ['active', 'paused'].includes(p.status) : filter.value === 'plan' ? p.status === 'plan' : ['done', 'cancelled'].includes(p.status)))
  && (!cat.value || p.category.code === cat.value)))
const counts = computed(() => {
  const ps = O.value?.projects ?? []
  return { live: ps.filter((p: any) => ['active', 'paused'].includes(p.status)).length, plan: ps.filter((p: any) => p.status === 'plan').length,
    done: ps.filter((p: any) => ['done', 'cancelled'].includes(p.status)).length, all: ps.length }
})
const K = computed(() => O.value?.kpis)
const donut = computed(() => (O.value?.health ?? []).map((h: any) => ({ key: h.key, label: h.label, value: h.value, color: HEALTH_COLOR[h.key] })))
const short = (v: number) => v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1).replace('.', ',')} mln` : money(v)
const open = (id: number, q: Record<string, any> = {}) => router.push({ path: `/projects/${id}`, query: q })

// kalendar
const WD = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']
const cells = computed(() => {
  if (!C.value) return []
  const out: any[] = []
  for (let i = 0; i < C.value.first_weekday; i++) out.push(null)
  for (let dd = 1; dd <= C.value.days; dd++) {
    const iso = `${C.value.year}-${String(C.value.month).padStart(2, '0')}-${String(dd).padStart(2, '0')}`
    out.push({ day: dd, iso, ev: C.value.events.filter((e: any) => e.date === iso) })
  }
  return out
})
const todayIso = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const agenda = computed(() => cells.value.filter((c: any) => c && c.ev.length))
function shift(n: number) { let m = ym.value.m + n, y = ym.value.y; if (m < 1) { m = 12; y-- } if (m > 12) { m = 1; y++ } ym.value = { y, m } }
const EV_ICON: Record<string, string> = { task: '•', milestone: '🏁', start: '🚀', due: '🎯' }
</script>

<template>
  <div v-if="M" class="pm">
    <div class="top">
      <nav class="tabs">
        <button :class="{ on: tab === 'home' }" @click="tab = 'home'">📁 Loyihalar</button>
        <button :class="{ on: tab === 'kanban' }" @click="tab = 'kanban'">🗂️ Kanban</button>
        <button :class="{ on: tab === 'calendar' }" @click="tab = 'calendar'">📅 Kalendar</button>
        <button :class="{ on: tab === 'feed' }" @click="tab = 'feed'">🔔 Bildirishnomalar</button>
      </nav>
      <UiButton v-if="M.can_create" variant="brand" @click="form = true"><UiIcon name="plus" :size="14" /> Yangi loyiha</UiButton>
    </div>

    <!-- BOSH -->
    <template v-if="tab === 'home' && O">
      <section class="kpis">
        <button type="button" class="kpi kpi-click" :class="{ on: filter === 'live' }" @click="filter = 'live'"><span class="ki b">📁</span><div><small>Faol loyihalar</small><b>{{ K.active }}</b><em>{{ K.plan }} tasi rejada · jami {{ K.total }}</em></div></button>
        <button type="button" class="kpi kpi-click" :class="{ on: filter === 'done' }" @click="filter = 'done'"><span class="ki g">📈</span><div><small>O'rtacha bajarilish</small><b>{{ K.avg_progress }}%</b><em>{{ K.done_month }} ta shu oy yakunlandi</em></div></button>
        <button type="button" class="kpi kpi-click" :class="{ on: filter === 'risk' }" @click="filter = filter === 'risk' ? 'live' : 'risk'"><span class="ki o">⚠️</span><div><small>Xavf ostida</small><b :class="{ bad: K.risk }">{{ K.risk }}</b><em>{{ K.late ? `${K.late} tasi kechikmoqda` : 'kechikkan yo\'q' }}</em></div></button>
        <button type="button" class="kpi kpi-click" @click="tab = 'kanban'; kMine = true"><span class="ki p">✅</span><div><small>Ochiq vazifalar</small><b>{{ K.open_tasks }}</b><em>{{ K.overdue_tasks }} ta muddati o'tgan · {{ K.my_tasks }} ta meniki</em></div></button>
        <button type="button" class="kpi kpi-click" @click="filter = 'live'"><span class="ki r">💰</span><div><small>Byudjet (faol)</small><b :title="money(K.spent)">{{ short(K.spent) }}</b><em>{{ short(K.budget) }} dan · {{ K.budget ? Math.round((100 * K.spent) / K.budget) : 0 }}%</em></div></button>
      </section>

      <div class="grid">
        <div class="main">
          <div class="flt">
            <button v-if="filter === 'risk'" class="on" @click="filter = 'live'">Xavf ostida ✕</button>
            <button v-for="x in ([['live', 'Faol'], ['plan', 'Rejada'], ['done', 'Yakunlangan'], ['all', 'Hammasi']] as const)" :key="x[0]" :class="{ on: filter === x[0] }" @click="filter = x[0]">{{ x[1] }} <i>{{ counts[x[0]] }}</i></button>
            <span class="sp"></span>
            <select v-model="cat" class="cs" aria-label="Toifa"><option value="">Barcha toifalar</option><option v-for="c in M.categories" :key="c.code" :value="c.code">{{ c.emoji }} {{ c.label }}</option></select>
          </div>
          <div class="cards">
            <button v-for="p in list" :key="p.id" type="button" class="pc" @click="open(p.id)">
              <div class="ph">
                <span class="em" :style="{ background: p.category.color + '1f' }">{{ p.category.emoji }}</span>
                <span class="tt"><small>{{ p.code }} · {{ p.category.label }}{{ p.branch ? ` · ${p.branch.name}` : '' }}</small><b>{{ p.title }}</b></span>
                <ProgressRing :value="p.progress" :size="54" :color="HEALTH_COLOR[p.health]" />
              </div>
              <div class="chips"><UiChip :tone="STATUS_TONE[p.status]">{{ p.status_label }}</UiChip><UiChip :tone="HEALTH_TONE[p.health]">{{ p.health_label }}</UiChip>
                <UiChip v-if="p.priority === 'high' || p.priority === 'critical'" tone="warn">{{ p.priority_label }}</UiChip></div>
              <div class="rows">
                <span>📅 {{ dShort(p.start) }} → {{ dShort(p.due) }} <em :class="{ bad: (p.days_left ?? 0) < 0 && p.status !== 'done' }">{{ p.status === 'done' ? 'yakunlangan' : left(p.days_left) }}</em></span>
                <span>✅ {{ p.tasks_done }}/{{ p.tasks_total }} vazifa<em v-if="p.overdue" class="bad"> · {{ p.overdue }} kechikkan</em></span>
                <span v-if="p.next_milestone && p.status !== 'done'">🏁 {{ p.next_milestone.title }} <em>{{ dShort(p.next_milestone.due) }}</em></span>
              </div>
              <div v-if="p.budget" class="bud"><span>💰 {{ short(p.spent) }} / {{ short(p.budget) }}</span><span class="bar"><i :class="{ over: (p.budget_percent ?? 0) > 100 }" :style="{ width: `${Math.min(100, p.budget_percent ?? 0)}%` }"></i></span><b :class="{ bad: (p.budget_percent ?? 0) > 100 }">{{ p.budget_percent }}%</b></div>
              <div class="team"><UiAvatar v-for="m in p.members.slice(0, 5)" :key="m.user.id" :name="m.user.name" :src="m.user.avatar" :size="26" :title="`${m.user.name} — ${m.role_label}`" />
                <small v-if="p.members.length > 5">+{{ p.members.length - 5 }}</small><span class="sp"></span><small>Rahbar: {{ p.owner?.name ?? '—' }}</small></div>
            </button>
          </div>
          <UiEmpty v-if="!list.length" title="Loyiha yo'q" :text="M.can_create ? '«Yangi loyiha» — tayyor shablondan 1 daqiqada.' : 'Sizni loyihaga qo\'shishsa shu yerda ko\'rinadi.'" />
        </div>

        <aside class="side">
          <UiCard title="Loyihalar holati"><Donut :items="donut" /></UiCard>
          <UiCard title="Yaqin muddatlar" subtitle="14 kun ichida" :padded="false">
            <button v-for="u in O.upcoming" :key="`${u.type}${u.id}`" type="button" class="up" @click="open(u.project_id, u.type === 'task' ? { task: u.id } : {})">
              <span class="ic">{{ u.type === 'milestone' ? '🏁' : '📝' }}</span>
              <span class="tx"><b>{{ u.title }}</b><small>{{ u.project_code }} · {{ u.project }}</small></span>
              <span class="dl" :class="{ bad: u.overdue, warn: !u.overdue && u.days_left <= 1 }">{{ dShort(u.due) }}<small>{{ left(u.days_left) }}</small></span>
            </button>
            <UiEmpty v-if="!O.upcoming.length" title="Yaqin muddat yo'q" />
          </UiCard>
          <UiCard title="Mening vazifalarim" :padded="false">
            <button v-for="t in O.my_tasks" :key="t.id" type="button" class="up" @click="open(t.project_id, { task: t.id })">
              <span class="ic">{{ t.status === 'doing' ? '🔵' : t.status === 'review' ? '🟡' : '⚪' }}</span>
              <span class="tx"><b>{{ t.title }}</b><small>{{ t.project }}</small></span>
              <span class="dl" :class="{ bad: t.overdue }">{{ dShort(t.due) }}<small>{{ left(t.days_left) }}</small></span>
            </button>
            <UiEmpty v-if="!O.my_tasks.length" title="Sizda ochiq vazifa yo'q 🎉" />
          </UiCard>
          <UiCard title="Bildirishnomalar" :padded="false">
            <template #actions><button class="lnk" @click="tab = 'feed'">Barchasi</button></template>
            <button v-for="a in O.feed.slice(0, 6)" :key="a.id" type="button" class="fd" @click="open(a.project_id, a.task_id ? { task: a.task_id } : {})">
              <span class="ic">{{ ACT_ICON[a.kind] ?? '•' }}</span><span class="tx"><b>{{ a.actor?.name ?? 'Tizim' }}</b> {{ a.text }}<small>{{ a.project }} · {{ ago(a.at) }}</small></span>
            </button>
            <UiEmpty v-if="!O.feed.length" title="Hozircha yangilik yo'q" />
          </UiCard>
        </aside>
      </div>
    </template>

    <!-- KANBAN -->
    <template v-else-if="tab === 'kanban'">
      <div class="flt">
        <button :class="{ on: !kMine }" @click="kMine = false">Hammasi</button>
        <button :class="{ on: kMine }" @click="kMine = true">Mening vazifalarim</button>
        <span class="sp"></span>
        <div class="ps"><UiSelect v-model="kProject" :options="[{ value: '', label: 'Barcha loyihalar' }, ...(O?.projects ?? []).filter((p: any) => !['done', 'cancelled'].includes(p.status)).map((p: any) => ({ value: String(p.id), label: `${p.code} ${p.title}` }))]" /></div>
      </div>
      <p class="hint">💡 Kartani sudrab boshqa ustunga tashlang (telefonda — bosib turing). Faqat o'zingizga berilgan yoki o'zingiz boshqaradigan vazifalar suriladi.</p>
      <KanbanBoard :tasks="tasks" show-project @open="(t: any) => open(t.project_id, { task: t.id })" @moved="load()" />
    </template>

    <!-- KALENDAR -->
    <template v-else-if="tab === 'calendar' && C">
      <div class="cal-h">
        <button type="button" aria-label="Oldingi oy" @click="shift(-1)">‹</button><b>{{ MONTHS[C.month - 1] }} {{ C.year }}</b><button type="button" aria-label="Keyingi oy" @click="shift(1)">›</button>
        <span class="sp"></span><span class="lg">🏁 bosqich · 🚀 boshlanish · 🎯 tugash · • vazifa</span>
      </div>
      <div class="cal">
        <div v-for="w in WD" :key="w" class="wd">{{ w }}</div>
        <div v-for="(c, i) in cells" :key="i" class="cell" :class="{ empty: !c, today: c?.iso === todayIso }">
          <template v-if="c">
            <span class="dn">{{ c.day }}</span>
            <button v-for="e in c.ev.slice(0, 4)" :key="`${e.type}${e.id}`" type="button" class="ev" :class="{ done: e.done, late: e.overdue }" :style="{ '--c': e.color }" :title="`${e.title} — ${e.project}`"
                    @click="open(e.project_id, e.type === 'task' ? { task: e.id } : {})">{{ EV_ICON[e.type] }} {{ e.title }}</button>
            <small v-if="c.ev.length > 4" class="more">+{{ c.ev.length - 4 }}</small>
          </template>
        </div>
      </div>
      <div class="agenda">
        <div v-for="c in agenda" :key="c.iso" class="ag"><b :class="{ tdy: c.iso === todayIso }">{{ d(c.iso) }}</b>
          <button v-for="e in c.ev" :key="`${e.type}${e.id}`" type="button" class="ev" :class="{ done: e.done, late: e.overdue }" :style="{ '--c': e.color }" @click="open(e.project_id, e.type === 'task' ? { task: e.id } : {})">{{ EV_ICON[e.type] }} {{ e.title }} <small>· {{ e.project }}</small></button>
        </div>
        <UiEmpty v-if="!agenda.length" title="Bu oyda muddat yo'q" />
      </div>
    </template>

    <!-- BILDIRISHNOMALAR -->
    <template v-else-if="tab === 'feed'">
      <UiCard :padded="false">
        <button v-for="a in feed" :key="a.id" type="button" class="fd big" @click="open(a.project_id, a.task_id ? { task: a.task_id } : {})">
          <UiAvatar :name="a.actor?.name ?? 'Tizim'" :src="a.actor?.avatar" :size="34" />
          <span class="tx"><b>{{ a.actor?.name ?? 'Tizim' }}</b> <span>{{ ACT_ICON[a.kind] ?? '' }} {{ a.text }}</span><small>{{ a.project_code }} · {{ a.project }} · {{ ago(a.at) }}</small></span>
        </button>
        <UiEmpty v-if="!feed.length" title="Hozircha bildirishnoma yo'q" text="Sizga vazifa berilsa, izoh yozilsa yoki bosqich yakunlansa — shu yerda ko'rinadi. Telegram botga ulangan bo'lsangiz, u yerga ham keladi." />
      </UiCard>
    </template>

    <ProjectForm :open="form" :meta="M" @close="form = false" @saved="(id: number) => open(id)" />
  </div>
</template>

<style scoped>
.pm { display: flex; flex-direction: column; gap: 14px; }
.top { display: flex; gap: 10px; align-items: center; }
.tabs { flex: 1; display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; min-width: 0; }
.tabs button { flex-shrink: 0; border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.kpi { display: flex; gap: 12px; align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; text-align: left; font: inherit; color: var(--ink); min-width: 0; }
button.kpi { cursor: pointer; } button.kpi:hover { border-color: var(--accent); }
.kpi div { display: flex; flex-direction: column; min-width: 0; } .kpi small { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.kpi b { font-family: var(--font-display); font-size: 22px; white-space: nowrap; } .kpi em { font-style: normal; font-size: 11px; color: var(--muted); }
.ki { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; font-size: 20px; flex-shrink: 0; }
.ki.g { background: color-mix(in srgb, var(--ok) 14%, transparent); } .ki.b { background: color-mix(in srgb, var(--accent) 14%, transparent); } .ki.o { background: color-mix(in srgb, var(--warn) 14%, transparent); } .ki.p { background: color-mix(in srgb, #8B5CF6 16%, transparent); } .ki.r { background: color-mix(in srgb, var(--danger) 13%, transparent); }
.bad { color: var(--danger) !important; } .warn { color: var(--warn-ink, #B45309) !important; }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; align-items: start; }
.main { display: flex; flex-direction: column; gap: 12px; min-width: 0; } .side { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.flt { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.flt > button { display: inline-flex; align-items: center; gap: 4px; min-height: 36px; padding: 0 14px; border: 1px solid var(--line); border-radius: 99px; background: var(--surface); font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; color: var(--ink); }
.flt > button.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); } .flt i { font-style: normal; opacity: .7; font-size: 11px; }
.sp { flex: 1; }
.cs { min-height: 36px; border: 1px solid var(--line); border-radius: 99px; padding: 0 12px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.ps { min-width: 240px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
.pc { display: flex; flex-direction: column; gap: 10px; padding: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; text-align: left; font: inherit; color: var(--ink); cursor: pointer; min-width: 0; }
.pc:hover { border-color: var(--accent); box-shadow: 0 4px 14px rgba(0,0,0,.05); }
.ph { display: flex; gap: 12px; align-items: center; }
.em { width: 46px; height: 46px; border-radius: 12px; display: grid; place-items: center; font-size: 24px; flex-shrink: 0; }
.tt { flex: 1; display: flex; flex-direction: column; min-width: 0; } .tt small { color: var(--muted); font-size: 11px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tt b { font-size: var(--fs-m); line-height: 1.3; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.rows { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-s); } .rows em { font-style: normal; color: var(--muted); font-size: var(--fs-xs); }
.bud { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; font-size: var(--fs-xs); }
.bar { height: 6px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: var(--series-2, #2563EB); border-radius: 99px; } .bar i.over { background: var(--danger); }
.team { display: flex; align-items: center; gap: 2px; } .team small { color: var(--muted); font-size: 11px; margin-left: 4px; }
.team :deep(.av) { border: 2px solid var(--surface); margin-left: -6px; } .team :deep(.av:first-child) { margin-left: 0; }
.up, .fd { display: flex; gap: 10px; align-items: center; width: 100%; padding: 10px 14px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; color: var(--ink); cursor: pointer; }
.up:hover, .fd:hover { background: var(--surface-2); }
.ic { width: 22px; text-align: center; flex-shrink: 0; }
.tx { flex: 1; display: flex; flex-direction: column; min-width: 0; font-size: var(--fs-s); } .tx b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tx small { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fd .tx { display: block; line-height: 1.4; } .fd .tx b { display: inline; white-space: normal; } .fd .tx small { display: block; }
.fd.big { padding: 12px 16px; } .fd.big .tx { font-size: var(--fs-s); }
.dl { display: flex; flex-direction: column; align-items: flex-end; font-size: var(--fs-s); font-weight: 800; flex-shrink: 0; } .dl small { font-size: 10px; color: var(--muted); font-weight: 600; }
.lnk { border: 0; background: transparent; color: var(--accent); font-weight: 700; cursor: pointer; font: inherit; }
.hint { margin: 0; font-size: var(--fs-xs); color: var(--muted); }
.cal-h { display: flex; align-items: center; gap: 10px; }
.cal-h button { width: 36px; height: 36px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); font-size: 20px; cursor: pointer; color: var(--ink); }
.cal-h b { font-size: var(--fs-l); min-width: 150px; text-align: center; } .lg { color: var(--muted); font-size: var(--fs-xs); }
.cal { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.wd { text-align: center; font-size: var(--fs-xs); font-weight: 800; color: var(--muted); padding: 4px; }
.cell { min-height: 104px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 4px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.cell.empty { background: transparent; border: 0; } .cell.today { border: 2px solid var(--accent); }
.dn { font-size: var(--fs-xs); font-weight: 800; color: var(--muted); padding: 0 2px; }
.ev { display: block; width: 100%; text-align: left; border: 0; border-left: 3px solid var(--c); background: color-mix(in srgb, var(--c) 10%, var(--surface)); border-radius: 4px; padding: 2px 5px;
  font: inherit; font-size: 11px; color: var(--ink); cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ev.done { opacity: .5; text-decoration: line-through; } .ev.late { background: var(--danger-tint); }
.more { font-size: 10px; color: var(--muted); padding-left: 4px; }
.agenda { display: none; flex-direction: column; gap: 10px; }
.ag { display: flex; flex-direction: column; gap: 4px; } .ag b { font-size: var(--fs-s); } .ag b.tdy { color: var(--accent); } .ag .ev { white-space: normal; font-size: var(--fs-s); padding: 8px 10px; }
.ag .ev small { color: var(--muted); }
@media (max-width: 1250px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .grid { grid-template-columns: minmax(0, 1fr); } .side { display: grid; grid-template-columns: 1fr 1fr; } }
@media (max-width: 760px) {
  .top { flex-direction: column-reverse; align-items: stretch; }
  .kpis { grid-template-columns: 1fr 1fr; } .kpis > :first-child { grid-column: 1 / -1; } .kpi b { font-size: 18px; }
  .side { grid-template-columns: minmax(0, 1fr); } .cards { grid-template-columns: minmax(0, 1fr); }
  .ps { min-width: 0; width: 100%; } .lg { display: none; }
  .cal, .wd { display: none; } .agenda { display: flex; }
}
</style>
