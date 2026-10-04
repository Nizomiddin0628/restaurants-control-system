<script setup lang="ts">
/** Platforma sayti: narxlar va taklif (saytda darhol o'zgaradi), AI maslahatchi, saytdan kelgan arizalar (lead). */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiEmpty, UiInput, UiToggle, toast } from '@restopos/ui'
import { useHq } from '../store'
import { dt } from '../fmt'

const s = useHq()
const canEdit = computed(() => s.can('sales', 'finance'))
const O = ref<any>(null), inc = ref(''), busy = ref(false)
const L = ref<{ items: any[]; new: number } | null>(null), fs = ref('')
const STATUS: Record<string, string> = { new: 'Yangi', contacted: "Bog'lanildi", won: "Mijoz bo'ldi", lost: 'Rad etdi' }
const SRC: Record<string, string> = { ai_chat: '🤖 AI suhbat', form: '📝 Forma' }
async function load() {
  O.value = await api.get('/hq/offer'); inc.value = (O.value.includes || []).join('\n')
  try { L.value = await api.get('/hq/leads', fs.value ? { status: fs.value } : {}) } catch { L.value = null }
}
onMounted(load)
async function save() {
  busy.value = true
  try {
    O.value = await api.put('/hq/offer', { ...O.value, base_price: Number(O.value.base_price), ai_price: Number(O.value.ai_price),
      trial_days: Number(O.value.trial_days), includes: inc.value.split('\n').map((x: string) => x.trim()).filter(Boolean) })
    inc.value = O.value.includes.join('\n'); toast('Saqlandi — saytda darhol ko\'rinadi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function setStatus(l: any, st: string) {
  try { Object.assign(l, await api.post(`/hq/leads/${l.id}`, { status: st })); if (L.value) L.value.new = L.value.items.filter(x => x.status === 'new').length } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function filter(v: string) { fs.value = v; await load() }
</script>

<template>
  <div class="si" v-if="O">
    <UiCard title="Narxlar va taklif">
      <p class="note">Bu qiymatlar platforma saytida (narxlar, savollar, ro'yxatdan o'tish) va AI maslahatchi javoblarida darhol ishlatiladi.
        <a href="/" target="_blank" rel="noopener">Saytni ochish ↗</a></p>
      <div class="g4">
        <UiInput v-model="O.currency" label="Valyuta belgisi" :disabled="!canEdit" />
        <UiInput v-model="O.base_price" label="Dastur — oyiga" type="number" :disabled="!canEdit" />
        <UiInput v-model="O.ai_price" label="Dastur + AI — oyiga" type="number" :disabled="!canEdit" />
        <UiInput v-model="O.trial_days" label="Bepul davr (kun)" type="number" :disabled="!canEdit" />
      </div>
      <UiInput v-model="O.price_note" label="Narx izohi" placeholder="bitta restoran uchun, oyiga" :disabled="!canEdit" />
      <div class="row"><UiToggle v-model="O.free_setup" label="Aksiya: ulab berish bepul" :disabled="!canEdit" /></div>
      <UiInput v-if="O.free_setup" v-model="O.setup_note" label="Aksiya matni" :disabled="!canEdit" />
      <label class="ta"><span>Narx ichida (har qator — bitta band)</span><textarea v-model="inc" rows="6" :disabled="!canEdit"></textarea></label>
      <div class="g2">
        <UiInput v-model="O.phone" label="Telefon (saytda)" placeholder="+998 71 200 00 00" :disabled="!canEdit" />
        <UiInput v-model="O.telegram" label="Telegram (@ siz)" placeholder="restopos_uz" :disabled="!canEdit" />
      </div>
      <div class="row"><UiToggle v-model="O.ai_chat" label="Saytda AI maslahatchi yoqilgan" :disabled="!canEdit" /></div>
      <div class="row end"><small v-if="O.updated_at">Oxirgi o'zgarish: {{ dt(O.updated_at) }}</small>
        <UiButton v-if="canEdit" variant="brand" :loading="busy" @click="save">Saqlash</UiButton></div>
    </UiCard>

    <UiCard v-if="L" :title="`Saytdan arizalar${L.new ? ' · ' + L.new + ' ta yangi' : ''}`">
      <div class="fl"><button v-for="(v, k) in { '': 'Hammasi', ...STATUS }" :key="k" type="button" :class="{ on: fs === k }" @click="filter(String(k))">{{ v }}</button></div>
      <UiEmpty v-if="!L.items.length" title="Hozircha ariza yo'q" text="Saytdagi AI maslahatchi yoki forma orqali kelgan arizalar shu yerda ko'rinadi." />
      <div v-for="l in L.items" :key="l.id" class="ld" :class="l.status">
        <div class="who"><b>{{ l.name || '—' }}</b><a :href="`tel:${l.phone}`">{{ l.phone }}</a><small>{{ SRC[l.source] || l.source }} · {{ dt(l.created_at) }}</small></div>
        <div class="what"><span v-if="l.business">🏪 {{ l.business }}</span><span v-if="l.note" class="nt">{{ l.note }}</span></div>
        <select :value="l.status" aria-label="Holat" @change="setStatus(l, ($event.target as HTMLSelectElement).value)">
          <option v-for="(v, k) in STATUS" :key="k" :value="k">{{ v }}</option></select>
      </div>
    </UiCard>
  </div>
</template>

<style scoped>
.si { display: flex; flex-direction: column; gap: 12px; }
.note { margin: 0 0 12px; color: var(--muted); font-size: var(--fs-s); } .note a { color: #2563EB; font-weight: 700; }
.g4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px; }
.g2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 10px 0; }
.row { display: flex; gap: 12px; align-items: center; margin: 10px 0; } .row.end { justify-content: flex-end; } .row small { color: var(--muted); margin-right: auto; }
.ta { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; } .ta span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.ta textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); resize: vertical; }
.fl { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.fl button { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 6px 12px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink); }
.fl button.on { background: #2563EB; border-color: #2563EB; color: #fff; }
.ld { display: grid; grid-template-columns: 220px minmax(0, 1fr) 150px; gap: 12px; align-items: center; padding: 12px 4px; border-top: 1px solid var(--line-2, var(--line)); }
.ld.new .who b::after { content: ' ●'; color: #DC2626; }
.who { display: flex; flex-direction: column; } .who a { color: #2563EB; font-weight: 700; text-decoration: none; } .who small { color: var(--muted); font-size: var(--fs-xs); }
.what { display: flex; flex-direction: column; gap: 2px; font-size: var(--fs-s); min-width: 0; } .nt { color: var(--muted); white-space: pre-wrap; }
select { min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); padding: 0 10px; font: inherit; background: var(--surface); color: var(--ink); }
@media (max-width: 760px) { .g4 { grid-template-columns: 1fr 1fr; } .g2 { grid-template-columns: 1fr; } .ld { grid-template-columns: 1fr; } }
</style>
