<script setup lang="ts">
/** Hisobot: har xodim — kurs, dars, video, test, topshiriq, standart. Qatorni bossangiz — batafsil (qaysi videoni necha % ko'rgan). */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiChip, UiDrawer, UiEmpty, UiInput } from '@restopos/ui'
import { fmtDate, fmtDateTime, fmtDur, initials, SUB_STATUS } from './upload'

const R = ref<any>(null)
const q = ref('')
const filter = ref<'all' | 'overdue' | 'idle' | 'review'>('all')
const detail = ref<any>(null)
onMounted(async () => { R.value = await api.get('/training/report/summary') })
const rows = computed(() => (R.value?.rows ?? []).filter((r: any) => {
  const s = q.value.trim().toLowerCase()
  if (s && !r.user.full_name.toLowerCase().includes(s) && !r.user.phone.includes(s)) return false
  if (filter.value === 'overdue') return r.courses_overdue > 0
  if (filter.value === 'idle') return r.lessons_done === 0 && r.lessons_total > 0
  if (filter.value === 'review') return r.assignments_review > 0
  return true
}))
async function open(r: any) { detail.value = await api.get(`/training/report/users/${r.user.id}`) }
const ST: Record<string, any> = { assigned: ['Boshlamagan', 'neutral'], in_progress: ["O'qiyapti", 'info'], completed: ['Tugatgan', 'ok'] }
const hours = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)} soat` : `${Math.round(s / 60)} daq`)
</script>

<template>
  <div v-if="R" class="rp">
    <div class="kpis">
      <div class="k"><b>{{ R.kpis.completion }}%</b><span>Umumiy tugatish</span><small>{{ R.kpis.completed }}/{{ R.kpis.enrollments }} kurs</small></div>
      <div class="k" :class="{ warn: R.kpis.overdue }"><b>{{ R.kpis.overdue }}</b><span>Muddati o'tgan</span></div>
      <div class="k"><b>{{ R.kpis.not_started }}</b><span>Boshlamagan</span></div>
      <div class="k"><b>{{ R.kpis.avg_score ?? '—' }}<small v-if="R.kpis.avg_score !== null">%</small></b><span>O'rtacha test bali</span></div>
      <div class="k" :class="{ info: R.kpis.to_review }"><b>{{ R.kpis.to_review }}</b><span>Tekshiruvni kutmoqda</span></div>
      <div class="k"><b>{{ R.kpis.standards_percent ?? '—' }}<small v-if="R.kpis.standards_percent !== null">%</small></b><span>Standartlar bilan tanishgan</span></div>
    </div>
    <div class="bar">
      <UiInput v-model="q" placeholder="Xodimni qidirish" />
      <div class="tr-seg f">
        <button :class="{ on: filter === 'all' }" @click="filter = 'all'">Hammasi</button>
        <button :class="{ on: filter === 'overdue' }" @click="filter = 'overdue'">Kechikkan</button>
        <button :class="{ on: filter === 'idle' }" @click="filter = 'idle'">Boshlamagan</button>
        <button :class="{ on: filter === 'review' }" @click="filter = 'review'">Tekshiruvda</button>
      </div>
    </div>
    <div class="tbl">
      <div class="th"><span>Xodim</span><span>Progress</span><span>Kurs</span><span>Dars / video</span><span>Test</span><span>Topshiriq</span><span>Standart</span><span>Oxirgi faollik</span></div>
      <button v-for="r in rows" :key="r.user.id" class="tr" type="button" @click="open(r)">
        <span class="u"><i class="ava">{{ initials(r.user.full_name) }}</i><span><b>{{ r.user.full_name }}</b><small>{{ r.roles.join(', ') }}</small></span></span>
        <span class="p"><div class="tr-bar"><i :style="{ width: r.progress + '%' }"></i></div><b>{{ r.progress }}%</b></span>
        <span data-l="Kurs"><b>{{ r.courses_done }}</b>/{{ r.courses_total }}<em v-if="r.courses_overdue" class="late"> · {{ r.courses_overdue }} kechikkan</em></span>
        <span data-l="Dars"><b>{{ r.lessons_done }}</b>/{{ r.lessons_total }}<small v-if="r.videos_total"> · 🎬 {{ r.videos_watched }}/{{ r.videos_total }}</small></span>
        <span data-l="Test"><b>{{ r.quizzes_passed }}</b>/{{ r.quizzes_total }}<small v-if="r.avg_score !== null"> · {{ r.avg_score }}%</small></span>
        <span data-l="Topshiriq"><b>{{ r.assignments_done }}</b>/{{ r.assignments_total }}<em v-if="r.assignments_review" class="rv"> · {{ r.assignments_review }} tekshiruvda</em></span>
        <span data-l="Standart" :class="{ late: r.standards_acked < r.standards_total }"><b>{{ r.standards_acked }}</b>/{{ r.standards_total }}</span>
        <span data-l="Faollik" class="la">{{ r.last_activity ? fmtDateTime(r.last_activity) : 'hali yo\'q' }}</span>
      </button>
      <UiEmpty v-if="!rows.length" title="Hech kim topilmadi" />
    </div>

    <UiDrawer :open="!!detail" :title="detail?.user.full_name ?? ''" width="760px" @close="detail = null">
      <template v-if="detail">
        <div class="dk">
          <div><b>{{ detail.summary.progress }}%</b><span>Progress</span></div>
          <div><b>{{ detail.summary.lessons_done }}/{{ detail.summary.lessons_total }}</b><span>Dars</span></div>
          <div><b>{{ hours(detail.summary.watch_seconds) }}</b><span>Video ko'rgan</span></div>
          <div><b>{{ detail.summary.avg_score ?? '—' }}{{ detail.summary.avg_score !== null ? '%' : '' }}</b><span>Test</span></div>
        </div>
        <section v-for="c in detail.courses" :key="c.enrollment_id" class="dc">
          <header><b>{{ c.course.title }}</b><UiChip :tone="c.is_overdue ? 'danger' : ST[c.status][1]">{{ c.is_overdue ? 'Kechikdi' : ST[c.status][0] }}</UiChip><span class="pct">{{ c.progress }}%</span></header>
          <small class="tr-muted">Biriktirilgan muddat: {{ fmtDate(c.due_at) }}<template v-if="c.completed_at"> · tugatgan {{ fmtDate(c.completed_at) }}</template><template v-if="c.certificate_no"> · sertifikat № {{ c.certificate_no }}</template></small>
          <div v-for="l in c.lessons" :key="l.id" class="dl">
            <span class="dot" :class="{ ok: l.done, mid: !l.done && l.percent > 0 }"></span>
            <span class="lt">{{ l.title }}</span>
            <span class="lm">{{ l.has_video ? `🎬 ${l.percent}%` : l.done ? '📄 o\'qidi' : '📄 —' }}<template v-if="l.watched_seconds"> · {{ fmtDur(l.watched_seconds) }}</template><template v-if="l.views"> · {{ l.views }} marta ochgan</template></span>
          </div>
          <div v-for="qz in c.quizzes" :key="'q' + qz.id" class="dl">
            <span class="dot" :class="{ ok: qz.passed, bad: !qz.passed && qz.attempts }"></span><span class="lt">❓ {{ qz.title }}</span>
            <span class="lm">{{ qz.attempts ? `eng yaxshi ${qz.best}% · ${qz.attempts} urinish` : 'topshirmagan' }}</span>
          </div>
        </section>
        <section v-if="detail.assignments.length" class="dc">
          <header><b>Topshiriqlar</b></header>
          <div v-for="s in detail.assignments" :key="s.id" class="dl"><span class="lt">{{ s.assignment.title }}</span><UiChip :tone="SUB_STATUS[s.status].tone">{{ SUB_STATUS[s.status].label }}</UiChip></div>
        </section>
        <section v-if="detail.standards.length" class="dc">
          <header><b>Standartlar</b></header>
          <div v-for="s in detail.standards" :key="s.id" class="dl"><span class="lt">{{ s.title }} · v{{ s.version }}</span><UiChip :tone="s.acked_at ? 'ok' : 'danger'">{{ s.acked_at ? fmtDate(s.acked_at) : 'Tanishmagan' }}</UiChip></div>
        </section>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.rp { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.k { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 14px; display: flex; flex-direction: column; gap: 2px; }
.k b { font-size: 24px; font-weight: 800; font-family: var(--font-display); } .k b small { font-size: 14px; } .k span { font-size: 12px; color: var(--muted); font-weight: 700; } .k > small { font-size: 12px; color: var(--muted); }
.k.warn b { color: var(--danger); } .k.info b { color: var(--info); }
.bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; } .bar > :first-child { flex: 1; min-width: 200px; } .f { flex: 0 1 auto; }
.tbl { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
.th, .tr { display: grid; grid-template-columns: 1.6fr 1.1fr .8fr 1fr .8fr 1fr .6fr 1fr; gap: 10px; align-items: center; padding: 10px 14px; }
.th { font-size: 12px; font-weight: 800; color: var(--muted); background: var(--surface-2); border-bottom: 1px solid var(--line); }
.tr { width: 100%; border: 0; border-bottom: 1px solid var(--line-2); background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; font-size: 14px; }
.tr:hover { background: var(--surface-2); }
.u { display: flex; align-items: center; gap: 10px; min-width: 0; } .u > span { display: flex; flex-direction: column; min-width: 0; } .u small { color: var(--muted); font-size: 12px; }
.ava { width: 34px; height: 34px; border-radius: 10px; background: var(--accent-tint); color: var(--accent); display: grid; place-items: center; font-style: normal; font-weight: 800; font-size: 12px; flex-shrink: 0; }
.p { display: flex; align-items: center; gap: 8px; } .p .tr-bar { flex: 1; }
.late { color: var(--danger); font-style: normal; font-weight: 700; } .rv { color: var(--info); font-style: normal; font-weight: 700; }
small { color: var(--muted); } .la { font-size: 12px; color: var(--muted); }
.dk { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.dk div { background: var(--surface-2); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; } .dk b { font-size: 18px; } .dk span { font-size: 12px; color: var(--muted); }
.dc { border: 1px solid var(--line); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 6px; }
.dc header { display: flex; align-items: center; gap: 8px; } .dc header b { flex: 1; } .pct { font-weight: 800; }
.dl { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line-2); font-size: 14px; }
.lt { flex: 1; min-width: 0; } .lm { color: var(--muted); font-size: 12px; text-align: right; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--line); flex-shrink: 0; } .dot.ok { background: var(--tr-green, #1E9E5A); } .dot.mid { background: var(--warn); } .dot.bad { background: var(--danger); }
@media (max-width: 1200px) { .kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) {
  .th { display: none; }
  .tr { grid-template-columns: 1fr 1fr; gap: 6px 12px; padding: 12px 14px; }
  .u, .p { grid-column: 1 / -1; }
  .tr > span[data-l]::before { content: attr(data-l) ': '; color: var(--muted); font-size: 12px; }
}
@media (max-width: 600px) { .kpis { grid-template-columns: repeat(2, 1fr); } .dk { grid-template-columns: repeat(2, 1fr); } .dl { flex-wrap: wrap; } .lm { width: 100%; text-align: left; padding-left: 20px; } }
</style>
