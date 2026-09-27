<script setup lang="ts">
/**
 * Vazifa kartochkasi (o'ng panel) — zanjirning ko'rinadigan qismi:
 * rasmlar → maydonlar (bajaruvchi/nazoratchi/muddat) → bosqichlar → dalil → tasdiq/rad → izoh va tarix.
 */
import { computed, ref, watch } from 'vue'
import { api, type Task, type TaskActivity, type TaskComment, type TaskMeta } from '@restopos/api'
import { UiAvatar, UiButton, UiChip, UiDropzone, UiIcon, money, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const props = defineProps<{ task: Task; meta: TaskMeta }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed', task: Task): void; (e: 'deleted', id: number): void }>()
const a = useAuth(), ui = useUi()

const tab = ref<'comments' | 'activity' | 'files'>('comments')
const comments = ref<TaskComment[]>([])
const activity = ref<TaskActivity[]>([])
const draft = ref('')
const newStep = ref('')
const busy = ref(false)
const rejecting = ref(false)
const rejectReason = ref('')

const canEdit = computed(() => props.meta.can.edit || props.task.assignee?.id === a.me?.id)
const photos = computed(() => props.task.attachments.filter(x => x.kind === 'photo' && x.is_image))
const proofs = computed(() => props.task.attachments.filter(x => x.kind === 'proof'))
const files = computed(() => props.task.attachments.filter(x => x.kind === 'doc' || !x.is_image))
const stepsDone = computed(() => props.task.steps.filter(s => s.is_done).length)
const PRIO: Record<string, { label: string; tone: any }> = {
  urgent: { label: 'Shoshilinch', tone: 'danger' }, high: { label: 'Muhim', tone: 'warn' },
  normal: { label: "O'rta", tone: 'info' }, low: { label: 'Past', tone: 'neutral' },
}
const userOptions = computed(() => [{ value: '', label: '— tanlanmagan —' }, ...props.meta.users.map(u => ({ value: u.id, label: u.full_name || u.phone }))])
const KORD: Record<string, number> = { backlog: 0, active: 1, review: 2, done: 3, cancelled: 4 }
const statusCols = computed(() => [...props.meta.columns].sort((x, y) => (KORD[x.kind] ?? 9) - (KORD[y.kind] ?? 9)))
const columnOptions = computed(() => props.meta.columns.map(c => ({ value: String(c.id), label: t(c.name as any, ui.lang) })))

const fmtDate = (s?: string | null) => s ? new Date(s).toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—'
const fmtTime = (s?: string | null) => s ? new Date(s).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }) : ''
const fmtDT = (s?: string | null) => s ? `${fmtDate(s)} ${fmtTime(s)}` : '—'
const toLocalInput = (s?: string | null) => s ? new Date(new Date(s).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''

async function load() {
  comments.value = await api.get(`/tasks/tasks/${props.task.id}/comments`)
  activity.value = await api.get(`/tasks/tasks/${props.task.id}/activity`)
}
watch(() => props.task.id, load, { immediate: true })

async function patch(body: any) {
  try { emit('changed', await api.patch<Task>(`/tasks/tasks/${props.task.id}`, body)); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function act(path: string, body: any = {}) {
  busy.value = true
  try { emit('changed', await api.post<Task>(`/tasks/tasks/${props.task.id}/${path}`, body)); await load(); return true }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); return false }
  finally { busy.value = false }
}
async function toggleStep(id: number, done: boolean) {
  try { await api.patch(`/tasks/steps/${id}`, { is_done: done }); emit('changed', await api.get<Task>(`/tasks/tasks/${props.task.id}`)); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function addStep() {
  if (!newStep.value.trim()) return
  await api.post(`/tasks/tasks/${props.task.id}/steps`, { title: newStep.value.trim() })
  newStep.value = ''
  emit('changed', await api.get<Task>(`/tasks/tasks/${props.task.id}`))
}
async function upload(fileList: File[], kind: 'photo' | 'proof') {
  for (const f of fileList) await api.upload(`/tasks/tasks/${props.task.id}/attachments?kind=${kind}`, f)
  emit('changed', await api.get<Task>(`/tasks/tasks/${props.task.id}`)); await load()
  toast(kind === 'proof' ? 'Dalil yuklandi' : 'Rasm yuklandi')
}
async function removeFile(id: number) {
  await api.del(`/tasks/attachments/${id}`)
  emit('changed', await api.get<Task>(`/tasks/tasks/${props.task.id}`))
}
async function comment() {
  if (!draft.value.trim()) return
  await api.post(`/tasks/tasks/${props.task.id}/comments`, { body: draft.value.trim() })
  draft.value = ''; await load()
}
async function doReject() {
  if (await act('reject', { reason: rejectReason.value })) { rejecting.value = false; rejectReason.value = '' }
}
async function remove() {
  if (!confirm(`#${props.task.number} vazifasi o'chirilsinmi?`)) return
  await api.del(`/tasks/tasks/${props.task.id}`)
  emit('deleted', props.task.id)
}
const ACTION_LABEL: Record<string, string> = {
  created: 'ochdi', moved: "ko'chirdi", assigned: 'tayinladi', step: 'bosqich', proof: 'dalil yukladi',
  photo: 'rasm yukladi', submitted: 'tekshiruvga berdi', approved: 'tasdiqladi', rejected: 'qaytardi',
  commented: 'izoh yozdi', updated: "o'zgartirdi", archived: 'arxivladi', overdue: 'muddati o\'tdi',
}
</script>

<template>
  <aside class="panel">
    <header class="hd">
      <div class="hd-l">
        <span class="num">#{{ task.number }}</span>
        <UiChip :tone="PRIO[task.priority].tone">{{ PRIO[task.priority].label }}</UiChip>
        <UiChip v-if="task.is_overdue" tone="danger"><UiIcon name="alert" :size="13" /> Kechikdi</UiChip>
        <UiChip v-if="task.source === 'issue'" tone="info">Muammo</UiChip>
        <UiChip v-if="task.rework_count" tone="warn"><UiIcon name="repeat" :size="13" /> {{ task.rework_count }}× qaytgan</UiChip>
      </div>
      <button class="x" type="button" aria-label="Yopish" @click="emit('close')"><UiIcon name="x" /></button>
    </header>

    <div class="body">
      <input v-if="canEdit" class="title-in" :value="task.title" @change="patch({ title: ($event.target as HTMLInputElement).value })" />
      <h2 v-else class="title-in as-text">{{ task.title }}</h2>
      <textarea v-if="canEdit" class="desc" rows="2" placeholder="Muammo tavsifi…" :value="task.description"
                @change="patch({ description: ($event.target as HTMLTextAreaElement).value })"></textarea>
      <p v-else-if="task.description" class="desc as-text">{{ task.description }}</p>

      <!-- holat: bir bosishda ko'chirish (telefonda sudrashdan qulay) -->
      <div v-if="canEdit" class="stat" role="radiogroup" aria-label="Holat">
        <button v-for="c in statusCols" :key="c.id" type="button" role="radio" :aria-checked="c.id === task.column_id" :class="{ on: c.id === task.column_id }"
                :disabled="busy" @click="c.id !== task.column_id && act('move', { column_id: c.id })">{{ t(c.name as any, ui.lang) }}</button>
      </div>

      <!-- muammo rasmlari -->
      <section class="blk">
        <div class="blk-h"><h4>Rasmlar <span class="muted">{{ photos.length }} ta</span></h4>
          <UiDropzone v-if="canEdit" accept="image/*" multiple capture label="+ Qo'shish" class="dz-s" @files="upload($event, 'photo')" />
        </div>
        <div v-if="photos.length" class="thumbs">
          <a v-for="p in photos" :key="p.id" :href="p.url" target="_blank" rel="noopener" class="thumb" :title="p.caption">
            <img :src="p.url" :alt="p.caption || 'Muammo rasmi'" loading="lazy" />
            <button v-if="canEdit" class="del" type="button" aria-label="O'chirish" @click.prevent="removeFile(p.id)"><UiIcon name="x" :size="12" /></button>
          </a>
        </div>
        <p v-else class="hint">Muammoni telefonda suratga oling — kim, qachon yuklaganini tizim o'zi yozadi.</p>
      </section>

      <!-- maydonlar -->
      <dl class="fields">
        <div><dt>Filial</dt><dd><UiIcon name="store" :size="14" />{{ task.branch_name ?? '—' }}</dd></div>
        <div><dt>Bo'lim</dt><dd><span v-if="task.department" class="dotc" :style="{ background: task.department.color }"></span>{{ task.department ? t(task.department.name as any, ui.lang) : '—' }}</dd></div>
        <div><dt>Muammo turi</dt><dd>{{ meta.categories.find(c => c.id === task.category_id) ? t(meta.categories.find(c => c.id === task.category_id)!.name as any, ui.lang) : '—' }}</dd></div>
        <div><dt>Joyi</dt><dd>{{ task.location || '—' }}</dd></div>
        <div>
          <dt>Javobgar (nazorat)</dt>
          <dd><select :disabled="!meta.can.assign" :value="task.supervisor?.id ?? ''" @change="patch({ supervisor_id: ($event.target as HTMLSelectElement).value || null })">
            <option v-for="o in userOptions" :key="o.value" :value="o.value">{{ o.label }}</option></select></dd>
        </div>
        <div>
          <dt>Bajaruvchi</dt>
          <dd><select :disabled="!meta.can.assign" :value="task.assignee?.id ?? ''" @change="patch({ assignee_id: ($event.target as HTMLSelectElement).value || null })">
            <option v-for="o in userOptions" :key="o.value" :value="o.value">{{ o.label }}</option></select></dd>
        </div>
        <div><dt>Boshlanish</dt><dd><input type="datetime-local" :disabled="!canEdit" :value="toLocalInput(task.start_at)" @change="patch({ start_at: ($event.target as HTMLInputElement).value || null })" /></dd></div>
        <div><dt>Muddat (deadline)</dt><dd :class="{ late: task.is_overdue }"><input type="datetime-local" :disabled="!canEdit" :value="toLocalInput(task.due_at)" @change="patch({ due_at: ($event.target as HTMLInputElement).value || null })" /></dd></div>
        <div><dt>Taxminiy xarajat</dt><dd><input type="number" :disabled="!canEdit" :value="task.estimated_cost" @change="patch({ estimated_cost: Number(($event.target as HTMLInputElement).value) })" /><span class="sfx">so'm</span></dd></div>
        <div v-if="task.actual_cost || task.status === 'done'"><dt>Haqiqiy xarajat</dt><dd><input type="number" :disabled="!canEdit" :value="task.actual_cost" @change="patch({ actual_cost: Number(($event.target as HTMLInputElement).value) })" /><span class="sfx">so'm</span></dd></div>
        <div><dt>Holat</dt><dd><select :value="String(task.column_id)" @change="act('move', { column_id: Number(($event.target as HTMLSelectElement).value) })">
          <option v-for="o in columnOptions" :key="o.value" :value="o.value">{{ o.label }}</option></select></dd></div>
        <div><dt>Ochdi</dt><dd>{{ task.reporter?.full_name || '—' }} · {{ fmtDate(task.created_at) }}</dd></div>
      </dl>

      <div v-if="task.labels.length" class="tags">
        <UiChip v-for="l in task.labels" :key="l.id" tone="neutral"><span class="dotc" :style="{ background: l.color }"></span>{{ l.name }}</UiChip>
      </div>

      <!-- bosqichlar -->
      <section class="blk">
        <div class="blk-h"><h4>Bajarilish bosqichlari <span class="muted">{{ stepsDone }}/{{ task.steps.length }}</span></h4></div>
        <ul class="steps">
          <li v-for="s in task.steps" :key="s.id">
            <label><input type="checkbox" :checked="s.is_done" @change="toggleStep(s.id, ($event.target as HTMLInputElement).checked)" />
              <span :class="{ done: s.is_done }">{{ s.title }}</span></label>
            <small v-if="s.is_done && s.done_by">{{ s.done_by.full_name.split(' ')[0] }} · {{ fmtTime(s.done_at) }}</small>
          </li>
        </ul>
        <div v-if="canEdit" class="add-step">
          <input v-model="newStep" placeholder="Yangi bosqich…" @keydown.enter="addStep()" />
          <UiButton size="s" variant="ghost" @click="addStep()"><UiIcon name="plus" :size="14" /></UiButton>
        </div>
      </section>

      <!-- dalil va tasdiq -->
      <section class="blk proof" :class="{ ready: proofs.length }">
        <div class="blk-h"><h4><UiIcon name="camera" :size="15" /> Bajarilgan ish dalili
          <span v-if="task.requires_proof" class="req">majburiy</span></h4></div>
        <div v-if="proofs.length" class="thumbs">
          <a v-for="p in proofs" :key="p.id" :href="p.url" target="_blank" rel="noopener" class="thumb ok">
            <img v-if="p.is_image" :src="p.url" :alt="p.caption || 'Dalil'" loading="lazy" />
            <span v-else class="file"><UiIcon name="paperclip" :size="16" /></span>
            <button v-if="canEdit" class="del" type="button" aria-label="O'chirish" @click.prevent="removeFile(p.id)"><UiIcon name="x" :size="12" /></button>
          </a>
        </div>
        <UiDropzone accept="image/*,application/pdf" multiple capture label="Dalil yuklash (foto)"
                    hint="Ishni tugatgach — natijaning rasmi" @files="upload($event, 'proof')" />

        <div class="flow">
          <UiButton v-if="task.status !== 'review' && task.status !== 'done'" :loading="busy" @click="act('submit')">
            <UiIcon name="send" :size="15" /> Tekshiruvga topshirish
          </UiButton>
          <template v-if="task.status === 'review' || task.status === 'active'">
            <UiButton v-if="task.can_approve" variant="primary" :loading="busy" @click="act('approve', { note: '' })">
              <UiIcon name="check" :size="15" /> Tasdiqlash
            </UiButton>
            <UiButton v-if="task.can_approve" variant="danger" @click="rejecting = !rejecting">
              <UiIcon name="repeat" :size="15" /> Qaytarish
            </UiButton>
          </template>
          <UiChip v-if="task.status === 'done'" tone="ok"><UiIcon name="check" :size="13" />
            {{ task.approved_by?.full_name || 'Tasdiqlandi' }} · {{ fmtDT(task.approved_at) }}</UiChip>
        </div>
        <div v-if="rejecting" class="reject">
          <input v-model="rejectReason" placeholder="Nima to'g'rilanishi kerak?" @keydown.enter="doReject()" />
          <UiButton variant="danger" size="s" :loading="busy" @click="doReject()">Qaytarish</UiButton>
        </div>
        <p v-if="!task.can_approve && task.requires_approval" class="hint">
          Tasdiqlashni nazoratchi ({{ task.supervisor?.full_name || 'tayinlanmagan' }}) bajaradi — o'z ishini o'zi yopib bo'lmaydi.
        </p>
      </section>

      <!-- izoh / tarix / fayllar -->
      <div class="tabs">
        <button :class="{ on: tab === 'comments' }" @click="tab = 'comments'">Izohlar <b>{{ comments.length }}</b></button>
        <button :class="{ on: tab === 'activity' }" @click="tab = 'activity'">Faoliyat tarixi</button>
        <button :class="{ on: tab === 'files' }" @click="tab = 'files'">Fayllar <b>{{ files.length }}</b></button>
      </div>

      <div v-if="tab === 'comments'" class="feed">
        <div v-for="c in comments" :key="c.id" class="msg" :class="{ sys: c.is_system }">
          <UiAvatar :name="c.author?.full_name" :src="c.author?.avatar" :size="30" />
          <div><b>{{ c.author?.full_name || 'Tizim' }}</b><time>{{ fmtDT(c.created_at) }}</time><p>{{ c.body }}</p></div>
        </div>
        <p v-if="!comments.length" class="hint">Hali izoh yo'q.</p>
      </div>

      <ul v-else-if="tab === 'activity'" class="log">
        <li v-for="e in activity" :key="e.id">
          <UiAvatar :name="e.actor?.full_name || 'Tizim'" :src="e.actor?.avatar" :size="22" />
          <div><b>{{ e.actor?.full_name || 'Tizim' }}</b> {{ ACTION_LABEL[e.action] ?? e.action }}
            <i v-if="e.detail">— {{ e.detail }}</i><time>{{ fmtDT(e.at) }}</time></div>
        </li>
      </ul>

      <div v-else class="files">
        <a v-for="f in files" :key="f.id" :href="f.url" target="_blank" rel="noopener" class="file-row">
          <UiIcon name="paperclip" :size="15" /> {{ f.caption || f.url.split('/').pop() }}
          <small>{{ fmtDate(f.created_at) }}</small>
        </a>
        <UiDropzone label="Hujjat yuklash" accept="application/pdf,.doc,.docx,.xlsx" @files="upload($event, 'photo')" />
      </div>

      <div v-if="meta.can.delete" class="danger-zone">
        <UiButton variant="ghost" size="s" @click="act('archive')"><UiIcon name="archive" :size="14" /> Arxivga</UiButton>
        <UiButton variant="ghost" size="s" @click="remove()"><UiIcon name="trash" :size="14" /> O'chirish</UiButton>
      </div>
    </div>

    <footer class="ft">
      <input v-model="draft" placeholder="Izoh yozing…" @keydown.enter="comment()" />
      <UiButton size="m" aria-label="Yuborish" @click="comment()"><UiIcon name="send" :size="16" /></UiButton>
    </footer>
  </aside>
</template>

<style scoped>
.panel { display: flex; flex-direction: column; width: 420px; flex-shrink: 0; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); max-height: calc(100vh - var(--topbar-h) - 2 * var(--gutter)); position: sticky; top: calc(var(--topbar-h) + var(--gutter)); }
.hd { display: flex; align-items: center; gap: 8px; padding: 12px 14px; border-bottom: 1px solid var(--line); }
.hd-l { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex: 1; }
.num { font-family: var(--font-display); font-weight: 800; color: var(--muted); }
.x { width: 32px; height: 32px; border-radius: 9px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; display: grid; place-items: center; }
.body { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 14px; }
.title-in { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; border: 1px solid transparent; background: transparent; border-radius: var(--radius-s); padding: 4px 6px; margin: -4px -6px; width: calc(100% + 12px); }
.title-in:hover { border-color: var(--line); } .title-in.as-text { margin: 0; }
.desc { min-height: 46px; border: 1px solid transparent; background: transparent; border-radius: var(--radius-s); padding: 4px 6px; margin: -4px -6px; resize: vertical; font-size: var(--fs-s); color: var(--ink-2); width: calc(100% + 12px); }
.desc:hover { border-color: var(--line); } .desc.as-text { margin: 0; }
.blk { display: flex; flex-direction: column; gap: 8px; }
.blk-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.blk h4 { margin: 0; font-size: var(--fs-b); font-weight: 800; display: flex; align-items: center; gap: 6px; }
.muted, .hint { color: var(--muted); font-weight: 600; font-size: var(--fs-xs); }
.hint { margin: 0; }
.req { background: var(--danger-tint); color: var(--danger); font-size: 10px; padding: 2px 6px; border-radius: 999px; }
.thumbs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.thumb { position: relative; aspect-ratio: 4/3; border-radius: var(--radius); overflow: hidden; border: 1px solid var(--line); display: block; background: var(--surface-2); }
.thumb.ok { border-color: color-mix(in srgb, var(--ok) 55%, var(--line)); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb .file { display: grid; place-items: center; height: 100%; color: var(--muted); }
.del { position: absolute; top: 4px; right: 4px; width: 20px; height: 20px; border-radius: 6px; border: 0; background: rgba(0,0,0,.55); color: #fff; cursor: pointer; display: grid; place-items: center; }
.dz-s { max-width: 130px; }
.fields { display: flex; flex-direction: column; gap: 2px; margin: 0; }
.fields > div { display: grid; grid-template-columns: 130px 1fr; align-items: center; gap: 8px; min-height: 34px; border-bottom: 1px solid var(--line-2); padding: 3px 0; }
dt { font-size: var(--fs-s); color: var(--muted); }
dd { margin: 0; font-size: var(--fs-s); font-weight: 600; display: flex; align-items: center; gap: 6px; min-width: 0; }
dd.late { color: var(--danger); }
dd select, dd input { width: 100%; border: 1px solid transparent; background: transparent; border-radius: var(--radius-s); padding: 4px 6px; font-weight: 600; font-size: var(--fs-s); }
dd select:hover, dd input:hover { border-color: var(--line); background: var(--surface-2); }
.sfx { color: var(--muted); font-size: var(--fs-xs); }
.dotc { width: 9px; height: 9px; border-radius: 3px; display: inline-block; flex-shrink: 0; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.steps li { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.steps label { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); cursor: pointer; }
.steps .done { text-decoration: line-through; color: var(--muted); }
.steps small { color: var(--muted); font-size: 10px; white-space: nowrap; }
.add-step { display: flex; gap: 6px; }
.add-step input { flex: 1; border: 1px dashed var(--line); background: transparent; border-radius: var(--radius-s); padding: 6px 8px; font-size: var(--fs-s); }
.proof { background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px; }
.proof.ready { border-color: color-mix(in srgb, var(--ok) 45%, var(--line)); }
.flow { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.reject { display: flex; gap: 6px; margin-top: 8px; }
.reject input { flex: 1; border: 1px solid var(--danger); border-radius: var(--radius-s); padding: 6px 8px; background: var(--surface); font-size: var(--fs-s); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); }
.tabs button { border: 0; background: transparent; padding: 8px 10px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.tabs b { color: var(--ink-2); }
.feed, .log, .files { display: flex; flex-direction: column; gap: 10px; }
.msg { display: flex; gap: 8px; }
.msg.sys > div { background: var(--danger-tint); border-radius: var(--radius); padding: 6px 8px; }
.ava { width: 30px; height: 30px; border-radius: 9px; background: var(--accent-tint); color: var(--accent); display: grid; place-items: center; font-size: 11px; font-weight: 800; flex-shrink: 0; }
.ava.sm { width: 22px; height: 22px; font-size: 10px; background: var(--surface-3); color: var(--ink-2); }
.msg b, .log b { font-size: var(--fs-s); }
.msg time, .log time { font-size: 10px; color: var(--muted); margin-left: 8px; }
.msg p { margin: 2px 0 0; font-size: var(--fs-s); color: var(--ink-2); }
.log { list-style: none; margin: 0; padding: 0; gap: 8px; }
.log li { display: flex; gap: 8px; font-size: var(--fs-s); color: var(--ink-2); }
.log i { font-style: normal; color: var(--muted); }
.file-row { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); text-decoration: none; color: var(--ink-2); border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; }
.file-row small { margin-left: auto; color: var(--muted); }
.danger-zone { display: flex; gap: 8px; border-top: 1px solid var(--line); padding-top: 10px; }
.ft { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); }
.ft input { flex: 1; border: 1px solid var(--line); border-radius: var(--radius); padding: 0 12px; min-height: var(--touch); background: var(--surface-2); }
.stat { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; flex-shrink: 0; padding: 2px 0; }
.stat button { flex-shrink: 0; border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 7px 12px; font: inherit; font-size: var(--fs-s); font-weight: 700; color: var(--ink-2); cursor: pointer; }
.stat button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
@media (max-width: 1024px) {
  .panel { position: fixed; inset: 0; width: 100%; max-height: none; border-radius: 0; z-index: 60; }
}
</style>
