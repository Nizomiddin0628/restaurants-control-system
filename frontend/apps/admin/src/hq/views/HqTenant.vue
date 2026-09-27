<script setup lang="ts">
/**
 * Mijoz kartasi: umumiy ko'rsatkichlar, har filial (savdo, chek, food cost, xodim), billing, murojaatlar,
 * kirish (faqat egasi ruxsati bilan), modullar, faoliyat. Daromad — faqat mijoz ulashishga rozi bo'lsa.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiEmpty, UiIcon, UiToggle, toast } from '@restopos/ui'
import AreaChart from '../charts/AreaChart.vue'
import { useHq } from '../store'
import { ACTION, HEALTH, STATUS_TONE, ago, big, d, dt, sum } from '../fmt'

const route = useRoute(), s = useHq()
const T = ref<any>(null)
const tab = ref<'overview' | 'branches' | 'billing' | 'tickets' | 'access' | 'modules' | 'activity'>('overview')
const reason = ref('')
const busy = ref(false)
const plans = ref<any[]>([])
async function load() { T.value = await api.get(`/hq/tenants/${route.params.id}`); syncAi() }
onMounted(async () => { await load(); plans.value = (await api.get('/hq/tenants')).plans })

const pts = computed(() => (T.value?.series ?? []).map((p: any) => ({ label: p.date.slice(8, 10) + '.' + p.date.slice(5, 7), value: p.revenue })))
const total30 = computed(() => T.value?.revenue_30d)
const avg = computed(() => T.value?.orders_30d ? Math.round(T.value.revenue_30d / T.value.orders_30d) : null)
const maxBr = computed(() => Math.max(1, ...(T.value?.branches_list ?? []).map((b: any) => b.revenue_30d ?? 0)))

async function act(fn: () => Promise<any>, ok: string) {
  busy.value = true
  try { await fn(); toast(ok); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
const requestAccess = () => act(() => api.post(`/hq/tenants/${T.value.id}/access-request`, { reason: reason.value }), 'So\'rov yuborildi — egasi panelida ko\'radi')
async function enter() {
  if (!reason.value.trim() && !s.direct) { toast('Kirish sababini yozing (masalan: murojaat #10482)', 'danger'); return }
  busy.value = true
  try { const r = await api.post(`/hq/tenants/${T.value.id}/impersonate`, { reason: reason.value }); window.open(r.url, '_blank'); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
const setPlan = (code: string) => act(() => api.post(`/hq/tenants/${T.value.id}/plan`, { plan_code: code }), 'Tarif o\'zgardi')
const trial = (days: number) => act(() => api.post(`/hq/tenants/${T.value.id}/trial`, { days }), `Sinov ${days} kunga uzaytirildi`)
function toggleActive() {
  const on = !(T.value.status !== 'stopped')
  if (!on && !confirm(`«${T.value.name}» to'xtatilsinmi? Ular panelga kira olmaydi.`)) return
  act(() => api.post(`/hq/tenants/${T.value.id}/status`, { is_active: on }), on ? 'Faollashtirildi' : 'To\'xtatildi')
}
function toggleModule(code: string, on: boolean) {
  const codes = T.value.modules.filter((m: any) => (m.code === code ? on : m.enabled)).map((m: any) => m.code)
  act(() => api.put(`/hq/tenants/${T.value.id}/modules`, { codes }), 'Modullar yangilandi')
}
// AI Kotib tarifi: yoqilgan, kunlik so'rov, nechta xodim (0 — cheklovsiz)
const ai = ref({ enabled: true, daily_limit: 0, seats: 0 })
const aiOpen = computed(() => !!T.value?.ai)
function syncAi() { if (T.value?.ai) ai.value = { enabled: T.value.ai.enabled, daily_limit: T.value.ai.daily_limit, seats: T.value.ai.seats } }
const saveAi = () => act(() => api.put(`/hq/tenants/${T.value.id}/ai`, { enabled: ai.value.enabled, daily_limit: Number(ai.value.daily_limit) || 0, seats: Number(ai.value.seats) || 0 }), 'AI Kotib tarifi saqlandi')
const invStatus = (id: number, status: string) => act(() => api.post(`/hq/invoices/${id}/status`, { status }), 'Hisob yangilandi')
</script>

<template>
  <div v-if="T" class="tt">
    <RouterLink to="/tenants" class="back">← Mijozlar</RouterLink>
    <header class="hd">
      <UiAvatar :name="T.name" :size="56" />
      <div class="ht">
        <h2>{{ T.name }} <UiChip :tone="STATUS_TONE[T.status]">{{ T.status_label }}</UiChip> <span class="hl" :class="T.health"><i></i>{{ HEALTH[T.health][0] }}</span></h2>
        <p>{{ T.domain }} · {{ T.plan }} · egasi {{ T.owner_phone }} · {{ d(T.created_at) }} dan beri</p>
      </div>
      <div class="ha">
        <a :href="T.site_url" target="_blank" rel="noopener" class="btn">Sayt ↗</a>
        <UiButton variant="brand" size="s" @click="tab = 'access'"><UiIcon name="logout" :size="14" style="transform: scaleX(-1)" /> Panelga kirish</UiButton>
      </div>
    </header>
    <div v-if="T.reasons.length" class="why"><b>Nimaga e'tibor:</b> {{ T.reasons.join(' · ') }}</div>

    <nav class="tabs" role="tablist">
      <button :class="{ on: tab === 'overview' }" @click="tab = 'overview'">Umumiy</button>
      <button :class="{ on: tab === 'branches' }" @click="tab = 'branches'">Filiallar <i>{{ T.branches_list.length }}</i></button>
      <button :class="{ on: tab === 'billing' }" @click="tab = 'billing'">Billing</button>
      <button :class="{ on: tab === 'tickets' }" @click="tab = 'tickets'">Murojaatlar <i v-if="T.open_tickets">{{ T.open_tickets }}</i></button>
      <button :class="{ on: tab === 'access' }" @click="tab = 'access'">Kirish</button>
      <button :class="{ on: tab === 'modules' }" @click="tab = 'modules'">Modullar</button>
      <button :class="{ on: tab === 'activity' }" @click="tab = 'activity'">Faoliyat</button>
    </nav>

    <!-- UMUMIY -->
    <template v-if="tab === 'overview'">
      <section class="tiles">
        <div><b>{{ T.branches }}</b><span>filial</span></div>
        <div><b>{{ T.employees }}</b><span>xodim</span></div>
        <div><b>{{ T.users }}</b><span>foydalanuvchi</span></div>
        <div><b>{{ sum(T.customers) }}</b><span>mijoz (CRM)</span></div>
        <div><b>{{ T.shares_finance ? big(total30) : '🔒' }}</b><span>savdo, 30 kun</span></div>
        <div><b>{{ T.shares_finance ? sum(T.orders_30d) : '🔒' }}</b><span>buyurtma</span></div>
        <div><b>{{ T.shares_finance ? big(avg) : '🔒' }}</b><span>o'rtacha chek</span></div>
        <div><b>{{ T.last_order ? d(T.last_order) : '—' }}</b><span>oxirgi savdo kuni</span></div>
      </section>
      <UiCard title="Kunlik savdo" subtitle="Oxirgi 30 kun">
        <AreaChart v-if="T.shares_finance && pts.length" :points="pts" :height="200" />
        <UiEmpty v-else-if="!T.shares_finance" title="Mijoz daromad ma'lumotini ulashmagan" text="Restoran egasi panelning «Yordam» bo'limida ulashishni yoqishi mumkin." />
        <UiEmpty v-else title="Savdo yo'q" />
      </UiCard>
      <UiCard title="Rozilik">
        <p class="cs">Daromad statistikasi: <b>{{ T.consent.share_finance ? 'ulashadi' : 'ulashmaydi' }}</b> · «Mijozlarimiz» ro'yxatida ko'rsatish: <b>{{ T.consent.showcase ? 'roziman' : 'rozilik yo\'q' }}</b></p>
      </UiCard>
    </template>

    <!-- FILIALLAR -->
    <UiCard v-else-if="tab === 'branches'" :padded="false">
      <div class="bh"><span>Filial</span><span>Xodim</span><span>Savdo (30 kun)</span><span>Buyurtma</span><span>O'rtacha chek</span><span>Food cost</span><span>Oxirgi savdo</span></div>
      <div v-for="b in T.branches_list" :key="b.id" class="br">
        <span class="bn"><b>🏪 {{ b.name }}</b><small>{{ b.address || '—' }}</small></span>
        <span><em>Xodim</em>{{ b.employees }}</span>
        <span class="rv"><em>Savdo</em><template v-if="b.revenue_30d != null"><b>{{ big(b.revenue_30d) }}</b><span class="bar"><i :style="{ width: `${(100 * b.revenue_30d) / maxBr}%` }"></i></span></template><template v-else>🔒</template></span>
        <span><em>Buyurtma</em>{{ sum(b.orders_30d) }}</span>
        <span><em>Chek</em>{{ b.avg_check != null ? big(b.avg_check) : '🔒' }}</span>
        <span><em>Food cost</em><b v-if="b.food_cost != null" :class="b.food_cost > 38 ? 'dn' : b.food_cost > 35 ? 'wr' : 'up'">{{ b.food_cost }}%</b><template v-else>—</template></span>
        <span><em>Oxirgi</em>{{ b.last_order ? ago(b.last_order) : '—' }}</span>
      </div>
      <UiEmpty v-if="!T.branches_list.length" title="Filial yo'q" />
    </UiCard>

    <!-- BILLING -->
    <div v-else-if="tab === 'billing'" class="grid2">
      <UiCard title="Tarif va holat">
        <div class="pl"><button v-for="p in plans" :key="p.code" type="button" :class="{ on: T.plan_code === p.code }" :disabled="busy || !s.can('sales', 'finance')" @click="setPlan(p.code)"><b>{{ p.name }}</b><small>{{ sum(p.price_per_branch) }} so'm / filial</small></button></div>
        <p class="mut">Oylik to'lov: {{ T.branches }} filial × tarif narxi.</p>
        <div class="acts">
          <UiButton v-if="T.status === 'trial' || s.can('sales')" size="s" variant="ghost" :disabled="busy" @click="trial(7)">Sinovni +7 kun</UiButton>
          <UiButton v-if="s.can('sales')" size="s" variant="ghost" :disabled="busy" @click="trial(30)">Sinovni +30 kun</UiButton>
          <UiButton v-if="s.can('finance')" size="s" :variant="T.status === 'stopped' ? 'brand' : 'danger'" :disabled="busy" @click="toggleActive()">{{ T.status === 'stopped' ? 'Faollashtirish' : 'To\'xtatish' }}</UiButton>
        </div>
      </UiCard>
      <UiCard title="Hisob-fakturalar" :padded="false">
        <div v-for="i in T.invoices" :key="i.id" class="inv">
          <span><b>{{ d(i.period).slice(3) }}</b><small>{{ i.plan }} · {{ i.branches }} filial</small></span>
          <b>{{ sum(i.amount) }}</b>
          <UiChip :tone="STATUS_TONE[i.status]">{{ i.status_label }}</UiChip>
          <UiButton v-if="i.status !== 'paid' && s.can('finance')" size="s" variant="ghost" @click="invStatus(i.id, 'paid')">To'landi</UiButton>
        </div>
        <UiEmpty v-if="!T.invoices.length" title="Hisob yo'q" text="Sinov muddatida hisob chiqmaydi." />
      </UiCard>
    </div>

    <!-- MUROJAATLAR -->
    <UiCard v-else-if="tab === 'tickets'" :padded="false">
      <RouterLink v-for="k in T.tickets" :key="k.id" :to="`/tickets?open=${k.id}`" class="tk">
        <span><b>#{{ k.number }} {{ k.subject }}</b><small>{{ k.branch }} · {{ k.author }} · {{ dt(k.created_at) }}</small></span>
        <UiChip :tone="STATUS_TONE[k.priority]">{{ k.priority_label }}</UiChip>
        <UiChip :tone="STATUS_TONE[k.status]">{{ k.status_label }}</UiChip>
      </RouterLink>
      <UiEmpty v-if="!T.tickets.length" title="Murojaat yo'q" />
    </UiCard>

    <!-- KIRISH -->
    <div v-else-if="tab === 'access'" class="grid2">
      <UiCard title="Restoran paneliga kirish" :subtitle="T.direct_entry ? 'Siz platforma rahbarisiz — to\'g\'ridan-to\'g\'ri kirasiz. Har kirish egasiga ko\'rinadi.' : 'Faqat egasi vaqtincha ruxsat berganda. Har kirish egasiga ko\'rinadi.'">
        <div v-if="T.direct_entry" class="acc ok">👑 To'g'ridan-to'g'ri kirish (8 soat). Sabab ixtiyoriy.</div>
        <div v-else-if="T.access" class="acc ok">✅ Ruxsat bor — <b>{{ dt(T.access.until) }}</b> gacha ({{ T.access.granted_by }})</div>
        <div v-else class="acc">🔒 Ruxsat yo'q. Egasidan so'rang — unga panelda va Telegram'da xabar boradi.</div>
        <div v-if="T.access_request && !T.access" class="acc wait">⏳ So'rov yuborilgan: {{ T.access_request.by }} · {{ ago(T.access_request.at) }}</div>
        <label class="fl"><span>{{ T.direct_entry ? 'Sabab (ixtiyoriy)' : 'Sabab (majburiy)' }}</span><input v-model="reason" placeholder="Masalan: murojaat #10482 — checklist ishlamayapti" /></label>
        <div class="acts">
          <UiButton v-if="T.access || T.direct_entry" variant="brand" :loading="busy" @click="enter()">Panelni ochish ↗</UiButton>
          <UiButton v-else variant="brand" :loading="busy" @click="requestAccess()">Ruxsat so'rash</UiButton>
        </div>
      </UiCard>
      <UiCard title="Kirishlar tarixi">
        <ul class="ss"><li v-for="(x, i) in T.sessions" :key="i"><b>{{ x.staff }}</b><span>{{ x.reason }}</span><small>{{ dt(x.at) }}</small></li></ul>
        <UiEmpty v-if="!T.sessions.length" title="Hali kirilmagan" />
      </UiCard>
    </div>

    <!-- MODULLAR -->
    <div v-else-if="tab === 'modules'" class="mstack">
    <UiCard v-if="aiOpen" title="🤖 AI Kotib — tarif chegarasi" subtitle="Restoran Superadmini shu chegara ichida xodimlariga taqsimlaydi. 0 — cheklovsiz.">
      <div class="aic">
        <UiToggle v-model="ai.enabled" label="AI Kotib yoqilgan" :disabled="!s.can('sales')" />
        <label class="fl"><span>Kuniga nechta so'rov</span><input v-model.number="ai.daily_limit" type="number" min="0" :disabled="!s.can('sales')" /></label>
        <label class="fl"><span>Nechta xodim foydalanadi</span><input v-model.number="ai.seats" type="number" min="0" :disabled="!s.can('sales')" /></label>
        <UiButton variant="brand" :loading="busy" :disabled="!s.can('sales')" @click="saveAi()">Saqlash</UiButton>
      </div>
      <p class="aiu">Hozir: <b>{{ T.ai.used }}</b> xodimda bor · bugun <b>{{ T.ai.today }}</b> ta so'rov{{ T.ai.module_enabled ? '' : ' · modul o\'chiq' }}</p>
    </UiCard>
    <UiCard title="Yoqilgan modullar" subtitle="Tarif ruxsat bermagan modul yoqilmaydi">
      <div class="mods"><div v-for="m in T.modules" :key="m.code" class="mod" :class="{ off: !m.allowed }"><UiToggle :model-value="m.enabled" :disabled="!m.allowed || busy || !s.can('support', 'sales')" :label="m.name" @update:model-value="(v: boolean) => toggleModule(m.code, v)" /></div></div>
    </UiCard>
    </div>

    <!-- FAOLIYAT -->
    <UiCard v-else title="Jamoa harakatlari (shu mijoz)">
      <ul class="ss"><li v-for="(a, i) in T.activity" :key="i"><b>{{ a.who }}</b><span>{{ ACTION[a.action] ?? a.action }}</span><small>{{ dt(a.at) }}</small></li></ul>
      <UiEmpty v-if="!T.activity.length" title="Hali harakat yo'q" />
    </UiCard>
  </div>
</template>

<style scoped>
.tt { display: flex; flex-direction: column; gap: 14px; }
.back { color: #2563EB; text-decoration: none; font-weight: 700; font-size: var(--fs-s); }
.hd { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 16px; }
.ht { flex: 1; min-width: 220px; } .ht h2 { margin: 0; font-family: var(--font-display); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .ht p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); }
.ha { display: flex; gap: 8px; }
.btn { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; border: 1px solid var(--line); border-radius: 10px; color: var(--ink); text-decoration: none; font-weight: 700; font-size: var(--fs-s); }
.hl { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-s); font-weight: 700; } .hl i { width: 10px; height: 10px; border-radius: 50%; }
.hl.healthy { color: #16A34A; } .hl.healthy i { background: #16A34A; } .hl.warning { color: #B45309; } .hl.warning i { background: #F59E0B; } .hl.critical { color: #DC2626; } .hl.critical i { background: #EF4444; }
.why { padding: 10px 14px; border-radius: 12px; background: var(--warn-tint); font-size: var(--fs-s); }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: #2563EB; border-bottom-color: #2563EB; } .tabs i { font-style: normal; font-size: 11px; background: var(--surface-3); border-radius: 99px; padding: 1px 7px; margin-left: 4px; }
.tiles { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 10px; }
.tiles div { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 12px; display: flex; flex-direction: column; }
.tiles b { font-family: var(--font-display); font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .tiles span { font-size: var(--fs-xs); color: var(--muted); }
.cs { margin: 0; font-size: var(--fs-s); }
.bh, .br { display: grid; grid-template-columns: minmax(0, 2fr) .6fr 1.4fr .8fr .9fr .8fr 1fr; gap: 10px; align-items: center; padding: 10px 16px; }
.bh { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.br { border-top: 1px solid var(--line-2); font-size: var(--fs-s); } .br em { display: none; font-style: normal; font-size: 11px; color: var(--muted); }
.bn { display: flex; flex-direction: column; min-width: 0; } .bn small { color: var(--muted); font-size: var(--fs-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rv { display: flex; flex-direction: column; gap: 4px; } .bar { height: 6px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: #2563EB; }
.up { color: var(--ok); } .wr { color: var(--warn-ink); } .dn { color: var(--danger); }
.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; } .grid2 > :deep(.ui-card) { min-width: 0; }
.pl { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }
.pl button { border: 1px solid var(--line); border-radius: 12px; background: var(--surface); padding: 12px; display: flex; flex-direction: column; gap: 2px; cursor: pointer; font: inherit; text-align: left; color: var(--ink); }
.pl button.on { border-color: #2563EB; background: #EFF4FF; } .pl small { color: var(--muted); font-size: var(--fs-xs); }
.mut { color: var(--muted); font-size: var(--fs-s); } .acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.inv { display: grid; grid-template-columns: 1fr auto auto auto; gap: 10px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.inv span { display: flex; flex-direction: column; } .inv small { color: var(--muted); font-size: var(--fs-xs); }
.tk { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; padding: 12px 16px; border-top: 1px solid var(--line-2); color: var(--ink); text-decoration: none; }
.tk span { display: flex; flex-direction: column; min-width: 0; } .tk small { color: var(--muted); font-size: var(--fs-xs); }
.acc { padding: 10px 12px; border-radius: 10px; background: var(--surface-2); font-size: var(--fs-s); margin-bottom: 10px; } .acc.ok { background: var(--ok-tint); } .acc.wait { background: var(--warn-tint); }
.fl { display: flex; flex-direction: column; gap: 6px; } .fl span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fl input { min-height: 42px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); }
.ss { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; } .ss li { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .ss small { color: var(--muted); }
.mods { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; } .mod { padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px; } .mod.off { opacity: .5; }
@media (max-width: 1400px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 900px) {
  .grid2 { grid-template-columns: minmax(0, 1fr); }
  .bh { display: none; } .br { grid-template-columns: repeat(3, minmax(0, 1fr)); } .br > .bn { grid-column: 1 / -1; } .br em { display: block; }
  .ss li { grid-template-columns: 1fr auto; } .ss li span { grid-column: 1 / -1; order: 3; color: var(--ink-2); }
}
@media (max-width: 560px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } .ha { width: 100%; } .inv { grid-template-columns: 1fr auto; } }
.mstack { display: flex; flex-direction: column; gap: 14px; }
.aic { display: grid; grid-template-columns: auto 1fr 1fr auto; gap: 12px; align-items: end; }
.aiu { margin: 10px 0 0; font-size: var(--fs-s); color: var(--muted); }
@media (max-width: 800px) { .aic { grid-template-columns: 1fr; } }
</style>
