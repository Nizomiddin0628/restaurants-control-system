<script setup lang="ts">
/** Test: bittadan savol, taymer, natija (92% · 9/10) va javoblarni ko'rib chiqish. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiIcon, toast } from '@restopos/ui'
import { fmtDur } from '@/components/training/upload'
import '@/components/training/tr.css'

const route = useRoute(), router = useRouter()
const A = ref<any>(null)
const i = ref(0)
const answers = ref<Record<string, string[]>>({})
const left = ref(0)
const result = ref<any>(null)
const showReview = ref(false)
const sending = ref(false)
let timer: number | undefined

async function start() {
  result.value = null; showReview.value = false; i.value = 0; answers.value = {}
  try { A.value = await api.post(`/training/my/quizzes/${route.params.id}/start`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); router.back(); return }
  const lim = A.value.quiz.time_limit_seconds
  if (lim) {
    const end = Date.now() + lim * 1000
    left.value = lim
    clearInterval(timer)
    timer = window.setInterval(() => { left.value = Math.max(0, Math.round((end - Date.now()) / 1000)); if (left.value === 0) { clearInterval(timer); toast('Vaqt tugadi', 'info'); finish() } }, 500)
  }
}
onMounted(start)
onBeforeUnmount(() => clearInterval(timer))

const Q = computed(() => A.value?.questions[i.value])
const total = computed(() => A.value?.questions.length ?? 0)
const chosen = (oid: string) => (answers.value[String(Q.value.id)] ?? []).includes(oid)
function pick(oid: string) {
  const k = String(Q.value.id)
  if (Q.value.multiple) { const cur = new Set(answers.value[k] ?? []); cur.has(oid) ? cur.delete(oid) : cur.add(oid); answers.value[k] = [...cur] }
  else answers.value[k] = [oid]
}
const answered = computed(() => (answers.value[String(Q.value?.id)] ?? []).length > 0)
function next() { if (i.value < total.value - 1) i.value++; else finish() }
async function finish() {
  if (sending.value || result.value) return
  sending.value = true; clearInterval(timer)
  try { result.value = await api.post(`/training/my/attempts/${A.value.attempt_id}/submit`, { answers: answers.value }) }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { sending.value = false }
}
const courseId = computed(() => A.value?.quiz.course_id)
const optText = (q: any, id: string) => q.options.find((o: any) => o.id === id)?.text ?? id
</script>

<template>
  <div class="qv">
    <!-- SAVOL -->
    <template v-if="A && !result">
      <header class="qh">
        <button class="tr-back" type="button" aria-label="Orqaga" @click="router.back()"><UiIcon name="chevron" :size="18" style="transform: rotate(90deg)" /></button>
        <h2>{{ A.quiz.title }}</h2>
        <span class="sp"></span>
      </header>
      <div class="card">
        <div class="pr">
          <div class="pl"><small>{{ i + 1 }} / {{ total }}</small><div class="tr-bar blue"><i :style="{ width: ((i + 1) / total) * 100 + '%' }"></i></div></div>
          <span v-if="A.quiz.time_limit_seconds" class="tm" :class="{ low: left < 30 }">⏱ {{ fmtDur(left) }}</span>
        </div>
        <h3 class="qt">{{ Q.text }}</h3>
        <img v-if="Q.image" :src="Q.image" alt="" class="qi" />
        <p v-if="Q.multiple" class="tr-muted mul">Bir nechta to'g'ri javob bor</p>
        <div class="opts">
          <button v-for="o in Q.options" :key="o.id" type="button" class="opt" :class="{ on: chosen(o.id), sq: Q.multiple }" @click="pick(o.id)">
            <span class="dot"><svg v-if="chosen(o.id)" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10" /></svg></span>
            {{ o.text }}
          </button>
        </div>
        <button class="tr-btn block" type="button" :disabled="!answered || sending" @click="next">{{ i < total - 1 ? 'Keyingi savol →' : 'Yakunlash ✓' }}</button>
        <button v-if="i > 0" class="back" type="button" @click="i--">← Oldingi savol</button>
      </div>
    </template>

    <!-- NATIJA -->
    <div v-else-if="result && !showReview" class="card res" :class="{ fail: !result.passed }">
      <div v-if="result.passed" class="confetti" aria-hidden="true"><i v-for="n in 14" :key="n" :style="{ '--n': n }"></i></div>
      <div class="cup">{{ result.passed ? '🏆' : '📘' }}</div>
      <h2>{{ result.passed ? 'Test muvaffaqiyatli topshirildi!' : 'Bu safar o\'tmadi' }}</h2>
      <div class="score">{{ result.score }}%</div>
      <p class="tr-muted">{{ result.correct }} / {{ result.total }} to'g'ri javob · o'tish bali {{ result.pass_score }}%</p>
      <div v-if="result.passed" class="good"><span>✓</span><div><b>{{ result.score >= 90 ? 'Ajoyib natija!' : 'Yaxshi natija!' }}</b><small>Siz bu mavzuni yaxshi o'zlashtirdingiz.</small></div></div>
      <div v-else class="bad"><b>Darslarni qayta ko'rib chiqing</b><small v-if="result.attempts_left !== null">{{ result.attempts_left }} ta urinish qoldi</small></div>
      <div v-if="result.course_completed" class="done">🎓 Kurs to'liq tugatildi!</div>
      <button class="tr-btn block" type="button" @click="showReview = true">Natijani ko'rish</button>
      <button v-if="result.course_completed && result.enrollment_id" class="tr-btn ghost block" type="button" @click="router.push(`/training/certificate/${result.enrollment_id}`)">Sertifikatni ochish</button>
      <button v-else-if="!result.passed && result.attempts_left !== 0" class="tr-btn ghost block" type="button" @click="start">Qayta urinish</button>
      <button class="tr-btn ghost block" type="button" @click="router.push(`/training/course/${courseId}`)">Kursga qaytish</button>
    </div>

    <!-- JAVOBLAR -->
    <div v-else-if="result" class="card rv">
      <header class="qh"><button class="tr-back" type="button" @click="showReview = false"><UiIcon name="chevron" :size="18" style="transform: rotate(90deg)" /> Natija</button></header>
      <div v-for="(r, n) in result.review" :key="r.id" class="ri" :class="{ ok: r.ok }">
        <b>{{ n + 1 }}. {{ r.text }}</b>
        <span>Sizning javobingiz: <i :class="r.ok ? 'g' : 'r'">{{ r.given.length ? r.given.map((x: string) => optText(r, x)).join(', ') : '— javob berilmagan' }}</i></span>
        <span v-if="!r.ok">To'g'ri javob: <i class="g">{{ r.correct.map((x: string) => optText(r, x)).join(', ') }}</i></span>
        <small v-if="r.explanation">💡 {{ r.explanation }}</small>
      </div>
      <button class="tr-btn block" type="button" @click="router.push(`/training/course/${courseId}`)">Kursga qaytish</button>
    </div>
  </div>
</template>

<style scoped>
.qv { max-width: 640px; width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.qh { display: flex; align-items: center; gap: 8px; } .qh h2 { flex: 1; text-align: center; margin: 0; font-size: 18px; font-weight: 800; } .sp { width: 32px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 20px; display: flex; flex-direction: column; gap: 14px; position: relative; overflow: hidden; }
.pr { display: flex; align-items: center; gap: 12px; }
.pl { flex: 1; display: flex; flex-direction: column; gap: 6px; } .pl small { font-weight: 800; }
.tr-bar.blue > i { background: var(--info); }
.tm { font-weight: 800; color: var(--danger); font-variant-numeric: tabular-nums; } .tm:not(.low) { color: var(--ink-2); }
.qt { margin: 4px 0 0; font-size: 19px; font-weight: 800; line-height: 1.35; }
.qi { width: 100%; border-radius: 12px; }
.mul { margin: -6px 0 0; font-size: 13px; }
.opts { display: flex; flex-direction: column; gap: 10px; }
.opt { display: flex; align-items: center; gap: 12px; min-height: 54px; padding: 0 16px; border: 1.5px solid var(--line); border-radius: 12px; background: var(--surface); font: inherit; font-size: 16px; font-weight: 600; color: var(--ink); cursor: pointer; text-align: left; }
.opt.on { border-color: var(--tr-green); background: var(--tr-green-tint); }
.dot { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--line); display: grid; place-items: center; flex-shrink: 0; }
.opt.sq .dot { border-radius: 6px; }
.opt.on .dot { background: var(--tr-green); border-color: var(--tr-green); }
.back { background: none; border: 0; color: var(--muted); font: inherit; font-weight: 700; cursor: pointer; }
.res { align-items: center; text-align: center; padding-top: 34px; }
.res h2 { margin: 0; font-size: 20px; font-weight: 800; }
.cup { font-size: 64px; line-height: 1; }
.score { font-size: 52px; font-weight: 900; color: var(--tr-green); line-height: 1; font-family: var(--font-display); }
.res.fail .score { color: var(--danger); }
.res p { margin: -6px 0 0; }
.good { width: 100%; box-sizing: border-box; display: flex; align-items: center; gap: 12px; padding: 14px; border-radius: 14px; background: var(--tr-green-tint); text-align: left; }
.good > span { width: 34px; height: 34px; border-radius: 50%; background: var(--tr-green); color: #fff; display: grid; place-items: center; font-weight: 900; flex-shrink: 0; }
.good div, .bad { display: flex; flex-direction: column; } .good small, .bad small { color: var(--muted); }
.bad { width: 100%; box-sizing: border-box; padding: 14px; border-radius: 14px; background: var(--danger-tint); color: var(--danger); }
.done { font-weight: 800; color: var(--tr-gold); }
.confetti { position: absolute; inset: 0 0 auto 0; height: 120px; pointer-events: none; }
.confetti i { position: absolute; top: -10px; left: calc(var(--n) * 7%); width: 7px; height: 12px; border-radius: 2px; background: hsl(calc(var(--n) * 47), 75%, 55%); animation: fall 1.8s ease-out forwards; animation-delay: calc(var(--n) * 40ms); transform: rotate(calc(var(--n) * 33deg)); }
@keyframes fall { to { top: 110px; opacity: 0; transform: rotate(calc(var(--n) * 90deg)); } }
@media (prefers-reduced-motion: reduce) { .confetti { display: none; } }
.rv { gap: 10px; }
.ri { display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: 12px; border: 1px solid var(--line); border-left: 4px solid var(--danger); }
.ri.ok { border-left-color: var(--tr-green); }
.ri span { font-size: 14px; } .ri i { font-style: normal; font-weight: 700; } .ri .g { color: var(--tr-green); } .ri .r { color: var(--danger); }
.ri small { color: var(--muted); }
</style>
