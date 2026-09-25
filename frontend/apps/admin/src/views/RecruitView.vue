<script setup lang="ts">
/**
 * Ishga olish: vakansiyalar (saytda va Telegram botda chiqadi) + nomzodlar taxtasi (bosqichlar bo'yicha).
 * Nomzod kartasi: javoblar, oldingi ish joylari, baho, izoh, tarix; suhbatga chaqirish (vaqt + joy → Telegram xabar),
 * rad etish (sabab), qabul qilish → xodim kartasi avtomatik ochiladi.
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiKpi, UiSelect, money, toast } from '@restopos/ui'
import { uploadWithProgress, fmtDateTime } from '@/components/training/upload'

const router = useRouter()
const tab = ref<'board' | 'vacancies'>('board')
const V = ref<any[]>([]), A = ref<any[]>([]), S = ref<any>(null), M = ref<any>(null)
const fVac = ref<string>(''), q = ref('')

const STAGES = [
  { key: 'new', label: 'Yangi', tone: 'info' }, { key: 'screen', label: 'Ko\'rib chiqilmoqda', tone: 'neutral' },
  { key: 'interview', label: 'Suhbat', tone: 'accent' }, { key: 'trial', label: 'Sinov kuni', tone: 'warn' },
  { key: 'offer', label: 'Taklif', tone: 'warn' }, { key: 'hired', label: 'Qabul qilindi', tone: 'ok' }, { key: 'rejected', label: 'Rad etildi', tone: 'danger' },
] as const
const SRC: Record<string, string> = { site: 'Sayt', telegram: 'Telegram', manual: 'Qo\'lda', referral: 'Tavsiya' }
const EMP = [{ value: 'full', label: 'To\'liq stavka' }, { value: 'part', label: 'Yarim stavka' }, { value: 'shift', label: 'Smenali' }, { value: 'intern', label: 'Amaliyot / o\'quvchi' }]
const VST = [{ value: 'draft', label: 'Qoralama' }, { value: 'open', label: 'Ochiq — saytda ko\'rinadi' }, { value: 'paused', label: 'To\'xtatilgan' }, { value: 'closed', label: 'Yopilgan' }]
const VTONE: Record<string, any> = { open: 'ok', draft: 'neutral', paused: 'warn', closed: 'danger' }

async function load() {
  const [v, a, s] = await Promise.all([api.get('/hr/vacancies'), api.get('/hr/applications'), api.get('/hr/recruit/stats')])
  V.value = v; A.value = a; S.value = s
  if (!M.value) M.value = await api.get('/hr/meta').catch(() => ({ positions: [], roles: [], branches: [], salary_types: [] }))
}
onMounted(load)

const filtered = computed(() => {
  const s = q.value.trim().toLowerCase()
  return A.value.filter((a) => (!fVac.value || String(a.vacancy_id) === fVac.value) && (!s || a.full_name.toLowerCase().includes(s) || a.phone.includes(s)))
})
const col = (k: string) => filtered.value.filter((a) => a.stage === k)
const vacOpts = computed(() => [{ value: '', label: 'Barcha vakansiyalar' }, ...V.value.map((v) => ({ value: String(v.id), label: `${v.title} (${v.applications})` }))])
const ago = (s: string) => { const h = Math.round((Date.now() - new Date(s).getTime()) / 36e5); return h < 1 ? 'hozir' : h < 24 ? `${h} soat oldin` : `${Math.round(h / 24)} kun oldin` }

// ------------------------------------------------ vakansiya muharriri
const ed = ref<any>(null), imgFile = ref<File | null>(null), saving = ref(false)
function newVac() {
  ed.value = { id: null, title: '', role_code: 'waiter', position_id: null, branch_id: null, employment: 'full', salary_from: 0, salary_to: 0, salary_note: '',
    schedule: '', summary: '', requirements: [''], duties: [''], benefits: ['Bepul ovqat', 'Rasmiy ishga joylashtirish'], image_url: '', video_url: '', link_url: '',
    questions: [{ text: 'Kechki smenada ishlay olasizmi?', type: 'yesno', must: 'ha' }], status: 'draft', closes_on: '' }
  imgFile.value = null
}
function editVac(v: any) {
  ed.value = JSON.parse(JSON.stringify({ ...v, closes_on: v.closes_on || '', requirements: v.requirements.length ? v.requirements : [''], duties: v.duties.length ? v.duties : [''], benefits: v.benefits.length ? v.benefits : [''] }))
  imgFile.value = null
}
async function saveVac() {
  const e = ed.value; saving.value = true
  const body = { ...e, salary_from: Number(e.salary_from) || 0, salary_to: Number(e.salary_to) || 0, position_id: e.position_id || null, branch_id: e.branch_id || null, closes_on: e.closes_on || null }
  try {
    let v = e.id ? await api.put(`/hr/vacancies/${e.id}`, body) : await api.post('/hr/vacancies', body)
    if (imgFile.value) v = await uploadWithProgress(`/hr/vacancies/${v.id}/image`, imgFile.value)
    ed.value = null; toast(v.is_open ? 'Saqlandi — saytda va botda ko\'rinadi' : 'Saqlandi'); await load()
  } catch (err: any) { toast(err.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
async function delVac(v: any) {
  if (!confirm(`«${v.title}» o'chirilsinmi? (arizalar bo'lsa — yopiladi)`)) return
  const r = await api.del(`/hr/vacancies/${v.id}`); toast(r.closed ? 'Arizalar bor — vakansiya yopildi' : 'O\'chirildi'); await load()
}
const copy = (s: string) => { navigator.clipboard?.writeText(s); toast('Havola nusxalandi') }
const siteLink = (v: any) => location.origin + v.public_path
const roleOpts = computed(() => (M.value?.roles || []).map((r: any) => ({ value: r.code, label: r.name })))
const posOpts = computed(() => [{ value: '', label: '—' }, ...(M.value?.positions || []).map((p: any) => ({ value: p.id, label: p.name }))])
const brOpts = computed(() => [{ value: '', label: 'Barcha filiallar' }, ...(M.value?.branches || []).map((b: any) => ({ value: b.id, label: b.name }))])

// ------------------------------------------------ nomzod kartasi
const C = ref<any>(null), act = ref<any>(null), msg = ref('')
async function openApp(a: any) { C.value = await api.get(`/hr/applications/${a.id}`); act.value = null; msg.value = '' }
async function patch(b: any) { C.value = await api.patch(`/hr/applications/${C.value.id}`, b); const i = A.value.findIndex((x) => x.id === C.value.id); if (i >= 0) A.value[i] = { ...A.value[i], rating: C.value.rating } }
function startMove(stage: string) {
  const need = stage === 'interview' || stage === 'trial'
  if (!need && stage !== 'rejected' && stage !== 'hired') return doMove({ stage })
  if (stage === 'hired') {
    const v = V.value.find((x) => x.id === C.value.vacancy_id)
    act.value = { kind: 'hire', role_code: v?.role_code || 'waiter', branch_id: v?.branch_id || '', position_id: v?.position_id || '', salary_type: 'monthly', rate: v?.salary_from || 0 }
    return
  }
  const t = new Date(Date.now() + 864e5); t.setHours(11, 0, 0, 0)
  const loc = new Date(t.getTime() - t.getTimezoneOffset() * 6e4).toISOString().slice(0, 16)
  act.value = { kind: stage, stage, interview_at: need ? loc : '', place: '', reason: '', note: '', notify: true }
}
async function doMove(b: any) {
  try {
    const body = { ...b }; if (body.interview_at) body.interview_at = new Date(body.interview_at).toISOString(); else delete body.interview_at
    C.value = await api.post(`/hr/applications/${C.value.id}/stage`, body); act.value = null; toast(`Bosqich: ${C.value.stage_label}`); await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function hire() {
  const x = act.value
  try {
    const r = await api.post(`/hr/applications/${C.value.id}/hire`, { role_code: x.role_code, branch_id: x.branch_id || null, position_id: x.position_id || null, salary_type: x.salary_type, rate: Number(x.rate) || 0 })
    toast('Xodim kartasi ochildi 🎉'); C.value = null; act.value = null; await load(); router.push(`/hr/employee/${r.employee_id}`)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function send() {
  try { await api.post(`/hr/applications/${C.value.id}/message`, { text: msg.value }); msg.value = ''; toast('Telegram\'ga yuborildi'); C.value = await api.get(`/hr/applications/${C.value.id}`) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
// qo'lda nomzod
const add = ref<any>(null)
async function saveAdd() {
  try { const a = await api.post('/hr/applications', { ...add.value, vacancy_id: add.value.vacancy_id || null, birth_year: Number(add.value.birth_year) || null }); add.value = null; await load(); openApp(a) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const nextStages = computed(() => {
  if (!C.value) return []
  const order = ['new', 'screen', 'interview', 'trial', 'offer', 'hired']
  const i = order.indexOf(C.value.stage)
  return C.value.stage === 'hired' ? [] : STAGES.filter((s) => s.key !== C.value.stage && (order.indexOf(s.key) > i || s.key === 'rejected' || C.value.stage === 'rejected'))
})
</script>

<template>
  <div class="rc">
    <header class="top">
      <div><h1>Ishga olish</h1><p>Vakansiya → saytda va Telegram botda ariza → suhbat → sinov kuni → xodim kartasi</p></div>
      <div class="acts">
        <UiButton variant="secondary" @click="add = { full_name: '', phone: '', vacancy_id: fVac || '', birth_year: '', experience: '', source: 'manual' }"><UiIcon name="plus" :size="16" /> Nomzod</UiButton>
        <UiButton variant="brand" @click="newVac"><UiIcon name="megaphone" :size="16" /> Vakansiya</UiButton>
      </div>
    </header>

    <div v-if="S" class="kpis">
      <UiKpi label="Ochiq vakansiya" :value="S.open" />
      <UiKpi label="Yangi ariza" :value="S.new" />
      <UiKpi label="Ariza (30 kun)" :value="S.applications_30d" />
      <UiKpi label="Kutilayotgan suhbat" :value="S.interviews_upcoming" />
      <UiKpi label="Qabul (30 kun)" :value="S.hired_30d" />
      <UiKpi label="O'rtacha yollash" :value="S.time_to_hire != null ? `${S.time_to_hire} kun` : '—'" />
    </div>

    <nav class="tabs">
      <button :class="{ on: tab === 'board' }" @click="tab = 'board'"><UiIcon name="columns" :size="15" /> Nomzodlar <small>{{ A.length }}</small></button>
      <button :class="{ on: tab === 'vacancies' }" @click="tab = 'vacancies'"><UiIcon name="megaphone" :size="15" /> Vakansiyalar <small>{{ V.length }}</small></button>
    </nav>

    <!-- NOMZODLAR TAXTASI -->
    <template v-if="tab === 'board'">
      <div class="flt"><UiSelect v-model="fVac" :options="vacOpts" /><UiInput v-model="q" placeholder="Ism yoki telefon…" /></div>
      <div class="board">
        <section v-for="s in STAGES" :key="s.key" class="colm">
          <header><UiChip :tone="s.tone as any">{{ s.label }}</UiChip><b>{{ col(s.key).length }}</b></header>
          <button v-for="a in col(s.key)" :key="a.id" class="card" :class="{ ko: a.knocked_out }" @click="openApp(a)">
            <span class="nm">{{ a.full_name }}<em v-if="a.rating">{{ '★'.repeat(a.rating) }}</em></span>
            <span class="vc">{{ a.vacancy || 'Vakansiyasiz' }}<template v-if="a.age"> · {{ a.age }} yosh</template></span>
            <span v-if="a.interview_at && (a.stage === 'interview' || a.stage === 'trial')" class="iv"><UiIcon name="calendar" :size="12" /> {{ fmtDateTime(a.interview_at) }}</span>
            <span class="ft"><span class="src">{{ SRC[a.source] || a.source }}</span><span v-if="a.knocked_out" class="kot">talabga mos emas</span><span class="ago">{{ ago(a.created_at) }}</span></span>
          </button>
          <p v-if="!col(s.key).length" class="none">—</p>
        </section>
      </div>
    </template>

    <!-- VAKANSIYALAR -->
    <div v-else class="vgrid">
      <article v-for="v in V" :key="v.id" class="vac">
        <div class="vimg" :style="v.image ? { backgroundImage: `url(${v.image})` } : {}"><UiIcon v-if="!v.image" name="megaphone" :size="30" /><UiChip :tone="VTONE[v.status]" class="vs">{{ v.status_label }}</UiChip></div>
        <div class="vb">
          <h3>{{ v.title }}</h3>
          <p class="sal">{{ v.salary_text }}</p>
          <p class="mut">{{ v.employment_label }}<template v-if="v.schedule"> · {{ v.schedule }}</template><template v-if="v.branch"> · {{ v.branch }}</template></p>
          <div class="vst">
            <span><b>{{ v.applications }}</b> ariza</span><span><b>{{ v.new }}</b> yangi</span><span><b>{{ v.by_stage?.hired || 0 }}</b> qabul</span><span><b>{{ v.views }}</b> ko'rildi</span>
          </div>
          <div class="vl">
            <button v-if="v.is_open" type="button" @click="copy(siteLink(v))"><UiIcon name="globe" :size="13" /> Sayt havolasi</button>
            <button v-if="v.bot_link" type="button" @click="copy(v.bot_link)"><UiIcon name="send" :size="13" /> Bot havolasi</button>
            <a v-if="v.is_open" :href="v.public_path" target="_blank" rel="noopener"><UiIcon name="eye" :size="13" /> Ko'rish</a>
          </div>
          <div class="vbtn">
            <UiButton size="s" variant="secondary" @click="fVac = String(v.id); tab = 'board'">Nomzodlar</UiButton>
            <UiButton size="s" variant="ghost" @click="editVac(v)"><UiIcon name="edit" :size="14" /></UiButton>
            <UiButton size="s" variant="ghost" @click="delVac(v)"><UiIcon name="trash" :size="14" /></UiButton>
          </div>
        </div>
      </article>
      <UiEmpty v-if="!V.length" title="Vakansiya yo'q" text="Birinchi vakansiyani yarating — saytda «Vakansiyalar» bo'limi va botda «💼 Vakansiyalar» tugmasi paydo bo'ladi." />
    </div>

    <!-- VAKANSIYA MUHARRIRI -->
    <UiDrawer :open="!!ed" :title="ed?.id ? 'Vakansiyani tahrirlash' : 'Yangi vakansiya'" width="640px" @close="ed = null">
      <template v-if="ed">
        <UiInput v-model="ed.title" label="Lavozim nomi" placeholder="Ofitsiant" />
        <div class="g3">
          <UiSelect v-model="ed.role_code" label="Tizimdagi rol" :options="roleOpts" />
          <UiSelect v-model="ed.position_id" label="Lavozim (maosh uchun)" :options="posOpts" />
          <UiSelect v-model="ed.branch_id" label="Filial" :options="brOpts" />
        </div>
        <div class="g3">
          <UiInput v-model="ed.salary_from" type="number" label="Maosh — dan" suffix="so'm" />
          <UiInput v-model="ed.salary_to" type="number" label="gacha" suffix="so'm" />
          <UiSelect v-model="ed.employment" label="Bandlik" :options="EMP" />
        </div>
        <div class="g2"><UiInput v-model="ed.salary_note" label="Maosh izohi" placeholder="+ choychaqa, KPI bonus" /><UiInput v-model="ed.schedule" label="Ish grafigi" placeholder="2/2, 10:00–23:00" /></div>
        <label class="fld"><span>Qisqacha tavsif</span><textarea v-model="ed.summary" rows="3" placeholder="Jamoamizga tajribali va xushmuomala ofitsiant kerak…"></textarea></label>
        <div v-for="k in (['requirements', 'duties', 'benefits'] as const)" :key="k" class="lst">
          <span class="lh">{{ { requirements: 'Talablar', duties: 'Majburiyatlar', benefits: 'Biz taklif qilamiz' }[k] }}</span>
          <div v-for="(_, i) in ed[k]" :key="i" class="lr"><input v-model="ed[k][i]" /><button type="button" aria-label="O'chirish" @click="ed[k].splice(i, 1)">✕</button></div>
          <button type="button" class="addl" @click="ed[k].push('')">+ qator</button>
        </div>
        <div class="media">
          <span class="lh">Rasm, video, havola</span>
          <UiInput v-model="ed.image_url" label="Rasm havolasi" placeholder="https://…" />
          <label class="fld"><span>yoki rasm yuklash (8 MB gacha)</span><input type="file" accept="image/*" @change="imgFile = ($event.target as HTMLInputElement).files?.[0] ?? null" /></label>
          <UiInput v-model="ed.video_url" label="Video (YouTube / Drive / mp4)" placeholder="https://youtube.com/watch?v=…" />
          <UiInput v-model="ed.link_url" label="Qo'shimcha havola" placeholder="Instagram, to'liq tavsif…" />
        </div>
        <div class="lst">
          <span class="lh">Saralash savollari <small>(«majburiy javob» — boshqa javob bersa «talabga mos emas» belgisi)</small></span>
          <div v-for="(x, i) in ed.questions" :key="i" class="qr">
            <input v-model="x.text" placeholder="Savol" />
            <select v-model="x.type"><option value="yesno">Ha / Yo'q</option><option value="text">Matn</option></select>
            <select v-if="x.type === 'yesno'" v-model="x.must"><option value="">farqi yo'q</option><option value="ha">«Ha» shart</option><option value="yo'q">«Yo'q» shart</option></select>
            <button type="button" aria-label="O'chirish" @click="ed.questions.splice(i, 1)">✕</button>
          </div>
          <button v-if="ed.questions.length < 10" type="button" class="addl" @click="ed.questions.push({ text: '', type: 'text', must: '' })">+ savol</button>
        </div>
        <div class="g2"><UiSelect v-model="ed.status" label="Holat" :options="VST" /><UiInput v-model="ed.closes_on" type="date" label="Qabul tugaydi (ixtiyoriy)" /></div>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="ed = null">Bekor</UiButton><UiButton variant="brand" :loading="saving" @click="saveVac">Saqlash</UiButton></template>
    </UiDrawer>

    <!-- NOMZOD KARTASI -->
    <UiDrawer :open="!!C" :title="C?.full_name" width="600px" @close="C = null">
      <template v-if="C">
        <div class="ch">
          <UiChip :tone="(STAGES.find((s) => s.key === C.stage)?.tone as any)">{{ C.stage_label }}</UiChip>
          <UiChip tone="neutral">{{ SRC[C.source] || C.source }}</UiChip>
          <UiChip v-if="C.knocked_out" tone="danger">Majburiy talabga mos emas</UiChip>
          <span class="sp"></span>
          <span class="rate"><button v-for="n in 5" :key="n" type="button" :class="{ on: C.rating >= n }" :aria-label="`${n}`" @click="patch({ rating: C.rating === n ? 0 : n })">★</button></span>
        </div>
        <dl class="dl">
          <dt>Vakansiya</dt><dd>{{ C.vacancy || '—' }}</dd>
          <dt>Telefon</dt><dd><a :href="`tel:${C.phone}`">{{ C.phone }}</a><template v-if="C.tg_username"> · <a :href="`https://t.me/${C.tg_username}`" target="_blank" rel="noopener">@{{ C.tg_username }}</a></template></dd>
          <dt>Yoshi</dt><dd>{{ C.age ? `${C.age} (${C.birth_year})` : '—' }}</dd>
          <dt v-if="C.interview_at">Uchrashuv</dt><dd v-if="C.interview_at">{{ fmtDateTime(C.interview_at) }} · {{ C.interview_place || '—' }}</dd>
          <dt v-if="C.reject_reason">Rad sababi</dt><dd v-if="C.reject_reason">{{ C.reject_reason }}</dd>
        </dl>
        <div v-if="C.photo" class="ph"><img :src="C.photo" alt="Nomzod rasmi" /></div>
        <h4>Savollarga javob</h4>
        <div v-for="(x, i) in C.answers" :key="i" class="ans"><span>{{ x.q }}</span><b :class="{ bad: x.ok === false }">{{ x.a || '—' }}</b></div>
        <p v-if="!C.answers?.length" class="mut">Savol yo'q</p>
        <h4>Tajriba</h4>
        <p class="pre">{{ C.experience || '—' }}</p>
        <div v-for="(w, i) in C.work_history" :key="i" class="wh"><b>{{ w.company }}</b> <span class="mut">{{ w.position }} {{ w.years }}</span></div>
        <label class="fld"><span>Ichki izoh (nomzod ko'rmaydi)</span><textarea :value="C.notes" rows="2" @change="patch({ notes: ($event.target as HTMLTextAreaElement).value })"></textarea></label>

        <template v-if="!act && C.stage !== 'hired'">
          <h4>Keyingi qadam</h4>
          <div class="mv"><UiButton v-for="s in nextStages" :key="s.key" size="s" :variant="s.key === 'hired' ? 'brand' : s.key === 'rejected' ? 'danger' : 'secondary'" @click="startMove(s.key)">{{ s.key === 'hired' ? '✓ Ishga qabul qilish' : s.label }}</UiButton></div>
        </template>
        <div v-else-if="act && act.kind !== 'hire'" class="box">
          <h4>{{ STAGES.find((s) => s.key === act.stage)?.label }}</h4>
          <template v-if="act.stage !== 'rejected'">
            <div class="g2"><UiInput v-model="act.interview_at" type="datetime-local" label="Sana va vaqt" /><UiInput v-model="act.place" label="Joy" placeholder="Chilonzor filiali, 2-qavat" /></div>
          </template>
          <UiInput v-else v-model="act.reason" label="Sabab (nomzodga muloyim xabar boradi, sabab — ichki)" placeholder="Tajriba yetarli emas" />
          <label class="chk"><input v-model="act.notify" type="checkbox" :disabled="!C.tg" /> Telegram orqali nomzodga xabar yuborish {{ C.tg ? '' : '(Telegram ulanmagan — telefon qiling)' }}</label>
          <div class="mv"><UiButton variant="ghost" size="s" @click="act = null">Bekor</UiButton><UiButton size="s" @click="doMove({ stage: act.stage, interview_at: act.interview_at, place: act.place, reason: act.reason, notify: act.notify })">Tasdiqlash</UiButton></div>
        </div>
        <div v-else-if="act?.kind === 'hire'" class="box">
          <h4>Ishga qabul qilish — xodim kartasi ochiladi</h4>
          <div class="g2"><UiSelect v-model="act.role_code" label="Rol" :options="roleOpts" /><UiSelect v-model="act.branch_id" label="Filial" :options="brOpts" /></div>
          <div class="g2"><UiSelect v-model="act.salary_type" label="Maosh turi" :options="(M?.salary_types || []).map((s: any) => ({ value: s.code, label: s.label }))" /><UiInput v-model="act.rate" type="number" label="Stavka" suffix="so'm" /></div>
          <p class="mut">Tizimga kirish: telefon {{ C.phone }} · ish tarixi anketadan ko'chiriladi{{ C.tg ? ' · Telegram\'ga tabrik boradi' : '' }}.</p>
          <div class="mv"><UiButton variant="ghost" size="s" @click="act = null">Bekor</UiButton><UiButton variant="brand" size="s" @click="hire">Qabul qilish · {{ money(Number(act.rate) || 0) }}</UiButton></div>
        </div>
        <UiButton v-if="C.employee_id" variant="secondary" @click="router.push(`/hr/employee/${C.employee_id}`)">Xodim profilini ochish →</UiButton>

        <template v-if="C.tg">
          <h4>Telegram xabar</h4>
          <div class="send"><input v-model="msg" placeholder="Assalomu alaykum! Ertaga 11:00 da kela olasizmi?" @keydown.enter="msg && send()" /><UiButton size="s" :disabled="!msg" @click="send"><UiIcon name="send" :size="14" /></UiButton></div>
        </template>
        <h4>Tarix</h4>
        <ul class="ev"><li v-for="(e, i) in C.events" :key="i"><small>{{ fmtDateTime(e.at) }}<template v-if="e.actor"> · {{ e.actor }}</template></small>{{ e.text }}</li></ul>
      </template>
    </UiDrawer>

    <UiDrawer :open="!!add" title="Nomzod qo'shish (qo'lda)" @close="add = null">
      <template v-if="add">
        <UiInput v-model="add.full_name" label="Ism familiya" />
        <UiInput v-model="add.phone" label="Telefon" placeholder="+998 90 123 45 67" />
        <UiSelect v-model="add.vacancy_id" label="Vakansiya" :options="vacOpts" />
        <div class="g2"><UiInput v-model="add.birth_year" type="number" label="Tug'ilgan yil" /><UiSelect v-model="add.source" label="Manba" :options="[{ value: 'manual', label: 'Qo\'lda / telefon' }, { value: 'referral', label: 'Xodim tavsiyasi' }]" /></div>
        <label class="fld"><span>Tajriba</span><textarea v-model="add.experience" rows="3"></textarea></label>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="add = null">Bekor</UiButton><UiButton variant="brand" @click="saveAdd">Qo'shish</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.rc { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.top h1 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; } .top p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); }
.acts { display: flex; gap: 8px; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 10px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); } .tabs small { background: var(--surface-3); border-radius: 99px; padding: 0 7px; }
.flt { display: flex; gap: 10px; max-width: 640px; } .flt > * { flex: 1; }
.board { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(220px, 1fr); gap: 12px; overflow-x: auto; padding-bottom: 8px; }
.colm { background: var(--surface-2); border: 1px solid var(--line); border-radius: 16px; padding: 10px; display: flex; flex-direction: column; gap: 8px; min-height: 200px; }
.colm header { display: flex; justify-content: space-between; align-items: center; padding: 2px 4px 6px; }
.card { text-align: left; border: 1px solid var(--line); background: var(--surface); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; gap: 4px; cursor: pointer; font: inherit; color: var(--ink); }
.card:hover { border-color: var(--accent); } .card.ko { border-left: 3px solid var(--danger); }
.nm { font-weight: 800; display: flex; justify-content: space-between; gap: 6px; } .nm em { font-style: normal; color: var(--series-4); font-size: var(--fs-xs); }
.vc, .ago, .src { font-size: var(--fs-xs); color: var(--muted); }
.iv { font-size: var(--fs-xs); font-weight: 700; color: var(--accent); display: inline-flex; gap: 4px; align-items: center; }
.ft { display: flex; gap: 6px; align-items: center; } .ago { margin-left: auto; } .kot { font-size: 10px; font-weight: 800; color: var(--danger); }
.none { color: var(--muted); text-align: center; margin: 8px 0; }
.vgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.vac { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; }
.vimg { height: 130px; background: var(--surface-3) center / cover; display: grid; place-items: center; color: var(--muted); position: relative; }
.vs { position: absolute; top: 10px; left: 10px; }
.vb { padding: 14px; display: flex; flex-direction: column; gap: 6px; flex: 1; } .vb h3 { margin: 0; font-size: 17px; font-weight: 800; }
.sal { margin: 0; font-weight: 800; color: var(--accent); } .mut { color: var(--muted); font-size: var(--fs-s); margin: 0; }
.vst { display: flex; gap: 12px; font-size: var(--fs-xs); color: var(--muted); flex-wrap: wrap; } .vst b { color: var(--ink); font-size: var(--fs-s); }
.vl { display: flex; gap: 10px; flex-wrap: wrap; } .vl button, .vl a { border: 0; background: none; color: var(--accent); font-weight: 700; font-size: var(--fs-xs); cursor: pointer; display: inline-flex; gap: 4px; align-items: center; padding: 0; text-decoration: none; }
.vbtn { display: flex; gap: 6px; margin-top: auto; padding-top: 6px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; } .g3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.fld { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fld textarea, .lr input, .qr input, .qr select, .send input { border: 1px solid var(--line); border-radius: var(--radius); padding: 9px 10px; font: inherit; background: var(--surface); color: var(--ink); min-width: 0; }
.lst, .media { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--line-2); padding-top: 10px; }
.lh { font-weight: 800; font-size: var(--fs-s); } .lh small { font-weight: 500; color: var(--muted); }
.lr, .qr { display: flex; gap: 6px; } .lr input, .qr input { flex: 1; }
.lr button, .qr button { border: 0; background: var(--surface-3); border-radius: 8px; width: 34px; cursor: pointer; color: var(--muted); }
.addl { align-self: flex-start; border: 0; background: none; color: var(--accent); font-weight: 700; cursor: pointer; padding: 2px 0; }
.ch { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; } .sp { flex: 1; }
.rate button { border: 0; background: none; font-size: 22px; color: var(--line); cursor: pointer; padding: 0 1px; } .rate button.on { color: var(--series-4); }
.dl { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; margin: 0; font-size: var(--fs-s); } .dl dt { color: var(--muted); font-weight: 700; } .dl dd { margin: 0; } .dl a { color: var(--accent); }
.ph img { max-width: 160px; border-radius: 12px; }
h4 { margin: 8px 0 0; font-size: var(--fs-s); font-weight: 800; }
.ans { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .ans span { color: var(--muted); } .bad { color: var(--danger); }
.pre { white-space: pre-line; margin: 0; font-size: var(--fs-s); } .wh { font-size: var(--fs-s); }
.mv { display: flex; gap: 6px; flex-wrap: wrap; }
.box { display: flex; flex-direction: column; gap: 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 14px; padding: 12px; }
.chk { display: flex; gap: 8px; align-items: center; font-size: var(--fs-s); }
.send { display: flex; gap: 6px; } .send input { flex: 1; }
.ev { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); }
.ev li { display: flex; flex-direction: column; border-left: 2px solid var(--line); padding-left: 10px; } .ev small { color: var(--muted); font-size: var(--fs-xs); }
@media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, 1fr); } .g3 { grid-template-columns: 1fr; } .flt { flex-direction: column; } }
</style>
