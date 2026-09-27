<script setup lang="ts">
/** Loyiha vazifasi: holat (katta tugmalar), mas'ul, muddat, bosqich, checklist, fayl va izohlar. Mas'ul faqat holat/checklist/izohni o'zgartiradi. */
import { computed, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiDrawer, UiInput, UiSelect, toast } from '@restopos/ui'
import { COLS, ACT_ICON, ago } from './pm'

const props = defineProps<{ open: boolean; task: any | null; project: any; meta: any; preset?: { status?: string; milestone_id?: number | null } }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()
const f = ref<any>(null)
const busy = ref(false)
const newItem = ref('')
const comment = ref('')
const lead = computed(() => !!props.project?.can_edit)
const isNew = computed(() => !props.task?.id)
const comments = computed(() => (props.project?.activity ?? []).filter((a: any) => a.task_id && a.task_id === props.task?.id))
const files = computed(() => (props.project?.files ?? []).filter((x: any) => x.task_id && x.task_id === props.task?.id))

watch(() => [props.open, props.task?.id], () => {
  if (!props.open) return
  const t = props.task
  f.value = t?.id
    ? { title: t.title, description: t.description ?? '', status: t.status, priority: t.priority, due: t.due ?? '', milestone_id: t.milestone_id ? String(t.milestone_id) : '',
        assignee_id: t.assignee?.id ?? '', checklist: (t.checklist ?? []).map((c: any) => ({ ...c })) }
    : { title: '', description: '', status: props.preset?.status ?? 'todo', priority: 'normal', due: '', milestone_id: props.preset?.milestone_id ? String(props.preset.milestone_id) : '',
        assignee_id: '', checklist: [] }
  newItem.value = ''; comment.value = ''
}, { immediate: true })

function addItem() { if (newItem.value.trim()) { f.value.checklist.push({ text: newItem.value.trim(), done: false }); newItem.value = '' } }
async function save(close = true) {
  if (!f.value.title.trim()) return toast('Vazifa nomini yozing', 'danger')
  busy.value = true
  const b = { ...f.value, due: f.value.due || null, milestone_id: f.value.milestone_id ? Number(f.value.milestone_id) : null, assignee_id: f.value.assignee_id || null }
  try {
    isNew.value ? await api.post(`/projects/${props.project.id}/tasks`, b) : await api.put(`/projects/tasks/${props.task.id}`, b)
    toast('Saqlandi'); emit('saved'); if (close) emit('close')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function setStatus(s: string) { f.value.status = s; if (!isNew.value) await save(false) }
async function del() {
  if (!confirm('Vazifa o\'chirilsinmi?')) return
  try { await api.del(`/projects/tasks/${props.task.id}`); toast('O\'chirildi'); emit('saved'); emit('close') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function send() {
  if (!comment.value.trim()) return
  try { await api.post(`/projects/${props.project.id}/comments`, { text: comment.value, task_id: props.task.id }); comment.value = ''; emit('saved') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  try { await api.upload(`/projects/${props.project.id}/files?task_id=${props.task.id}`, file); toast('Fayl qo\'shildi'); emit('saved') } catch (err: any) { toast(err.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <UiDrawer :open="open" :title="isNew ? 'Yangi vazifa' : 'Vazifa'" width="560px" @close="emit('close')">
    <template v-if="f">
      <div class="st">
        <button v-for="c in COLS" :key="c.code" type="button" :class="{ on: f.status === c.code }" :style="{ '--c': c.color }" @click="setStatus(c.code)">{{ c.label }}</button>
      </div>
      <template v-if="lead || isNew">
        <UiInput v-model="f.title" label="Nima qilish kerak" placeholder="Masalan: 3 ta pudratchidan smeta olish" />
        <div class="g2">
          <UiSelect v-model="f.assignee_id" label="Mas'ul" :options="[{ value: '', label: '— tayinlanmagan —' }, ...meta.users.map((u: any) => ({ value: u.id, label: u.name }))]" />
          <UiInput v-model="f.due" type="date" label="Muddat" />
          <UiSelect v-model="f.milestone_id" label="Bosqich" :options="[{ value: '', label: '— bosqichsiz —' }, ...project.milestones.map((m: any) => ({ value: String(m.id), label: m.title }))]" />
          <UiSelect v-model="f.priority" label="Muhimlik" :options="meta.priorities.map((p: any) => ({ value: p.code, label: p.label }))" />
        </div>
        <label class="fl"><span>Izoh / tafsilot</span><textarea v-model="f.description" rows="3" placeholder="Qanday qilish, kim bilan gaplashish, qayerga borish…"></textarea></label>
      </template>
      <template v-else>
        <h3 class="tt">{{ task.title }}</h3>
        <p class="mut">{{ task.assignee?.name ?? 'Tayinlanmagan' }} · muddat {{ task.due ?? '—' }}</p>
        <p v-if="task.description" class="ds">{{ task.description }}</p>
      </template>

      <h4>Checklist <small v-if="f.checklist.length">{{ f.checklist.filter((c: any) => c.done).length }}/{{ f.checklist.length }}</small></h4>
      <label v-for="(c, i) in f.checklist" :key="i" class="ck"><input v-model="c.done" type="checkbox" /><span :class="{ dn: c.done }">{{ c.text }}</span>
        <button v-if="lead" type="button" aria-label="O'chirish" @click.prevent="f.checklist.splice(i, 1)">×</button></label>
      <div v-if="lead || isNew" class="ni"><input v-model="newItem" placeholder="+ band qo'shish" @keydown.enter.prevent="addItem()" /><button type="button" @click="addItem()">Qo'shish</button></div>

      <template v-if="!isNew">
        <h4>Fayllar</h4>
        <div class="fs">
          <a v-for="x in files" :key="x.id" :href="x.url" target="_blank" rel="noopener" class="fi"><img v-if="x.is_image" :src="x.url" alt="" /><span v-else>📄</span>{{ x.title }}</a>
          <label class="up">📷 Rasm / fayl<input type="file" @change="upload" /></label>
        </div>
        <h4>Izohlar</h4>
        <div v-for="a in comments" :key="a.id" class="cm"><b>{{ ACT_ICON[a.kind] }} {{ a.actor?.name ?? 'Tizim' }}</b><small>{{ ago(a.at) }}</small><p>{{ a.text }}</p></div>
        <div class="ni"><input v-model="comment" placeholder="Izoh yozing…" @keydown.enter.prevent="send()" /><button type="button" @click="send()">Yuborish</button></div>
      </template>
    </template>
    <template #footer>
      <UiButton v-if="!isNew && lead" variant="ghost" @click="del()">O'chirish</UiButton>
      <span class="sp"></span>
      <UiButton variant="ghost" @click="emit('close')">Yopish</UiButton>
      <UiButton variant="brand" :loading="busy" @click="save()">Saqlash</UiButton>
    </template>
  </UiDrawer>
</template>

<style scoped>
.st { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 14px; }
.st button { min-height: 44px; border: 2px solid var(--line); border-radius: 12px; background: var(--surface); font: inherit; font-size: var(--fs-xs); font-weight: 800; cursor: pointer; color: var(--ink); }
.st button.on { border-color: var(--c); background: color-mix(in srgb, var(--c) 14%, var(--surface)); color: var(--c); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.fl { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; } .fl span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
textarea { border: 1px solid var(--line); border-radius: 12px; padding: 10px; font: inherit; background: var(--surface); color: var(--ink); }
h4 { margin: 18px 0 6px; font-size: var(--fs-s); } h4 small { color: var(--muted); }
.tt { margin: 0; } .mut { color: var(--muted); font-size: var(--fs-s); margin: 4px 0; } .ds { white-space: pre-wrap; font-size: var(--fs-s); }
.ck { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 4px 8px; border-radius: 10px; font-size: var(--fs-s); cursor: pointer; }
.ck:hover { background: var(--surface-2); } .ck input { width: 20px; height: 20px; accent-color: var(--ok); } .ck span { flex: 1; } .dn { text-decoration: line-through; color: var(--muted); }
.ck button { border: 0; background: transparent; color: var(--muted); font-size: 18px; cursor: pointer; }
.ni { display: flex; gap: 6px; margin-top: 6px; }
.ni input { flex: 1; min-height: 40px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); min-width: 0; }
.ni button { border: 0; border-radius: 10px; background: var(--surface-2); padding: 0 14px; font: inherit; font-weight: 700; cursor: pointer; color: var(--ink); }
.fs { display: flex; flex-wrap: wrap; gap: 8px; }
.fi { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 10px; font-size: var(--fs-xs); color: var(--ink); text-decoration: none; max-width: 100%; }
.fi img { width: 32px; height: 32px; object-fit: cover; border-radius: 6px; }
.up { position: relative; display: flex; align-items: center; padding: 6px 12px; border: 1px dashed var(--line); border-radius: 10px; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--muted); }
.up input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.cm { padding: 8px 10px; border-radius: 10px; background: var(--surface-2); margin-bottom: 6px; font-size: var(--fs-s); } .cm small { color: var(--muted); margin-left: 8px; } .cm p { margin: 4px 0 0; }
.sp { flex: 1; }
@media (max-width: 600px) { .g2 { grid-template-columns: 1fr; } .st button { font-size: 11px; } }
</style>
