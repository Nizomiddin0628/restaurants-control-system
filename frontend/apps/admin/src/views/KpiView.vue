<script setup lang="ts">
/**
 * Baholash va KPI: oylik reyting (tizim ma'lumotidan avtomatik + menejer bahosi), A/B/C/D daraja,
 * «xavf» (kayfiyat past / davomat past), tavsiya bonus → qoralama oylikka bir tugma bilan yozish.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiInput, UiKpi, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter()
const now = new Date()
const ym = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
const month = ref(ym(now)), branch = ref<string>('')
const D = ref<any>(null), branches = ref<any[]>([]), loading = ref(false)
const MONTHS = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentyabr', 'Oktyabr', 'Noyabr', 'Dekabr']
const monthOpts = Array.from({ length: 6 }, (_, i) => { const d = new Date(now.getFullYear(), now.getMonth() - i, 1); return { value: ym(d), label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` } })
const GT: Record<string, any> = { A: 'ok', B: 'info', C: 'warn', D: 'danger', '—': 'neutral' }
const PARTS = ['attendance', 'punctuality', 'training', 'tasks', 'role', 'review']
const SHORT: Record<string, string> = { attendance: 'Davomat', punctuality: 'Vaqtida', training: 'O\'qitish', tasks: 'Vazifa', role: 'Natija', review: 'Baho' }
const short = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 2).replace('.', ',')} mln` : n >= 1e3 ? `${Math.round(n / 1e3)} ming` : String(n))
const MOOD = (m: number | null) => (m == null ? '—' : m >= 3.5 ? '😀' : m >= 2.75 ? '🙂' : m >= 2 ? '😐' : '🙁')

async function load() {
  loading.value = true
  try { D.value = await api.get(`/hr/kpi?month=${month.value}${branch.value ? `&branch_id=${branch.value}` : ''}`) } finally { loading.value = false }
}
onMounted(async () => { load(); branches.value = (await api.get('/hr/meta').catch(() => ({ branches: [] }))).branches })
watch([month, branch], load)

const allRows = computed(() => D.value?.rows ?? [])
/** KPI kartasi bosilsa — reyting jadvali shu bo'yicha filtrlanadi */
type KF = '' | 'A' | 'D' | 'risk' | 'noreview' | 'bonus'
const kf = ref<KF>('')
const tblEl = ref<any>(null)
const KFL: Record<string, string> = { A: 'A daraja', D: 'D daraja', risk: 'xavf ostida', noreview: 'baholanmagan', bonus: 'bonus tavsiya etilgan' }
function kpiGo(k: KF) { kf.value = kf.value === k ? '' : k; requestAnimationFrame(() => (tblEl.value?.$el ?? tblEl.value)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })) }
const rows = computed(() => allRows.value.filter((r: any) => !kf.value || (kf.value === 'A' || kf.value === 'D' ? r.grade === kf.value
  : kf.value === 'risk' ? r.risk : kf.value === 'noreview' ? !r.reviewed : r.bonus_suggest > 0)))
const top3 = computed(() => allRows.value.filter((r: any) => r.score != null).slice(0, 3))
const tone = (v: number) => (v >= 85 ? 'a' : v >= 70 ? 'b' : v >= 50 ? 'c' : 'd')
const brOpts = computed(() => [{ value: '', label: 'Barcha filiallar' }, ...branches.value.map((b: any) => ({ value: String(b.id), label: b.name }))])
const isCurrent = computed(() => month.value === ym(now))

// baholash
const rv = ref<any>(null)
function review(r: any) { rv.value = { row: r, month: D.value.month, scores: Object.fromEntries(D.value.criteria.map((c: any) => [c.key, 0])), strengths: '', improve: '', goals: '' } }
async function saveReview() {
  const { row, ...b } = rv.value
  try { await api.post(`/hr/employees/${row.employee_id}/reviews`, b); rv.value = null; toast('Baho saqlandi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const pick = ref<Set<number>>(new Set())
const bonusRows = computed(() => allRows.value.filter((r: any) => r.bonus_suggest > 0))
function toggleAll() { pick.value = pick.value.size === bonusRows.value.length ? new Set() : new Set(bonusRows.value.map((r: any) => r.employee_id)) }
async function applyBonus() {
  const ids = [...pick.value]
  if (!ids.length) return toast('Xodimlarni belgilang', 'danger')
  if (!confirm(`${ids.length} xodimga KPI bonusi qoralama oylikka yozilsinmi?`)) return
  try { const r = await api.post('/hr/kpi/apply-bonus', { month: D.value.month, employee_ids: ids }); toast(r.updated ? `${r.updated} ta oylikka yozildi` : 'Qoralama oylik topilmadi — avval «Oylik»da hisoblang', r.updated ? 'ok' : 'danger'); pick.value = new Set() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div class="kp">
    <header class="top">
      <div><h1>Baholash va KPI</h1><p>Ball tizimdagi haqiqiy ma'lumotdan: davomat, kechikish, o'qitish, vazifalar, ish natijasi + menejer bahosi</p></div>
      <div class="flt"><UiSelect v-model="month" :options="monthOpts" /><UiSelect v-model="branch" :options="brOpts" /></div>
    </header>

    <template v-if="D">
      <div class="kpis">
        <UiKpi label="O'rtacha ball" :value="D.summary.avg ?? '—'" clickable :on="!kf" @click="kpiGo('')" />
        <UiKpi label="A daraja" :value="D.summary.grades.A" tone="ok" clickable :on="kf === 'A'" @click="kpiGo('A')" />
        <UiKpi label="D daraja" :value="D.summary.grades.D" :tone="D.summary.grades.D ? 'danger' : 'muted'" clickable :on="kf === 'D'" @click="kpiGo('D')" />
        <UiKpi label="Xavf ostida" :value="D.summary.risk" :tone="D.summary.risk ? 'warn' : 'muted'" note="kayfiyat yoki davomat past" clickable :on="kf === 'risk'" @click="kpiGo('risk')" />
        <UiKpi label="Baholangan" :value="`${D.summary.reviewed}/${D.summary.total}`" note="bosing — baholanmaganlar" clickable :on="kf === 'noreview'" @click="kpiGo('noreview')" />
        <UiKpi label="Tavsiya bonus" :value="short(D.summary.bonus_total)" note="A — 10%, B — 5%" clickable :on="kf === 'bonus'" @click="kpiGo('bonus')" />
      </div>

      <div v-if="top3.length" class="podium">
        <button v-for="(r, i) in top3" :key="r.employee_id" type="button" class="pd" :class="`p${i + 1}`" @click="router.push(`/hr/employee/${r.employee_id}?tab=kpi`)">
          <span class="medal">{{ ['🥇', '🥈', '🥉'][i] }}</span>
          <UiAvatar :name="r.full_name" :src="r.avatar" :size="52" />
          <b>{{ r.full_name }}</b><small>{{ r.position || '—' }}</small>
          <span class="sc">{{ r.score }}</span>
        </button>
      </div>

      <UiCard ref="tblEl" title="Reyting" :subtitle="`Og'irliklar: ${D.weights.map((w: any) => `${w.label} ${w.weight}`).join(' · ')}. Ma'lumot yo'q ko'rsatkich hisobga olinmaydi.`" :padded="false">
        <template #actions>
          <UiButton v-if="a.can('hr.payroll') && bonusRows.length" size="s" variant="secondary" @click="toggleAll">{{ pick.size === bonusRows.length ? 'Belgini olish' : 'Bonuslilarni belgilash' }}</UiButton>
          <UiButton v-if="a.can('hr.payroll') && bonusRows.length" size="s" variant="brand" :disabled="!pick.size" @click="applyBonus">Bonusni oylikka yozish ({{ pick.size }})</UiButton>
        </template>
        <div class="tw">
          <table>
            <thead><tr><th></th><th>#</th><th>Xodim</th><th class="c">Ball</th><th v-for="p in PARTS" :key="p" class="c">{{ SHORT[p] }}</th><th class="c">Kayfiyat</th><th class="r">Bonus</th><th></th></tr></thead>
            <tbody>
              <tr v-if="kf"><td colspan="20" class="kf-row">Filtr: <b>{{ KFL[kf] }}</b> — {{ rows.length }} kishi · <button type="button" @click="kf = ''">hammasi ✕</button></td></tr>
              <tr v-for="r in rows" :key="r.employee_id" :class="{ risk: r.risk }">
                <td><input v-if="r.bonus_suggest" type="checkbox" :checked="pick.has(r.employee_id)" :aria-label="`${r.full_name} bonus`" @change="pick.has(r.employee_id) ? pick.delete(r.employee_id) : pick.add(r.employee_id)" /></td>
                <td class="rk">{{ r.rank ?? '—' }}</td>
                <td><button type="button" class="who" @click="router.push(`/hr/employee/${r.employee_id}?tab=kpi`)"><UiAvatar :name="r.full_name" :src="r.avatar" :size="30" /><span><b>{{ r.full_name }}</b><small>{{ r.position || '—' }}<template v-if="r.branch"> · {{ r.branch }}</template></small></span></button></td>
                <td class="c"><span class="score"><b>{{ r.score ?? '—' }}</b><UiChip :tone="GT[r.grade]">{{ r.grade }}</UiChip></span></td>
                <td v-for="p in PARTS" :key="p" class="c">
                  <span v-if="r.parts[p]" class="cell" :title="r.parts[p].text"><i :class="tone(r.parts[p].value)" :style="{ width: r.parts[p].value + '%' }"></i><em>{{ r.parts[p].value }}</em></span>
                  <span v-else class="na">—</span>
                </td>
                <td class="c" :title="r.mood ? `${r.mood} / 4 · ${r.mood_count} smena` : ''">{{ MOOD(r.mood) }}</td>
                <td class="r">{{ r.bonus_suggest ? money(r.bonus_suggest) : '—' }}</td>
                <td><UiButton v-if="a.can('hr.review')" size="s" :variant="r.reviewed ? 'ghost' : 'secondary'" @click="review(r)">{{ r.reviewed ? 'Qayta' : 'Baholash' }}</UiButton></td>
              </tr>
            </tbody>
          </table>
          <UiEmpty v-if="!rows.length" title="Xodim yo'q" />
        </div>
      </UiCard>
      <p class="note">💡 {{ isCurrent ? 'Joriy oy — ball kun sayin yangilanadi.' : 'O\'tgan oy natijasi.' }} Xavf belgisi: smenadan keyingi kayfiyat o'rtachasi 2.5 dan past yoki davomat 70% dan kam — xodim bilan suhbatlashing.</p>
    </template>

    <UiDrawer :open="!!rv" :title="`Baholash · ${rv?.row.full_name ?? ''}`" @close="rv = null">
      <template v-if="rv">
        <div v-for="c in D.criteria" :key="c.key" class="star">
          <span>{{ c.label }}</span>
          <span class="st"><button v-for="n in 5" :key="n" type="button" :class="{ on: rv.scores[c.key] >= n }" :aria-label="`${n} yulduz`" @click="rv.scores[c.key] = n">★</button></span>
        </div>
        <p class="mut">Kamida 3 mezonni baholang.</p>
        <UiInput v-model="rv.strengths" label="Kuchli tomoni" />
        <UiInput v-model="rv.improve" label="Nimani yaxshilash kerak" />
        <UiInput v-model="rv.goals" label="Keyingi oy maqsadi (xodimga Telegram'da boradi)" />
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="rv = null">Bekor</UiButton><UiButton variant="brand" @click="saveReview">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.kp { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.top h1 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; } .top p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); max-width: 620px; }
.flt { display: flex; gap: 8px; min-width: 320px; } .flt > * { flex: 1; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.podium { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.pd { border: 1px solid var(--line); background: var(--surface); border-radius: 16px; padding: 14px; display: flex; flex-direction: column; align-items: center; gap: 4px; cursor: pointer; font: inherit; color: var(--ink); position: relative; }
.pd.p1 { border-color: var(--series-4); box-shadow: 0 0 0 1px var(--series-4) inset; }
.pd small { color: var(--muted); font-size: var(--fs-xs); } .medal { position: absolute; top: 8px; left: 10px; font-size: 22px; }
.pd .sc { font-family: var(--font-display); font-size: 26px; font-weight: 800; }
.tw { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
th { text-align: left; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; padding: 10px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 8px; border-bottom: 1px solid var(--line-2); vertical-align: middle; }
.kf-row { background: var(--warn-tint); font-size: var(--fs-s); } .kf-row button { border: 0; background: none; color: var(--accent); font: inherit; font-weight: 700; cursor: pointer; }
tr.risk td:nth-child(3) { box-shadow: inset 3px 0 0 var(--danger); }
.c { text-align: center; } .r { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; } .rk { color: var(--muted); font-weight: 800; }
.who { display: flex; gap: 8px; align-items: center; border: 0; background: none; cursor: pointer; font: inherit; color: var(--ink); text-align: left; padding: 0; }
.who span { display: flex; flex-direction: column; } .who small { color: var(--muted); font-size: var(--fs-xs); }
.score { display: inline-flex; gap: 6px; align-items: center; } .score b { font-size: 16px; font-variant-numeric: tabular-nums; }
.cell { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; width: 56px; }
.cell i { display: block; height: 6px; border-radius: 99px; align-self: flex-start; }
.cell i.a { background: var(--ok); } .cell i.b { background: var(--info); } .cell i.c { background: var(--warn); } .cell i.d { background: var(--danger); }
.cell em { font-style: normal; font-size: var(--fs-xs); font-variant-numeric: tabular-nums; } .na { color: var(--line); }
.note, .mut { color: var(--muted); font-size: var(--fs-s); margin: 0; } .sp { flex: 1; }
.star { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 0; font-size: var(--fs-s); font-weight: 600; }
.st button { border: 0; background: none; font-size: 26px; color: var(--line); cursor: pointer; padding: 0 2px; line-height: 1; } .st button.on { color: var(--series-4); }
@media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, 1fr); } .podium { grid-template-columns: 1fr; } .flt { min-width: 0; width: 100%; } }
</style>
