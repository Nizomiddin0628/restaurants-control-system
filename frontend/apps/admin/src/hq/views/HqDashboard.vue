<script setup lang="ts">
/**
 * HQ bosh sahifa: nechta mijoz, filial, xodim; oylik daromad (MRR); platformadan o'tgan savdo;
 * mijozlar holati (sog'lom / e'tibor / kritik); platformada eng ko'p sotilganlar («nechta choy ichildi»).
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiEmpty, UiIcon, toast } from '@restopos/ui'
import AreaChart from '../charts/AreaChart.vue'
import { trimZeros } from '../fmt'
import Donut from '../charts/Donut.vue'
import { ACTION, HEALTH, ago, big, sum } from '../fmt'

const O = ref<any>(null)
const busy = ref(false)
async function load() { O.value = await api.get('/hq/overview') }
onMounted(load)
async function refresh() {
  busy.value = true
  try { await api.post('/hq/stats/refresh'); await load(); toast('Statistika yangilandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
const K = computed(() => O.value?.kpis)
const delta = (cur: number, prev: number) => prev ? Math.round((100 * (cur - prev)) / prev) : null
const tiles = computed(() => !K.value ? [] : [
  { label: 'Mijozlar', value: sum(K.value.clients), note: K.value.clients_new ? `+${K.value.clients_new} shu oy` : 'restoran kompaniyalari', icon: 'users', bg: '#2563EB', to: '/tenants' },
  { label: 'Filiallar', value: sum(K.value.branches), note: 'jami restoran nuqtalari', icon: 'store', bg: '#0EA5E9', to: '/tenants' },
  { label: 'Xodimlar', value: sum(K.value.employees), note: `${sum(K.value.users)} ta foydalanuvchi`, icon: 'users', bg: '#8B5CF6', to: '/tenants' },
  { label: 'Oylik daromad (MRR)', value: `${big(K.value.mrr)}`, note: delta(K.value.mrr, K.value.mrr_prev) != null ? `${delta(K.value.mrr, K.value.mrr_prev)! >= 0 ? '↑' : '↓'} ${Math.abs(delta(K.value.mrr, K.value.mrr_prev)!)}% o'tgan oyga` : 'so\'m / oy', icon: 'receipt', bg: '#16A34A', to: '/billing' },
  { label: 'Platformadagi savdo', value: big(K.value.revenue_30d), note: `30 kun · ${K.value.share_count} ta restoran ulashgan`, icon: 'chart', bg: '#F59E0B', to: '/tenants' },
  { label: 'Buyurtmalar', value: sum(K.value.orders_30d), note: `o'rtacha chek ${big(K.value.avg_check)}`, icon: 'list', bg: '#EF4444', to: '/tenants' },
])
const donut = computed(() => [
  { key: 'healthy', label: 'Sog\'lom', value: O.value?.health.healthy ?? 0, color: '#16A34A' },
  { key: 'warning', label: 'E\'tibor kerak', value: O.value?.health.warning ?? 0, color: '#F59E0B' },
  { key: 'critical', label: 'Kritik', value: O.value?.health.critical ?? 0, color: '#EF4444' },
])
const mrrPts = computed(() => trimZeros((O.value?.mrr ?? []).map((m: any) => ({ label: m.label, value: m.amount }))))
const dayPts = computed(() => (O.value?.daily ?? []).map((m: any) => ({ label: m.date.slice(8, 10) + '.' + m.date.slice(5, 7), value: m.revenue })))
const topMax = computed(() => Math.max(1, ...(O.value?.top_products ?? []).map((p: any) => p.qty)))
</script>

<template>
  <div v-if="O" class="dash">
    <div class="hd">
      <p>Barcha restoranlar bir joyda. Daromad va savdo faqat ma'lumot ulashishga rozi bo'lgan restoranlar bo'yicha ko'rsatiladi.</p>
      <UiButton size="s" variant="ghost" :loading="busy" @click="refresh()"><UiIcon name="repeat" :size="14" /> Yangilash</UiButton>
    </div>

    <section class="kpis">
      <component :is="t.to ? RouterLink : 'div'" v-for="t in tiles" :key="t.label" :to="t.to" class="kpi" :class="{ 'kpi-click': t.to }">
        <span class="ki" :style="{ background: t.bg }"><UiIcon :name="t.icon" :size="18" /></span>
        <span class="kl">{{ t.label }}</span>
        <b class="kv">{{ t.value }}</b>
        <small>{{ t.note }}</small>
      </component>
    </section>

    <div class="row r1">
      <UiCard title="Oylik daromad (MRR)" subtitle="Oxirgi 12 oy · hisob-fakturalar bo'yicha">
        <AreaChart :points="mrrPts" />
      </UiCard>
      <UiCard title="Mijozlar holati" subtitle="Savdo, to'lov va murojaatlar bo'yicha">
        <Donut :items="donut" />
        <ul v-if="O.attention.length" class="att">
          <li v-for="a in O.attention" :key="a.id"><RouterLink :to="`/tenants/${a.id}`"><UiChip :tone="HEALTH[a.level][1] as any">{{ HEALTH[a.level][0] }}</UiChip><b>{{ a.name }}</b><small>{{ a.reasons.join(' · ') }}</small></RouterLink></li>
        </ul>
        <p v-else class="ok">✓ Barcha mijozlar sog'lom</p>
      </UiCard>
    </div>

    <div class="row r2">
      <UiCard title="Platformadagi savdo" subtitle="Oxirgi 30 kun, kunlik (barcha ulashgan restoranlar)">
        <AreaChart :points="dayPts" bars :height="200" />
      </UiCard>
      <UiCard title="Eng ko'p sotilganlar" subtitle="Platforma bo'yicha, 30 kun · porsiya">
        <ol class="top">
          <li v-for="(p, i) in O.top_products" :key="p.name"><span class="n">{{ i + 1 }}</span><span class="tn"><b>{{ p.name }}</b><span class="bar"><i :style="{ width: `${(100 * p.qty) / topMax}%` }"></i></span></span><b class="q">{{ sum(p.qty) }}</b></li>
        </ol>
        <UiEmpty v-if="!O.top_products.length" title="Hali sotuv yo'q" />
      </UiCard>
    </div>

    <div class="row r3">
      <UiCard title="Top mijozlar" subtitle="30 kunlik savdo bo'yicha">
        <ul class="tc">
          <li v-for="(c, i) in O.top_clients" :key="c.id"><RouterLink :to="`/tenants/${c.id}`"><span class="n">{{ i + 1 }}</span><b>{{ c.name }}</b><small>{{ c.branches }} filial</small><span class="v">{{ big(c.revenue) }}</span></RouterLink></li>
        </ul>
      </UiCard>
      <UiCard title="Qisqacha">
        <dl class="mini">
          <dt>CRM dagi mijozlar</dt><dd>{{ sum(K.customers) }}</dd>
          <dt>Ochiq murojaatlar</dt><dd><RouterLink to="/tickets">{{ K.open_tickets }}</RouterLink></dd>
          <dt>30 kunlik savdo o'zgarishi</dt><dd :class="(K.revenue_delta ?? 0) >= 0 ? 'up' : 'dn'">{{ K.revenue_delta == null ? '—' : `${K.revenue_delta > 0 ? '+' : ''}${K.revenue_delta}%` }}</dd>
          <dt>O'rtacha chek</dt><dd>{{ sum(K.avg_check) }} so'm</dd>
        </dl>
      </UiCard>
      <UiCard title="So'nggi faoliyat" subtitle="Jamoa harakatlari">
        <ul class="act"><li v-for="(a, i) in O.activity" :key="i"><b>{{ a.who }}</b> {{ ACTION[a.action] ?? a.action }}<template v-if="a.tenant"> · {{ a.tenant }}</template><small>{{ ago(a.at) }}</small></li></ul>
        <UiEmpty v-if="!O.activity.length" title="Hali faoliyat yo'q" />
      </UiCard>
    </div>
  </div>
</template>

<style scoped>
.dash { display: flex; flex-direction: column; gap: 16px; }
.hd { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; } .hd p { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 14px; display: grid; grid-template-columns: 36px 1fr; grid-template-rows: auto auto auto; gap: 4px 10px; color: var(--ink); text-decoration: none; min-width: 0; }
a.kpi:hover { border-color: #2563EB; }
.ki { grid-row: span 1; width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: #fff; }
.kl { align-self: center; font-size: var(--fs-s); font-weight: 700; color: var(--ink-2); }
.kv { grid-column: 1 / -1; font-family: var(--font-display); font-size: 24px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi small { grid-column: 1 / -1; font-size: var(--fs-xs); color: var(--muted); }
.row { display: grid; gap: 16px; } .row > :deep(.ui-card) { min-width: 0; }
.r1 { grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); } .r2 { grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); } .r3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.att { list-style: none; margin: 14px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.att a { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; align-items: center; color: var(--ink); text-decoration: none; padding: 8px; border-radius: 10px; background: var(--surface-2); }
.att small { grid-column: 1 / -1; color: var(--muted); font-size: var(--fs-xs); }
.ok { color: var(--ok); font-weight: 700; margin: 12px 0 0; }
.top { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.top li { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.n { color: var(--muted); font-weight: 800; font-size: var(--fs-s); } .tn { display: flex; flex-direction: column; gap: 4px; min-width: 0; } .tn b { font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 6px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: #2563EB; border-radius: 99px; }
.q { font-variant-numeric: tabular-nums; }
.tc { list-style: none; margin: 0; padding: 0; } .tc a { display: grid; grid-template-columns: 20px 1fr auto; grid-template-rows: auto auto; gap: 0 10px; padding: 8px 0; border-bottom: 1px solid var(--line-2); color: var(--ink); text-decoration: none; }
.tc small { grid-column: 2; color: var(--muted); font-size: var(--fs-xs); } .tc .v { grid-row: 1 / 3; grid-column: 3; align-self: center; font-weight: 800; }
.mini { display: grid; grid-template-columns: 1fr auto; gap: 10px; margin: 0; font-size: var(--fs-s); } .mini dt { color: var(--muted); } .mini dd { margin: 0; font-weight: 800; text-align: right; } .mini a { color: #2563EB; }
.up { color: var(--ok); } .dn { color: var(--danger); }
.act { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-s); } .act li { display: flex; flex-wrap: wrap; gap: 4px; } .act small { color: var(--muted); width: 100%; font-size: 11px; }
@media (max-width: 1400px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1100px) { .r1, .r2 { grid-template-columns: minmax(0, 1fr); } .r3 { grid-template-columns: 1fr 1fr; } .r3 > :first-child { grid-column: 1 / -1; } }
@media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } .kv { font-size: 20px; } .r3 { grid-template-columns: minmax(0, 1fr); } .r3 > :first-child { grid-column: auto; } }
</style>
