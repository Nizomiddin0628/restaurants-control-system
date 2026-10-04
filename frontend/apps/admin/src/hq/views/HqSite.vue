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
const C = ref<any[]>([]), openChat = ref<number | null>(null), newKey = ref('')
const STATUS: Record<string, string> = { new: 'Yangi', contacted: "Bog'lanildi", won: "Mijoz bo'ldi", lost: 'Rad etdi' }
const SRC: Record<string, string> = { ai_chat: '🤖 AI suhbat', form: '📝 Forma' }
async function load() {
  O.value = await api.get('/hq/offer'); inc.value = (O.value.includes || []).join('\n')
  try { L.value = await api.get('/hq/leads', fs.value ? { status: fs.value } : {}) } catch { L.value = null }
  try { C.value = (await api.get('/hq/chats')).items } catch { C.value = [] }
}
onMounted(load)
async function save() {
  busy.value = true
  try {
    O.value = await api.put('/hq/offer', { ...O.value, base_price: Number(O.value.base_price), ai_price: Number(O.value.ai_price),
      trial_days: Number(O.value.trial_days), includes: inc.value.split('\n').map((x: string) => x.trim()).filter(Boolean), ai_key: newKey.value.trim() })
    newKey.value = ''
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
      <div class="key">
        <UiInput v-model="newKey" label="Gemini API kaliti (saytdagi AI uchun)" :placeholder="O.ai_key || 'AIza… (aistudio.google.com/apikey)'" type="password" autocomplete="off" :disabled="!canEdit" />
        <small :class="{ bad: O.ai_key_source?.startsWith('YO') }">Hozir ishlatilayotgan kalit: <b>{{ O.ai_key_source }}</b>{{ O.ai_key ? ' · ' + O.ai_key : '' }}</small>
      </div>
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
    <UiCard :title="`AI maslahatchi bilan suhbatlar · ${C.length}`">
      <UiEmpty v-if="!C.length" title="Hozircha suhbat yo'q" text="Saytga kirganlar AI bilan gaplashsa, suhbatlar shu yerda ko'rinadi — o'qib, qo'ng'iroq qilasiz." />
      <div v-for="c in C" :key="c.id" class="ch">
        <button type="button" class="chh" :aria-expanded="openChat === c.id" @click="openChat = openChat === c.id ? null : c.id">
          <span class="cq">{{ c.first || '(rasm)' }}</span>
          <span class="cm">{{ c.count }} savol · {{ dt(c.updated_at) }}</span>
          <b v-if="c.lead" class="cl">📞 {{ c.lead.name || '' }} {{ c.lead.phone }}</b>
        </button>
        <div v-if="openChat === c.id" class="cb">
          <p v-for="(m, i) in c.messages" :key="i" :class="m.role">{{ m.text }}</p>
        </div>
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
.key { display: grid; gap: 6px; margin: 10px 0; } .key small { color: var(--muted); font-size: var(--fs-xs); } .key small.bad b { color: #DC2626; }
.ch { border-top: 1px solid var(--line-2, var(--line)); }
.chh { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; text-align: left; border: 0; background: transparent; padding: 12px 4px; cursor: pointer; font: inherit; color: var(--ink); }
.cq { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .cm { color: var(--muted); font-size: var(--fs-xs); } .cl { grid-column: 1 / -1; color: #16A34A; font-size: var(--fs-s); }
.cb { display: flex; flex-direction: column; gap: 6px; padding: 4px 4px 14px; }
.cb p { margin: 0; max-width: 80%; padding: 8px 12px; border-radius: 12px; font-size: var(--fs-s); white-space: pre-wrap; }
.cb p.me { align-self: flex-end; background: #2563EB; color: #fff; } .cb p.ai { align-self: flex-start; background: var(--surface-2); }
.ld { display: grid; grid-template-columns: 220px minmax(0, 1fr) 150px; gap: 12px; align-items: center; padding: 12px 4px; border-top: 1px solid var(--line-2, var(--line)); }
.ld.new .who b::after { content: ' ●'; color: #DC2626; }
.who { display: flex; flex-direction: column; } .who a { color: #2563EB; font-weight: 700; text-decoration: none; } .who small { color: var(--muted); font-size: var(--fs-xs); }
.what { display: flex; flex-direction: column; gap: 2px; font-size: var(--fs-s); min-width: 0; } .nt { color: var(--muted); white-space: pre-wrap; }
select { min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); padding: 0 10px; font: inherit; background: var(--surface); color: var(--ink); }
@media (max-width: 760px) { .g4 { grid-template-columns: 1fr 1fr; } .g2 { grid-template-columns: 1fr; } .ld { grid-template-columns: 1fr; } }
</style>
