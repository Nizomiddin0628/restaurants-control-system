<script setup lang="ts">
/** Texnik yordam: holat bo'yicha tablar, ro'yxat; bosilsa — yozishma, holat/muhimlik/mas'ul, javob yozish. */
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, toast } from '@restopos/ui'
import { useHq } from '../store'
import { STATUS_TONE, dt } from '../fmt'

const route = useRoute(), s = useHq()
const L = ref<any>(null)
const st = ref('')
const T = ref<any>(null)
const reply = ref('')
async function load() { L.value = await api.get('/hq/tickets', { status: st.value || undefined }); s.openTickets = L.value.counts.open }
async function open(id: number) { T.value = await api.get(`/hq/tickets/${id}`); reply.value = '' }
onMounted(async () => { await load(); if (route.query.open) open(Number(route.query.open)) })
watch(st, load)
async function upd(body: any) {
  try { T.value = await api.put(`/hq/tickets/${T.value.id}`, body); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function send() {
  if (!reply.value.trim()) return
  try { T.value = await api.post(`/hq/tickets/${T.value.id}/messages`, { body: reply.value }); reply.value = ''; await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div v-if="L" class="tk">
    <nav class="tabs" role="tablist">
      <button :class="{ on: st === '' }" @click="st = ''">Barchasi <i>{{ L.total }}</i></button>
      <button v-for="x in L.statuses" :key="x.code" :class="{ on: st === x.code }" @click="st = x.code">{{ x.label }} <i>{{ L.counts[x.code] }}</i></button>
    </nav>
    <UiCard :padded="false">
      <div class="th"><span>#</span><span>Mijoz</span><span>Filial</span><span>Muammo</span><span>Muhimlik</span><span>Holat</span><span>Yaratilgan</span></div>
      <button v-for="k in L.items" :key="k.id" type="button" class="tr" @click="open(k.id)">
        <b>#{{ k.number }}</b><span class="t">{{ k.tenant }}</span><span class="m">{{ k.branch || '—' }}</span><span class="sj">{{ k.subject }}</span>
        <span><UiChip :tone="STATUS_TONE[k.priority]">{{ k.priority_label }}</UiChip></span><span><UiChip :tone="STATUS_TONE[k.status]">{{ k.status_label }}</UiChip></span>
        <span class="m">{{ dt(k.created_at) }}</span>
      </button>
      <UiEmpty v-if="!L.items.length" title="Murojaat yo'q" text="Restoranlar panelning «Yordam» bo'limidan yozadi." />
    </UiCard>

    <UiDrawer :open="!!T" :title="T ? `#${T.number} ${T.subject}` : ''" width="560px" @close="T = null">
      <template v-if="T">
        <p class="meta"><RouterLink :to="`/tenants/${T.tenant_id}`">{{ T.tenant }}</RouterLink> · {{ T.branch || '—' }} · {{ T.author }} {{ T.phone }}</p>
        <div class="ctl">
          <label><span>Holat</span><select :value="T.status" @change="upd({ status: ($event.target as HTMLSelectElement).value })"><option v-for="x in L.statuses" :key="x.code" :value="x.code">{{ x.label }}</option></select></label>
          <label><span>Muhimlik</span><select :value="T.priority" @change="upd({ priority: ($event.target as HTMLSelectElement).value })"><option v-for="x in L.priorities" :key="x.code" :value="x.code">{{ x.label }}</option></select></label>
          <label><span>Mas'ul</span><select :value="L.staff.find((x: any) => x.name === T.assigned)?.id ?? ''" @change="upd({ assigned_id: Number(($event.target as HTMLSelectElement).value) || 0 })"><option value="">—</option><option v-for="x in L.staff" :key="x.id" :value="x.id">{{ x.name }}</option></select></label>
        </div>
        <ul class="chat">
          <li v-for="m in T.messages" :key="m.id" :class="{ me: m.from_staff }"><b>{{ m.author }}</b><p>{{ m.body }}</p><small>{{ dt(m.at) }}</small></li>
        </ul>
        <textarea v-model="reply" rows="3" placeholder="Javob yozing… (mijoz panelida ko'radi)"></textarea>
      </template>
      <template #footer>
        <UiButton variant="ghost" @click="upd({ status: 'closed' })">Yopish</UiButton>
        <div style="flex: 1"></div>
        <UiButton variant="brand" @click="send()">Yuborish</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.tk { display: flex; flex-direction: column; gap: 12px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: #2563EB; border-bottom-color: #2563EB; } .tabs i { font-style: normal; font-size: 11px; background: var(--surface-3); border-radius: 99px; padding: 1px 7px; margin-left: 4px; }
.th, .tr { display: grid; grid-template-columns: 70px 1.2fr 1fr 2fr .9fr 1fr 1fr; gap: 10px; align-items: center; padding: 10px 16px; font-size: var(--fs-s); }
.th { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.tr { width: 100%; border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; text-align: left; cursor: pointer; color: var(--ink); } .tr:hover { background: #EFF4FF; }
.t, .sj { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .m { color: var(--muted); }
.meta { margin: 0 0 10px; color: var(--muted); font-size: var(--fs-s); } .meta a { color: #2563EB; font-weight: 700; }
.ctl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; } .ctl label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
select { min-height: 38px; border: 1px solid var(--line); border-radius: 10px; padding: 0 8px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.chat { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.chat li { max-width: 85%; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); align-self: flex-start; } .chat li.me { align-self: flex-end; background: #EFF4FF; }
.chat b { font-size: var(--fs-xs); } .chat p { margin: 2px 0; white-space: pre-wrap; font-size: var(--fs-s); } .chat small { color: var(--muted); font-size: 11px; }
textarea { width: 100%; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); box-sizing: border-box; }
@media (max-width: 900px) { .th { display: none; } .tr { grid-template-columns: auto 1fr auto; } .tr .m, .tr > span:nth-child(5) { display: none; } .tr .sj { grid-column: 1 / -1; order: 5; } .ctl { grid-template-columns: 1fr; } }
</style>
