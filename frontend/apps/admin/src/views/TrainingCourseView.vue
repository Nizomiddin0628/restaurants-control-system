<script setup lang="ts">
/** Kurs sahifasi (xodim): darslar ketma-ketligi, testlar, sertifikat. */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiChip, UiIcon, toast } from '@restopos/ui'
import { daysLeft, fmtDate, fmtDur } from '@/components/training/upload'
import '@/components/training/tr.css'

const route = useRoute(), router = useRouter()
const c = ref<any>(null)
onMounted(async () => {
  try { c.value = await api.get(`/training/my/courses/${route.params.id}`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); router.replace('/training') }
})
const due = computed(() => { const n = daysLeft(c.value?.due_at); return n === null ? null : n < 0 ? `${-n} kun kechikdi` : `${n} kun qoldi` })
function openLesson(l: any) { if (l.locked) { toast('Avval oldingi darsni tugating', 'info'); return } router.push(`/training/lesson/${l.id}`) }
function openQuiz(q: any) {
  if (q.locked) { toast(q.lesson_id ? 'Avval shu testga tegishli darsni tugating' : 'Avval barcha darslarni tugating', 'info'); return }
  if (q.attempts_left === 0) { toast('Urinishlar tugadi', 'danger'); return }
  router.push(`/training/quiz/${q.id}`)
}
</script>

<template>
  <div v-if="c" class="cv">
    <RouterLink to="/training" class="tr-back"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /> O'qitish</RouterLink>
    <header class="hero" :style="c.course.cover ? { backgroundImage: `linear-gradient(0deg, rgba(0,0,0,.72), rgba(0,0,0,.15)), url(${c.course.cover})` } : {}">
      <div class="chips">
        <UiChip v-if="c.course.category" tone="neutral">{{ c.course.category }}</UiChip>
        <UiChip v-if="c.status === 'completed'" tone="ok">Tugatildi</UiChip>
        <UiChip v-else-if="c.is_overdue" tone="danger">Kechikdi</UiChip>
      </div>
      <h2>{{ c.course.title }}</h2>
      <p v-if="c.course.description">{{ c.course.description }}</p>
      <div class="prow"><div class="tr-bar"><i :style="{ width: c.progress + '%' }"></i></div><b>{{ c.progress }}%</b></div>
      <div class="facts">
        <span>{{ c.lessons_done }}/{{ c.lessons_total }} dars</span>
        <span v-if="c.due_at && c.status !== 'completed'">Muddat: {{ fmtDate(c.due_at) }} · {{ due }}</span>
        <span v-if="c.course.responsible">Mas'ul: {{ c.course.responsible.full_name }}</span>
        <span>O'tish bali: {{ c.course.pass_score }}%</span>
      </div>
    </header>

    <RouterLink v-if="c.certificate_no" :to="`/training/certificate/${c.enrollment_id}`" class="certbar">🏆 <b>Sertifikat tayyor</b> · № {{ c.certificate_no }} <UiIcon name="chevron" :size="16" style="transform: rotate(-90deg)" /></RouterLink>

    <section class="block">
      <h3>Darslar</h3>
      <button v-for="(l, i) in c.lessons" :key="l.id" class="ls" :class="{ locked: l.locked, done: l.done }" type="button" @click="openLesson(l)">
        <span class="num">
          <svg v-if="l.done" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10" /></svg>
          <svg v-else-if="l.locked" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
          <template v-else>{{ i + 1 }}</template>
        </span>
        <span class="lt"><b>{{ l.title }}</b>
          <small>{{ l.has_video ? '🎬 Video' : '📄 Matn' }}<template v-if="l.duration_seconds"> · {{ fmtDur(l.duration_seconds) }}</template><template v-if="l.opened && !l.done && l.has_video"> · {{ l.percent }}% ko'rildi</template></small>
        </span>
        <UiIcon name="chevron" :size="16" style="transform: rotate(-90deg)" />
      </button>
    </section>

    <section v-if="c.quizzes.length" class="block">
      <h3>Testlar</h3>
      <button v-for="q in c.quizzes" :key="q.id" class="ls" :class="{ locked: q.locked, done: q.passed }" type="button" @click="openQuiz(q)">
        <span class="num quiz">{{ q.passed ? '✓' : '?' }}</span>
        <span class="lt"><b>{{ q.title }}</b>
          <small>{{ q.questions_count }} savol<template v-if="q.time_limit_seconds"> · {{ Math.round(q.time_limit_seconds / 60) }} daqiqa</template> · o'tish {{ q.pass_score }}%<template v-if="q.best_score !== null"> · eng yaxshi natija {{ q.best_score }}%</template><template v-if="q.attempts_left !== null"> · {{ q.attempts_left }} urinish qoldi</template></small>
        </span>
        <UiChip v-if="q.passed" tone="ok">O'tdi</UiChip>
        <UiChip v-else-if="q.best_score !== null" tone="danger">Qayta topshiring</UiChip>
        <UiIcon v-else name="chevron" :size="16" />
      </button>
    </section>
  </div>
</template>

<style scoped>
.cv { display: flex; flex-direction: column; gap: 14px; max-width: 820px; width: 100%; margin: 0 auto; }
.hero { border-radius: 18px; padding: 22px; color: #fff; background: linear-gradient(135deg, #3a2f22, #8a6d3b) center / cover no-repeat; display: flex; flex-direction: column; gap: 10px; min-height: 180px; justify-content: flex-end; }
.hero h2 { margin: 0; font-family: var(--font-display); font-size: 26px; font-weight: 800; letter-spacing: -.02em; }
.hero p { margin: 0; opacity: .9; max-width: 60ch; }
.chips { display: flex; gap: 6px; }
.prow { display: flex; align-items: center; gap: 10px; } .prow .tr-bar { flex: 1; background: rgba(255,255,255,.25); }
.facts { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; opacity: .92; }
.certbar { display: flex; align-items: center; gap: 8px; padding: 14px 16px; border-radius: 14px; background: var(--tr-gold-tint); color: var(--ink); text-decoration: none; }
.certbar b { flex: 0; white-space: nowrap; }
.block { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 8px; display: flex; flex-direction: column; }
.block h3 { margin: 8px 10px 6px; font-size: 16px; font-weight: 800; }
.ls { display: flex; align-items: center; gap: 12px; padding: 12px 10px; border: 0; background: none; border-radius: 12px; cursor: pointer; text-align: left; font: inherit; color: inherit; min-height: 60px; }
.ls:hover { background: var(--surface-3); }
.num { width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; font-weight: 800; background: var(--tr-gold-tint); color: var(--tr-gold); flex-shrink: 0; }
.ls.done .num { background: var(--tr-green); color: #fff; }
.ls.locked { opacity: .55; } .ls.locked .num { background: var(--surface-3); color: var(--muted); }
.lt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; } .lt b { font-size: 15px; } .lt small { color: var(--muted); font-size: 12px; }
@media (max-width: 600px) { .hero { padding: 18px; } .hero h2 { font-size: 22px; } }
</style>
