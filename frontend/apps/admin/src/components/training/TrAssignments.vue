<script setup lang="ts">
/** Topshiriqlar: yaratish (namuna video/rasm bilan), xodimlar dalillarini tekshirish (qabul / qaytarish). */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiDropzone, UiEmpty, UiIcon, UiInput, UiSelect, UiToggle, toast } from '@restopos/ui'
import AudiencePicker from './AudiencePicker.vue'
import MediaView from './MediaView.vue'
import { fmtDate, fmtDateTime, isUrl, SUB_STATUS, uploadWithProgress } from './upload'

const props = defineProps<{ meta: any; courses: any[] }>()
const list = ref<any[]>([])
const form = ref<any>(null)
const pct = ref<number | null>(null)
const pending = ref<File | null>(null)
const view = ref<any>(null)
const subs = ref<any[]>([])
const notes = ref<Record<number, string>>({})

async function load() { list.value = await api.get('/training/assignments') }
onMounted(load)
function openForm(a?: any) {
  pending.value = null
  form.value = a ? { ...a, due: a.due_at ? a.due_at.slice(0, 16) : '' } : { title: '', description: '', media_url: '', course_id: null, due: '', requires_proof: true, responsible_id: null, is_active: true, roles: [], positions: [], user_ids: [], everyone: false }
}
const aud = computed({ get: () => form.value, set: (v) => Object.assign(form.value, v) })
async function save() {
  const f = form.value
  if (!f.title.trim()) { toast('Topshiriq nomini yozing', 'danger'); return }
  if (f.media_url && !isUrl(f.media_url)) { toast('Havola https:// bilan boshlanishi kerak', 'danger'); return }
  const body = { title: f.title, description: f.description, media_url: (f.media_url || '').trim(), course_id: f.course_id || null, due_at: f.due ? new Date(f.due).toISOString() : null, requires_proof: f.requires_proof,
    responsible_id: f.responsible_id || null, is_active: f.is_active, roles: f.roles, positions: f.positions, user_ids: f.user_ids, everyone: f.everyone }
  try {
    const r = f.id ? await api.put(`/training/assignments/${f.id}`, body) : await api.post('/training/assignments', body)
    if (pending.value) { pct.value = 0; await uploadWithProgress(`/training/assignments/${r.id}/media`, pending.value, p => (pct.value = p)) }
    toast(r.assigned ? `Yuborildi · ${r.assigned} xodimga` : 'Saqlandi'); form.value = null; await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { pct.value = null }
}
async function remove(a: any) { if (!confirm(`«${a.title}» o'chirilsinmi?`)) return; await api.del(`/training/assignments/${a.id}`); view.value = null; await load() }
async function openView(a: any) { view.value = a; subs.value = await api.get(`/training/assignments/${a.id}/submissions`) }
async function review(s: any, approve: boolean) {
  try { Object.assign(s, await api.post(`/training/submissions/${s.id}/review`, { approve, note: notes.value[s.id] ?? '' })); toast(approve ? 'Qabul qilindi ✓' : 'Qaytarildi'); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const userOpts = computed(() => [{ value: '', label: '— tanlanmagan —' }, ...props.meta.users.map((u: any) => ({ value: u.id, label: u.full_name }))])
const courseOpts = computed(() => [{ value: '', label: '— kursga bog\'lanmagan —' }, ...props.courses.map((c: any) => ({ value: c.id, label: c.title }))])
</script>

<template>
  <div class="ta">
    <div class="bar"><UiButton v-if="meta.can.manage" variant="brand" @click="openForm()"><UiIcon name="plus" :size="15" /> Topshiriq</UiButton></div>
    <div class="rows">
      <button v-for="a in list" :key="a.id" type="button" class="row" :class="{ off: !a.is_active }" @click="openView(a)">
        <span class="ic"><UiIcon :name="['video', 'youtube', 'drive', 'vimeo'].includes(a.media_view?.kind) ? 'play' : a.media_view ? 'image' : 'camera'" :size="18" /></span>
        <span class="minfo"><b>{{ a.title }}</b><small>{{ a.due_at ? 'Muddat: ' + fmtDate(a.due_at) : 'Muddatsiz' }}<template v-if="a.responsible"> · Mas'ul: {{ a.responsible.full_name }}</template></small></span>
        <span class="cnt">
          <UiChip v-if="a.counts.submitted" tone="info">{{ a.counts.submitted }} tekshiruvda</UiChip>
          <span class="done"><b>{{ a.counts.approved }}</b>/{{ a.total }} qabul</span>
        </span>
      </button>
      <UiEmpty v-if="!list.length" title="Topshiriq yo'q" text="Masalan: «Burgerni standart bo'yicha tayyorlab, rasmini yuboring»." />
    </div>

    <UiDrawer :open="!!form" :title="form?.id ? 'Topshiriqni tahrirlash' : 'Yangi topshiriq'" width="620px" @close="form = null">
      <template v-if="form">
        <UiInput v-model="form.title" label="Nomi" placeholder="Nima qilish kerak" />
        <label class="fld"><span>Batafsil</span><textarea v-model="form.description" rows="3" placeholder="Qanday bajariladi, qanday dalil kerak"></textarea></label>
        <b class="lbl">Namuna (video yoki rasm)</b>
        <MediaView v-if="form.media_view && !pending" :media="form.media_view" />
        <UiDropzone accept="image/*,video/*" :label="pending ? '✓ ' + pending.name : 'Video yoki rasm yuklash'" @files="(f) => (pending = f[0])" />
        <UiInput v-model="form.media_url" placeholder="yoki havola: YouTube, Google Drive, rasm/video manzili" />
        <div v-if="pct !== null" class="tr-bar"><i :style="{ width: pct + '%' }"></i></div>
        <div class="g2">
          <label class="fld"><span>Muddat</span><input v-model="form.due" type="datetime-local" /></label>
          <UiSelect :model-value="form.responsible_id ?? ''" label="Mas'ul (tekshiradi)" :options="userOpts" @update:model-value="(v) => (form.responsible_id = v || null)" />
        </div>
        <UiSelect :model-value="form.course_id ?? ''" label="Kurs" :options="courseOpts" @update:model-value="(v) => (form.course_id = v ? Number(v) : null)" />
        <b class="lbl">Kimga</b>
        <AudiencePicker v-model="aud" :meta="meta" />
        <UiToggle v-model="form.requires_proof" label="Rasm/video dalil majburiy" />
      </template>
      <template #footer><UiButton variant="ghost" @click="form = null">Bekor</UiButton><UiButton variant="brand" @click="save">{{ form?.id ? 'Saqlash' : 'Yuborish' }}</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!view" :title="view?.title ?? ''" width="720px" @close="view = null">
      <template v-if="view">
        <p v-if="view.description" class="desc">{{ view.description }}</p>
        <div class="acts" v-if="meta.can.manage"><UiButton size="s" variant="secondary" @click="openForm(view); view = null"><UiIcon name="edit" :size="14" /> Tahrirlash</UiButton><UiButton size="s" variant="danger" @click="remove(view)"><UiIcon name="trash" :size="14" /></UiButton></div>
        <article v-for="s in subs" :key="s.id" class="sub" :class="s.status">
          <header><b>{{ s.user.full_name }}</b><UiChip :tone="SUB_STATUS[s.status].tone">{{ SUB_STATUS[s.status].label }}</UiChip></header>
          <small v-if="s.submitted_at" class="tr-muted">Topshirdi: {{ fmtDateTime(s.submitted_at) }}<template v-if="s.attempts > 1"> · {{ s.attempts }}-urinish</template></small>
          <p v-if="s.text">{{ s.text }}</p>
          <div v-if="s.files.length" class="proofs">
            <a v-for="f in s.files" :key="f.id" :href="f.url" target="_blank" class="pf"><img v-if="f.is_image" :src="f.url" alt="Dalil" /><video v-else-if="f.is_video" :src="f.url" controls playsinline></video><span v-else>Fayl</span></a>
          </div>
          <p v-if="s.review_note" class="note">Izoh: {{ s.review_note }}</p>
          <div v-if="s.status === 'submitted'" class="rv">
            <input v-model="notes[s.id]" placeholder="Izoh (qaytarishda majburiy)" />
            <UiButton size="s" variant="danger" @click="review(s, false)">Qaytarish</UiButton>
            <UiButton size="s" @click="review(s, true)">Qabul qilish ✓</UiButton>
          </div>
        </article>
        <UiEmpty v-if="!subs.length" title="Hech kimga biriktirilmagan" />
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.ta { display: flex; flex-direction: column; gap: 12px; }
.rows { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; cursor: pointer; font: inherit; color: inherit; text-align: left; }
.row.off { opacity: .5; }
.ic { width: 40px; height: 40px; border-radius: 10px; background: var(--tr-gold-tint, #F6F0E4); color: var(--tr-gold, #A8894F); display: grid; place-items: center; flex-shrink: 0; }
.minfo { flex: 1; min-width: 0; display: flex; flex-direction: column; } .minfo small { color: var(--muted); font-size: 12px; }
.cnt { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.done { font-size: 13px; color: var(--muted); white-space: nowrap; } .done b { color: var(--ink); font-size: 16px; }
.fld { display: flex; flex-direction: column; gap: 6px; } .fld span, .lbl { font-size: 13px; font-weight: 700; color: var(--ink-2); }
.fld textarea, .fld input, .rv input { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); min-height: 40px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: end; }
.pv { width: 100%; max-height: 220px; object-fit: contain; border-radius: 10px; background: var(--surface-3); }
.desc { margin: 0; color: var(--ink-2); white-space: pre-line; }
.acts { display: flex; gap: 8px; }
.sub { border: 1px solid var(--line); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 6px; }
.sub.submitted { border-color: var(--info); }
.sub header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.sub p { margin: 0; }
.proofs { display: flex; flex-wrap: wrap; gap: 8px; }
.pf { width: 120px; height: 120px; border-radius: 10px; overflow: hidden; background: var(--surface-3); display: grid; place-items: center; }
.pf img, .pf video { width: 100%; height: 100%; object-fit: cover; }
.note { font-size: 13px; color: var(--muted); }
.rv { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .rv input { flex: 1; min-width: 180px; }
@media (max-width: 600px) { .g2 { grid-template-columns: 1fr; } .row { flex-wrap: wrap; } .cnt { width: 100%; justify-content: flex-start; } }
</style>
