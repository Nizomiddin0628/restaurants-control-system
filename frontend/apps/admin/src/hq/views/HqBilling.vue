<script setup lang="ts">
/** Billing: shu oy jami / to'langan / kutilmoqda / muddati o'tgan, MRR grafigi, hisob-fakturalar. */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiEmpty, toast } from '@restopos/ui'
import AreaChart from '../charts/AreaChart.vue'
import { trimZeros } from '../fmt'
import { useHq } from '../store'
import { STATUS_TONE, big, d, sum } from '../fmt'

const s = useHq()
const B = ref<any>(null)
const status = ref('')
async function load() { B.value = await api.get('/hq/billing', { status: status.value || undefined }) }
onMounted(load)
watch(status, load)
const pts = computed(() => trimZeros((B.value?.mrr ?? []).map((m: any) => ({ label: m.label, value: m.amount }))))
async function set(id: number, st: string) {
  try { await api.post(`/hq/invoices/${id}/status`, { status: st }); toast('Yangilandi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div v-if="B" class="bl">
    <section class="tiles">
      <div><span>Shu oy jami</span><b>{{ big(B.summary.month_total) }}</b></div>
      <div class="ok"><span>To'langan</span><b>{{ big(B.summary.paid) }}</b></div>
      <div class="wr"><span>Kutilmoqda</span><b>{{ big(B.summary.pending) }}</b></div>
      <div class="dn"><span>Muddati o'tgan</span><b>{{ big(B.summary.overdue) }}</b><small>{{ B.summary.overdue_count }} ta hisob</small></div>
    </section>
    <UiCard title="Oylik daromad (MRR)" subtitle="12 oy"><AreaChart :points="pts" :height="190" /></UiCard>
    <UiCard :padded="false" title="Hisob-fakturalar">
      <template #actions>
        <select v-model="status" aria-label="Holat"><option value="">Hammasi</option><option v-for="x in B.statuses" :key="x.code" :value="x.code">{{ x.label }}</option></select>
      </template>
      <div class="th"><span>Mijoz</span><span>Oy</span><span>Tarif</span><span>Filial</span><span>Summa</span><span>Muddat</span><span>Holat</span><span></span></div>
      <div v-for="i in B.items" :key="i.id" class="tr">
        <RouterLink :to="`/tenants/${i.tenant_id}`" class="nm">{{ i.tenant }}</RouterLink>
        <span>{{ d(i.period).slice(3) }}</span><span>{{ i.plan }}</span><span>{{ i.branches }}</span>
        <b>{{ sum(i.amount) }}</b><span>{{ d(i.due_date) }}</span>
        <span><UiChip :tone="STATUS_TONE[i.status]">{{ i.status_label }}</UiChip></span>
        <span class="ac"><UiButton v-if="i.status !== 'paid' && s.can('finance')" size="s" variant="ghost" @click="set(i.id, 'paid')">To'landi</UiButton>
          <UiButton v-if="i.status === 'pending' && s.can('finance')" size="s" variant="ghost" @click="set(i.id, 'cancelled')">Bekor</UiButton></span>
      </div>
      <UiEmpty v-if="!B.items.length" title="Hisob yo'q" />
    </UiCard>
  </div>
</template>

<style scoped>
.bl { display: flex; flex-direction: column; gap: 14px; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.tiles div { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid #2563EB; border-radius: 14px; padding: 14px; display: flex; flex-direction: column; }
.tiles .ok { border-left-color: #16A34A; } .tiles .wr { border-left-color: #F59E0B; } .tiles .dn { border-left-color: #EF4444; }
.tiles span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .tiles b { font-family: var(--font-display); font-size: 24px; } .tiles small { color: var(--muted); font-size: 11px; }
select { min-height: 36px; border: 1px solid var(--line); border-radius: 10px; padding: 0 10px; font: inherit; background: var(--surface); color: var(--ink); }
.th, .tr { display: grid; grid-template-columns: minmax(0, 2fr) .7fr 1fr .6fr 1fr .9fr 1fr 1.3fr; gap: 10px; align-items: center; padding: 10px 16px; font-size: var(--fs-s); }
.th { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); } .tr { border-top: 1px solid var(--line-2); }
.nm { color: #2563EB; font-weight: 700; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ac { display: flex; gap: 4px; justify-content: flex-end; flex-wrap: wrap; }
@media (max-width: 900px) { .tiles { grid-template-columns: 1fr 1fr; } .th { display: none; } .tr { grid-template-columns: 1fr auto; } .tr > span:nth-child(3), .tr > span:nth-child(4), .tr > span:nth-child(6) { display: none; } .tr .ac { grid-column: 1 / -1; justify-content: flex-start; } }
</style>
