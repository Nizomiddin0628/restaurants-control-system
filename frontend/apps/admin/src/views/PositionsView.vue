<script setup lang="ts">
/**
 * Lavozimlar: chapda bo'limlar, o'rtada lavozimlar, o'ngda lavozim kartasi.
 * Karta — lavozimning «pasporti»: maqsad, vazifalar, kurs va standartlar (biriktirish), xodimlar, KPI.
 * Kursni lavozimga biriktirsangiz — shu lavozimdagi va keyin keladigan har bir xodimga o'zi beriladi.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import PositionEditor from '@/components/ops/PositionEditor.vue'
import DepartmentsDrawer from '@/components/ops/DepartmentsDrawer.vue'

const a = useAuth(), route = useRoute(), router = useRouter()
const meta = ref<any>(null)
const list = ref<any[]>([])
const dept = ref<number | 'all' | 0>('all')
const q = ref('')
const P = ref<any>(null)
const tab = ref<'info' | 'tasks' | 'training' | 'standards' | 'people' | 'kpi'>('info')
const editor = ref(false)
const edValue = ref<any>(null)
const depts = ref(false)
const linking = ref<'courses' | 'standards' | null>(null)
const picked = ref<Set<number>>(new Set())
const canEdit = computed(() => a.can('ops.edit'))
const hasTraining = computed(() => a.hasModule('training'))
const narrow = ref(window.matchMedia('(max-width: 1100px)').matches)

async function loadMeta() { meta.value = await api.get('/ops/meta') }
async function loadList() { list.value = await api.get('/ops/positions', { q: q.value || undefined }) }
async function open(id: number) {
  P.value = await api.get(`/ops/positions/${id}`)
  linking.value = null
  if (String(route.query.id ?? '') !== String(id)) router.replace({ query: { ...route.query, id: String(id) } })
}
onMounted(async () => {
  await Promise.all([loadMeta(), loadList()])
  const id = Number(route.query.id)
  if (id) await open(id)
  else if (!narrow.value && list.value.length) await open(list.value[0].id)
})
let t: number | undefined
watch(q, () => { clearTimeout(t); t = window.setTimeout(loadList, 250) })

const shown = computed(() => list.value.filter(p => dept.value === 'all' ? true : dept.value === 0 ? !p.department : p.department?.id === dept.value))
const counts = computed(() => {
  const c: Record<string, number> = { all: list.value.length, 0: list.value.filter(p => !p.department).length }
  for (const p of list.value) if (p.department) c[p.department.id] = (c[p.department.id] ?? 0) + 1
  return c
})
const FREQ: Record<string, string> = { daily: 'Har kuni', weekly: 'Har hafta', monthly: 'Har oy', shift: 'Har smenada', needed: 'Kerak bo\'lganda' }
const FREQ_TONE: Record<string, any> = { daily: 'info', shift: 'accent', weekly: 'ok', monthly: 'warn', needed: 'neutral' }
const VIA: Record<string, string> = { position: 'shu lavozimga', role: 'rol orqali', everyone: 'hammaga' }
const GRADE_TONE: Record<string, any> = { A: 'ok', B: 'info', C: 'warn', D: 'danger' }
const respGroups = computed(() => {
  const g: Record<string, string[]> = {}
  for (const r of P.value?.responsibilities ?? []) (g[r.freq] ??= []).push(r.text)
  return ['shift', 'daily', 'weekly', 'monthly', 'needed'].filter(k => g[k]).map(k => ({ freq: k, items: g[k] }))
})

function startLink(kind: 'courses' | 'standards') {
  linking.value = kind
  picked.value = new Set((P.value.training?.[kind] ?? []).filter((x: any) => x.linked).map((x: any) => x.id))
}
function toggle(id: number) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
async function saveLinks() {
  try {
    const r = await api.put(`/ops/positions/${P.value.id}/links`, { [linking.value!]: [...picked.value] })
    P.value = r.position; linking.value = null
    toast(r.enrolled ? `Saqlandi · ${r.enrolled} ta xodimga kurs biriktirildi` : 'Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function newPos() { edValue.value = null; editor.value = true }
function editPos() { edValue.value = P.value; editor.value = true }
async function onSaved(p: any) { editor.value = false; await Promise.all([loadMeta(), loadList()]); if (p?.id) { P.value = p; tab.value = 'info' } }
async function onDeleted() { editor.value = false; P.value = null; router.replace({ query: {} }); await Promise.all([loadMeta(), loadList()]) }
function close() { P.value = null; router.replace({ query: {} }) }
const fmt = (d: string | null) => d ? d.split('-').reverse().join('.') : '—'
</script>

<template>
  <div v-if="meta" class="pos">
    <!-- bo'limlar -->
    <UiCard class="deps" :padded="false">
      <div class="dh"><b>Bo'limlar</b><button v-if="canEdit" type="button" class="add" aria-label="Bo'limlar" @click="depts = true"><UiIcon name="sliders" :size="15" /></button></div>
      <button type="button" class="dp" :class="{ on: dept === 'all' }" @click="dept = 'all'"><span>🗂️</span><b>Barchasi</b><small>{{ counts.all }}</small></button>
      <button v-for="d in meta.departments" :key="d.id" type="button" class="dp" :class="{ on: dept === d.id }" :style="{ '--c': d.color }" @click="dept = d.id">
        <span>{{ d.icon }}</span><b>{{ d.name }}</b><small>{{ counts[d.id] ?? 0 }}</small>
      </button>
      <button v-if="counts[0]" type="button" class="dp" :class="{ on: dept === 0 }" @click="dept = 0"><span>❔</span><b>Bo'limsiz</b><small>{{ counts[0] }}</small></button>
      <RouterLink v-if="!meta.has_structure" to="/org" class="tpl">🏢 Tayyor tuzilma shabloni →</RouterLink>
    </UiCard>

    <!-- lavozimlar -->
    <UiCard class="lst" :padded="false">
      <div class="lh">
        <UiInput v-model="q" placeholder="Lavozim qidirish…" />
        <UiButton v-if="canEdit" variant="brand" size="s" @click="newPos()"><UiIcon name="plus" :size="14" /> Lavozim</UiButton>
      </div>
      <button v-for="p in shown" :key="p.id" type="button" class="pc" :class="{ on: P?.id === p.id }" :style="{ '--c': p.department?.color ?? 'var(--line)' }" @click="open(p.id)">
        <span class="pi">{{ p.icon }}</span>
        <span class="pt"><b>{{ p.name }}</b><small>{{ p.department?.name ?? 'Bo\'limsiz' }} · {{ p.scope === 'hq' ? 'Bosh ofis' : 'Filial' }}</small></span>
        <span class="pn" :class="{ bad: p.headcount && p.scope === 'hq' && p.employees_count < p.headcount }">👥 {{ p.employees_count }}</span>
        <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg); color: var(--muted)" />
      </button>
      <UiEmpty v-if="!shown.length" title="Lavozim topilmadi" />
    </UiCard>

    <!-- lavozim kartasi -->
    <component :is="narrow ? UiDrawer : 'section'" v-if="P" :open="true" :title="P.name" width="720px" class="card" @close="close()">
      <header class="ch" :style="{ '--c': P.department?.color ?? 'var(--accent)' }">
        <span class="ci">{{ P.icon }}</span>
        <div class="ct">
          <h2>{{ P.name }} <UiChip tone="ok">Faol</UiChip></h2>
          <p>{{ P.department ? `${P.department.icon} ${P.department.name}` : 'Bo\'limsiz' }} · {{ P.level_label }} · {{ P.scope_label }}</p>
        </div>
        <UiButton v-if="canEdit" size="s" variant="ghost" @click="editPos()"><UiIcon name="edit" :size="14" /> Tahrirlash</UiButton>
      </header>

      <nav class="tabs" role="tablist">
        <button :class="{ on: tab === 'info' }" @click="tab = 'info'">Ma'lumot</button>
        <button :class="{ on: tab === 'tasks' }" @click="tab = 'tasks'">Vazifalar <i>{{ P.counts.responsibilities + P.counts.tasks }}</i></button>
        <button v-if="P.training" :class="{ on: tab === 'training' }" @click="tab = 'training'">Trening <i>{{ P.counts.courses }}</i></button>
        <button v-if="P.training" :class="{ on: tab === 'standards' }" @click="tab = 'standards'">Standartlar <i>{{ P.counts.standards }}</i></button>
        <button :class="{ on: tab === 'people' }" @click="tab = 'people'">Xodimlar <i>{{ P.counts.employees }}</i></button>
        <button :class="{ on: tab === 'kpi' }" @click="tab = 'kpi'">KPI</button>
      </nav>

      <!-- MA'LUMOT -->
      <div v-if="tab === 'info'" class="pane">
        <div class="auto">
          <b>⚡ Avtomatik ulanish</b>
          <span>Bu lavozimga qo'yilgan har bir xodim darhol oladi: <u>{{ P.counts.responsibilities }} vazifa</u>, <u>{{ P.counts.courses }} kurs</u>, <u>{{ P.counts.standards }} standart</u> va KPI baholash. Hech narsani qo'lda biriktirish shart emas.</span>
        </div>
        <p v-if="P.purpose" class="purp"><b>Lavozim maqsadi.</b> {{ P.purpose }}</p>
        <p v-else class="purp mut">Lavozim maqsadi yozilmagan. <a v-if="canEdit" href="#" @click.prevent="editPos()">Yozish</a></p>
        <dl class="kv">
          <dt>Bo'lim</dt><dd>{{ P.department?.name ?? '—' }}</dd>
          <dt>To'g'ridan-to'g'ri rahbar</dt><dd><a v-if="P.reports_to" href="#" @click.prevent="open(P.reports_to.id)">{{ P.reports_to.name }}</a><template v-else>— (eng yuqori)</template></dd>
          <dt>Qo'l ostidagilar</dt><dd><template v-if="P.subordinates.length"><a v-for="s in P.subordinates" :key="s.id" href="#" class="sub" @click.prevent="open(s.id)">{{ s.icon }} {{ s.name }}</a></template><template v-else>—</template></dd>
          <dt>Qayerda ishlaydi</dt><dd>{{ P.scope_label }}</dd>
          <dt>Shtat</dt><dd>{{ P.headcount || '—' }}{{ P.headcount && P.scope === 'branch' ? ' kishi har filialda' : P.headcount ? ' kishi' : '' }} · hozir {{ P.employees.length }}</dd>
          <dt>Maosh</dt><dd>{{ ({ monthly: 'Oylik', shift: 'Smena', hourly: 'Soatbay', percent: 'Foiz' } as Record<string, string>)[P.default_salary_type] }}{{ P.default_rate ? ` · ${P.default_rate.toLocaleString('ru-RU').replace(/,/g, ' ')} so'm` : '' }}</dd>
        </dl>
        <div class="tiles">
          <button @click="tab = 'tasks'"><b>{{ P.counts.responsibilities }}</b><span>asosiy vazifa</span></button>
          <button v-if="P.training" @click="tab = 'training'"><b>{{ P.counts.courses }}</b><span>kurs</span></button>
          <button v-if="P.training" @click="tab = 'standards'"><b>{{ P.counts.standards }}</b><span>standart</span></button>
          <button @click="tab = 'people'"><b>{{ P.counts.employees }}</b><span>xodim</span></button>
          <button @click="tab = 'kpi'"><b>{{ P.kpi.avg ?? '—' }}</b><span>o'rtacha KPI</span></button>
        </div>
        <div v-if="P.vacancies.length" class="vac">📢 Ochiq vakansiya: <RouterLink v-for="v in P.vacancies" :key="v.id" to="/recruiting">{{ v.title }}{{ v.branch ? ` (${v.branch})` : '' }}</RouterLink></div>
      </div>

      <!-- VAZIFALAR -->
      <div v-else-if="tab === 'tasks'" class="pane">
        <div v-for="g in respGroups" :key="g.freq" class="rg">
          <UiChip :tone="FREQ_TONE[g.freq]">{{ FREQ[g.freq] }}</UiChip>
          <ol><li v-for="(t2, i) in g.items" :key="i">{{ t2 }}</li></ol>
        </div>
        <UiEmpty v-if="!respGroups.length" title="Asosiy vazifalar yozilmagan" text="«Tahrirlash» orqali qo'shing — xodim o'z telefonida ko'radi." />
        <div v-if="P.tasks?.length" class="rg">
          <UiChip tone="neutral">Takroriy vazifalar (Vazifalar bo'limidan)</UiChip>
          <ul class="rt"><li v-for="r in P.tasks" :key="r.id"><b>{{ r.title }}</b><small>{{ r.freq }} · {{ r.time }}{{ r.assignee ? ` · ${r.assignee}` : '' }}</small></li></ul>
        </div>
      </div>

      <!-- TRENING / STANDARTLAR -->
      <div v-else-if="(tab === 'training' || tab === 'standards') && P.training" class="pane">
        <template v-if="!linking">
          <div class="lk-h">
            <p class="mut">{{ tab === 'training' ? 'Bu lavozimdagi xodimlar o\'tishi kerak bo\'lgan kurslar. Yangi xodimga o\'zi biriktiriladi.' : 'Xodim o\'qib «Tanishdim» deb tasdiqlashi kerak bo\'lgan standartlar.' }}</p>
            <UiButton v-if="canEdit" size="s" variant="brand" @click="startLink(tab === 'training' ? 'courses' : 'standards')"><UiIcon name="plus" :size="14" /> Biriktirish</UiButton>
          </div>
          <ul class="ln">
            <li v-for="c in (tab === 'training' ? P.training.courses : P.training.standards).filter((x: any) => x.via)" :key="c.id">
              <span class="lni">{{ tab === 'training' ? '🎓' : '📘' }}</span>
              <span class="lnt"><b>{{ c.title }}</b><small>{{ c.category || '—' }}{{ tab === 'standards' ? ` · v${c.version}` : c.published ? '' : ' · e\'lon qilinmagan' }} · <em :class="c.via">{{ VIA[c.via] }}</em></small></span>
              <span v-if="tab === 'training'" class="pr"><span class="bar"><i :style="{ width: `${c.total ? (100 * c.done) / c.total : 0}%` }"></i></span><small>{{ c.done }}/{{ c.total }} tugatgan</small></span>
            </li>
          </ul>
          <UiEmpty v-if="!(tab === 'training' ? P.training.courses : P.training.standards).some((x: any) => x.via)" :title="tab === 'training' ? 'Kurs biriktirilmagan' : 'Standart biriktirilmagan'" text="«Biriktirish» tugmasini bosing va ro'yxatdan belgilang." />
        </template>
        <template v-else>
          <p class="mut">Belgilang — saqlangach, shu lavozimdagi hamma xodimga beriladi:</p>
          <label v-for="c in P.training[linking]" :key="c.id" class="pick" :class="{ on: picked.has(c.id) }">
            <input type="checkbox" :checked="picked.has(c.id)" @change="toggle(c.id)" /><span><b>{{ c.title }}</b><small>{{ c.category || '—' }}</small></span>
          </label>
          <UiEmpty v-if="!P.training[linking].length" :title="linking === 'courses' ? 'Hali kurs yo\'q' : 'Hali standart yo\'q'" text="Avval «O'qitish» bo'limida yarating." />
          <div class="lk-f"><UiButton variant="ghost" @click="linking = null">Bekor</UiButton><UiButton variant="brand" @click="saveLinks()">Saqlash ({{ picked.size }})</UiButton></div>
        </template>
      </div>

      <!-- XODIMLAR -->
      <div v-else-if="tab === 'people'" class="pane">
        <ul class="pp">
          <li v-for="e in P.employees" :key="e.id">
            <RouterLink :to="`/hr/employee/${e.id}`" class="ppl">
              <UiAvatar :name="e.name" :src="e.avatar" :size="36" />
              <span><b>{{ e.name }}</b><small>{{ e.branch ?? '—' }} · ishga kirgan {{ fmt(e.hire_date) }}</small></span>
              <UiChip v-if="e.grade" :tone="GRADE_TONE[e.grade]">KPI {{ e.kpi }} · {{ e.grade }}</UiChip>
            </RouterLink>
          </li>
        </ul>
        <UiEmpty v-if="!P.employees.length" title="Bu lavozimda hali xodim yo'q" text="Xodimlar bo'limida xodimga shu lavozimni tanlang yoki vakansiya oching." />
      </div>

      <!-- KPI -->
      <div v-else class="pane">
        <div class="kh"><div class="big"><b>{{ P.kpi.avg ?? '—' }}</b><span>o'rtacha KPI · shu oy</span></div>
          <div class="gr"><div v-for="g in ['A', 'B', 'C', 'D']" :key="g"><UiChip :tone="GRADE_TONE[g]">{{ g }}</UiChip><b>{{ P.kpi.grades[g] }}</b></div></div></div>
        <p class="mut">KPI: davomat, o'z vaqtida kelish, o'qitish, vazifalar, ish natijasi va menejer bahosi. Batafsil — <RouterLink to="/kpi">Baholash va KPI</RouterLink>.</p>
        <ul class="pp"><li v-for="e in [...P.employees].sort((x: any, y: any) => (y.kpi ?? -1) - (x.kpi ?? -1))" :key="e.id"><span class="ppl"><UiAvatar :name="e.name" :src="e.avatar" :size="30" /><span><b>{{ e.name }}</b><small>{{ e.branch ?? '' }}</small></span><b class="kv2">{{ e.kpi ?? '—' }}</b></span></li></ul>
      </div>
    </component>
    <UiCard v-else-if="!narrow" class="card"><UiEmpty title="Lavozimni tanlang" text="Chapdagi ro'yxatdan lavozimni bosing — kartasi shu yerda ochiladi." /></UiCard>

    <PositionEditor :open="editor" :value="edValue" :meta="meta" @close="editor = false" @saved="onSaved" @deleted="onDeleted" />
    <DepartmentsDrawer :open="depts" :departments="meta.departments" @close="depts = false" @changed="loadMeta(); loadList()" />
  </div>
</template>

<style scoped>
.pos { display: grid; grid-template-columns: 220px minmax(0, 330px) minmax(0, 1fr); gap: 14px; align-items: start; }
.deps, .lst { position: sticky; top: 12px; }
.dh { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px 6px; }
.add { width: 32px; height: 32px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); cursor: pointer; display: grid; place-items: center; color: var(--ink); }
.dp { display: grid; grid-template-columns: 26px 1fr auto; gap: 8px; align-items: center; width: 100%; padding: 10px 14px; border: 0; border-left: 3px solid transparent; background: transparent; font: inherit; text-align: left; cursor: pointer; color: var(--ink); }
.dp b { font-size: var(--fs-s); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .dp small { color: var(--muted); font-weight: 700; font-size: var(--fs-xs); }
.dp:hover { background: var(--surface-2); } .dp.on { background: var(--accent-tint); border-left-color: var(--c, var(--accent)); } .dp.on b { font-weight: 800; }
.tpl { display: block; margin: 8px 14px 14px; padding: 10px; border-radius: 10px; background: var(--warn-tint); color: var(--warn-ink); font-weight: 700; font-size: var(--fs-s); text-decoration: none; }
.lh { display: flex; gap: 8px; padding: 12px; align-items: center; } .lh > :first-child { flex: 1; }
.pc { display: grid; grid-template-columns: 40px minmax(0, 1fr) auto 16px; gap: 10px; align-items: center; width: 100%; padding: 10px 12px; border: 0; border-top: 1px solid var(--line-2); border-left: 4px solid var(--c); background: transparent; font: inherit; text-align: left; cursor: pointer; color: var(--ink); min-height: 60px; }
.pc:hover { background: var(--surface-2); } .pc.on { background: var(--accent-tint); }
.pi { width: 40px; height: 40px; border-radius: 12px; background: var(--surface-2); display: grid; place-items: center; font-size: 22px; }
.pt { display: flex; flex-direction: column; min-width: 0; } .pt b { font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .pt small { font-size: var(--fs-xs); color: var(--muted); }
.pn { font-size: var(--fs-xs); font-weight: 800; color: var(--ink-2); white-space: nowrap; } .pn.bad { color: var(--warn-ink); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 18px; min-width: 0; }
.ch { flex-shrink: 0; display: flex; align-items: center; gap: 14px; padding-bottom: 14px; border-bottom: 3px solid var(--c); }
.ci { width: 56px; height: 56px; border-radius: 16px; background: color-mix(in srgb, var(--c) 14%, var(--surface)); display: grid; place-items: center; font-size: 30px; flex-shrink: 0; }
.ct { flex: 1; min-width: 0; } .ct h2 { margin: 0; font-family: var(--font-display); font-size: 22px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .ct p { margin: 2px 0 0; color: var(--muted); font-size: var(--fs-s); }
.tabs { flex-shrink: 0; display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; margin: 6px 0 14px; }
.tabs button { border: 0; background: transparent; padding: 10px 12px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); } .tabs i { font-style: normal; font-size: 11px; background: var(--surface-3); border-radius: 99px; padding: 1px 7px; margin-left: 4px; }
.pane { flex-shrink: 0; display: flex; flex-direction: column; gap: 14px; }
.auto { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px; background: var(--ok-tint); font-size: var(--fs-s); } .auto u { text-decoration: none; font-weight: 800; }
.purp { margin: 0; line-height: 1.5; } .mut { color: var(--muted); font-size: var(--fs-s); margin: 0; }
.kv { display: grid; grid-template-columns: 190px 1fr; gap: 8px 14px; margin: 0; font-size: var(--fs-s); } .kv dt { color: var(--muted); } .kv dd { margin: 0; font-weight: 600; display: flex; flex-wrap: wrap; gap: 4px 10px; }
.kv a { color: var(--accent); text-decoration: none; } .sub { white-space: nowrap; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
.tiles button { border: 1px solid var(--line); border-radius: 12px; background: var(--surface-2); padding: 12px 8px; display: flex; flex-direction: column; align-items: center; cursor: pointer; font: inherit; color: var(--ink); }
.tiles button:hover { border-color: var(--accent); } .tiles b { font-family: var(--font-display); font-size: 22px; } .tiles span { font-size: var(--fs-xs); color: var(--muted); }
.vac { padding: 10px 12px; border-radius: 10px; background: var(--info-tint); font-size: var(--fs-s); display: flex; gap: 8px; flex-wrap: wrap; } .vac a { color: var(--accent); font-weight: 700; }
.rg { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.rg ol { margin: 0; padding-left: 22px; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); line-height: 1.4; width: 100%; }
.rt { list-style: none; margin: 0; padding: 0; width: 100%; } .rt li { display: flex; flex-direction: column; padding: 6px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .rt small { color: var(--muted); }
.lk-h { display: flex; justify-content: space-between; gap: 10px; align-items: center; flex-wrap: wrap; }
.ln, .pp { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.ln li { display: grid; grid-template-columns: 36px minmax(0, 1fr) 150px; gap: 10px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--line-2); }
.lni { font-size: 22px; } .lnt em { font-style: normal; font-weight: 700; } .lnt em.position { color: var(--ok); } .lnt { display: flex; flex-direction: column; min-width: 0; } .lnt b { font-size: var(--fs-s); } .lnt small, .pr small { color: var(--muted); font-size: var(--fs-xs); }
.pr { display: flex; flex-direction: column; gap: 4px; } .bar { height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; } .bar i { display: block; height: 100%; background: var(--series-1); }
.pick { display: flex; gap: 12px; align-items: center; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; cursor: pointer; min-height: 52px; }
.pick.on { border-color: var(--accent); background: var(--accent-tint); } .pick input { width: 20px; height: 20px; } .pick span { display: flex; flex-direction: column; } .pick small { color: var(--muted); font-size: var(--fs-xs); }
.lk-f { display: flex; justify-content: flex-end; gap: 8px; position: sticky; bottom: 0; background: var(--surface); padding-top: 8px; }
.ppl { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line-2); color: var(--ink); text-decoration: none; }
.ppl > span { flex: 1; display: flex; flex-direction: column; min-width: 0; } .ppl small { color: var(--muted); font-size: var(--fs-xs); } .kv2 { font-family: var(--font-display); font-size: var(--fs-l); }
.kh { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; } .big { display: flex; flex-direction: column; } .big b { font-family: var(--font-display); font-size: 40px; line-height: 1; } .big span { color: var(--muted); font-size: var(--fs-xs); }
.gr { display: flex; gap: 12px; } .gr div { display: flex; align-items: center; gap: 6px; }
@media (max-width: 1400px) { .pos { grid-template-columns: 200px minmax(0, 300px) minmax(0, 1fr); } .kv { grid-template-columns: 150px 1fr; } }
@media (max-width: 1100px) { .pos { grid-template-columns: 200px minmax(0, 1fr); } }
@media (max-width: 720px) {
  .pos { grid-template-columns: minmax(0, 1fr); }
  .deps { position: static; display: flex; overflow-x: auto; gap: 6px; padding: 8px; border-radius: 12px; }
  .deps .dh, .deps .tpl { display: none; }
  .dp { width: auto; flex-shrink: 0; grid-template-columns: auto auto auto; border: 1px solid var(--line); border-radius: 99px; padding: 6px 12px; }
  .dp.on { border-color: var(--accent); }
  .lst { position: static; }
  .card { padding: 0; border: 0; }
  .ct h2 { font-size: 18px; }
  .kv { grid-template-columns: 1fr; gap: 2px; } .kv dt { margin-top: 8px; }
  .ln li { grid-template-columns: 32px minmax(0, 1fr); } .ln .pr { grid-column: 2; }
}
</style>
