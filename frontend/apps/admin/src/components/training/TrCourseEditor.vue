<script setup lang="ts">
/**
 * Kurs muharriri (egasi/menejer): asosiy ma'lumot → darslar (video/rasm/fayl/matn/mazmun) → testlar (savollar).
 * Hammasi shu oynada, dasturchisiz.
 */
import { computed, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDropzone, UiIcon, UiInput, UiSelect, UiToggle, toast } from '@restopos/ui'
import AudiencePicker from './AudiencePicker.vue'
import { fmtDur, isUrl, LINK_LABEL, linkKind, uploadWithProgress } from './upload'

const props = defineProps<{ courseId: number | null; meta: any }>()
const emit = defineEmits<{ (e: 'saved'): void; (e: 'close'): void }>()

const blank = () => ({ title: '', description: '', category: '', is_mandatory: true, due_days: props.meta.settings.default_due_days ?? 7,
  pass_score: props.meta.settings.pass_score ?? 80, responsible_id: null as string | null, is_published: false, certificate: true, is_archived: false, cover_url: '',
  roles: [] as string[], positions: [] as number[], user_ids: [] as string[], everyone: false })
const form = ref<any>(blank())
const course = ref<any>(null)
const lessons = ref<any[]>([])
const quizzes = ref<any[]>([])
const openLesson = ref<number | null>(null)
const openQuiz = ref<any>(null)
const pct = ref<Record<string, number>>({})
const saving = ref(false)
const aud = computed({ get: () => ({ roles: form.value.roles, positions: form.value.positions, user_ids: form.value.user_ids, everyone: form.value.everyone }), set: (v) => Object.assign(form.value, v) })

async function load(id: number | null) {
  openLesson.value = null; openQuiz.value = null
  if (!id) { course.value = null; form.value = blank(); lessons.value = []; quizzes.value = []; return }
  const c = await api.get(`/training/courses/${id}`)
  course.value = c
  form.value = { ...blank(), ...Object.fromEntries(Object.keys(blank()).map(k => [k, c[k]])) }
  lessons.value = c.lessons.map(prep)
  quizzes.value = c.quizzes
}
watch(() => props.courseId, load, { immediate: true })
/** Dars tahrir holati: mazmun matni, davomiylik (daqiqa), yangi havola maydonlari */
const prep = (l: any) => ({ ...l, checklistText: l.checklist.join('\n'), durMin: l.duration_seconds ? Math.round(l.duration_seconds / 60) : '', linkTitle: '', linkUrl: '' })
const timeMode = (l: any) => !l.video && ['drive', 'vimeo', 'link'].includes(linkKind(l.video_url))

async function save() {
  if (!form.value.title.trim()) { toast('Kurs nomini yozing', 'danger'); return }
  saving.value = true
  try {
    const body = { ...form.value, due_days: Number(form.value.due_days) || 0, pass_score: Number(form.value.pass_score) || 0 }
    const r = course.value ? await api.put(`/training/courses/${course.value.id}`, body) : await api.post('/training/courses', body)
    toast(r.assigned ? `Saqlandi · ${r.assigned} xodimga biriktirildi` : 'Saqlandi')
    await load(r.id); emit('saved')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}

async function upCover(files: File[]) {
  try { pct.value.cover = 0; await uploadWithProgress(`/training/courses/${course.value.id}/cover`, files[0], p => (pct.value.cover = p)); await load(course.value.id); emit('saved') }
  catch (e: any) { toast(e.detail ?? 'Yuklanmadi', 'danger') } finally { delete pct.value.cover }
}

// ---------- darslar
async function addLesson() {
  const l = await api.post(`/training/courses/${course.value.id}/lessons`, { title: `${lessons.value.length + 1}-dars`, body: '', checklist: [], video_url: '' })
  lessons.value.push(prep(l)); openLesson.value = l.id; emit('saved')
}
async function saveLesson(l: any) {
  try {
    for (const [u, what] of [[l.video_url, 'Video'], [l.image_url, 'Rasm']]) if (u && !isUrl(u)) { toast(`${what} havolasi https:// bilan boshlanishi kerak`, 'danger'); return }
    if (timeMode(l) && !Number(l.durMin)) { toast('Video davomiyligini daqiqada yozing — shunga qarab «ko\'rdi» hisoblanadi', 'danger'); return }
    const r = await api.put(`/training/lessons/${l.id}`, { title: l.title, body: l.body, video_url: (l.video_url || '').trim(), image_url: (l.image_url || '').trim(),
      duration_seconds: timeMode(l) ? Number(l.durMin) * 60 : l.duration_seconds, checklist: l.checklistText.split('\n').map((x: string) => x.trim()).filter(Boolean) })
    Object.assign(l, prep(r)); toast('Dars saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delLesson(l: any) {
  if (!confirm(`«${l.title}» darsini o'chirasizmi? Xodimlarning shu dars bo'yicha natijasi ham o'chadi.`)) return
  await api.del(`/training/lessons/${l.id}`); lessons.value = lessons.value.filter(x => x.id !== l.id); emit('saved')
}
async function move(l: any, d: number) {
  const i = lessons.value.indexOf(l), j = i + d
  if (j < 0 || j >= lessons.value.length) return
  const arr = [...lessons.value]; [arr[i], arr[j]] = [arr[j], arr[i]]; lessons.value = arr
  await api.post(`/training/courses/${course.value.id}/lessons/order`, { ids: arr.map(x => x.id) })
}
async function upLesson(l: any, kind: 'video' | 'image' | 'files', files: File[]) {
  for (const f of files) {
    const key = `${l.id}-${kind}`
    try { pct.value[key] = 0; const r = await uploadWithProgress(`/training/lessons/${l.id}/${kind}`, f, p => (pct.value[key] = p)); Object.assign(l, r, { checklistText: l.checklistText }) }
    catch (e: any) { toast(e.detail ?? 'Yuklanmadi', 'danger') } finally { delete pct.value[key] }
  }
}
async function delVideo(l: any) { Object.assign(l, await api.del(`/training/lessons/${l.id}/video`), { checklistText: l.checklistText }) }
async function addLink(l: any) {
  if (!isUrl(l.linkUrl)) { toast('Havolani to\'liq yozing: https://…', 'danger'); return }
  try { const r = await api.post(`/training/lessons/${l.id}/links`, { url: l.linkUrl.trim(), title: l.linkTitle }); l.files = r.files; l.linkUrl = ''; l.linkTitle = ''; toast('Havola qo\'shildi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delFile(l: any, f: any) { await api.del(`/training/files/${f.id}`); l.files = l.files.filter((x: any) => x.id !== f.id) }

// ---------- testlar
const letters = 'abcdef'
async function addQuiz() {
  const q = await api.post(`/training/courses/${course.value.id}/quizzes`, { title: lessons.value.length ? 'Yakuniy test' : 'Test', time_limit_seconds: 0, pass_score: 0, max_attempts: 0, shuffle: true })
  quizzes.value.push(q); editQuiz(q); emit('saved')
}
async function editQuiz(q: any) {
  const full = await api.get(`/training/quizzes/${q.id}`)
  openQuiz.value = { ...full, minutes: Math.round(full.time_limit_seconds / 60), questions: full.questions.map((x: any) => ({ ...x, options: letters.slice(0, Math.max(4, x.options.length)).split('').map(id => ({ id, text: x.options.find((o: any) => o.id === id)?.text ?? '' })) })) }
  if (!openQuiz.value.questions.length) addQuestion()
}
function addQuestion() { openQuiz.value.questions.push({ id: null, text: '', explanation: '', correct: [], options: letters.slice(0, 4).split('').map(id => ({ id, text: '' })) }) }
function toggleCorrect(x: any, id: string, multi: boolean) { x.correct = multi ? (x.correct.includes(id) ? x.correct.filter((c: string) => c !== id) : [...x.correct, id]) : [id] }
async function saveQuiz() {
  const q = openQuiz.value
  try {
    await api.put(`/training/quizzes/${q.id}`, { title: q.title, lesson_id: q.lesson_id || null, time_limit_seconds: (Number(q.minutes) || 0) * 60, pass_score: Number(q.own_pass_score) || 0, max_attempts: Number(q.max_attempts) || 0, shuffle: q.shuffle })
    const qs = q.questions.filter((x: any) => x.text.trim())
    const r = await api.put(`/training/quizzes/${q.id}/questions`, { questions: qs.map((x: any) => ({ id: x.id, text: x.text, explanation: x.explanation, correct: x.correct, options: x.options.filter((o: any) => o.text.trim()) })) })
    const i = quizzes.value.findIndex(x => x.id === q.id); quizzes.value[i] = r
    toast(`Test saqlandi · ${r.questions_count} savol`); openQuiz.value = null; emit('saved')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delQuiz(q: any) {
  if (!confirm(`«${q.title}» testini o'chirasizmi?`)) return
  await api.del(`/training/quizzes/${q.id}`); quizzes.value = quizzes.value.filter(x => x.id !== q.id); openQuiz.value = null; emit('saved')
}
const userOpts = computed(() => [{ value: '', label: '— tanlanmagan —' }, ...props.meta.users.map((u: any) => ({ value: u.id, label: u.full_name }))])
const lessonOpts = computed(() => [{ value: '', label: 'Kurs yakuniy testi' }, ...lessons.value.map(l => ({ value: l.id, label: `Dars: ${l.title}` }))])
</script>

<template>
  <div class="ed">
    <!-- ASOSIY -->
    <section class="sec">
      <h4>1. Asosiy ma'lumot</h4>
      <div class="coverrow" v-if="course">
        <div class="cov" :style="course.cover ? { backgroundImage: `url(${course.cover})` } : {}"><span v-if="!course.cover">Muqova yo'q</span></div>
        <UiDropzone accept="image/*" label="Muqova rasmi" hint="16:9, JPG/PNG" @files="upCover" />
      </div>
      <div v-if="pct.cover !== undefined" class="tr-bar"><i :style="{ width: pct.cover + '%' }"></i></div>
      <UiInput v-model="form.title" label="Kurs nomi" placeholder="Masalan: Burger tayyorlash standarti" />
      <UiInput v-model="form.cover_url" label="Muqova rasmi havolasi (ixtiyoriy)" placeholder="https://… yoki Google Drive havolasi" hint="Faylni yuklash shart emas — internetdagi rasm havolasini qo'ysangiz bo'ladi" />
      <label class="fld"><span>Qisqa tavsif</span><textarea v-model="form.description" rows="2" placeholder="Kurs nima haqida"></textarea></label>
      <div class="g3">
        <label class="fld"><span>Bo'lim</span><input v-model="form.category" list="tr-cats" placeholder="Oshxona, Zal…" /><datalist id="tr-cats"><option v-for="c in meta.categories" :key="c" :value="c" /></datalist></label>
        <UiInput v-model="form.due_days" type="number" label="Muddat (kun)" hint="0 — muddatsiz" />
        <UiInput v-model="form.pass_score" type="number" label="O'tish bali" suffix="%" />
      </div>
      <UiSelect :model-value="form.responsible_id ?? ''" label="Mas'ul (natijani kuzatadi)" :options="userOpts" @update:model-value="(v) => (form.responsible_id = v || null)" />
      <b class="lbl">Kimlar o'qiydi</b>
      <AudiencePicker v-model="aud" :meta="meta" />
      <div class="tg">
        <UiToggle v-model="form.is_mandatory" label="Majburiy kurs" />
        <UiToggle v-model="form.certificate" label="Tugatganda sertifikat" />
        <UiToggle v-model="form.is_published" label="E'lon qilish (xodimlarga ko'rinadi)" />
      </div>
      <UiButton variant="brand" :loading="saving" @click="save">{{ course ? 'Saqlash' : 'Kursni yaratish' }}</UiButton>
      <div v-if="!course" class="next">
        <b>Keyingi qadam</b>
        <span>«Kursni yaratish»ni bosgach, shu oynada pastda <b>Darslar</b> (video, rasm, fayl, havola) va <b>Testlar</b> bo'limlari ochiladi.</span>
      </div>
    </section>

    <template v-if="course">
      <!-- DARSLAR -->
      <section class="sec">
        <div class="sh"><h4>2. Darslar ({{ lessons.length }})</h4><UiButton size="s" @click="addLesson"><UiIcon name="plus" :size="14" /> Dars</UiButton></div>
        <div v-for="(l, i) in lessons" :key="l.id" class="les" :class="{ open: openLesson === l.id }">
          <div class="lh">
            <span class="n">{{ i + 1 }}</span>
            <button class="lt" type="button" @click="openLesson = openLesson === l.id ? null : l.id"><b>{{ l.title }}</b>
              <small>{{ l.video ? '🎬 video fayl' : { youtube: '▶ YouTube', drive: '📁 Drive video', vimeo: '▶ Vimeo', video: '🎬 video havola', image: '🔗 havola', pdf: '🔗 havola', link: '🔗 havola', none: '📄 matn' }[linkKind(l.video_url)] }}<template v-if="l.duration_seconds"> · {{ fmtDur(l.duration_seconds) }}</template><template v-if="l.files.length"> · {{ l.files.length }} fayl</template></small></button>
            <button class="ib" type="button" aria-label="Yuqoriga" :disabled="i === 0" @click="move(l, -1)">↑</button>
            <button class="ib" type="button" aria-label="Pastga" :disabled="i === lessons.length - 1" @click="move(l, 1)">↓</button>
          </div>
          <div v-if="openLesson === l.id" class="lb">
            <UiInput v-model="l.title" label="Dars nomi" />
            <div class="vid">
              <b class="lbl">Video</b>
              <video v-if="l.video" :src="l.video" controls playsinline class="pv"></video>
              <div v-if="l.video || l.video_url" class="vrow"><UiChip tone="ok">{{ l.video ? 'Video yuklangan' : 'Havola: ' + l.video_url }}</UiChip><UiButton size="s" variant="ghost" @click="delVideo(l)">Olib tashlash</UiButton></div>
              <template v-if="!l.video">
                <UiDropzone accept="video/mp4,video/webm,video/quicktime,video/*" label="Video fayl yuklash (MP4)" hint="500 MB gacha. Telefondan ham bo'ladi" @files="(f) => upLesson(l, 'video', f)" />
                <div v-if="pct[`${l.id}-video`] !== undefined" class="up"><div class="tr-bar"><i :style="{ width: pct[`${l.id}-video`] + '%' }"></i></div><small>Video yuklanmoqda… {{ pct[`${l.id}-video`] }}% — sahifani yopmang</small></div>
                <UiInput v-model="l.video_url" label="yoki video havolasi" placeholder="YouTube, Google Drive, Vimeo yoki .mp4 havola" />
                <small v-if="l.video_url" class="kind">{{ LINK_LABEL[linkKind(l.video_url)] }}</small>
                <UiInput v-if="timeMode(l)" v-model="l.durMin" type="number" label="Video davomiyligi (daqiqa)" hint="Xodim sahifada shuncha vaqt tursa — dars ko'rilgan hisoblanadi" />
              </template>
            </div>
            <label class="fld"><span>Tavsif / dars matni</span><textarea v-model="l.body" rows="4" placeholder="Bu darsda nimani o'rganadi"></textarea></label>
            <label class="fld"><span>Dars mazmuni (har qatorda bitta band)</span><textarea v-model="l.checklistText" rows="4" placeholder="Kerakli mahsulotlar&#10;Tayyorlash bosqichlari&#10;Sifat standartlari"></textarea></label>
            <div class="g2">
              <div><b class="lbl">Rasm</b><img v-if="l.image" :src="l.image" class="thumb" alt="" /><UiDropzone accept="image/*" label="Rasm yuklash" @files="(f) => upLesson(l, 'image', f)" />
                <UiInput v-model="l.image_url" placeholder="yoki rasm havolasi: https://…" /></div>
              <div><b class="lbl">Fayllar (PDF, rasm, hujjat)</b>
                <div v-for="f in l.files" :key="f.id" class="fr"><a :href="f.url" target="_blank">{{ f.is_link ? '🔗' : '📎' }} {{ f.title }}</a><button type="button" class="ib" aria-label="O'chirish" @click="delFile(l, f)">✕</button></div>
                <UiDropzone multiple label="Fayl qo'shish" @files="(f) => upLesson(l, 'files', f)" />
                <div v-if="pct[`${l.id}-files`] !== undefined" class="tr-bar"><i :style="{ width: pct[`${l.id}-files`] + '%' }"></i></div>
                <div class="linkadd">
                  <input v-model="l.linkTitle" placeholder="Nomi (masalan: Qo'llanma PDF)" />
                  <input v-model="l.linkUrl" placeholder="https://… havola" @keydown.enter="addLink(l)" />
                  <UiButton size="s" variant="secondary" @click="addLink(l)">🔗 Havola qo'shish</UiButton>
                </div>
              </div>
            </div>
            <div class="row"><UiButton @click="saveLesson(l)">Darsni saqlash</UiButton><span class="sp"></span><UiButton variant="danger" size="s" @click="delLesson(l)"><UiIcon name="trash" :size="14" /></UiButton></div>
          </div>
        </div>
        <p v-if="!lessons.length" class="tr-muted small">Hali dars yo'q — «Dars» tugmasini bosing.</p>
      </section>

      <!-- TESTLAR -->
      <section class="sec">
        <div class="sh"><h4>3. Testlar ({{ quizzes.length }})</h4><UiButton size="s" @click="addQuiz"><UiIcon name="plus" :size="14" /> Test</UiButton></div>
        <button v-for="q in quizzes" v-show="openQuiz?.id !== q.id" :key="q.id" type="button" class="qrow" @click="editQuiz(q)">
          <b>{{ q.title }}</b><small>{{ q.questions_count }} savol · o'tish {{ q.pass_score }}%{{ q.time_limit_seconds ? ` · ${Math.round(q.time_limit_seconds / 60)} daq` : '' }}</small><UiIcon name="edit" :size="14" />
        </button>
        <div v-if="openQuiz" class="qed">
          <UiInput v-model="openQuiz.title" label="Test nomi" />
          <div class="g3">
            <UiSelect :model-value="openQuiz.lesson_id ?? ''" label="Qaysi dars uchun" :options="lessonOpts" @update:model-value="(v) => (openQuiz.lesson_id = v ? Number(v) : null)" />
            <UiInput v-model="openQuiz.minutes" type="number" label="Vaqt (daqiqa)" hint="0 — cheklovsiz" />
            <UiInput v-model="openQuiz.max_attempts" type="number" label="Urinishlar" hint="0 — cheksiz" />
          </div>
          <div class="g3"><UiInput v-model="openQuiz.own_pass_score" type="number" label="O'tish bali" hint="0 — kurs bali" suffix="%" /><UiToggle v-model="openQuiz.shuffle" label="Savollarni aralashtirish" /></div>
          <div v-for="(x, n) in openQuiz.questions" :key="n" class="qq">
            <div class="row"><b>{{ n + 1 }}-savol</b><span class="sp"></span><label class="multi"><input type="checkbox" :checked="x.correct.length > 1" @change="(e) => { if (!(e.target as HTMLInputElement).checked) x.correct = x.correct.slice(0, 1) ; x._multi = (e.target as HTMLInputElement).checked }" /> bir nechta to'g'ri</label><button type="button" class="ib" aria-label="Savolni o'chirish" @click="openQuiz.questions.splice(n, 1)">✕</button></div>
            <textarea v-model="x.text" rows="2" class="qtext" placeholder="Savol matni"></textarea>
            <div v-for="o in x.options" :key="o.id" class="opt" :class="{ ok: x.correct.includes(o.id) }">
              <button type="button" class="mark" :aria-label="`${o.id.toUpperCase()} to'g'ri javob`" @click="toggleCorrect(x, o.id, x._multi || x.correct.length > 1)">{{ x.correct.includes(o.id) ? '✓' : o.id.toUpperCase() }}</button>
              <input v-model="o.text" :placeholder="`${o.id.toUpperCase()} variant`" />
            </div>
            <input v-model="x.explanation" class="expl" placeholder="Izoh: nega bu javob to'g'ri (natijada ko'rinadi)" />
          </div>
          <p class="tr-muted small">To'g'ri javobni belgilash uchun harf tugmasini bosing — yashil bo'ladi.</p>
          <div class="row"><UiButton size="s" variant="secondary" @click="addQuestion"><UiIcon name="plus" :size="14" /> Savol</UiButton><span class="sp"></span>
            <UiButton size="s" variant="ghost" @click="openQuiz = null">Bekor</UiButton><UiButton variant="danger" size="s" @click="delQuiz(openQuiz)"><UiIcon name="trash" :size="14" /></UiButton><UiButton @click="saveQuiz">Testni saqlash</UiButton></div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ed { display: flex; flex-direction: column; gap: 18px; }
.sec { display: flex; flex-direction: column; gap: 12px; }
.sec h4 { margin: 0; font-size: 15px; font-weight: 800; }
.sh { display: flex; justify-content: space-between; align-items: center; }
.lbl { font-size: 13px; font-weight: 700; color: var(--ink-2); }
.small { font-size: 13px; margin: 0; }
.fld { display: flex; flex-direction: column; gap: 6px; } .fld span { font-size: 13px; font-weight: 700; color: var(--ink-2); }
.fld textarea, .fld input, .qtext, .opt input, .expl { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); }
.fld input { min-height: 40px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } .g2 > div { display: flex; flex-direction: column; gap: 6px; }
.g3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; align-items: end; }
.tg { display: flex; flex-direction: column; gap: 8px; }
.coverrow { display: grid; grid-template-columns: 160px 1fr; gap: 10px; align-items: center; }
.cov { aspect-ratio: 16/9; border-radius: 10px; background: var(--surface-3) center / cover; display: grid; place-items: center; color: var(--muted); font-size: 12px; }
.les { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.les.open { border-color: var(--tr-gold, #A8894F); }
.lh { display: flex; align-items: center; gap: 8px; padding: 8px 10px; }
.n { width: 28px; height: 28px; border-radius: 50%; background: var(--surface-3); display: grid; place-items: center; font-weight: 800; font-size: 13px; flex-shrink: 0; }
.lt { flex: 1; min-width: 0; text-align: left; border: 0; background: none; cursor: pointer; font: inherit; color: inherit; display: flex; flex-direction: column; padding: 4px 0; }
.lt small { color: var(--muted); font-size: 12px; }
.ib { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; color: var(--ink-2); flex-shrink: 0; }
.ib:disabled { opacity: .35; }
.lb { padding: 12px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 12px; background: var(--surface-2); }
.vid { display: flex; flex-direction: column; gap: 8px; }
.pv { width: 100%; max-height: 240px; border-radius: 10px; background: #000; }
.vrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.up { display: flex; flex-direction: column; gap: 4px; } .up small { color: var(--muted); }
.next { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px; background: var(--info-tint); color: var(--ink-2); font-size: 13px; }
.next > b { color: var(--info); }
.kind { color: var(--muted); font-size: 12px; margin-top: -4px; }
.linkadd { display: flex; flex-direction: column; gap: 6px; padding-top: 6px; border-top: 1px dashed var(--line); }
.linkadd input { min-height: 38px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); }
.thumb { width: 100%; max-height: 120px; object-fit: cover; border-radius: 10px; }
.fr { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 13px; } .fr a { color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .sp { flex: 1; }
.qrow { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); cursor: pointer; font: inherit; color: inherit; text-align: left; }
.qrow b { flex: 1; } .qrow small { color: var(--muted); }
.qed { display: flex; flex-direction: column; gap: 12px; padding: 12px; border: 1px solid var(--tr-gold, #A8894F); border-radius: 12px; background: var(--surface-2); }
.qq { display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.multi { font-size: 12px; color: var(--muted); display: inline-flex; gap: 4px; align-items: center; }
.opt { display: flex; gap: 6px; align-items: center; }
.mark { width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface-3); font-weight: 800; cursor: pointer; flex-shrink: 0; color: var(--ink-2); }
.opt.ok .mark { background: var(--tr-green, #1E9E5A); border-color: var(--tr-green, #1E9E5A); color: #fff; }
.opt.ok input { border-color: var(--tr-green, #1E9E5A); }
@media (max-width: 600px) { .g2, .g3 { grid-template-columns: 1fr; } .coverrow { grid-template-columns: 1fr; } }
</style>
