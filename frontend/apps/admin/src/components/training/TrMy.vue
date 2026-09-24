<script setup lang="ts">
/**
 * Xodim kabineti: mening kurslarim · topshiriqlar · standartlar · sertifikatlar + umumiy progress.
 * Telefon uchun birinchi navbatda (katta tugmalar, kam matn).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiChip, UiDropzone, UiEmpty, UiIcon, toast } from '@restopos/ui'
import MediaView from './MediaView.vue'
import { daysLeft, fmtDate, SUB_STATUS, uploadWithProgress } from './upload'
import './tr.css'

type Sub = 'courses' | 'assignments' | 'standards' | 'certs'
const route = useRoute(), router = useRouter()
const sub = ref<Sub>((route.query.sub as Sub) || 'courses')
watch(sub, (v) => router.replace({ query: { ...route.query, sub: v } }))

const home = ref<any>(null)
const subs = ref<any[]>([])
const stds = ref<any[]>([])
const openSub = ref<number | null>(null)
const texts = ref<Record<number, string>>({})
const upPct = ref<Record<number, number>>({})

async function load() {
  const [h, a, s] = await Promise.all([api.get('/training/my'), api.get('/training/my/assignments'), api.get('/training/my/standards')])
  home.value = h; subs.value = a; stds.value = s
}
onMounted(load)

const first = computed(() => (home.value?.user.full_name || '').split(' ')[0])
const openAssign = computed(() => subs.value.filter(s => s.status === 'todo' || s.status === 'rejected').length)
const pendingStd = computed(() => stds.value.filter(s => !s.acked_at).length)
const S = computed(() => home.value?.summary ?? {})
const pct = computed(() => {
  const s = S.value; const tot = (s.lessons_total || 0) + (s.quizzes_total || 0)
  return tot ? Math.round((100 * ((s.lessons_done || 0) + (s.quizzes_passed || 0))) / tot) : 0
})
const R = 34, C = 2 * Math.PI * R

function btnLabel(c: any) { return c.status === 'completed' ? 'Qayta ko\'rish' : c.progress > 0 ? 'Davom ettirish' : 'Boshlash' }
function go(c: any) {
  if (c.status !== 'completed' && c.next_lesson_id) router.push(`/training/lesson/${c.next_lesson_id}`)
  else router.push(`/training/course/${c.course.id}`)
}

async function addProof(s: any, files: File[]) {
  for (const f of files) {
    try {
      upPct.value[s.id] = 0
      const r = await uploadWithProgress(`/training/my/assignments/${s.id}/files`, f, (p) => (upPct.value[s.id] = p))
      Object.assign(s, r)
    } catch (e: any) { toast(e.detail ?? 'Yuklanmadi', 'danger') } finally { delete upPct.value[s.id] }
  }
}
async function delProof(s: any, f: any) {
  try { await api.del(`/training/my/submission-files/${f.id}`); s.files = s.files.filter((x: any) => x.id !== f.id) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function submitSub(s: any) {
  try { Object.assign(s, await api.post(`/training/my/assignments/${s.id}/submit`, { text: texts.value[s.id] ?? s.text ?? '' })); toast('Topshirildi — mas\'ul tekshiradi'); openSub.value = null }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function ack(s: any) {
  try { Object.assign(s, await api.post(`/training/my/standards/${s.id}/ack`)); toast('Tasdiqlandi ✓') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const dueText = (d?: string | null) => { const n = daysLeft(d); if (n === null) return ''; return n < 0 ? `${-n} kun kechikdi` : n === 0 ? 'Bugun tugaydi' : `${n} kun qoldi` }
</script>

<template>
  <div v-if="home" class="my">
    <section class="hello">
      <h2>Salom, {{ first }}! 👋</h2>
      <p class="tr-muted">Bugun o'qishingiz kerak bo'lgan darslar</p>
    </section>

    <div class="layout">
      <div class="col">
        <nav class="tr-seg">
          <button :class="{ on: sub === 'courses' }" @click="sub = 'courses'">Mening kurslarim</button>
          <button :class="{ on: sub === 'assignments' }" @click="sub = 'assignments'">Topshiriqlar <span v-if="openAssign" class="tr-badge">{{ openAssign }}</span></button>
          <button :class="{ on: sub === 'standards' }" @click="sub = 'standards'">Standartlar <span v-if="pendingStd" class="tr-badge">{{ pendingStd }}</span></button>
          <button :class="{ on: sub === 'certs' }" @click="sub = 'certs'">Sertifikatlar</button>
        </nav>

        <!-- KURSLAR -->
        <div v-if="sub === 'courses'" class="cards">
          <article v-for="c in home.courses" :key="c.enrollment_id" class="course">
            <button class="cover" type="button" :style="c.course.cover ? { backgroundImage: `url(${c.course.cover})` } : {}" @click="go(c)">
              <span class="play"><svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg></span>
              <span v-if="c.status === 'completed'" class="done-badge">✓ Tugatildi</span>
              <span v-else-if="c.is_overdue" class="late-badge">Kechikdi</span>
            </button>
            <div class="cbody">
              <RouterLink :to="`/training/course/${c.course.id}`" class="ct">{{ c.course.title }}</RouterLink>
              <div class="prow"><div class="tr-bar"><i :style="{ width: c.progress + '%' }"></i></div><small>{{ c.lessons_done }}/{{ c.lessons_total }} dars</small></div>
              <div class="meta">
                <UiChip v-if="c.course.category" tone="neutral">{{ c.course.category }}</UiChip>
                <UiChip v-if="c.course.is_mandatory && c.status !== 'completed'" tone="warn">Majburiy</UiChip>
                <span v-if="c.due_at && c.status !== 'completed'" :class="{ late: c.is_overdue }" class="due">{{ dueText(c.due_at) }}</span>
              </div>
              <button class="tr-btn block" type="button" @click="go(c)">{{ btnLabel(c) }}</button>
            </div>
          </article>
          <UiEmpty v-if="!home.courses.length" title="Hozircha kurs yo'q" text="Rahbaringiz kurs biriktirganda shu yerda paydo bo'ladi." />
        </div>

        <!-- TOPSHIRIQLAR -->
        <div v-else-if="sub === 'assignments'" class="list">
          <article v-for="s in subs" :key="s.id" class="asg" :class="{ open: openSub === s.id }">
            <button class="ah" type="button" @click="openSub = openSub === s.id ? null : s.id">
              <span class="ai" :class="s.status"><UiIcon :name="s.status === 'approved' ? 'check' : s.status === 'rejected' ? 'repeat' : 'camera'" :size="18" /></span>
              <span class="at"><b>{{ s.assignment.title }}</b><small>{{ s.assignment.due_at ? 'Muddat: ' + fmtDate(s.assignment.due_at) : 'Muddatsiz' }}<template v-if="s.assignment.responsible"> · Mas'ul: {{ s.assignment.responsible.full_name }}</template></small></span>
              <UiChip :tone="s.assignment.is_overdue ? 'danger' : SUB_STATUS[s.status].tone">{{ s.assignment.is_overdue ? 'Kechikdi' : SUB_STATUS[s.status].label }}</UiChip>
            </button>
            <div v-if="openSub === s.id" class="ab">
              <p v-if="s.assignment.description">{{ s.assignment.description }}</p>
              <MediaView :media="s.assignment.media_view" label="Namunani ochish" />
              <div v-if="s.status === 'rejected'" class="note bad"><b>Qaytarildi:</b> {{ s.review_note }}</div>
              <div v-if="s.status === 'approved' && s.review_note" class="note good"><b>Izoh:</b> {{ s.review_note }}</div>
              <div class="proofs">
                <div v-for="f in s.files" :key="f.id" class="pf">
                  <img v-if="f.is_image" :src="f.url" alt="Dalil" /><video v-else-if="f.is_video" :src="f.url" muted playsinline></video><a v-else :href="f.url" target="_blank">Fayl</a>
                  <button v-if="s.status === 'todo' || s.status === 'rejected'" class="rm" type="button" aria-label="O'chirish" @click="delProof(s, f)">✕</button>
                </div>
              </div>
              <template v-if="s.status === 'todo' || s.status === 'rejected'">
                <div v-if="upPct[s.id] !== undefined" class="up"><div class="tr-bar"><i :style="{ width: upPct[s.id] + '%' }"></i></div><small>Yuklanmoqda… {{ upPct[s.id] }}%</small></div>
                <UiDropzone accept="image/*,video/*" multiple capture label="📷 Rasm yoki video dalil" hint="Telefonda kamera ochiladi" @files="(f) => addProof(s, f)" />
                <textarea v-model="texts[s.id]" class="ta" rows="2" placeholder="Izoh (ixtiyoriy)"></textarea>
                <button class="tr-btn block" type="button" @click="submitSub(s)">Topshirish</button>
              </template>
              <p v-else-if="s.status === 'submitted'" class="tr-muted">Mas'ul tekshirmoqda. Natija Telegram va shu yerda chiqadi.</p>
            </div>
          </article>
          <UiEmpty v-if="!subs.length" title="Topshiriq yo'q" text="Yangi topshiriq kelsa shu yerda chiqadi." />
        </div>

        <!-- STANDARTLAR -->
        <div v-else-if="sub === 'standards'" class="list">
          <article v-for="s in stds" :key="s.id" class="std" :class="{ ok: s.acked_at }">
            <header><span class="si"><UiIcon name="shield" :size="18" /></span><div><b>{{ s.title }}</b><small>{{ s.category }} · v{{ s.version }}</small></div></header>
            <p class="sb">{{ s.body }}</p>
            <MediaView :media="s.file_view" label="Hujjatni ochish" />
            <div v-if="s.acked_at" class="acked">✓ Tanishgansiz · {{ fmtDate(s.acked_at) }}</div>
            <button v-else class="tr-btn block" type="button" @click="ack(s)">O'qidim, tanishdim</button>
          </article>
          <UiEmpty v-if="!stds.length" title="Standart yo'q" />
        </div>

        <!-- SERTIFIKATLAR -->
        <div v-else class="list">
          <RouterLink v-for="c in home.certificates" :key="c.enrollment_id" :to="`/training/certificate/${c.enrollment_id}`" class="cert">
            <span class="trophy">🏆</span><div><b>{{ c.course_title }}</b><small>№ {{ c.certificate_no }} · {{ fmtDate(c.completed_at) }}</small></div><UiIcon name="chevron" :size="16" style="transform: rotate(-90deg)" />
          </RouterLink>
          <UiEmpty v-if="!home.certificates.length" title="Hali sertifikat yo'q" text="Kursni to'liq tugatib, testdan o'tsangiz — sertifikat beriladi." />
        </div>
      </div>

      <aside class="prog">
        <h3>Mening progressim</h3>
        <div class="ring-row">
          <svg class="ring" viewBox="0 0 80 80" width="96" height="96" role="img" :aria-label="`${pct}%`">
            <circle cx="40" cy="40" :r="R" fill="none" stroke="var(--tr-track)" stroke-width="8" />
            <circle cx="40" cy="40" :r="R" fill="none" stroke="var(--tr-green)" stroke-width="8" stroke-linecap="round"
                    :stroke-dasharray="C" :stroke-dashoffset="C * (1 - pct / 100)" transform="rotate(-90 40 40)" />
            <text x="40" y="45" text-anchor="middle" font-size="16" font-weight="800" fill="currentColor">{{ pct }}%</text>
          </svg>
          <div class="nums">
            <b>{{ S.lessons_done }} / {{ S.lessons_total }} dars</b>
            <span>{{ S.quizzes_total }} ta testdan {{ S.quizzes_passed }} tasi</span>
            <span v-if="S.videos_total">{{ S.videos_watched }}/{{ S.videos_total }} video ko'rilgan</span>
          </div>
        </div>
        <div class="mini">
          <div><b>{{ S.courses_done }}/{{ S.courses_total }}</b><span>Kurs</span></div>
          <div><b>{{ S.avg_score ?? '—' }}<small v-if="S.avg_score !== null">%</small></b><span>O'rtacha ball</span></div>
          <div :class="{ warn: S.courses_overdue }"><b>{{ S.courses_overdue }}</b><span>Kechikkan</span></div>
          <div><b>{{ S.standards_acked }}/{{ S.standards_total }}</b><span>Standart</span></div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.my { display: flex; flex-direction: column; gap: 16px; }
.hello h2 { margin: 0; font-family: var(--font-display); font-size: var(--fs-2xl); font-weight: 800; letter-spacing: -.02em; }
.hello p { margin: 4px 0 0; }
.layout { display: grid; grid-template-columns: 1fr 300px; gap: 20px; align-items: start; }
.col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
.course { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; }
.cover { position: relative; aspect-ratio: 16 / 9; border: 0; cursor: pointer; background: linear-gradient(135deg, #3a2f22, #8a6d3b) center / cover no-repeat; display: grid; place-items: center; }
.play { width: 54px; height: 54px; border-radius: 50%; background: rgba(0,0,0,.45); color: #fff; display: grid; place-items: center; border: 2px solid rgba(255,255,255,.8); padding-left: 3px; }
.done-badge, .late-badge { position: absolute; top: 10px; left: 10px; padding: 4px 10px; border-radius: 99px; font-size: 12px; font-weight: 800; background: var(--tr-green); color: #fff; }
.late-badge { background: var(--danger); }
.cbody { padding: 14px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.ct { font-weight: 800; font-size: 16px; color: var(--ink); text-decoration: none; }
.prow { display: flex; align-items: center; gap: 10px; } .prow .tr-bar { flex: 1; } .prow small { color: var(--muted); font-weight: 700; white-space: nowrap; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: auto; }
.due { font-size: 12px; font-weight: 700; color: var(--muted); } .due.late { color: var(--danger); }
.prog { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px; display: flex; flex-direction: column; gap: 14px; position: sticky; top: calc(var(--topbar-h) + 16px); }
.prog h3 { margin: 0; font-size: 17px; font-weight: 800; }
.ring-row { display: flex; align-items: center; gap: 16px; }
.nums { display: flex; flex-direction: column; gap: 4px; } .nums b { font-size: 17px; } .nums span { color: var(--muted); font-size: 13px; }
.mini { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mini div { background: var(--surface-2); border: 1px solid var(--line-2); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; }
.mini b { font-size: 18px; font-weight: 800; } .mini span { font-size: 12px; color: var(--muted); } .mini .warn b { color: var(--danger); }
.list { display: flex; flex-direction: column; gap: 10px; }
.asg, .std { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
.ah { width: 100%; display: flex; align-items: center; gap: 12px; padding: 14px; background: none; border: 0; cursor: pointer; text-align: left; font: inherit; color: inherit; }
.ai, .si { width: 38px; height: 38px; border-radius: 10px; display: grid; place-items: center; background: var(--tr-gold-tint); color: var(--tr-gold); flex-shrink: 0; }
.ai.approved { background: var(--tr-green-tint); color: var(--tr-green); } .ai.rejected { background: var(--danger-tint); color: var(--danger); }
.at { flex: 1; min-width: 0; display: flex; flex-direction: column; } .at b { font-size: 15px; } .at small { color: var(--muted); font-size: 12px; }
.ab { padding: 0 14px 14px; display: flex; flex-direction: column; gap: 10px; } .ab p { margin: 0; color: var(--ink-2); }
.media { width: 100%; max-height: 320px; object-fit: contain; border-radius: 12px; background: #000; }
img.media { background: var(--surface-3); }
.note { padding: 10px 12px; border-radius: 10px; font-size: 14px; } .note.bad { background: var(--danger-tint); color: var(--danger); } .note.good { background: var(--tr-green-tint); color: var(--tr-green); }
.proofs { display: flex; flex-wrap: wrap; gap: 8px; }
.pf { position: relative; width: 88px; height: 88px; border-radius: 10px; overflow: hidden; background: var(--surface-3); display: grid; place-items: center; }
.pf img, .pf video { width: 100%; height: 100%; object-fit: cover; }
.rm { position: absolute; top: 4px; right: 4px; width: 24px; height: 24px; border-radius: 50%; border: 0; background: rgba(0,0,0,.6); color: #fff; cursor: pointer; }
.up { display: flex; flex-direction: column; gap: 4px; } .up small { color: var(--muted); }
.ta { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 10px; padding: 10px; font: inherit; background: var(--surface); color: var(--ink); resize: vertical; }
.std { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.std header { display: flex; align-items: center; gap: 12px; } .std header div { display: flex; flex-direction: column; } .std header small { color: var(--muted); font-size: 12px; }
.std.ok .si { background: var(--tr-green-tint); color: var(--tr-green); }
.sb { margin: 0; white-space: pre-line; color: var(--ink-2); line-height: 1.5; }
.file { color: var(--accent); font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
.acked { color: var(--tr-green); font-weight: 800; font-size: 14px; }
.cert { display: flex; align-items: center; gap: 12px; padding: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; color: inherit; text-decoration: none; }
.cert div { flex: 1; display: flex; flex-direction: column; } .cert small { color: var(--muted); }
.trophy { font-size: 28px; }
@media (max-width: 1024px) { .layout { grid-template-columns: 1fr; } .prog { position: static; } }
@media (max-width: 600px) { .cards { grid-template-columns: 1fr; } .tr-seg button { flex: none; } }
</style>
