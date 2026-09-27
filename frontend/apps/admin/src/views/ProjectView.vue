<script setup lang="ts">
/** Bitta loyiha: sarlavha va ko'rsatkichlar; tablar — Umumiy (bosqichlar, jamoa), Vazifalar (kanban), Ro'yxat, Hujjatlar, Byudjet, Faoliyat. */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import KanbanBoard from '@/components/projects/KanbanBoard.vue'
import ProgressRing from '@/components/projects/ProgressRing.vue'
import ProjectForm from '@/components/projects/ProjectForm.vue'
import PTaskDrawer from '@/components/projects/PTaskDrawer.vue'
import { ACT_ICON, HEALTH_COLOR, HEALTH_TONE, STATUS_TONE, ago, d, dShort, left } from '@/components/projects/pm'

const route = useRoute(), router = useRouter()
type Tab = 'overview' | 'board' | 'list' | 'files' | 'budget' | 'activity'
const tab = ref<Tab>('overview')
const M = ref<any>(null), P = ref<any>(null)
const td = ref<{ open: boolean; task: any; preset: any }>({ open: false, task: null, preset: null })
const edit = ref(false)
const nm = ref<any>(null)            // yangi bosqich
const em = ref<any>(null)            // bosqich tahriri
const ex = ref({ amount: '', note: '', date: '' })
const link = ref<any>(null)
const cmt = ref('')
const team = ref<any>(null)
const id = computed(() => Number(route.params.id))

async function load() {
  try { P.value = await api.get(`/projects/${id.value}`) } catch (e: any) { toast(e.detail ?? 'Loyiha topilmadi', 'danger'); router.replace('/projects') }
}
onMounted(async () => {
  M.value = await api.get('/projects/meta'); await load()
  if (route.query.task) { const t = P.value?.tasks.find((x: any) => x.id === Number(route.query.task)); if (t) openTask(t) }
})
watch(id, load)

const me = computed(() => M.value?.me)
const tasks = computed(() => (P.value?.tasks ?? []).map((t: any) => ({ ...t, can_move: P.value.can_edit || t.assignee?.id === me.value })))
const groups = computed(() => {
  if (!P.value) return []
  const g = P.value.milestones.map((m: any) => ({ m, tasks: tasks.value.filter((t: any) => t.milestone_id === m.id) }))
  const rest = tasks.value.filter((t: any) => !t.milestone_id)
  if (rest.length || !g.length) g.push({ m: null, tasks: rest })
  return g
})
const currentMs = computed(() => P.value?.milestones.find((m: any) => !m.done)?.id)
const upcoming = computed(() => tasks.value.filter((t: any) => t.status !== 'done' && t.due).sort((a: any, b: any) => a.due.localeCompare(b.due)).slice(0, 6))

function openTask(t: any) { td.value = { open: true, task: t, preset: null } }
function newTask(preset: any = {}) { td.value = { open: true, task: null, preset } }
async function toggleDone(t: any) {
  if (!t.can_move) return toast('Faqat o\'zingizga berilgan vazifani belgilaysiz', 'danger')
  try { await api.post(`/projects/tasks/${t.id}/move`, { status: t.status === 'done' ? 'todo' : 'done' }); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function setStatus(s: string) {
  if (s === 'done' && P.value.tasks_done < P.value.tasks_total && !confirm(`${P.value.tasks_total - P.value.tasks_done} ta vazifa hali ochiq. Baribir yakunlansinmi?`)) return
  try { P.value = await api.post(`/projects/${P.value.id}/status`, { status: s }); toast('Holat o\'zgardi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function saveMs() {
  const v = nm.value
  if (!v?.title?.trim()) return
  try { P.value = await api.post(`/projects/${P.value.id}/milestones`, { title: v.title, due: v.due || null }); nm.value = null } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function updMs() {
  try { P.value = await api.put(`/projects/milestones/${em.value.id}`, { title: em.value.title, due: em.value.due || null }); em.value = null } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delMs(m: any) {
  if (!confirm(`«${m.title}» bosqichi o'chirilsinmi? Vazifalar qoladi (bosqichsiz).`)) return
  P.value = await api.del(`/projects/milestones/${m.id}`)
}
async function addExp() {
  try { P.value = await api.post(`/projects/${P.value.id}/expenses`, { amount: Number(ex.value.amount) || 0, note: ex.value.note, date: ex.value.date || null }); ex.value = { amount: '', note: '', date: '' }; toast('Xarajat yozildi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delExp(e: any) { if (confirm('Xarajat o\'chirilsinmi?')) P.value = await api.del(`/projects/expenses/${e.id}`) }
async function upload(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files?.length) return
  try { for (const f of Array.from(files)) await api.upload(`/projects/${P.value.id}/files`, f); toast('Yuklandi'); load() } catch (err: any) { toast(err.detail ?? 'Xato', 'danger') }
}
async function addLink() {
  try { await api.post(`/projects/${P.value.id}/links`, link.value); link.value = null; load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delFile(f: any) { if (confirm(`«${f.title}» o'chirilsinmi?`)) { await api.del(`/projects/files/${f.id}`); load() } }
async function send() {
  if (!cmt.value.trim()) return
  try { await api.post(`/projects/${P.value.id}/comments`, { text: cmt.value }); cmt.value = ''; load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function editTeam() { team.value = P.value.members.map((m: any) => ({ user_id: m.user.id, role: m.role })) }
function teamHas(uid: string) { return team.value.find((x: any) => x.user_id === uid) }
function teamToggle(uid: string) { const i = team.value.findIndex((x: any) => x.user_id === uid); i >= 0 ? team.value.splice(i, 1) : team.value.push({ user_id: uid, role: 'member' }) }
async function saveTeam() { try { P.value = await api.put(`/projects/${P.value.id}/members`, { members: team.value }); team.value = null } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
async function delProject() {
  if (!confirm(`«${P.value.title}» butunlay o'chirilsinmi? Barcha vazifa va hujjatlar ham o'chadi.`)) return
  await api.del(`/projects/${P.value.id}`); router.replace('/projects')
}
const short = (v: number) => v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1).replace('.', ',')} mln` : money(v)
const EXT: Record<string, string> = { pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙', link: '🔗', jpg: '🖼️', jpeg: '🖼️', png: '🖼️' }
const kb = (n: number) => n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n ? `${Math.round(n / 1024)} KB` : ''
</script>

<template>
  <div v-if="P && M" class="pv">
    <RouterLink to="/projects" class="back">‹ Loyihalar</RouterLink>
    <section class="hd">
      <div class="h1">
        <span class="em" :style="{ background: P.category.color + '1f' }">{{ P.category.emoji }}</span>
        <div class="tt"><small>{{ P.code }} · {{ P.category.label }}{{ P.branch ? ` · ${P.branch.name}` : '' }}</small><h2>{{ P.title }}</h2>
          <div class="chips"><UiChip :tone="STATUS_TONE[P.status]">{{ P.status_label }}</UiChip><UiChip :tone="HEALTH_TONE[P.health]">{{ P.health_label }}</UiChip><UiChip v-if="P.priority !== 'normal'" :tone="P.priority === 'low' ? 'neutral' : 'warn'">{{ P.priority_label }}</UiChip></div></div>
        <div v-if="P.can_edit" class="acts">
          <select class="stsel" :value="P.status" aria-label="Loyiha holati" @change="setStatus(($event.target as HTMLSelectElement).value)">
            <option v-for="s in M.statuses" :key="s.code" :value="s.code">{{ s.label }}</option></select>
          <UiButton variant="ghost" size="s" @click="edit = true"><UiIcon name="edit" :size="14" /> Tahrirlash</UiButton>
        </div>
      </div>
      <div class="stats">
        <div class="ring"><ProgressRing :value="P.progress" :size="76" :stroke="9" :color="HEALTH_COLOR[P.health]" /><span><small>Bajarildi</small><b>{{ P.tasks_done }}/{{ P.tasks_total }} vazifa</b><em v-if="P.planned_progress != null && P.status !== 'done'" :class="{ bad: P.planned_progress - P.progress > 15 }">reja: {{ P.planned_progress }}%</em><em v-if="P.overdue" class="bad">{{ P.overdue }} ta kechikkan</em></span></div>
        <div><small>Muddat</small><b>{{ dShort(P.start) }} → {{ d(P.due) }}</b><em :class="{ bad: (P.days_left ?? 0) < 0 && P.status !== 'done' }">{{ P.status === 'done' ? 'yakunlangan' : left(P.days_left) }}</em></div>
        <div><small>Bosqichlar</small><b>{{ P.milestones_done }}/{{ P.milestones_total }}</b><em>{{ P.next_milestone ? `hozir: ${P.next_milestone.title}` : '—' }}</em></div>
        <div><small>Byudjet</small><b :class="{ bad: (P.budget_percent ?? 0) > 100 }">{{ P.budget ? `${short(P.spent)} / ${short(P.budget)}` : short(P.spent) }}</b><em>{{ P.budget ? `${P.budget_percent}% sarflandi` : 'byudjet belgilanmagan' }}</em></div>
        <div class="own"><UiAvatar :name="P.owner?.name" :src="P.owner?.avatar" :size="36" /><span><small>Rahbar</small><b>{{ P.owner?.name ?? '—' }}</b><em>{{ P.members.length }} kishilik jamoa</em></span></div>
      </div>
    </section>

    <nav class="tabs">
      <button v-for="x in ([['overview', '🧭 Umumiy'], ['board', '🗂️ Vazifalar'], ['list', '☑️ Ro\'yxat'], ['files', `📎 Hujjatlar (${P.files.length})`], ['budget', '💰 Byudjet'], ['activity', '💬 Faoliyat']] as const)"
              :key="x[0]" :class="{ on: tab === x[0] }" @click="tab = x[0]">{{ x[1] }}</button>
    </nav>

    <!-- UMUMIY -->
    <div v-if="tab === 'overview'" class="ov">
      <UiCard title="Bosqichlar" subtitle="Loyiha yo'l xaritasi">
        <template v-if="P.can_edit" #actions><UiButton size="s" variant="ghost" @click="nm = { title: '', due: '' }">＋ Bosqich</UiButton></template>
        <ol class="tl">
          <li v-for="(m, i) in P.milestones" :key="m.id" :class="{ done: m.done, cur: m.id === currentMs, late: m.overdue }">
            <span class="dot">{{ m.done ? '✓' : i + 1 }}</span>
            <div class="mb">
              <template v-if="em?.id === m.id">
                <div class="inl"><input v-model="em.title" aria-label="Bosqich nomi" /><input v-model="em.due" type="date" aria-label="Muddat" /><UiButton size="s" variant="brand" @click="updMs()">OK</UiButton><UiButton size="s" variant="ghost" @click="em = null">×</UiButton></div>
              </template>
              <template v-else>
                <div class="mt"><b>{{ m.title }}</b><small :class="{ bad: m.overdue }">{{ d(m.due) }}</small>
                  <span v-if="P.can_edit" class="mx"><button aria-label="Tahrirlash" @click="em = { ...m, due: m.due ?? '' }"><UiIcon name="edit" :size="13" /></button><button aria-label="O'chirish" @click="delMs(m)"><UiIcon name="trash" :size="13" /></button></span></div>
                <div class="mp"><span class="bar"><i :style="{ width: `${m.done ? 100 : m.progress}%` }"></i></span><small>{{ m.done ? 100 : m.progress }}% · {{ m.tasks_total }} vazifa</small></div>
              </template>
            </div>
          </li>
        </ol>
        <div v-if="nm" class="inl"><input v-model="nm.title" placeholder="Bosqich nomi" aria-label="Bosqich nomi" /><input v-model="nm.due" type="date" aria-label="Muddat" /><UiButton size="s" variant="brand" @click="saveMs()">Qo'shish</UiButton><UiButton size="s" variant="ghost" @click="nm = null">×</UiButton></div>
        <UiEmpty v-if="!P.milestones.length && !nm" title="Bosqich yo'q" text="Katta loyihani 3–6 bosqichga bo'ling: masalan «Joy» → «Ta'mir» → «Ochilish»." />
      </UiCard>
      <div class="col2">
        <UiCard v-if="P.description" title="Maqsad"><p class="desc">{{ P.description }}</p></UiCard>
        <UiCard title="Yaqin vazifalar" :padded="false">
          <button v-for="t in upcoming" :key="t.id" type="button" class="tr" @click="openTask(t)">
            <UiAvatar :name="t.assignee?.name ?? '?'" :src="t.assignee?.avatar" :size="26" /><span class="tx"><b>{{ t.title }}</b><small>{{ t.assignee?.name ?? 'Tayinlanmagan' }} · {{ t.status_label }}</small></span>
            <span class="dl" :class="{ bad: t.overdue }">{{ dShort(t.due) }}<small>{{ left(t.days_left) }}</small></span>
          </button>
          <UiEmpty v-if="!upcoming.length" title="Ochiq vazifa yo'q" />
        </UiCard>
        <UiCard title="Jamoa" :padded="false">
          <template v-if="P.can_edit" #actions><UiButton size="s" variant="ghost" @click="editTeam()">O'zgartirish</UiButton></template>
          <div v-for="m in P.members" :key="m.user.id" class="tm"><UiAvatar :name="m.user.name" :src="m.user.avatar" :size="32" /><span class="tx"><b>{{ m.user.name }}</b><small>{{ m.role_label }} · {{ P.tasks.filter((t: any) => t.assignee?.id === m.user.id && t.status !== 'done').length }} ochiq vazifa</small></span></div>
        </UiCard>
      </div>
    </div>

    <!-- KANBAN -->
    <template v-else-if="tab === 'board'">
      <p class="hint">💡 Kartani sudrab ustunlar orasida suring. Kartani bosing — tafsilot, checklist, fayl va izoh.</p>
      <KanbanBoard :tasks="tasks" :can-add="P.can_edit" @open="openTask" @moved="load()" @add="(s: string) => newTask({ status: s })" />
    </template>

    <!-- RO'YXAT -->
    <div v-else-if="tab === 'list'" class="lst">
      <UiCard v-for="g in groups" :key="g.m?.id ?? 0" :title="g.m ? g.m.title : 'Bosqichsiz vazifalar'" :subtitle="g.m ? `${d(g.m.due)} · ${g.m.done ? 'yakunlangan' : g.m.progress + '%'}` : undefined" :padded="false">
        <template v-if="P.can_edit" #actions><UiButton size="s" variant="ghost" @click="newTask({ milestone_id: g.m?.id ?? null })">＋ Vazifa</UiButton></template>
        <div v-for="t in g.tasks" :key="t.id" class="lr" :class="{ dn: t.status === 'done' }">
          <button type="button" class="cb" :class="{ on: t.status === 'done' }" :aria-label="t.status === 'done' ? 'Qaytarish' : 'Bajarildi'" @click="toggleDone(t)">✓</button>
          <button type="button" class="tx" @click="openTask(t)"><b>{{ t.title }}</b><small>{{ t.status_label }}{{ t.check_total ? ` · ☑ ${t.check_done}/${t.check_total}` : '' }}</small></button>
          <UiAvatar :name="t.assignee?.name ?? '?'" :src="t.assignee?.avatar" :size="26" :title="t.assignee?.name ?? 'Tayinlanmagan'" />
          <span class="dl" :class="{ bad: t.overdue }">{{ dShort(t.due) }}</span>
        </div>
        <UiEmpty v-if="!g.tasks.length" title="Vazifa yo'q" />
      </UiCard>
    </div>

    <!-- HUJJATLAR -->
    <template v-else-if="tab === 'files'">
      <div class="fh">
        <label class="upl">📤 Fayl yuklash (shartnoma, smeta, rasm, PDF)<input type="file" multiple @change="upload" /></label>
        <UiButton variant="ghost" @click="link = { title: '', url: 'https://' }">🔗 Havola qo'shish</UiButton>
      </div>
      <div v-if="link" class="inl"><input v-model="link.title" placeholder="Nomi (masalan: Dizayn loyihasi)" aria-label="Nomi" /><input v-model="link.url" placeholder="https://" aria-label="Havola" /><UiButton size="s" variant="brand" @click="addLink()">Qo'shish</UiButton><UiButton size="s" variant="ghost" @click="link = null">×</UiButton></div>
      <div class="fg">
        <div v-for="f in P.files" :key="f.id" class="fc">
          <a :href="f.url" target="_blank" rel="noopener" class="fp"><img v-if="f.is_image" :src="f.url" alt="" /><span v-else>{{ EXT[f.ext] ?? '📄' }}</span></a>
          <div class="fm"><a :href="f.url" target="_blank" rel="noopener"><b>{{ f.title }}</b></a><small>{{ f.by?.name ?? '' }} · {{ dShort(f.created_at) }} {{ kb(f.size) }}{{ f.task_id ? ' · vazifaga' : '' }}</small></div>
          <button type="button" aria-label="O'chirish" @click="delFile(f)"><UiIcon name="trash" :size="14" /></button>
        </div>
      </div>
      <UiEmpty v-if="!P.files.length" title="Hujjat yo'q" text="Shartnoma, smeta, dizayn, rasmlar — hammasi bir joyda turadi." />
    </template>

    <!-- BYUDJET -->
    <div v-else-if="tab === 'budget'" class="bg">
      <UiCard title="Byudjet">
        <div class="bs"><div><small>Reja</small><b>{{ money(P.budget) }}</b></div><div><small>Sarflandi</small><b :class="{ bad: (P.budget_percent ?? 0) > 100 }">{{ money(P.spent) }}</b></div>
          <div><small>{{ P.budget - P.spent >= 0 ? 'Qoldi' : 'Oshib ketdi' }}</small><b :class="{ bad: P.budget - P.spent < 0 }">{{ money(Math.abs(P.budget - P.spent)) }}</b></div></div>
        <div v-if="P.budget" class="bbar"><i :class="{ over: P.budget_percent > 100 }" :style="{ width: `${Math.min(100, P.budget_percent)}%` }"></i><span>{{ P.budget_percent }}%</span></div>
        <p class="mut">💡 Bajarilish {{ P.progress }}%, pul {{ P.budget_percent ?? 0 }}% sarflangan{{ P.budget && P.budget_percent > P.progress + 15 ? ' — pul ishdan tezroq ketyapti, tekshiring.' : '.' }}</p>
        <template v-if="P.can_edit">
          <h4>Xarajat qo'shish</h4>
          <div class="g3"><UiInput v-model="ex.amount" type="number" label="Summa (so'm)" /><UiInput v-model="ex.note" label="Nimaga" placeholder="Pudratchiga avans" /><UiInput v-model="ex.date" type="date" label="Sana" /></div>
          <UiButton variant="brand" style="margin-top: 10px" :disabled="!ex.amount" @click="addExp()">Yozish</UiButton>
        </template>
      </UiCard>
      <UiCard title="Xarajatlar" :padded="false">
        <div v-for="e in P.expenses" :key="e.id" class="er"><span class="tx"><b>{{ e.note || 'Xarajat' }}</b><small>{{ d(e.date) }} · {{ e.by?.name ?? '' }}</small></span><b>{{ money(e.amount) }}</b>
          <button v-if="P.can_edit" type="button" aria-label="O'chirish" @click="delExp(e)"><UiIcon name="trash" :size="14" /></button></div>
        <UiEmpty v-if="!P.expenses.length" title="Xarajat yozilmagan" />
      </UiCard>
    </div>

    <!-- FAOLIYAT -->
    <UiCard v-else-if="tab === 'activity'" :padded="false">
      <div class="cbx"><input v-model="cmt" placeholder="Jamoaga yozing… (masalan: pudratchi ertaga keladi)" aria-label="Izoh" @keydown.enter.prevent="send()" /><UiButton variant="brand" @click="send()">Yuborish</UiButton></div>
      <div v-for="a in P.activity" :key="a.id" class="ac" :class="{ cm: a.kind === 'comment' }">
        <UiAvatar :name="a.actor?.name ?? 'Tizim'" :src="a.actor?.avatar" :size="30" />
        <span class="tx"><span><b>{{ a.actor?.name ?? 'Tizim' }}</b> {{ ACT_ICON[a.kind] ?? '' }} {{ a.text }}</span>
          <small>{{ ago(a.at) }}<template v-if="a.task"> · <button type="button" class="lnk" @click="openTask(P.tasks.find((t: any) => t.id === a.task_id))">{{ a.task }}</button></template></small></span>
      </div>
    </UiCard>

    <p v-if="P.can_delete" class="del"><button type="button" @click="delProject()">Loyihani o'chirish</button></p>

    <PTaskDrawer :open="td.open" :task="td.task ? tasks.find((t: any) => t.id === td.task.id) ?? td.task : null" :project="P" :meta="M" :preset="td.preset" @close="td.open = false" @saved="load()" />
    <ProjectForm :open="edit" :project="P" :meta="M" @close="edit = false" @saved="load()" />
    <UiDrawer :open="!!team" title="Loyiha jamoasi" width="460px" @close="team = null">
      <template v-if="team">
        <p class="mut">Jamoa a'zolari loyihani ko'radi, o'z vazifalarini yuritadi. «Rahbar» — loyihani to'liq boshqaradi.</p>
        <div v-for="u in M.users" :key="u.id" class="tu">
          <label><input type="checkbox" :checked="!!teamHas(u.id) || u.id === P.owner?.id" :disabled="u.id === P.owner?.id" @change="teamToggle(u.id)" /> {{ u.name }}</label>
          <UiSelect v-if="teamHas(u.id) && u.id !== P.owner?.id" :model-value="teamHas(u.id).role" @update:model-value="(v: any) => (teamHas(u.id).role = v)" :options="M.member_roles.map((r: any) => ({ value: r.code, label: r.label }))" />
          <small v-else-if="u.id === P.owner?.id">Rahbar</small>
        </div>
      </template>
      <template #footer><UiButton variant="ghost" @click="team = null">Bekor</UiButton><UiButton variant="brand" @click="saveTeam()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.pv { display: flex; flex-direction: column; gap: 14px; }
.back { color: var(--muted); text-decoration: none; font-weight: 700; font-size: var(--fs-s); }
.hd { background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 16px; display: flex; flex-direction: column; gap: 14px; }
.h1 { display: flex; gap: 14px; align-items: flex-start; }
.em { width: 56px; height: 56px; border-radius: 14px; display: grid; place-items: center; font-size: 30px; flex-shrink: 0; }
.tt { flex: 1; min-width: 0; } .tt small { color: var(--muted); font-size: var(--fs-xs); font-weight: 700; } .tt h2 { margin: 2px 0 6px; font-size: 22px; line-height: 1.25; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.acts { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.stsel { min-height: 36px; border: 1px solid var(--line); border-radius: 10px; padding: 0 10px; font: inherit; font-weight: 700; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.stats { display: grid; grid-template-columns: 1.3fr 1fr 1fr 1fr 1.1fr; gap: 10px; }
.stats > div { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; background: var(--surface-2); border-radius: 12px; min-width: 0; }
.stats small { font-size: 11px; color: var(--muted); font-weight: 700; } .stats b { font-size: var(--fs-s); } .stats em { font-style: normal; font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stats .ring, .stats .own { flex-direction: row; align-items: center; gap: 10px; } .ring span, .own span { display: flex; flex-direction: column; min-width: 0; }
.bad { color: var(--danger) !important; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { flex-shrink: 0; border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.ov { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.col2 { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.tl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.tl li { display: flex; gap: 12px; position: relative; padding-bottom: 14px; }
.tl li:not(:last-child)::before { content: ''; position: absolute; left: 15px; top: 32px; bottom: 0; width: 2px; background: var(--line); }
.tl li.done:not(:last-child)::before { background: var(--ok); }
.dot { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; font-weight: 800; font-size: var(--fs-s); background: var(--surface-3); color: var(--muted); flex-shrink: 0; z-index: 1; }
.done .dot { background: var(--ok); color: #fff; } .cur .dot { background: var(--accent); color: var(--accent-ink); box-shadow: 0 0 0 4px var(--accent-tint); } .late .dot { background: var(--danger); color: #fff; }
.mb { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; padding-top: 4px; }
.mt { display: flex; gap: 8px; align-items: baseline; } .mt b { font-size: var(--fs-s); } .mt small { color: var(--muted); font-size: var(--fs-xs); }
.mx { margin-left: auto; display: flex; } .mx button { border: 0; background: transparent; color: var(--muted); cursor: pointer; padding: 2px 4px; }
.mp { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: center; } .mp small { font-size: 11px; color: var(--muted); }
.bar { height: 6px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: var(--ok); border-radius: 99px; }
.inl { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 6px; }
.inl input { flex: 1 1 140px; min-height: 36px; border: 1px solid var(--line); border-radius: 10px; padding: 0 10px; font: inherit; background: var(--surface); color: var(--ink); min-width: 0; }
.inl input[type=date] { flex: 0 1 150px; }
.desc { margin: 0; white-space: pre-wrap; line-height: 1.5; font-size: var(--fs-s); }
.tr, .tm { display: flex; gap: 10px; align-items: center; width: 100%; padding: 10px 14px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; color: var(--ink); }
.tr { cursor: pointer; } .tr:hover { background: var(--surface-2); }
.tx { flex: 1; display: flex; flex-direction: column; min-width: 0; font-size: var(--fs-s); border: 0; background: transparent; text-align: left; font-family: inherit; color: var(--ink); padding: 0; cursor: pointer; }
.tx b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; } .tx small { color: var(--muted); font-size: 11px; }
.dl { display: flex; flex-direction: column; align-items: flex-end; font-size: var(--fs-s); font-weight: 800; flex-shrink: 0; } .dl small { font-size: 10px; color: var(--muted); font-weight: 600; }
.hint { margin: 0; font-size: var(--fs-xs); color: var(--muted); }
.lst { display: flex; flex-direction: column; gap: 12px; }
.lr { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border-top: 1px solid var(--line-2); }
.lr.dn .tx b { text-decoration: line-through; color: var(--muted); }
.cb { width: 28px; height: 28px; border-radius: 50%; border: 2px solid var(--line); background: var(--surface); color: transparent; font-weight: 900; cursor: pointer; flex-shrink: 0; }
.cb:hover { border-color: var(--ok); color: var(--ok); } .cb.on { background: var(--ok); border-color: var(--ok); color: #fff; }
.fh { display: flex; gap: 10px; flex-wrap: wrap; }
.upl { position: relative; flex: 1; min-height: 56px; display: grid; place-items: center; border: 2px dashed var(--line); border-radius: 14px; font-weight: 700; color: var(--muted); cursor: pointer; font-size: var(--fs-s); text-align: center; padding: 0 10px; }
.upl:hover { border-color: var(--accent); color: var(--accent); } .upl input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.fg { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.fc { display: flex; gap: 10px; align-items: center; padding: 10px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; min-width: 0; }
.fp { width: 48px; height: 48px; border-radius: 10px; background: var(--surface-2); display: grid; place-items: center; font-size: 24px; overflow: hidden; flex-shrink: 0; text-decoration: none; }
.fp img { width: 100%; height: 100%; object-fit: cover; }
.fm { flex: 1; display: flex; flex-direction: column; min-width: 0; } .fm a { color: var(--ink); text-decoration: none; } .fm b { font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.fm small { color: var(--muted); font-size: 11px; }
.fc > button, .er button { border: 0; background: transparent; color: var(--muted); cursor: pointer; }
.bg { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.bs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; } .bs div { display: flex; flex-direction: column; background: var(--surface-2); border-radius: 12px; padding: 10px; }
.bs small { font-size: 11px; color: var(--muted); font-weight: 700; } .bs b { font-size: var(--fs-m); }
.bbar { position: relative; height: 22px; background: var(--surface-3); border-radius: 99px; overflow: hidden; margin-top: 12px; }
.bbar i { display: block; height: 100%; background: var(--series-2, #2563EB); } .bbar i.over { background: var(--danger); }
.bbar span { position: absolute; inset: 0; display: grid; place-items: center; font-size: 11px; font-weight: 800; }
.mut { color: var(--muted); font-size: var(--fs-s); }
h4 { margin: 14px 0 6px; font-size: var(--fs-s); }
.g3 { display: grid; grid-template-columns: 1fr 1.4fr 1fr; gap: 8px; }
.er { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.cbx { display: flex; gap: 8px; padding: 12px 14px; }
.cbx input { flex: 1; min-height: 42px; border: 1px solid var(--line); border-radius: 12px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); min-width: 0; }
.ac { display: flex; gap: 10px; align-items: flex-start; padding: 10px 14px; border-top: 1px solid var(--line-2); }
.ac .tx { cursor: default; } .ac .tx > span { white-space: normal; line-height: 1.45; } .ac.cm { background: var(--surface-2); }
.lnk { border: 0; background: transparent; color: var(--accent); font: inherit; font-size: 11px; cursor: pointer; padding: 0; font-weight: 700; }
.del { text-align: right; margin: 0; } .del button { border: 0; background: transparent; color: var(--danger); font: inherit; font-size: var(--fs-s); cursor: pointer; }
.tu { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 48px; border-bottom: 1px solid var(--line-2); }
.tu label { display: flex; gap: 10px; align-items: center; font-size: var(--fs-s); cursor: pointer; } .tu input { width: 18px; height: 18px; } .tu small { color: var(--muted); }
@media (max-width: 1100px) { .stats { grid-template-columns: 1fr 1fr 1fr; } .stats .ring { grid-column: span 2; } .ov, .bg { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 640px) {
  .h1 { flex-wrap: wrap; } .acts { width: 100%; } .acts .stsel { flex: 1; } .tt h2 { font-size: 18px; }
  .stats { grid-template-columns: 1fr 1fr; } .stats .ring, .stats .own { grid-column: 1 / -1; }
  .g3 { grid-template-columns: 1fr; } .fg { grid-template-columns: minmax(0, 1fr); }
}
</style>
