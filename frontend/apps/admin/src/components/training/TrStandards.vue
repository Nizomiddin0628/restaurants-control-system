<script setup lang="ts">
/** Standartlar (komplayens): qoida yozish, rasm/video/PDF biriktirish, kim tanishdi — kim yo'q, yangi versiya. */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiDropzone, UiEmpty, UiIcon, UiInput, UiSelect, toast } from '@restopos/ui'
import AudiencePicker from './AudiencePicker.vue'
import { fmtDate, uploadWithProgress } from './upload'

const props = defineProps<{ meta: any }>()
const list = ref<any[]>([])
const form = ref<any>(null)
const pending = ref<File | null>(null)
const pct = ref<number | null>(null)
const acks = ref<any>(null)

async function load() { list.value = await api.get('/training/standards') }
onMounted(load)
function openForm(s?: any) { pending.value = null; form.value = s ? { ...s } : { title: '', category: '', body: '', responsible_id: null, is_active: true, roles: [], positions: [], user_ids: [], everyone: true } }
const aud = computed({ get: () => form.value, set: (v) => Object.assign(form.value, v) })
async function save() {
  const f = form.value
  if (!f.title.trim()) { toast('Nomini yozing', 'danger'); return }
  const body = { title: f.title, category: f.category, body: f.body, responsible_id: f.responsible_id || null, is_active: f.is_active, roles: f.roles, positions: f.positions, user_ids: f.user_ids, everyone: f.everyone }
  try {
    const r = f.id ? await api.put(`/training/standards/${f.id}`, body) : await api.post('/training/standards', body)
    if (pending.value) { pct.value = 0; await uploadWithProgress(`/training/standards/${r.id}/file`, pending.value, p => (pct.value = p)) }
    toast('Saqlandi'); form.value = null; await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { pct.value = null }
}
async function newVersion(s: any) {
  if (!confirm(`«${s.title}» yangilandimi? Hamma qaytadan tanishib chiqishi kerak bo'ladi.`)) return
  await api.post(`/training/standards/${s.id}/new-version`); toast(`v${s.version + 1} — xodimlarga xabar yuborildi`); await load()
}
async function remove(s: any) { if (!confirm(`«${s.title}» o'chirilsinmi?`)) return; await api.del(`/training/standards/${s.id}`); form.value = null; await load() }
async function openAcks(s: any) { acks.value = { s, rows: await api.get(`/training/standards/${s.id}/acks`) } }
const userOpts = computed(() => [{ value: '', label: '— tanlanmagan —' }, ...props.meta.users.map((u: any) => ({ value: u.id, label: u.full_name }))])
</script>

<template>
  <div class="ts">
    <div class="bar"><UiButton variant="brand" @click="openForm()"><UiIcon name="plus" :size="15" /> Standart</UiButton></div>
    <div class="rows">
      <article v-for="s in list.filter(x => x.is_active)" :key="s.id" class="row">
        <span class="ic"><UiIcon name="shield" :size="18" /></span>
        <button type="button" class="info" @click="openForm(s)"><b>{{ s.title }}</b><small>{{ s.category || 'Bo\'limsiz' }} · v{{ s.version }} · yangilangan {{ fmtDate(s.updated_at) }}</small></button>
        <button type="button" class="st" @click="openAcks(s)">
          <b>{{ s.acked }}<small>/{{ s.audience }}</small></b><span>tanishgan</span>
          <div class="tr-bar"><i :style="{ width: (s.audience ? (100 * s.acked) / s.audience : 0) + '%' }"></i></div>
        </button>
        <UiButton size="s" variant="secondary" @click="newVersion(s)">Yangi versiya</UiButton>
      </article>
      <UiEmpty v-if="!list.length" title="Standart yo'q" text="Qo'l yuvish, forma, harorat nazorati kabi qoidalarni yozing — xodim «Tanishdim» deb tasdiqlaydi." />
    </div>

    <UiDrawer :open="!!form" :title="form?.id ? 'Standartni tahrirlash' : 'Yangi standart'" width="620px" @close="form = null">
      <template v-if="form">
        <UiInput v-model="form.title" label="Nomi" placeholder="Masalan: Qo'l yuvish qoidasi" />
        <div class="g2">
          <label class="fld"><span>Bo'lim</span><input v-model="form.category" list="tr-cats2" placeholder="Gigiyena, Oshxona…" /><datalist id="tr-cats2"><option v-for="c in meta.categories" :key="c" :value="c" /></datalist></label>
          <UiSelect :model-value="form.responsible_id ?? ''" label="Mas'ul" :options="userOpts" @update:model-value="(v) => (form.responsible_id = v || null)" />
        </div>
        <label class="fld"><span>Qoida matni</span><textarea v-model="form.body" rows="6" placeholder="Nima, qachon, qanday qilinadi"></textarea></label>
        <b class="lbl">Rasm, video yoki PDF</b>
        <a v-if="form.file && !pending" :href="form.file" target="_blank" class="cur">Joriy fayl</a>
        <UiDropzone accept="image/*,video/*,application/pdf" :label="pending ? '✓ ' + pending.name : 'Fayl tanlang'" @files="(f) => (pending = f[0])" />
        <div v-if="pct !== null" class="tr-bar"><i :style="{ width: pct + '%' }"></i></div>
        <b class="lbl">Kim tanishishi kerak</b>
        <AudiencePicker v-model="aud" :meta="meta" />
      </template>
      <template #footer><UiButton v-if="form?.id" variant="danger" @click="remove(form)"><UiIcon name="trash" :size="14" /></UiButton><span style="flex: 1"></span><UiButton variant="ghost" @click="form = null">Bekor</UiButton><UiButton variant="brand" @click="save">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!acks" :title="acks ? `${acks.s.title} · v${acks.s.version}` : ''" width="520px" @close="acks = null">
      <template v-if="acks">
        <div v-for="r in acks.rows" :key="r.user.id" class="ar"><b>{{ r.user.full_name }}</b><UiChip :tone="r.acked_at ? 'ok' : 'danger'">{{ r.acked_at ? '✓ ' + fmtDate(r.acked_at) : 'Tanishmagan' }}</UiChip></div>
        <UiEmpty v-if="!acks.rows.length" title="Auditoriya bo'sh" />
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.ts { display: flex; flex-direction: column; gap: 12px; }
.rows { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; }
.ic { width: 40px; height: 40px; border-radius: 10px; background: var(--tr-green-tint, #E6F5EC); color: var(--tr-green, #1E9E5A); display: grid; place-items: center; flex-shrink: 0; }
.info { flex: 1; min-width: 0; border: 0; background: none; cursor: pointer; font: inherit; color: inherit; text-align: left; display: flex; flex-direction: column; } .info small { color: var(--muted); font-size: 12px; }
.st { width: 130px; border: 0; background: var(--surface-2); border-radius: 10px; padding: 8px 10px; cursor: pointer; font: inherit; color: inherit; display: flex; flex-direction: column; gap: 3px; text-align: left; }
.st b { font-size: 17px; } .st b small { font-size: 12px; color: var(--muted); } .st span { font-size: 11px; color: var(--muted); }
.fld { display: flex; flex-direction: column; gap: 6px; } .fld span, .lbl { font-size: 13px; font-weight: 700; color: var(--ink-2); }
.fld textarea, .fld input { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); min-height: 40px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: end; }
.cur { color: var(--accent); font-weight: 700; }
.ar { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--line-2); }
@media (max-width: 600px) { .g2 { grid-template-columns: 1fr; } .row { flex-wrap: wrap; } .st { flex: 1; } }
</style>
