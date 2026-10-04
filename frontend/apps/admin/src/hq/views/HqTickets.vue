<script setup lang="ts">
/**
 * Vazifalar doskasi (kanban) va texnik yordam: restoran murojaatlari va ichki vazifalar bitta joyda.
 * Ustunlar — holat; kartani sudrab boshqa ustunga yoki yuqoriga surish mumkin. Muhimlik rangi, muddat (SLA) — kechiksa qizil.
 * Bosilsa — yozishma, holat/muhimlik/tur/mas'ul/muddat; javob restoran panelida ko'rinadi. «Ro'yxat» ko'rinishi ham bor.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, toast } from '@restopos/ui'
import { useHq } from '../store'
import { KIND_ICON, PRIO_COLOR, STATUS_TONE, ago, dt } from '../fmt'

const route = useRoute(), s = useHq()
const B = ref<any>(null)
const view = ref<'board' | 'list'>((localStorage.getItem('hq.tk.view') as any) || 'board')
watch(view, v => { try { localStorage.setItem('hq.tk.view', v) } catch { /* jim */ } })
const mine = ref(false), fTenant = ref<number | ''>(''), fKind = ref(''), q = ref('')
const T = ref<any>(null), reply = ref('')
const COLS: Record<string, { hint: string; color: string }> = {
  open: { hint: 'Yangi, hali olinmagan', color: '#EF4444' }, progress: { hint: 'Ustida ishlanmoqda', color: '#2563EB' },
  waiting: { hint: 'Mijoz javobi / tekshiruv', color: '#8B5CF6' }, closed: { hint: 'Hal qilindi (14 kun)', color: '#16A34A' },
}
async function load() {
  B.value = await api.get('/hq/board', { mine: mine.value || undefined, tenant_id: fTenant.value || undefined, kind: fKind.value || undefined, q: q.value || undefined })
  s.openTickets = B.value.columns.find((c: any) => c.code === 'open')?.items.length ?? 0
}
let qt: number | undefined
watch(q, () => { clearTimeout(qt); qt = window.setTimeout(load, 250) })
watch([mine, fTenant, fKind], load)
onMounted(async () => { await load(); if (route.query.open) open(Number(route.query.open)) })
const all = computed(() => (B.value?.columns ?? []).flatMap((c: any) => c.items))
const late = (c: any) => c.sla === 'late'
function due(c: any) {
  if (!c.due_at || c.status === 'closed') return ''
  const h = Math.round((new Date(c.due_at).getTime() - Date.now()) / 3600000)
  if (h < 0) return `${-h < 24 ? -h + ' soat' : Math.round(-h / 24) + ' kun'} kechikdi`
  return h < 24 ? `${h} soat qoldi` : `${Math.round(h / 24)} kun qoldi`
}

// --- sudrab surish
const drag = ref<number | null>(null), over = ref<string>(''), overCard = ref<number | null>(null)
function onDragStart(e: DragEvent, c: any) { drag.value = c.id; e.dataTransfer?.setData('text/plain', String(c.id)); if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move' }
function onDragOverCard(e: DragEvent, col: string, c: any) { e.preventDefault(); over.value = col; overCard.value = c.id }
function onDragOverCol(e: DragEvent, col: string) { e.preventDefault(); over.value = col }
async function onDrop(col: string) {
  const id = drag.value, before = overCard.value
  drag.value = null; over.value = ''; overCard.value = null
  if (!id || before === id) return
  await move(id, col, before)
}
async function move(id: number, status: string, before: number | null = null) {
  try { await api.post(`/hq/tickets/${id}/move`, { status, before_id: before }); await load(); if (T.value?.id === id) await open(id) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// --- karta oynasi
async function open(id: number) { T.value = await api.get(`/hq/tickets/${id}`); reply.value = '' }
async function upd(body: any) {
  try { T.value = await api.put(`/hq/tickets/${T.value.id}`, body); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function send() {
  if (!reply.value.trim()) return
  try { T.value = await api.post(`/hq/tickets/${T.value.id}/messages`, { body: reply.value }); reply.value = ''; await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const local = (iso: string | null) => { if (!iso) return ''; const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16) }

// --- yangi karta
const N = ref<any>(null), busy = ref(false)
function newCard(status = 'open') { N.value = { subject: '', body: '', tenant_id: fTenant.value || null, kind: 'task', priority: 'normal', assigned_id: s.me?.id ?? null, due_at: '', status } }
async function create() {
  if (!N.value.subject.trim()) { toast('Sarlavha yozing', 'danger'); return }
  busy.value = true
  try {
    const c = await api.post('/hq/tickets', { ...N.value, due_at: N.value.due_at ? new Date(N.value.due_at).toISOString() : null })
    if (N.value.status !== 'open') await api.post(`/hq/tickets/${c.id}/move`, { status: N.value.status })
    N.value = null; toast('Qo\'shildi'); await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
</script>

<template>
  <div v-if="B" class="tk">
    <div class="bar">
      <div class="seg" role="tablist"><button :class="{ on: view === 'board' }" @click="view = 'board'"><UiIcon name="columns" :size="15" /> Doska</button><button :class="{ on: view === 'list' }" @click="view = 'list'"><UiIcon name="list" :size="15" /> Ro'yxat</button></div>
      <label class="sr"><UiIcon name="search" :size="15" /><input v-model="q" placeholder="Qidirish…" /></label>
      <select v-model="fTenant" aria-label="Restoran"><option value="">Barcha restoranlar</option><option v-for="t in B.tenants" :key="t.id" :value="t.id">{{ t.name }}</option></select>
      <select v-model="fKind" aria-label="Tur"><option value="">Barcha turlar</option><option v-for="k in B.kinds" :key="k.code" :value="k.code">{{ KIND_ICON[k.code] }} {{ k.label }}</option></select>
      <label class="chk"><input v-model="mine" type="checkbox" /> Faqat meniki</label>
      <span v-if="B.late" class="late-b">⏰ {{ B.late }} ta muddati o'tgan</span>
      <UiButton variant="brand" size="s" @click="newCard()"><UiIcon name="plus" :size="14" /> Vazifa</UiButton>
    </div>

    <!-- DOSKA -->
    <div v-if="view === 'board'" class="board">
      <section v-for="c in B.columns" :key="c.code" class="col" :class="{ over: over === c.code }" @dragover="onDragOverCol($event, c.code)" @dragleave="over = ''" @drop.prevent="onDrop(c.code)">
        <header :style="{ '--cc': COLS[c.code].color }"><i></i><b>{{ c.label }}</b><span>{{ c.items.length }}</span><button type="button" :aria-label="`${c.label}ga qo'shish`" @click="newCard(c.code)"><UiIcon name="plus" :size="14" /></button></header>
        <small class="ch">{{ COLS[c.code].hint }}</small>
        <div class="cards">
          <article v-for="k in c.items" :key="k.id" class="card" :class="{ late: late(k), dragging: drag === k.id, before: overCard === k.id && drag !== k.id }"
                   :style="{ '--pc': PRIO_COLOR[k.priority] }" draggable="true" tabindex="0"
                   @dragstart="onDragStart($event, k)" @dragend="drag = null; over = ''; overCard = null" @dragover="onDragOverCard($event, c.code, k)"
                   @click="open(k.id)" @keydown.enter="open(k.id)">
            <div class="ct"><span class="kd" :title="k.kind_label">{{ KIND_ICON[k.kind] }}</span><b>#{{ k.number }}</b><UiChip :tone="STATUS_TONE[k.priority]">{{ k.priority_label }}</UiChip></div>
            <p class="sj">{{ k.subject }}</p>
            <div class="cm"><span class="tn">{{ k.tenant }}</span><span v-if="k.branch" class="mu">· {{ k.branch }}</span></div>
            <div class="cf">
              <span v-if="due(k)" class="due" :class="k.sla">⏱ {{ due(k) }}</span><span v-else class="mu">{{ ago(k.updated_at) }}</span>
              <UiAvatar v-if="k.assigned" :name="k.assigned" :size="22" :title="k.assigned" />
            </div>
          </article>
          <div v-if="!c.items.length" class="empty">Bo'sh — kartani shu yerga suring</div>
        </div>
      </section>
    </div>

    <!-- RO'YXAT -->
    <UiCard v-else :padded="false">
      <div class="th"><span>#</span><span>Mijoz</span><span>Muammo</span><span>Muhimlik</span><span>Holat</span><span>Muddat</span><span>Mas'ul</span></div>
      <button v-for="k in all" :key="k.id" type="button" class="tr" @click="open(k.id)">
        <b>{{ KIND_ICON[k.kind] }} #{{ k.number }}</b><span class="t">{{ k.tenant }}</span><span class="sj2">{{ k.subject }}</span>
        <span><UiChip :tone="STATUS_TONE[k.priority]">{{ k.priority_label }}</UiChip></span><span><UiChip :tone="STATUS_TONE[k.status]">{{ k.status_label }}</UiChip></span>
        <span class="due" :class="k.sla">{{ due(k) || '—' }}</span><span class="m">{{ k.assigned || '—' }}</span>
      </button>
      <UiEmpty v-if="!all.length" title="Vazifa yo'q" text="Restoranlar panelning «Yordam» bo'limidan yozadi; ichki vazifani «+ Vazifa» bilan qo'shing." />
    </UiCard>

    <!-- KARTA -->
    <UiDrawer :open="!!T" :title="T ? `#${T.number} ${T.subject}` : ''" width="600px" no-guard @close="T = null">
      <template v-if="T">
        <p class="meta"><RouterLink v-if="T.tenant_id" :to="`/tenants/${T.tenant_id}`">{{ T.tenant }}</RouterLink><b v-else>📌 Ichki vazifa</b> · {{ T.branch || '—' }} · {{ T.author }} {{ T.phone }} · {{ dt(T.created_at) }}</p>
        <div class="ctl">
          <label><span>Holat</span><select :value="T.status" @change="move(T.id, ($event.target as HTMLSelectElement).value)"><option v-for="c in B.columns" :key="c.code" :value="c.code">{{ c.label }}</option></select></label>
          <label><span>Muhimlik</span><select :value="T.priority" @change="upd({ priority: ($event.target as HTMLSelectElement).value })"><option v-for="x in B.priorities" :key="x.code" :value="x.code">{{ x.label }}</option></select></label>
          <label><span>Turi</span><select :value="T.kind" @change="upd({ kind: ($event.target as HTMLSelectElement).value })"><option v-for="x in B.kinds" :key="x.code" :value="x.code">{{ KIND_ICON[x.code] }} {{ x.label }}</option></select></label>
          <label><span>Mas'ul</span><select :value="B.staff.find((x: any) => x.name === T.assigned)?.id ?? ''" @change="upd({ assigned_id: Number(($event.target as HTMLSelectElement).value) || 0 })"><option value="">—</option><option v-for="x in B.staff" :key="x.id" :value="x.id">{{ x.name }}</option></select></label>
          <label class="w2"><span>Muddat (SLA)</span><input type="datetime-local" :value="local(T.due_at)" @change="upd({ due_at: ($event.target as HTMLInputElement).value ? new Date(($event.target as HTMLInputElement).value).toISOString() : '' })" /></label>
        </div>
        <p v-if="T.body" class="body">{{ T.body }}</p>
        <ul class="chat">
          <li v-for="m in T.messages" :key="m.id" :class="{ me: m.from_staff }"><b>{{ m.author }}</b><p>{{ m.body }}</p><small>{{ dt(m.at) }}</small></li>
        </ul>
        <textarea v-model="reply" rows="3" :placeholder="T.tenant_id ? 'Javob yozing… (restoran panelida ko\'radi)' : 'Izoh yozing…'"></textarea>
      </template>
      <template #footer>
        <UiButton v-if="T && T.status !== 'closed'" variant="ghost" @click="move(T.id, 'closed')">✓ Hal qilindi</UiButton>
        <div style="flex: 1"></div>
        <UiButton variant="brand" @click="send()">Yuborish</UiButton>
      </template>
    </UiDrawer>

    <!-- YANGI VAZIFA -->
    <UiDrawer :open="!!N" title="Yangi vazifa" width="520px" no-guard @close="N = null">
      <div v-if="N" class="nf">
        <label><span>Sarlavha *</span><input v-model="N.subject" placeholder="Masalan: Lazzat — kassa printeri chek chiqarmayapti" /></label>
        <label><span>Tafsilot</span><textarea v-model="N.body" rows="4" placeholder="Nima bo'ldi, qanday takrorlanadi, kim aytdi…"></textarea></label>
        <div class="g2">
          <label><span>Restoran</span><select v-model="N.tenant_id"><option :value="null">— ichki vazifa —</option><option v-for="t in B.tenants" :key="t.id" :value="t.id">{{ t.name }}</option></select></label>
          <label><span>Turi</span><select v-model="N.kind"><option v-for="k in B.kinds" :key="k.code" :value="k.code">{{ KIND_ICON[k.code] }} {{ k.label }}</option></select></label>
          <label><span>Muhimlik</span><select v-model="N.priority"><option v-for="p in B.priorities" :key="p.code" :value="p.code">{{ p.label }}</option></select></label>
          <label><span>Mas'ul</span><select v-model="N.assigned_id"><option :value="null">—</option><option v-for="x in B.staff" :key="x.id" :value="x.id">{{ x.name }}</option></select></label>
          <label class="w2"><span>Muddat (bo'sh — muhimlik bo'yicha avtomatik)</span><input v-model="N.due_at" type="datetime-local" /></label>
        </div>
        <p class="hint">Avtomatik muddat: Kritik — 4 soat, Yuqori — 1 kun, O'rta — 3 kun, Past — 7 kun.</p>
      </div>
      <template #footer><UiButton variant="ghost" @click="N = null">Bekor</UiButton><div style="flex: 1"></div><UiButton variant="brand" :loading="busy" @click="create()">Qo'shish</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.tk { display: flex; flex-direction: column; gap: 12px; }
.bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.seg { display: inline-flex; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 3px; }
.seg button { border: 0; background: transparent; border-radius: 8px; padding: 6px 12px; font: inherit; font-size: var(--fs-s); font-weight: 700; color: var(--muted); cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
.seg button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 2px rgba(0,0,0,.08); }
.sr { flex: 1 1 200px; display: flex; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: 10px; padding: 0 10px; min-height: 38px; background: var(--surface); color: var(--muted); }
.sr input { border: 0; outline: none; font: inherit; flex: 1; background: transparent; color: var(--ink); min-width: 0; }
select { min-height: 38px; border: 1px solid var(--line); border-radius: 10px; padding: 0 8px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.chk { display: inline-flex; gap: 6px; align-items: center; font-size: var(--fs-s); font-weight: 600; }
.bar > :last-child { margin-left: auto; }
.late-b { font-size: var(--fs-s); font-weight: 800; color: #B91C1C; background: #FEE2E2; padding: 6px 10px; border-radius: 99px; }
.board { display: grid; grid-template-columns: repeat(4, minmax(260px, 1fr)); gap: 12px; overflow-x: auto; padding-bottom: 6px; scroll-snap-type: x mandatory; align-items: start; }
.col { background: var(--surface-2); border: 1px solid var(--line); border-radius: 16px; padding: 10px; display: flex; flex-direction: column; gap: 6px; min-height: 220px; scroll-snap-align: start; transition: background-color .2s, border-color .2s; }
.col.over { background: #EFF4FF; border-color: #93B4F5; }
.col header { display: flex; align-items: center; gap: 8px; } .col header i { width: 10px; height: 10px; border-radius: 50%; background: var(--cc); }
.col header b { font-size: var(--fs-s); } .col header span { font-size: 11px; font-weight: 800; background: var(--surface-3); border-radius: 99px; padding: 1px 8px; }
.col header button { margin-left: auto; border: 0; background: transparent; color: var(--muted); cursor: pointer; border-radius: 8px; width: 28px; height: 28px; display: grid; place-items: center; } .col header button:hover { background: var(--surface); color: #2563EB; }
.ch { color: var(--muted); font-size: 11px; margin: -2px 0 4px 18px; }
.cards { display: flex; flex-direction: column; gap: 8px; }
.card { position: relative; background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--pc); border-radius: 12px; padding: 10px 12px; cursor: grab; display: grid; gap: 6px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .05); transition: box-shadow .2s, transform .2s, opacity .2s; }
.card:hover { box-shadow: 0 8px 20px -10px rgba(15, 23, 42, .35); transform: translateY(-1px); }
.card.dragging { opacity: .4; } .card.before::before { content: ""; position: absolute; left: 0; right: 0; top: -6px; height: 3px; border-radius: 3px; background: #2563EB; }
.card.late { background: #FFF7F7; border-color: #FCA5A5; border-left-color: #DC2626; }
.ct { display: flex; align-items: center; gap: 6px; } .ct b { font-size: var(--fs-xs); color: var(--muted); flex: 1; } .kd { font-size: 14px; }
.sj { margin: 0; font-weight: 700; font-size: var(--fs-s); line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.cm { font-size: var(--fs-xs); display: flex; gap: 4px; min-width: 0; } .tn { font-weight: 700; color: #2563EB; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .mu { color: var(--muted); font-size: var(--fs-xs); }
.cf { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.due { font-size: 11px; font-weight: 700; color: var(--muted); } .due.soon { color: #C2410C; } .due.late { color: #DC2626; }
.empty { border: 1.5px dashed var(--line); border-radius: 12px; padding: 18px 10px; text-align: center; color: var(--muted); font-size: var(--fs-xs); }
.th, .tr { display: grid; grid-template-columns: 90px 1.1fr 2fr .9fr 1fr 1fr 1fr; gap: 10px; align-items: center; padding: 10px 16px; font-size: var(--fs-s); }
.th { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.tr { width: 100%; border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; text-align: left; cursor: pointer; color: var(--ink); } .tr:hover { background: #EFF4FF; }
.t, .sj2 { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .m { color: var(--muted); }
.meta { margin: 0 0 10px; color: var(--muted); font-size: var(--fs-s); } .meta a { color: #2563EB; font-weight: 700; }
.ctl { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; } .ctl label, .nf label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.ctl .w2, .nf .w2 { grid-column: span 2; }
input[type=datetime-local], .nf input, .nf select, .nf textarea { min-height: 38px; border: 1px solid var(--line); border-radius: 10px; padding: 0 10px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); box-sizing: border-box; width: 100%; }
.nf textarea { padding: 8px 10px; } .nf { display: flex; flex-direction: column; gap: 10px; } .g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.body { white-space: pre-wrap; background: var(--surface-2); border-radius: 12px; padding: 10px 12px; font-size: var(--fs-s); margin: 0 0 12px; }
.hint { margin: 0; color: var(--muted); font-size: var(--fs-xs); }
.chat { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.chat li { max-width: 85%; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); align-self: flex-start; } .chat li.me { align-self: flex-end; background: #EFF4FF; }
.chat b { font-size: var(--fs-xs); } .chat p { margin: 2px 0; white-space: pre-wrap; font-size: var(--fs-s); } .chat small { color: var(--muted); font-size: 11px; }
textarea { width: 100%; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); box-sizing: border-box; }
@media (max-width: 900px) {
  .board { grid-template-columns: repeat(4, 82%); } .th { display: none; } .tr { grid-template-columns: auto 1fr auto; } .tr > span:nth-child(4), .tr .m, .tr > span:nth-child(6) { display: none; } .tr .sj2 { grid-column: 1 / -1; order: 5; }
  .ctl { grid-template-columns: 1fr 1fr; } .g2 { grid-template-columns: 1fr; } .nf .w2 { grid-column: auto; }
}
</style>
