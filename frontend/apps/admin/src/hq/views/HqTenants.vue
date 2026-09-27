<script setup lang="ts">
/** Mijozlar (restoran kompaniyalari): qidiruv, holat/tarif filtri, filial/xodim/savdo, sog'lomlik. Bosilsa — mijoz kartasi. */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiCard, UiChip, UiEmpty, UiIcon } from '@restopos/ui'
import { HEALTH, STATUS_TONE, big, d, sum } from '../fmt'

const route = useRoute(), router = useRouter()
const R = ref<any>(null)
const q = ref(String(route.query.q ?? ''))
const status = ref(''), health = ref(''), plan = ref('')
const sort = ref<'revenue' | 'branches' | 'employees' | 'name'>('revenue')
async function load() {
  R.value = await api.get('/hq/tenants', { q: q.value || undefined, status: status.value || undefined, health: health.value || undefined, plan: plan.value || undefined })
}
onMounted(load)
let t: number | undefined
watch(q, () => { clearTimeout(t); t = window.setTimeout(load, 250) })
watch([status, health, plan], load)
watch(() => route.query.q, (v) => { if (v !== undefined) q.value = String(v) })
const rows = computed(() => [...(R.value?.items ?? [])].sort((a: any, b: any) => sort.value === 'name' ? a.name.localeCompare(b.name) : (b[sort.value === 'revenue' ? 'revenue_30d' : sort.value] ?? -1) - (a[sort.value === 'revenue' ? 'revenue_30d' : sort.value] ?? -1)))
const totals = computed(() => ({ n: rows.value.length, br: rows.value.reduce((s: number, r: any) => s + r.branches, 0), emp: rows.value.reduce((s: number, r: any) => s + r.employees, 0) }))
</script>

<template>
  <div v-if="R" class="tn">
    <div class="flt">
      <label class="sr"><UiIcon name="search" :size="16" /><input v-model="q" placeholder="Nomi, manzil yoki egasi telefoni…" /></label>
      <select v-model="status" aria-label="Holat"><option value="">Barcha holatlar</option><option value="active">Faol</option><option value="trial">Sinov</option><option value="stopped">To'xtatilgan</option></select>
      <select v-model="health" aria-label="Sog'lomlik"><option value="">Barcha sog'lomlik</option><option value="healthy">Sog'lom</option><option value="warning">E'tibor kerak</option><option value="critical">Kritik</option></select>
      <select v-model="plan" aria-label="Tarif"><option value="">Barcha tariflar</option><option v-for="p in R.plans" :key="p.code" :value="p.code">{{ p.name }}</option></select>
      <select v-model="sort" aria-label="Saralash"><option value="revenue">Savdo bo'yicha</option><option value="branches">Filiallar bo'yicha</option><option value="employees">Xodimlar bo'yicha</option><option value="name">Nomi bo'yicha</option></select>
    </div>
    <p class="sum">{{ totals.n }} ta mijoz · {{ totals.br }} filial · {{ totals.emp }} xodim</p>

    <UiCard :padded="false">
      <div class="th"><span>Mijoz</span><span>Filial</span><span>Xodim</span><span>Savdo (30 kun)</span><span>Tarif</span><span>Holat</span><span>Sog'lomlik</span></div>
      <button v-for="r in rows" :key="r.id" type="button" class="tr" @click="router.push(`/tenants/${r.id}`)">
        <span class="nm"><UiAvatar :name="r.name" :size="36" /><span><b>{{ r.name }}</b><small>{{ r.domain }}</small></span></span>
        <span class="c"><em>Filial</em>{{ r.branches }}</span>
        <span class="c"><em>Xodim</em>{{ r.employees }}</span>
        <span class="c rv"><em>Savdo</em><template v-if="r.shares_finance"><b>{{ big(r.revenue_30d) }}</b><small v-if="r.trend != null" :class="r.trend >= 0 ? 'up' : 'dn'">{{ r.trend >= 0 ? '↑' : '↓' }} {{ Math.abs(r.trend) }}%</small></template><small v-else class="lock">🔒 yashirin</small></span>
        <span class="c"><em>Tarif</em>{{ r.plan }}</span>
        <span class="c"><UiChip :tone="STATUS_TONE[r.status]">{{ r.status_label }}</UiChip><small v-if="r.status === 'trial' && r.trial_ends_at">{{ d(r.trial_ends_at) }} gacha</small></span>
        <span class="c hl" :title="r.reasons.join(' · ')"><i :class="r.health"></i>{{ HEALTH[r.health][0] }}<small v-if="r.reasons.length">{{ r.reasons[0] }}</small></span>
      </button>
      <UiEmpty v-if="!rows.length" title="Mijoz topilmadi" text="Qidiruv yoki filtrni o'zgartiring." />
    </UiCard>
    <p class="note">Jami {{ sum(R.items.length) }} ta. Mijoz o'zi ro'yxatdan o'tadi (platforma sayti) yoki sotuv jamoasi yaratadi.</p>
  </div>
</template>

<style scoped>
.tn { display: flex; flex-direction: column; gap: 12px; }
.flt { display: flex; gap: 8px; flex-wrap: wrap; }
.sr { flex: 1 1 280px; display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; min-height: 42px; background: var(--surface); color: var(--muted); }
.sr input { border: 0; outline: none; font: inherit; flex: 1; background: transparent; color: var(--ink); min-width: 0; }
select { min-height: 42px; border: 1px solid var(--line); border-radius: 10px; padding: 0 10px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.sum, .note { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.th, .tr { display: grid; grid-template-columns: minmax(0, 2.2fr) .6fr .6fr 1.1fr .8fr 1fr 1.3fr; gap: 10px; align-items: center; padding: 10px 16px; }
.th { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.tr { width: 100%; border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; text-align: left; cursor: pointer; color: var(--ink); min-height: 64px; }
.tr:hover { background: #EFF4FF; }
.nm { display: flex; align-items: center; gap: 10px; min-width: 0; } .nm span { display: flex; flex-direction: column; min-width: 0; } .nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { color: var(--muted); font-size: var(--fs-xs); }
.c { display: flex; flex-direction: column; align-items: flex-start; font-size: var(--fs-s); font-variant-numeric: tabular-nums; } .c em { display: none; } .c small { font-size: 11px; color: var(--muted); }
.up { color: var(--ok) !important; } .dn { color: var(--danger) !important; } .lock { color: var(--muted); }
.hl { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 2px 6px; } .hl small { width: 100%; }
.hl i { width: 9px; height: 9px; border-radius: 50%; } .hl i.healthy { background: #16A34A; } .hl i.warning { background: #F59E0B; } .hl i.critical { background: #EF4444; }
@media (max-width: 900px) {
  .th { display: none; }
  .tr { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 12px 14px; }
  .tr > .nm { grid-column: 1 / -1; }
  .c em { display: block; font-style: normal; font-size: 11px; color: var(--muted); }
}
</style>
