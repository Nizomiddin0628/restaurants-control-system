<script setup lang="ts">
/**
 * Xodimning to'liq profili: shaxsiy ma'lumot · oldingi ish joylari · hujjatlar (tibbiy daftarcha muddati) ·
 * KPI (oylik, 6 oy tarixi) · menejer baholari · smenadan keyingi kayfiyat · qayerdan (qaysi vakansiyadan) kelgani.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { uploadWithProgress } from '@/components/training/upload'
import AccessDrawer from '@/components/users/AccessDrawer.vue'
import AccessPanel from '@/components/users/AccessPanel.vue'

const a = useAuth(), route = useRoute(), router = useRouter()
const P = ref<any>(null)
const tab = ref<'info' | 'kpi' | 'history' | 'docs'>((route.query.tab as any) || 'info')
const canEdit = computed(() => a.can('hr.edit'))
const accessFor = ref<{ id: string; full_name?: string; phone?: string } | null>(null)
const panelFor = ref<string | null>(null)
function openAccess() {
  if (!P.value) return
  if (a.can('core.users.manage')) { panelFor.value = P.value.employee.user_id; return }
  accessFor.value = { id: P.value.employee.user_id, full_name: P.value.employee.full_name, phone: P.value.employee.phone }
}
const eid = computed(() => Number(route.params.id))
async function load() {
  try { P.value = await api.get(`/hr/employees/${eid.value}/profile`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); router.replace('/hr') }
}
onMounted(load)

const p2 = (n: number) => String(n).padStart(2, '0')
const dmy = (s?: string | null) => { if (!s) return '—'; const d = new Date(s); return `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.${d.getFullYear()}` }
const GTONE: Record<string, any> = { A: 'ok', B: 'info', C: 'warn', D: 'danger', '—': 'neutral' }
const MOOD = ['', '🙁', '😐', '🙂', '😀']

// ---- shaxsiy ma'lumot
const edit = ref<any>(null)
function startEdit() {
  const x = P.value.profile, e = P.value.employee
  edit.value = { birth_date: x.birth_date || '', gender: x.gender || '', address: x.address, emergency_name: x.emergency_name, emergency_phone: e.emergency_phone,
    education: x.education, languages: (x.languages || []).join(', '), skills: (x.skills || []).join(', '), about: x.about, medical_book_until: x.medical_book_until || '' }
}
async function saveEdit() {
  const b = { ...edit.value, birth_date: edit.value.birth_date || null, medical_book_until: edit.value.medical_book_until || null,
    languages: edit.value.languages.split(',').map((s: string) => s.trim()).filter(Boolean), skills: edit.value.skills.split(',').map((s: string) => s.trim()).filter(Boolean) }
  try { P.value = await api.put(`/hr/employees/${eid.value}/profile`, b); edit.value = null; toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- ish tarixi
const wh = ref<any>(null)
function newWork() { wh.value = { id: null, company: '', position: '', start: '', end: '', reason_left: '', reference_phone: '', note: '' } }
async function saveWork() {
  try { wh.value.id ? await api.put(`/hr/work-history/${wh.value.id}`, wh.value) : await api.post(`/hr/employees/${eid.value}/work-history`, wh.value); wh.value = null; await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delWork(w: any) { if (confirm('O\'chirilsinmi?')) { await api.del(`/hr/work-history/${w.id}`); await load() } }

// ---- hujjatlar
const doc = ref<any>(null)
const upPct = ref<number | null>(null)
const KINDS = [{ value: 'contract', label: 'Mehnat shartnomasi' }, { value: 'medbook', label: 'Tibbiy daftarcha' }, { value: 'passport', label: 'Pasport nusxasi' }, { value: 'diploma', label: 'Diplom / sertifikat' }, { value: 'other', label: 'Boshqa' }]
function newDoc() { doc.value = { title: '', kind: 'contract', url: '', expires_on: '', file: null as File | null } }
async function saveDoc() {
  const d = doc.value
  const qs = new URLSearchParams({ title: d.title, kind: d.kind, ...(d.url ? { url: d.url } : {}), ...(d.expires_on ? { expires_on: d.expires_on } : {}) }).toString()
  try {
    if (d.file) { upPct.value = 0; await uploadWithProgress(`/hr/employees/${eid.value}/documents?${qs}`, d.file, (p) => (upPct.value = p)) }
    else await api.post(`/hr/employees/${eid.value}/documents?${qs}`)
    doc.value = null; await load(); toast('Hujjat qo\'shildi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { upPct.value = null }
}
async function delDoc(x: any) { if (confirm(`«${x.title}» o'chirilsinmi?`)) { await api.del(`/hr/documents/${x.id}`); await load() } }

// ---- baholash
const rv = ref<any>(null)
function newReview() { rv.value = { month: P.value.kpi.month, scores: Object.fromEntries(P.value.criteria.map((c: any) => [c.key, 0])), strengths: '', improve: '', goals: '' } }
async function saveReview() {
  try { await api.post(`/hr/employees/${eid.value}/reviews`, rv.value); rv.value = null; await load(); toast('Baho saqlandi — KPI yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- ishdan bo'shatish
async function fire() {
  const reason = prompt('Ishdan bo\'shatish sababi (ichki):'); if (!reason) return
  try { await api.post(`/hr/employees/${eid.value}/fire`, { reason }); toast('Karta arxivga o\'tdi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const crit = (k: string) => P.value?.criteria.find((c: any) => c.key === k)?.label ?? k
</script>

<template>
  <div v-if="P" class="pf">
    <AccessDrawer :user="accessFor" @close="accessFor = null" />
    <AccessPanel :user-id="panelFor" tab="login" @close="panelFor = null" />
    <RouterLink to="/hr" class="back"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /> Xodimlar</RouterLink>

    <header class="hero">
      <UiAvatar :name="P.employee.full_name" :src="P.employee.avatar" :size="76" :online="P.employee.on_shift" />
      <div class="hi">
        <h1>{{ P.employee.full_name }}</h1>
        <p>{{ P.employee.position_name || P.employee.role_name }} · {{ P.employee.branch_name || '—' }} · <a :href="`tel:${P.employee.phone}`">{{ P.employee.phone }}</a></p>
        <div class="chips">
          <UiChip tone="neutral">Ishda: {{ P.profile.tenure_text }}</UiChip>
          <UiChip v-if="P.employee.telegram_id" tone="ok">Telegram ulangan</UiChip>
          <button v-if="canEdit" type="button" class="acc" @click="openAccess">🔐 Kirish va ruxsatlar</button>
          <UiChip v-if="P.profile.medical_expired" tone="danger">⚠ Tibbiy daftarcha muddati o'tgan</UiChip>
          <UiChip v-else-if="P.profile.medical_expiring" tone="warn">Tibbiy daftarcha tugayapti: {{ dmy(P.profile.medical_book_until) }}</UiChip>
          <UiChip v-if="!P.employee.is_active" tone="danger">Ishdan ketgan · {{ dmy(P.profile.fire_date) }}</UiChip>
          <UiChip v-if="P.kpi.risk" tone="danger">Ketib qolish xavfi</UiChip>
        </div>
      </div>
      <div class="kpibox" :class="GTONE[P.kpi.grade]">
        <span>KPI · {{ P.kpi.month }}</span><b>{{ P.kpi.score ?? '—' }}</b><em>{{ P.kpi.grade }}</em>
      </div>
    </header>

    <nav class="tabs">
      <button :class="{ on: tab === 'info' }" @click="tab = 'info'"><UiIcon name="users" :size="15" /> Ma'lumot</button>
      <button :class="{ on: tab === 'kpi' }" @click="tab = 'kpi'"><UiIcon name="star" :size="15" /> KPI va baholar</button>
      <button :class="{ on: tab === 'history' }" @click="tab = 'history'"><UiIcon name="archive" :size="15" /> Ish tarixi</button>
      <button :class="{ on: tab === 'docs' }" @click="tab = 'docs'"><UiIcon name="paperclip" :size="15" /> Hujjatlar <small v-if="P.documents.length">{{ P.documents.length }}</small></button>
    </nav>

    <!-- MA'LUMOT -->
    <div v-if="tab === 'info'" class="two">
      <UiCard title="Shaxsiy ma'lumot">
        <template #actions><UiButton v-if="canEdit" size="s" variant="secondary" @click="startEdit"><UiIcon name="edit" :size="14" /> O'zgartirish</UiButton></template>
        <dl class="dl">
          <dt>Tug'ilgan sana</dt><dd>{{ dmy(P.profile.birth_date) }}<template v-if="P.profile.age"> · {{ P.profile.age }} yosh</template></dd>
          <dt>Jinsi</dt><dd>{{ P.profile.gender === 'm' ? 'Erkak' : P.profile.gender === 'f' ? 'Ayol' : '—' }}</dd>
          <dt>Manzil</dt><dd>{{ P.profile.address || '—' }}</dd>
          <dt>Ma'lumoti</dt><dd>{{ P.profile.education || '—' }}</dd>
          <dt>Tillar</dt><dd><UiChip v-for="l in P.profile.languages" :key="l" tone="neutral">{{ l }}</UiChip><span v-if="!P.profile.languages.length">—</span></dd>
          <dt>Ko'nikmalar</dt><dd><UiChip v-for="s in P.profile.skills" :key="s" tone="info">{{ s }}</UiChip><span v-if="!P.profile.skills.length">—</span></dd>
          <dt>Favqulodda aloqa</dt><dd>{{ P.profile.emergency_name || '—' }} <a v-if="P.employee.emergency_phone" :href="`tel:${P.employee.emergency_phone}`">{{ P.employee.emergency_phone }}</a></dd>
          <dt>Tibbiy daftarcha</dt><dd :class="{ bad: P.profile.medical_expired }">{{ dmy(P.profile.medical_book_until) }}</dd>
          <dt>O'zi haqida</dt><dd class="pre">{{ P.profile.about || '—' }}</dd>
        </dl>
      </UiCard>
      <div class="col">
        <UiCard title="Ish sharoiti">
          <dl class="dl">
            <dt>Maosh</dt><dd><b>{{ money(P.employee.rate) }}</b> / {{ ({ monthly: 'oy', hourly: 'soat', shift: 'smena', percent: '% savdo' } as any)[P.employee.salary_type] }}</dd>
            <dt>Ishga kirgan</dt><dd>{{ dmy(P.employee.hire_date) }}</dd>
            <dt>Qayerdan kelgan</dt><dd>{{ P.application ? `Vakansiya: ${P.application.vacancy} (${P.application.source})` : (P.profile.source || '—') }}</dd>
            <dt>Karta</dt><dd>{{ P.employee.card_number || '—' }}</dd>
          </dl>
          <UiButton v-if="canEdit && P.employee.is_active" size="s" variant="ghost" @click="fire">Ishdan bo'shatish…</UiButton>
        </UiCard>
        <UiCard v-if="P.application?.answers?.length" title="Ariza javoblari">
          <div v-for="(x, i) in P.application.answers" :key="i" class="ans"><span>{{ x.q }}</span><b :class="{ bad: !x.ok }">{{ x.a || '—' }}</b></div>
        </UiCard>
        <UiCard title="Kayfiyat (smenadan keyin)">
          <div class="moods"><span v-for="(f, i) in P.feedback" :key="i" :title="`${dmy(f.date)} ${f.comment}`">{{ MOOD[f.mood] }}</span></div>
          <p v-if="!P.feedback.length" class="mut">Hali baho yo'q — /ketdim dan keyin bot so'raydi.</p>
        </UiCard>
      </div>
    </div>

    <!-- KPI -->
    <div v-else-if="tab === 'kpi'" class="two">
      <UiCard :title="`KPI · ${P.kpi.month}`" :subtitle="P.kpi.bonus_suggest ? `Tavsiya bonus: ${money(P.kpi.bonus_suggest)} so'm` : 'Ball — mavjud ko\'rsatkichlarning og\'irlikli o\'rtachasi'">
        <div v-for="(x, k) in P.kpi.parts" :key="k" class="kp">
          <span class="kl"><b>{{ x.label }}</b><small>{{ x.text }} · og'irlik {{ x.weight }}</small></span>
          <span class="kb"><i :style="{ width: x.value + '%' }" :class="x.value >= 85 ? 'a' : x.value >= 70 ? 'b' : x.value >= 50 ? 'c' : 'd'"></i></span>
          <b class="kv">{{ x.value }}</b>
        </div>
        <p v-if="!Object.keys(P.kpi.parts).length" class="mut">Bu oy uchun ma'lumot yo'q.</p>
        <div class="hist">
          <div v-for="h in P.kpi_history" :key="h.month" class="hb"><span class="bar"><i :style="{ height: (h.score ?? 0) + '%' }" :class="GTONE[h.grade]"></i></span><small>{{ h.month.slice(5) }}</small><b>{{ h.score ?? '—' }}</b></div>
        </div>
      </UiCard>
      <UiCard title="Menejer baholari">
        <template #actions><UiButton v-if="a.can('hr.review')" size="s" @click="newReview"><UiIcon name="star" :size="14" /> Baholash</UiButton></template>
        <div v-for="r in P.reviews" :key="r.id" class="rv">
          <header><b>{{ r.period }}</b><UiChip tone="info">{{ r.average }} / 5</UiChip><small>{{ r.reviewer }}</small></header>
          <div class="sc"><span v-for="(v, k) in r.scores" :key="k">{{ crit(String(k)) }}: <b>{{ '★'.repeat(v) }}</b></span></div>
          <p v-if="r.strengths">💪 {{ r.strengths }}</p><p v-if="r.improve">🔧 {{ r.improve }}</p><p v-if="r.goals">🎯 {{ r.goals }}</p>
        </div>
        <UiEmpty v-if="!P.reviews.length" title="Hali baho yo'q" text="Oyiga bir marta baholang — KPI ning 20%." />
      </UiCard>
    </div>

    <!-- ISH TARIXI -->
    <UiCard v-else-if="tab === 'history'" title="Oldingi ish joylari" subtitle="Nomzod anketasidan o'zi ko'chadi — qo'shimcha ma'lumot qo'shish mumkin">
      <template #actions><UiButton v-if="canEdit" size="s" @click="newWork"><UiIcon name="plus" :size="14" /> Qo'shish</UiButton></template>
      <div class="tl">
        <div v-for="w in P.work_history" :key="w.id" class="ti">
          <span class="dot"></span>
          <div><b>{{ w.company }}</b><span class="mut"> · {{ w.position || 'lavozim ko\'rsatilmagan' }}</span>
            <div class="mut">{{ w.start || '?' }} — {{ w.end || 'hozirgacha' }}<template v-if="w.reason_left"> · ketish sababi: {{ w.reason_left }}</template></div>
            <div v-if="w.reference_phone" class="mut">Tavsiya: <a :href="`tel:${w.reference_phone}`">{{ w.reference_phone }}</a></div>
            <div v-if="w.note">{{ w.note }}</div></div>
          <span class="sp"></span>
          <template v-if="canEdit"><UiButton size="s" variant="ghost" @click="wh = { ...w }"><UiIcon name="edit" :size="14" /></UiButton><UiButton size="s" variant="ghost" @click="delWork(w)"><UiIcon name="trash" :size="14" /></UiButton></template>
        </div>
        <UiEmpty v-if="!P.work_history.length" title="Ma'lumot yo'q" />
      </div>
    </UiCard>

    <!-- HUJJATLAR -->
    <UiCard v-else title="Hujjatlar" subtitle="Fayl yuklang yoki havola qo'ying (Google Drive) — baza tejaladi">
      <template #actions><UiButton v-if="canEdit" size="s" @click="newDoc"><UiIcon name="plus" :size="14" /> Hujjat</UiButton></template>
      <div v-for="x in P.documents" :key="x.id" class="doc">
        <span class="di"><UiIcon name="paperclip" :size="16" /></span>
        <span class="dn"><b>{{ x.title }}</b><small>{{ x.kind_label }}<template v-if="x.expires_on"> · muddati {{ dmy(x.expires_on) }}</template></small></span>
        <UiChip v-if="x.expired" tone="danger">muddati o'tgan</UiChip><UiChip v-else-if="x.expiring" tone="warn">tugayapti</UiChip>
        <a v-if="x.url" :href="x.url" target="_blank" rel="noopener" class="lnk">Ochish</a>
        <UiButton v-if="canEdit" size="s" variant="ghost" @click="delDoc(x)"><UiIcon name="trash" :size="14" /></UiButton>
      </div>
      <UiEmpty v-if="!P.documents.length" title="Hujjat yo'q" text="Mehnat shartnomasi va tibbiy daftarcha — birinchi navbatda." />
    </UiCard>

    <!-- DRAWERS -->
    <UiDrawer :open="!!edit" title="Shaxsiy ma'lumot" @close="edit = null">
      <template v-if="edit">
        <div class="g2"><UiInput v-model="edit.birth_date" type="date" label="Tug'ilgan sana" /><UiSelect v-model="edit.gender" label="Jinsi" :options="[{ value: '', label: '—' }, { value: 'm', label: 'Erkak' }, { value: 'f', label: 'Ayol' }]" /></div>
        <UiInput v-model="edit.address" label="Manzil" />
        <UiInput v-model="edit.education" label="Ma'lumoti" placeholder="Oshpazlik kolleji, 2019" />
        <UiInput v-model="edit.languages" label="Tillar (vergul bilan)" placeholder="o'zbek, rus" />
        <UiInput v-model="edit.skills" label="Ko'nikmalar (vergul bilan)" placeholder="tandir, kassa, latte-art" />
        <div class="g2"><UiInput v-model="edit.emergency_name" label="Favqulodda aloqa — kim" placeholder="Onasi" /><UiInput v-model="edit.emergency_phone" label="Uning telefoni" /></div>
        <UiInput v-model="edit.medical_book_until" type="date" label="Tibbiy daftarcha amal qiladi" />
        <label class="fld"><span>O'zi haqida</span><textarea v-model="edit.about" rows="4"></textarea></label>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="edit = null">Bekor</UiButton><UiButton variant="brand" @click="saveEdit">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!wh" :title="wh?.id ? 'Ish joyini o\'zgartirish' : 'Oldingi ish joyi'" @close="wh = null">
      <template v-if="wh">
        <UiInput v-model="wh.company" label="Ish joyi" placeholder="«Rayhon» restorani" />
        <UiInput v-model="wh.position" label="Lavozim" />
        <div class="g2"><UiInput v-model="wh.start" label="Boshlagan (yil yoki oy)" placeholder="2019-03" /><UiInput v-model="wh.end" label="Tugatgan" placeholder="bo'sh — hozirgacha" /></div>
        <UiInput v-model="wh.reason_left" label="Ketish sababi" />
        <UiInput v-model="wh.reference_phone" label="Tavsiya beruvchi telefon" />
        <UiInput v-model="wh.note" label="Izoh" />
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="wh = null">Bekor</UiButton><UiButton variant="brand" @click="saveWork">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!doc" title="Hujjat qo'shish" @close="doc = null">
      <template v-if="doc">
        <UiSelect v-model="doc.kind" label="Turi" :options="KINDS" />
        <UiInput v-model="doc.title" label="Nomi" placeholder="Mehnat shartnomasi №12" />
        <UiInput v-model="doc.url" label="Havola (ixtiyoriy)" placeholder="https://drive.google.com/…" />
        <label class="fld"><span>yoki fayl (15 MB gacha)</span><input type="file" @change="doc.file = ($event.target as HTMLInputElement).files?.[0] ?? null" /></label>
        <UiInput v-model="doc.expires_on" type="date" label="Amal qilish muddati (ixtiyoriy)" />
        <div v-if="upPct !== null" class="kb"><i class="b" :style="{ width: upPct + '%' }"></i></div>
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="doc = null">Bekor</UiButton><UiButton variant="brand" @click="saveDoc">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!rv" :title="`Baholash · ${rv?.month ?? ''}`" @close="rv = null">
      <template v-if="rv">
        <div v-for="c in P.criteria" :key="c.key" class="star">
          <span>{{ c.label }}</span>
          <span class="st"><button v-for="n in 5" :key="n" type="button" :class="{ on: rv.scores[c.key] >= n }" :aria-label="`${n} yulduz`" @click="rv.scores[c.key] = n">★</button></span>
        </div>
        <UiInput v-model="rv.strengths" label="Kuchli tomoni" placeholder="Mehmon bilan juda yaxshi muomala" />
        <UiInput v-model="rv.improve" label="Nimani yaxshilash kerak" placeholder="Kechikish" />
        <UiInput v-model="rv.goals" label="Keyingi oy maqsadi (xodimga Telegram'da boradi)" placeholder="O'rtacha chekni 85 000 ga chiqarish" />
      </template>
      <template #footer><span class="sp"></span><UiButton variant="ghost" @click="rv = null">Bekor</UiButton><UiButton variant="brand" @click="saveReview">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.pf { display: flex; flex-direction: column; gap: 16px; max-width: 1180px; }
.back { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-weight: 700; text-decoration: none; }
.hero { display: flex; gap: 18px; align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 18px; flex-wrap: wrap; }
.hi { flex: 1; min-width: 220px; } .hi h1 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; }
.hi p { margin: 4px 0 8px; color: var(--muted); } .hi a { color: var(--accent); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.kpibox { display: flex; flex-direction: column; align-items: center; min-width: 110px; padding: 12px 16px; border-radius: 16px; background: var(--surface-2); border: 1px solid var(--line); }
.kpibox span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; } .kpibox b { font-family: var(--font-display); font-size: 34px; line-height: 1.1; }
.kpibox em { font-style: normal; font-weight: 800; font-size: var(--fs-s); padding: 1px 10px; border-radius: 99px; background: var(--surface-3); }
.kpibox.ok em { background: var(--ok-tint); color: var(--ok); } .kpibox.info em { background: var(--info-tint); color: var(--info); }
.kpibox.warn em { background: var(--warn-tint); color: var(--warn-ink); } .kpibox.danger em { background: var(--danger-tint); color: var(--danger); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 10px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.two { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 16px; align-items: start; }
.col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.dl { display: grid; grid-template-columns: 150px 1fr; gap: 10px 14px; margin: 0; font-size: var(--fs-s); }
.dl dt { color: var(--muted); font-weight: 700; } .dl dd { margin: 0; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.dl dd.pre { white-space: pre-line; } .bad { color: var(--danger); font-weight: 700; }
.ans { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .ans span { color: var(--muted); }
.moods { display: flex; flex-wrap: wrap; gap: 6px; font-size: 24px; }
.mut { color: var(--muted); font-size: var(--fs-s); margin: 0; }
.kp { display: grid; grid-template-columns: minmax(0, 1fr) 140px 40px; gap: 12px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line-2); }
.kl { display: flex; flex-direction: column; } .kl small { color: var(--muted); font-size: var(--fs-xs); }
.kb { height: 8px; border-radius: 99px; background: var(--surface-3); overflow: hidden; display: block; }
.kb i { display: block; height: 100%; border-radius: 99px; background: var(--accent); }
.kb i.a { background: var(--ok); } .kb i.b { background: var(--info); } .kb i.c { background: var(--warn); } .kb i.d { background: var(--danger); }
.kv { text-align: right; font-variant-numeric: tabular-nums; }
.hist { display: flex; gap: 10px; align-items: flex-end; margin-top: 16px; height: 120px; }
.hb { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; }
.hb .bar { flex: 1; width: 100%; max-width: 36px; background: var(--surface-3); border-radius: 8px; display: flex; align-items: flex-end; overflow: hidden; }
.hb .bar i { width: 100%; border-radius: 8px; background: var(--series-mute); } .hb .bar i.ok { background: var(--ok); } .hb .bar i.info { background: var(--info); } .hb .bar i.warn { background: var(--warn); } .hb .bar i.danger { background: var(--danger); }
.hb small { color: var(--muted); font-size: var(--fs-xs); } .hb b { font-size: var(--fs-xs); }
.rv { padding: 10px 0; border-bottom: 1px solid var(--line-2); display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); }
.rv header { display: flex; gap: 8px; align-items: center; } .rv header small { color: var(--muted); margin-left: auto; }
.sc { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--muted); font-size: var(--fs-xs); } .sc b { color: var(--series-4); letter-spacing: 1px; }
.rv p { margin: 0; }
.tl { display: flex; flex-direction: column; }
.ti { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); align-items: flex-start; }
.dot { width: 12px; height: 12px; border-radius: 50%; background: var(--accent); margin-top: 4px; flex-shrink: 0; } .sp { flex: 1; }
.doc { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line-2); }
.di { width: 34px; height: 34px; border-radius: 10px; background: var(--surface-3); display: grid; place-items: center; color: var(--accent); }
.dn { flex: 1; display: flex; flex-direction: column; min-width: 0; } .dn small { color: var(--muted); font-size: var(--fs-xs); }
.lnk { color: var(--accent); font-weight: 700; text-decoration: none; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fld { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fld textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; font: inherit; background: var(--surface); color: var(--ink); }
.star { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 6px 0; font-size: var(--fs-s); font-weight: 600; }
.st button { border: 0; background: none; font-size: 26px; color: var(--line); cursor: pointer; padding: 0 2px; line-height: 1; } .st button.on { color: var(--series-4); }
@media (max-width: 900px) { .two { grid-template-columns: 1fr; } .dl { grid-template-columns: 120px 1fr; } .kp { grid-template-columns: minmax(0, 1fr) 80px 34px; } }
.acc { border: 1px solid var(--accent); background: var(--accent-tint); color: var(--accent); border-radius: 99px; padding: 3px 10px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; }
</style>
