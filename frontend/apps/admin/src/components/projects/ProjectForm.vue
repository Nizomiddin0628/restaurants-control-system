<script setup lang="ts">
/** Yangi loyiha (1-qadam: shablon tanlash, 2-qadam: ma'lumotlar) yoki mavjudini tahrirlash. */
import { computed, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiDrawer, UiInput, UiSelect, money, toast } from '@restopos/ui'

const props = defineProps<{ open: boolean; project?: any | null; meta: any }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', id: number): void }>()
const step = ref(1)
const f = ref<any>(null)
const busy = ref(false)
const tpl = computed(() => props.meta.templates.find((t: any) => t.key === f.value?.template_key))
const iso = (dt: Date) => new Date(dt.getTime() - dt.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const addDays = (s: string, n: number) => { const x = new Date(s + 'T00:00:00'); x.setDate(x.getDate() + n); return iso(x) }
const BUD = [5_000_000, 20_000_000, 50_000_000, 100_000_000, 300_000_000]

watch(() => props.open, (o) => {
  if (!o) return
  const p = props.project
  if (p) {
    step.value = 2
    f.value = { title: p.title, category: p.category.code, template_key: p.template_key, description: p.description, priority: p.priority, branch_id: p.branch ? String(p.branch.id) : '',
      owner_id: p.owner?.id ?? '', start: p.start ?? '', due: p.due ?? '', budget: p.budget, member_ids: [] }
  } else {
    step.value = 1
    const s = iso(new Date())
    f.value = { title: '', category: 'other', template_key: '', description: '', priority: 'normal', branch_id: '', owner_id: props.meta.me, start: s, due: addDays(s, 30), budget: 0, member_ids: [] }
  }
}, { immediate: true })

function pick(key: string) {
  const t = props.meta.templates.find((x: any) => x.key === key)
  f.value.template_key = key
  if (t) { f.value.title = t.title; f.value.category = t.category; f.value.due = addDays(f.value.start, t.days) }
  step.value = 2
}
watch(() => f.value?.start, (s, old) => { if (s && old && f.value?.due && tpl.value && !props.project) f.value.due = addDays(s, tpl.value.days) })
function toggle(id: string) { const s = new Set(f.value.member_ids); s.has(id) ? s.delete(id) : s.add(id); f.value.member_ids = [...s] }

async function save() {
  busy.value = true
  const b = { ...f.value, branch_id: f.value.branch_id ? Number(f.value.branch_id) : null, budget: Number(f.value.budget) || 0, start: f.value.start || null, due: f.value.due || null, owner_id: f.value.owner_id || null }
  try {
    const r = props.project ? await api.put(`/projects/${props.project.id}`, b) : await api.post('/projects/', b)
    toast(props.project ? 'Saqlandi' : 'Loyiha yaratildi'); emit('saved', r.id); emit('close')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
</script>

<template>
  <UiDrawer :open="open" :title="project ? 'Loyihani tahrirlash' : step === 1 ? 'Qanday loyiha?' : 'Yangi loyiha'" width="620px" @close="emit('close')">
    <template v-if="f">
      <template v-if="step === 1">
        <p class="mut">Tayyor shablon bosqich va vazifalarni o'zi yaratadi — keyin xohlagancha o'zgartirasiz.</p>
        <div class="tp">
          <button v-for="t in meta.templates" :key="t.key" type="button" @click="pick(t.key)">
            <span class="e">{{ t.emoji }}</span><b>{{ t.title }}</b><small>{{ t.description }}</small>
            <em>{{ t.milestones }} bosqich · {{ t.tasks }} vazifa · ~{{ t.days }} kun</em>
          </button>
          <button type="button" class="blank" @click="pick('')"><span class="e">✏️</span><b>Bo'sh loyiha</b><small>Bosqich va vazifalarni o'zingiz qo'shasiz</small></button>
        </div>
      </template>
      <template v-else>
        <p v-if="tpl && !project" class="tb">{{ tpl.emoji }} «{{ tpl.title }}» shabloni: {{ tpl.milestones }} bosqich, {{ tpl.tasks }} vazifa avtomatik qo'shiladi. <button type="button" @click="step = 1">O'zgartirish</button></p>
        <UiInput v-model="f.title" label="Loyiha nomi" placeholder="Masalan: Yunusobod filialini ochish" />
        <div class="cats"><button v-for="c in meta.categories" :key="c.code" type="button" :class="{ on: f.category === c.code }" :style="{ '--c': c.color }" @click="f.category = c.code">{{ c.emoji }} {{ c.label }}</button></div>
        <div class="g2">
          <UiSelect v-model="f.owner_id" label="Loyiha rahbari" :options="meta.users.map((u: any) => ({ value: u.id, label: u.name }))" />
          <UiSelect v-model="f.branch_id" label="Filial" :options="[{ value: '', label: '— umumiy / yangi filial —' }, ...meta.branches.map((b: any) => ({ value: String(b.id), label: b.name }))]" />
          <UiInput v-model="f.start" type="date" label="Boshlanish" />
          <UiInput v-model="f.due" type="date" label="Tugash (reja)" />
          <UiSelect v-model="f.priority" label="Muhimlik" :options="meta.priorities.map((p: any) => ({ value: p.code, label: p.label }))" />
          <UiInput v-model="f.budget" type="number" label="Byudjet (so'm)" />
        </div>
        <div class="qk"><button v-for="b in BUD" :key="b" type="button" :class="{ on: Number(f.budget) === b }" @click="f.budget = b">{{ money(b) }}</button></div>
        <template v-if="!project">
          <h4>Jamoa</h4>
          <div class="mm"><button v-for="u in meta.users.filter((x: any) => x.id !== f.owner_id)" :key="u.id" type="button" :class="{ on: f.member_ids.includes(u.id) }" @click="toggle(u.id)">{{ u.name }}</button></div>
        </template>
        <label class="fl"><span>Maqsad va tavsif</span><textarea v-model="f.description" rows="3" placeholder="Nima uchun, qanday natija kutamiz"></textarea></label>
      </template>
    </template>
    <template #footer>
      <template v-if="step === 2">
        <UiButton v-if="!project" variant="ghost" @click="step = 1">Orqaga</UiButton>
        <UiButton variant="brand" :loading="busy" @click="save()">{{ project ? 'Saqlash' : 'Loyihani yaratish' }}</UiButton>
      </template>
    </template>
  </UiDrawer>
</template>

<style scoped>
.mut { color: var(--muted); font-size: var(--fs-s); margin: 0 0 12px; }
.tp { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tp button { display: flex; flex-direction: column; gap: 4px; text-align: left; padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); font: inherit; cursor: pointer; color: var(--ink); }
.tp button:hover { border-color: var(--accent); background: var(--accent-tint); }
.tp .e { font-size: 28px; } .tp small { color: var(--muted); font-size: var(--fs-xs); line-height: 1.4; } .tp em { font-style: normal; font-size: 11px; color: var(--accent); font-weight: 700; margin-top: auto; }
.tp .blank { border-style: dashed; }
.tb { background: var(--accent-tint); padding: 10px 12px; border-radius: 12px; font-size: var(--fs-s); margin: 0 0 12px; }
.tb button { border: 0; background: transparent; color: var(--accent); font-weight: 700; cursor: pointer; font: inherit; text-decoration: underline; }
.cats { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
.cats button { min-height: 36px; padding: 0 12px; border: 1px solid var(--line); border-radius: 99px; background: var(--surface); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink); }
.cats button.on { border-color: var(--c); background: color-mix(in srgb, var(--c) 12%, var(--surface)); color: var(--c); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.qk, .mm { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.qk button, .mm button { min-height: 32px; padding: 0 10px; border: 1px solid var(--line); border-radius: 99px; background: var(--surface); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink); }
.qk button.on, .mm button.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
h4 { margin: 16px 0 4px; font-size: var(--fs-s); }
.fl { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; } .fl span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
textarea { border: 1px solid var(--line); border-radius: 12px; padding: 10px; font: inherit; background: var(--surface); color: var(--ink); }
@media (max-width: 600px) { .tp, .g2 { grid-template-columns: 1fr; } }
</style>
