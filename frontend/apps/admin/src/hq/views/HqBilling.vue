<script setup lang="ts">
/**
 * Billing: kim qachon qancha to'lashi kerak (to'lov kalendari), shu oy jami / to'langan / kutilmoqda / muddati o'tgan,
 * MRR ($ ekvivalenti), hisob-fakturalar. To'lov usuli bilan «To'landi».
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiEmpty, toast } from '@restopos/ui'
import AreaChart from '../charts/AreaChart.vue'
import { useHq } from '../store'
import { STATUS_TONE, d, money, moneyMix, trimZeros, usdEq } from '../fmt'

const s = useHq()
const B = ref<any>(null), U = ref<any[]>([])
const status = ref('')
async function load() {
  const [b, u] = await Promise.all([api.get('/hq/billing', { status: status.value || undefined }), api.get('/hq/payments/upcoming', { days: 45 })])
  B.value = b; U.value = u.items
}
onMounted(load)
watch(status, load)
const pts = computed(() => trimZeros((B.value?.mrr ?? []).map((m: any) => ({ label: m.label, value: m.amount }))))
const method = ref<Record<number, string>>({})
const METHODS = [['bank', 'Bank'], ['naqd', 'Naqd'], ['karta', 'Karta'], ['payme', 'Payme'], ['click', 'Click']]
async function set(id: number, st: string) {
  try { await api.post(`/hq/invoices/${id}/status`, { status: st, method: method.value[id] || '' }); toast(st === 'paid' ? 'To\'lov qabul qilindi' : 'Yangilandi'); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const GROUPS = [
  { key: 'overdue', title: 'Muddati o\'tgan', tone: 'dn' },
  { key: 'today', title: 'Bugun', tone: 'wr' },
  { key: 'soon', title: 'Yaqin kunlarda', tone: 'in' },
  { key: 'trial', title: 'Sinov tugaydi — birinchi to\'lov', tone: 'ai' },
]
const grouped = computed(() => GROUPS.map(g => ({ ...g, items: U.value.filter(x => x.state === g.key) })).filter(g => g.items.length))
const dayLabel = (x: any) => x.state === 'overdue' ? `${-x.days} kun kechikdi` : x.days === 0 ? 'bugun' : `${x.days} kundan keyin`
</script>

<template>
  <div v-if="B" class="bl">
    <section class="tiles">
      <button type="button" class="kpi-click" :class="{ on: !status }" @click="status = ''"><span>Shu oy jami</span><b>{{ moneyMix(B.summary.month_total) }}</b><small>{{ usdEq(B.summary.month_total) }}</small></button>
      <button type="button" class="ok kpi-click" :class="{ on: status === 'paid' }" @click="status = status === 'paid' ? '' : 'paid'"><span>To'langan</span><b>{{ moneyMix(B.summary.paid) }}</b><small>{{ usdEq(B.summary.paid) }}</small></button>
      <button type="button" class="wr kpi-click" :class="{ on: status === 'pending' }" @click="status = status === 'pending' ? '' : 'pending'"><span>Kutilmoqda</span><b>{{ moneyMix(B.summary.pending) }}</b><small>{{ usdEq(B.summary.pending) }}</small></button>
      <button type="button" class="dn kpi-click" :class="{ on: status === 'overdue' }" @click="status = status === 'overdue' ? '' : 'overdue'"><span>Muddati o'tgan</span><b>{{ moneyMix(B.summary.overdue) }}</b><small>{{ B.summary.overdue_count }} ta hisob</small></button>
    </section>

    <div class="row">
      <UiCard title="To'lov kalendari" subtitle="Kim, qachon, qancha — keyingi 45 kun">
        <div v-for="g in grouped" :key="g.key" class="grp">
          <h4 :class="g.tone">{{ g.title }} <i>{{ g.items.length }}</i></h4>
          <RouterLink v-for="x in g.items" :key="x.tenant_id + x.date" :to="`/tenants/${x.tenant_id}?tab=billing`" class="up" :class="g.tone">
            <span class="dt"><b>{{ d(x.date).slice(0, 5) }}</b><small>{{ dayLabel(x) }}</small></span>
            <span class="who"><b>{{ x.tenant }}</b><small>{{ x.tariff }}{{ x.region ? ' · ' + x.region : '' }}</small></span>
            <b class="am">{{ money(x.amount, x.currency) }}</b>
          </RouterLink>
        </div>
        <UiEmpty v-if="!grouped.length" title="Yaqin kunlarda to'lov yo'q" />
      </UiCard>
      <UiCard title="Oylik daromad (MRR)" :subtitle="`12 oy · $ ekvivalenti (1$ = ${B.usd_rate} so'm)`"><AreaChart :points="pts" :height="230" /></UiCard>
    </div>

    <UiCard :padded="false" title="Hisob-fakturalar">
      <template #actions>
        <select v-model="status" aria-label="Holat"><option value="">Hammasi</option><option v-for="x in B.statuses" :key="x.code" :value="x.code">{{ x.label }}</option></select>
      </template>
      <div class="th"><span>Mijoz</span><span>Oy</span><span>Tarif</span><span>Summa</span><span>Muddat</span><span>Holat</span><span></span></div>
      <div v-for="i in B.items" :key="i.id" class="tr">
        <RouterLink :to="`/tenants/${i.tenant_id}?tab=billing`" class="nm">{{ i.tenant }}</RouterLink>
        <span>{{ d(i.period).slice(3) }}</span><span class="mu">{{ i.plan }}<small v-if="i.branches > 1"> · {{ i.branches }} filial</small></span>
        <b>{{ money(i.amount, i.currency) }}</b><span>{{ d(i.due_date) }}</span>
        <span><UiChip :tone="STATUS_TONE[i.status]">{{ i.status_label }}</UiChip><small v-if="i.method" class="mu"> · {{ i.method }}</small></span>
        <span class="ac">
          <template v-if="(i.status === 'pending' || i.status === 'overdue') && s.can('finance')">
            <select v-model="method[i.id]" aria-label="Usul"><option :value="undefined">usul…</option><option v-for="m in METHODS" :key="m[0]" :value="m[0]">{{ m[1] }}</option></select>
            <UiButton size="s" variant="ghost" @click="set(i.id, 'paid')">To'landi</UiButton>
            <UiButton size="s" variant="ghost" @click="set(i.id, 'cancelled')">Bekor</UiButton>
          </template>
        </span>
      </div>
      <UiEmpty v-if="!B.items.length" title="Hisob yo'q" />
    </UiCard>
  </div>
</template>

<style scoped>
.bl { display: flex; flex-direction: column; gap: 14px; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.tiles button { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid #2563EB; border-radius: 14px; padding: 14px; display: flex; flex-direction: column; text-align: left; font: inherit; color: var(--ink); cursor: pointer; min-width: 0; }
.tiles button.on { box-shadow: 0 0 0 2px #2563EB inset; }
.tiles .ok { border-left-color: #16A34A; } .tiles .wr { border-left-color: #F59E0B; } .tiles .dn { border-left-color: #EF4444; }
.tiles span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .tiles b { font-family: var(--font-display); font-size: 22px; overflow-wrap: anywhere; } .tiles small { color: var(--muted); font-size: 11px; min-height: 14px; }
.row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; } .row > :deep(.ui-card) { min-width: 0; }
.grp + .grp { margin-top: 14px; }
.grp h4 { margin: 0 0 6px; font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.grp h4 i { font-style: normal; background: var(--surface-3); border-radius: 99px; padding: 0 7px; }
.grp h4.dn { color: #DC2626; } .grp h4.wr { color: #C2410C; } .grp h4.ai { color: #7C3AED; }
.up { display: grid; grid-template-columns: 76px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 9px 10px; border-radius: 10px; color: var(--ink); text-decoration: none; border-left: 3px solid #2563EB; background: var(--surface-2); margin-bottom: 6px; }
.up:hover { background: #EFF4FF; } .up.dn { border-left-color: #DC2626; background: #FEF2F2; } .up.wr { border-left-color: #F97316; background: #FFF7ED; } .up.ai { border-left-color: #8B5CF6; }
.dt, .who { display: flex; flex-direction: column; min-width: 0; } .dt small, .who small { color: var(--muted); font-size: 11px; } .who b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.am { font-variant-numeric: tabular-nums; white-space: nowrap; }
select { min-height: 34px; border: 1px solid var(--line); border-radius: 8px; padding: 0 8px; font: inherit; font-size: var(--fs-xs); background: var(--surface); color: var(--ink); }
.th, .tr { display: grid; grid-template-columns: minmax(0, 1.6fr) .6fr 1.2fr 1fr .8fr 1.1fr 2.3fr; gap: 10px; align-items: center; padding: 10px 16px; font-size: var(--fs-s); }
.th { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); } .tr { border-top: 1px solid var(--line-2); }
.nm { color: #2563EB; font-weight: 700; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .mu { color: var(--muted); font-size: var(--fs-xs); }
.ac { display: flex; gap: 4px; justify-content: flex-end; flex-wrap: nowrap; align-items: center; }
@media (max-width: 1100px) { .row { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 900px) { .tiles { grid-template-columns: 1fr 1fr; } .th { display: none; } .tr { grid-template-columns: 1fr auto; } .tr > span:nth-child(2), .tr > span:nth-child(3), .tr > span:nth-child(5) { display: none; } .tr .ac { grid-column: 1 / -1; justify-content: flex-start; } }
</style>
