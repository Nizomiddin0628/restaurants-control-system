<script setup lang="ts">
/** Lavozim formasi: nomi, ikonka, bo'lim, kimga bo'ysunadi, daraja, bosh ofis/filial, shtat, rol, maosh, maqsad, asosiy vazifalar. */
import { ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiDrawer, UiIcon, UiInput, UiSelect, toast } from '@restopos/ui'

const props = defineProps<{ open: boolean; value: any | null; meta: any }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', p: any): void; (e: 'deleted'): void }>()
const f = ref<any>(null)
const saving = ref(false)
const ICONS = ['👑', '⚙️', '👨‍🍳', '🍳', '🥕', '🧑‍💼', '📣', '💰', '🚚', '🏪', '⏱️', '💵', '🧑‍🍳', '🙋', '📦', '🧹', '🎧', '🛵', '🔧', '🛡️', '🧾', '🍕', '☕', '👤']

watch(() => [props.open, props.value], () => {
  if (!props.open) return
  const v = props.value
  f.value = v ? {
    id: v.id, name: v.name, icon: v.icon, code: v.code, department_id: v.department?.id ? String(v.department.id) : '', reports_to_id: v.reports_to?.id ? String(v.reports_to.id) : '',
    level: String(v.level), scope: v.scope, purpose: v.purpose, responsibilities: (v.responsibilities ?? []).map((r: any) => ({ ...r })), role_code: v.role_code,
    headcount: v.headcount, default_salary_type: v.default_salary_type, default_rate: v.default_rate,
  } : { name: '', icon: '👤', code: '', department_id: '', reports_to_id: '', level: '5', scope: 'branch', purpose: '', responsibilities: [{ text: '', freq: 'daily' }], role_code: '', headcount: 1, default_salary_type: 'monthly', default_rate: 0 }
}, { immediate: true })

async function save() {
  saving.value = true
  const b = { ...f.value, department_id: f.value.department_id ? Number(f.value.department_id) : null, reports_to_id: f.value.reports_to_id ? Number(f.value.reports_to_id) : null,
    level: Number(f.value.level), headcount: Number(f.value.headcount) || 0, default_rate: Number(f.value.default_rate) || 0,
    responsibilities: f.value.responsibilities.filter((r: any) => r.text.trim()) }
  try {
    const r = f.value.id ? await api.put(`/ops/positions/${f.value.id}`, b) : await api.post('/ops/positions', b)
    toast('Saqlandi'); emit('saved', r)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
async function remove() {
  if (!confirm(`«${f.value.name}» lavozimi o'chirilsinmi?`)) return
  try { await api.del(`/ops/positions/${f.value.id}`); toast('O\'chirildi'); emit('deleted') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <UiDrawer :open="open" :title="f?.id ? 'Lavozimni tahrirlash' : 'Yangi lavozim'" width="560px" @close="emit('close')">
    <template v-if="f">
      <div class="nm-row">
        <details class="icp"><summary :aria-label="'Ikonka'">{{ f.icon }}</summary>
          <div class="icg"><button v-for="i in ICONS" :key="i" type="button" :class="{ on: f.icon === i }" @click="f.icon = i">{{ i }}</button></div>
        </details>
        <UiInput v-model="f.name" label="Lavozim nomi" placeholder="Masalan: Filial menejeri" />
      </div>
      <div class="g2">
        <UiSelect v-model="f.department_id" label="Bo'lim" :options="[{ value: '', label: '— bo\'limsiz —' }, ...meta.departments.map((d: any) => ({ value: String(d.id), label: `${d.icon} ${d.name}` }))]" />
        <UiSelect v-model="f.reports_to_id" label="Kimga bo'ysunadi" :options="[{ value: '', label: '— hech kimga (eng yuqori) —' }, ...meta.positions.filter((p: any) => p.id !== f.id).map((p: any) => ({ value: String(p.id), label: p.name }))]" />
        <UiSelect v-model="f.level" label="Daraja" :options="meta.levels.map((l: any) => ({ value: String(l.value), label: l.label }))" />
        <UiInput v-model="f.headcount" type="number" :label="f.scope === 'branch' ? 'Shtat (har filialda nechta)' : 'Shtat (nechta kishi)'" />
      </div>
      <div class="seg" role="radiogroup" aria-label="Qayerda ishlaydi">
        <button v-for="s in meta.scopes" :key="s.value" type="button" :class="{ on: f.scope === s.value }" @click="f.scope = s.value">{{ s.value === 'hq' ? '🏢' : '🏪' }} {{ s.label }}</button>
      </div>
      <label class="fl"><span>Lavozim maqsadi — nima uchun kerak (1–2 gap)</span>
        <textarea v-model="f.purpose" rows="2" placeholder="Filialning kundalik ishi, xizmat sifati va savdosi uchun javobgar."></textarea></label>
      <div class="fl"><span>Asosiy vazifalar</span>
        <div v-for="(r, i) in f.responsibilities" :key="i" class="rs">
          <b>{{ i + 1 }}</b>
          <input v-model="r.text" placeholder="Masalan: Kassani tekshirish" />
          <select v-model="r.freq" aria-label="Qanchalik tez-tez"><option v-for="q in meta.freqs" :key="q.value" :value="q.value">{{ q.label }}</option></select>
          <button type="button" class="x" aria-label="O'chirish" @click="f.responsibilities.splice(i, 1)"><UiIcon name="x" :size="14" /></button>
        </div>
        <UiButton size="s" variant="ghost" @click="f.responsibilities.push({ text: '', freq: 'daily' })"><UiIcon name="plus" :size="14" /> Vazifa qo'shish</UiButton>
      </div>
      <details class="more"><summary>Qo'shimcha: rol, maosh, kod</summary>
        <div class="g2">
          <UiSelect v-model="f.role_code" label="Ishga olishda tizim roli" :options="[{ value: '', label: '— tanlanmagan —' }, ...meta.roles.map((r: any) => ({ value: r.code, label: r.name }))]" />
          <UiInput v-model="f.code" label="Lavozim kodi" placeholder="FM-01" />
          <UiSelect v-model="f.default_salary_type" label="Maosh turi" :options="[{ value: 'monthly', label: 'Oylik' }, { value: 'shift', label: 'Smena' }, { value: 'hourly', label: 'Soatbay' }, { value: 'percent', label: 'Foiz' }]" />
          <UiInput v-model="f.default_rate" type="number" label="Standart stavka" suffix="so'm" />
        </div>
      </details>
    </template>
    <template #footer>
      <UiButton v-if="f?.id" variant="danger" @click="remove()">O'chirish</UiButton>
      <div style="flex: 1"></div>
      <UiButton variant="ghost" @click="emit('close')">Bekor</UiButton>
      <UiButton variant="brand" :loading="saving" @click="save()">Saqlash</UiButton>
    </template>
  </UiDrawer>
</template>

<style scoped>
.nm-row { display: grid; grid-template-columns: 56px 1fr; gap: 10px; align-items: end; }
.icp { position: relative; } .icp summary { list-style: none; width: 56px; height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); display: grid; place-items: center; font-size: 24px; cursor: pointer; background: var(--surface); }
.icp summary::-webkit-details-marker { display: none; }
.icg { position: absolute; z-index: 5; top: calc(100% + 4px); left: 0; width: 260px; display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; padding: 8px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow); }
.icg button { height: 36px; border: 0; border-radius: 8px; background: transparent; font-size: 20px; cursor: pointer; } .icg button.on, .icg button:hover { background: var(--accent-tint); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 12px; }
.seg button { min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); font: inherit; font-weight: 700; cursor: pointer; }
.seg button.on { border-color: var(--accent); background: var(--accent-tint); color: var(--accent); }
.fl { display: flex; flex-direction: column; gap: 6px; margin-top: 14px; } .fl > span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fl textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); }
.rs { display: grid; grid-template-columns: 20px 1fr 130px 32px; gap: 6px; align-items: center; }
.rs b { color: var(--muted); font-size: var(--fs-xs); text-align: center; }
.rs input, .rs select { min-height: 40px; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 0 10px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); min-width: 0; }
.x { border: 0; background: transparent; color: var(--muted); cursor: pointer; height: 40px; }
.more { margin-top: 14px; } .more summary { cursor: pointer; font-weight: 700; color: var(--accent); font-size: var(--fs-s); }
@media (max-width: 600px) { .g2 { grid-template-columns: 1fr; } .rs { grid-template-columns: 18px 1fr 32px; } .rs select { grid-column: 2 / 3; } }
</style>
