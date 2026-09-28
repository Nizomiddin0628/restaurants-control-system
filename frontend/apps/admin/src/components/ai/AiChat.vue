<script setup lang="ts">
/**
 * AI Kotib chati — rahbar/menejer panelning istalgan sahifasida o'ng pastki burchakdagi tugma orqali.
 *   • yozma savol yoki 🎙 ovoz (ovoz matnga aylanib, darhol yuboriladi);
 *   • javob chatdagidek yozila boradi (oqim), kerak bo'lsa diagramma (rasm) ham keladi;
 *   • «⏹ To'xtatish» — AI ishi to'xtaydi, savol maydonga qaytadi (o'zgartirib qayta yuborish mumkin);
 *   • «📊 Hisobot» — bugungi hisobot; javob kelmaguncha yangi savol yuborilmaydi;
 *   • suhbat shu brauzer oynasida saqlanadi (sessionStorage), oxirgi xabarlar AI'ga kontekst sifatida boradi.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@restopos/api'
import { UiIcon } from '@restopos/ui'

type Chart = { title: string; src: string }
type Msg = { role: 'user' | 'ai'; html: string; text: string; err?: boolean; at: string; live?: boolean; charts?: Chart[] }
const KEY = 'restopos.aichat'
const route = useRoute()
const open = ref(false)
const msgs = ref<Msg[]>((() => { try { return JSON.parse(sessionStorage.getItem(KEY) || '[]') } catch { return [] } })())
const q = ref('')
const busy = ref(false)
const status = ref<any>(null)
const listEl = ref<HTMLElement | null>(null), inputEl = ref<HTMLTextAreaElement | null>(null)
const hint = ref('')
const SUG = ['Kecha savdo qancha bo\'ldi?', 'Oxirgi 7 kun savdosini diagrammada ko\'rsat', 'Omborda nima tugayapti?', 'Kechikkan vazifalar kimda?']

watch(msgs, (v) => { try { sessionStorage.setItem(KEY, JSON.stringify(v.slice(-30).map(m => ({ ...m, live: false })))) } catch { /* to'lsa — saqlanmaydi */ } }, { deep: true })
const now = () => new Date().toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' })
const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string))
async function scroll() { await nextTick(); listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: 'smooth' }) }

async function toggle() {
  open.value = !open.value
  if (open.value) {
    if (!status.value) { try { status.value = await api.get('/ai/status') } catch { status.value = { has_key: false } } }
    scroll(); nextTick(() => inputEl.value?.focus())
  }
}
function push(m: Omit<Msg, 'at'>) { msgs.value.push({ ...m, at: now() }); scroll() }

/** Yozilayotgan javob qoralamasi → xavfsiz HTML (faqat <b>, <i>) */
function fmt(raw: string) {
  let t = esc(raw).replace(/&lt;(\/?)(b|i)&gt;/g, '<$1$2>')
  t = t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^#{1,6}\s*(.+)$/gm, '<b>$1</b>').replace(/^\s*[*-]\s+/gm, '• ')
  return t
}
let ctrl: AbortController | null = null
let lastQ = ''
async function send(text?: string) {
  const question = (text ?? q.value).trim()
  if (!question || busy.value) return
  const history = msgs.value.filter(m => !m.err).slice(-8).map(m => ({ role: m.role, text: m.text }))
  push({ role: 'user', html: esc(question), text: question })
  q.value = ''; hint.value = ''; lastQ = question
  busy.value = true
  msgs.value.push({ role: 'ai', html: '', text: '', at: now(), live: true })
  const m = msgs.value[msgs.value.length - 1]
  let raw = ''
  ctrl = new AbortController()
  try {
    await api.stream('/ai/ask-stream', { question, history }, (x) => {
      if (x.reset) { raw = ''; m.html = '' }
      else if (typeof x.t === 'string') { raw += x.t; m.html = fmt(raw); scroll() }
      else if (x.done) {
        m.live = false
        if (x.ok) { m.html = x.answer; m.text = String(x.answer).replace(/<[^>]+>/g, ''); m.charts = x.charts?.length ? x.charts : undefined }
        else { m.html = `⚠️ ${esc(x.error || 'Xato')}`; m.text = x.error || ''; m.err = true }
        scroll()
      }
    }, ctrl.signal)
    if (m.live) { m.live = false; if (!m.html) { m.html = '⚠️ Javob kelmadi — qayta urinib ko\'ring'; m.err = true } }
  } catch (e: any) {
    m.live = false
    if (e?.name === 'AbortError') { m.html = (raw ? fmt(raw) + '\n\n' : '') + '⏹ <i>To\'xtatildi.</i>'; m.err = true }
    else { m.html = `⚠️ ${esc(e.detail ?? 'Xato')}`; m.err = true }
  } finally { busy.value = false; ctrl = null; nextTick(() => inputEl.value?.focus()) }
}
/** ⏹ To'xtatish: AI ishi to'xtaydi, savol maydonga qaytadi — o'zgartirib qayta yuborish mumkin */
function stop() {
  if (!ctrl) return
  ctrl.abort()
  q.value = lastQ
  hint.value = '⏹ To\'xtatildi. Savolingiz maydonda — o\'zgartirib yuboring yoki yangisini yozing.'
}
async function report() {
  if (busy.value) return
  push({ role: 'user', html: '📊 Bugungi hisobot', text: 'Bugungi hisobot' })
  busy.value = true
  try { const r = await api.get('/ai/report', { ai: 1 }); push({ role: 'ai', html: r.html, text: r.html.replace(/<[^>]+>/g, '').slice(0, 1500) }) }
  catch (e: any) { push({ role: 'ai', html: `⚠️ ${esc(e.detail ?? 'Xato')}`, text: '', err: true }) } finally { busy.value = false }
}
function clear() { if (!busy.value) { msgs.value = []; hint.value = '' } }

// ---------- ovoz: bosib yozish → to'xtatish → matn (tahrirlab «Yuborish»)
const rec = ref<MediaRecorder | null>(null), secs = ref(0), transcribing = ref(false)
let chunks: Blob[] = [], timer: number | undefined, stream: MediaStream | null = null
const canRec = typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'
async function mic() {
  if (busy.value || transcribing.value) return
  if (rec.value) { rec.value.stop(); return }
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) } catch { hint.value = 'Mikrofonga ruxsat berilmadi (brauzer sozlamasida ruxsat bering)'; return }
  const type = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported?.(t)) || ''
  const r = new MediaRecorder(stream, type ? { mimeType: type } : undefined)
  chunks = []; secs.value = 0
  r.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
  r.onstop = async () => {
    clearInterval(timer); stream?.getTracks().forEach(t => t.stop()); rec.value = null
    const blob = new Blob(chunks, { type: r.mimeType || 'audio/webm' })
    if (blob.size < 1500) { hint.value = 'Juda qisqa — tugmani bosib, gapirib, yana bosing'; return }
    transcribing.value = true; hint.value = ''
    try {
      const f = new File([blob], `ovoz.${(r.mimeType || 'audio/webm').includes('mp4') ? 'm4a' : 'webm'}`, { type: (r.mimeType || 'audio/webm').split(';')[0] })
      const res = await api.upload('/ai/transcribe', f)
      transcribing.value = false
      send(res.text)            // tasdiqsiz: eshitilgan matn darhol yuboriladi (xato bo'lsa — ⏹ va tuzatish)
    } catch (e: any) { hint.value = `⚠️ ${e.detail ?? 'Ovozni o\'qib bo\'lmadi'}` } finally { transcribing.value = false }
  }
  r.start(); rec.value = r
  timer = window.setInterval(() => { secs.value++; if (secs.value >= 120) r.stop() }, 1000)
}
onBeforeUnmount(() => { clearInterval(timer); stream?.getTracks().forEach(t => t.stop()) })

const lifted = computed(() => route.path.startsWith('/tasks'))     // telefonda vazifalar sahifasining «+» tugmasi bilan to'qnashmasin
</script>

<template>
  <div class="aic-root" :class="{ lifted }">
    <button type="button" class="aic-fab" :class="{ on: open }" :aria-expanded="open" aria-label="AI Kotib" title="AI Kotib — savol bering" @click="toggle">
      <UiIcon :name="open ? 'x' : 'spark'" :size="24" />
      <span v-if="busy && !open" class="aic-dot"></span>
    </button>

    <section v-if="open" class="aic" role="dialog" aria-label="AI Kotib chati">
      <header class="aic-hd">
        <span class="aic-av"><UiIcon name="spark" :size="18" /></span>
        <div class="aic-t"><b>AI Kotib</b><small>{{ busy ? 'yozmoqda…' : 'Savol bering yoki 🎙 gapiring' }}</small></div>
        <button type="button" class="aic-ib" title="Bugungi hisobot" :disabled="busy" @click="report"><UiIcon name="chart" :size="17" /></button>
        <button type="button" class="aic-ib" title="Yangi suhbat" :disabled="busy || !msgs.length" @click="clear"><UiIcon name="trash" :size="17" /></button>
        <button type="button" class="aic-ib" title="Yopish" @click="open = false"><UiIcon name="x" :size="17" /></button>
      </header>

      <div ref="listEl" class="aic-list">
        <div v-if="status && !status.has_key" class="aic-note">⚠️ AI kaliti hali kiritilmagan. <RouterLink to="/ai" @click="open = false">AI Kotib sahifasida</RouterLink> kalitni qo'ying.</div>
        <div v-if="!msgs.length" class="aic-empty">
          <p>Salom! Men restoraningiz bo'yicha savollarga tizimdagi haqiqiy raqamlar bilan javob beraman. Vazifa ham bera olaman: «Rustamga ertaga 10:00 gacha … vazifasini ber».</p>
          <div class="aic-sug"><button v-for="s in SUG" :key="s" type="button" :disabled="busy" @click="send(s)">{{ s }}</button></div>
        </div>
        <div v-for="(m, i) in msgs" :key="i" class="aic-m" :class="[m.role, { err: m.err }]">
          <div v-if="m.live && !m.html" class="aic-b aic-typing"><i></i><i></i><i></i></div>
          <div v-else class="aic-b" :class="{ live: m.live }" v-html="m.html"></div>
          <a v-for="(c, k) in m.charts ?? []" :key="k" class="aic-chart" :href="c.src" :download="`${c.title || 'diagramma'}.png`" :title="`${c.title} — yuklab olish`"><img :src="c.src" :alt="c.title" loading="lazy" /></a>
          <small>{{ m.at }}</small>
        </div>
      </div>

      <p v-if="hint" class="aic-hint">{{ hint }}</p>
      <form class="aic-in" @submit.prevent="send()">
        <button v-if="canRec" type="button" class="aic-mic" :class="{ rec: !!rec, wait: transcribing }" :disabled="busy || transcribing"
                :title="rec ? 'To\'xtatish' : 'Ovoz bilan'" @click="mic">
          <UiIcon :name="rec ? 'x' : 'mic'" :size="18" /><span v-if="rec" class="aic-sec">{{ secs }}s</span>
        </button>
        <textarea ref="inputEl" v-model="q" rows="1" :placeholder="rec ? 'Gapiring… tugatgach ⏹ bosing' : transcribing ? 'Eshityapman…' : busy ? 'Javob yozilyapti… (⏹ — to\'xtatish)' : 'Savol yozing yoki 🎙 gapiring…'"
                  :disabled="busy || transcribing" @keydown.enter.exact.prevent="send()"></textarea>
        <button v-if="busy" type="button" class="aic-send aic-stop" aria-label="To'xtatish" title="To'xtatish" @click="stop"><span class="aic-sq"></span></button>
        <button v-else type="submit" class="aic-send" :disabled="transcribing || !q.trim()" aria-label="Yuborish"><UiIcon name="send" :size="18" /></button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.aic-fab { position: fixed; right: 20px; bottom: 20px; z-index: 45; width: 56px; height: 56px; border-radius: 18px; border: 0; cursor: pointer; color: #fff;
  background: linear-gradient(135deg, #7C3AED, #0891B2); box-shadow: 0 12px 28px -8px rgba(124, 58, 237, .55); display: grid; place-items: center; transition: transform .15s; }
.aic-fab:hover { transform: translateY(-2px) scale(1.03); } .aic-fab.on { border-radius: 50%; }
.aic-dot { position: absolute; top: 8px; right: 8px; width: 10px; height: 10px; border-radius: 50%; background: #F59E0B; border: 2px solid #fff; animation: aic-p 1s infinite alternate; }
@keyframes aic-p { to { transform: scale(1.3); } }
.aic { position: fixed; right: 20px; bottom: 88px; z-index: 46; width: min(400px, calc(100vw - 40px)); height: min(600px, calc(100dvh - 120px)); display: flex; flex-direction: column;
  background: var(--surface); border: 1px solid var(--line); border-radius: 20px; box-shadow: 0 24px 60px -12px rgba(0, 0, 0, .35); overflow: hidden; animation: aic-in .16s ease-out; }
@keyframes aic-in { from { transform: translateY(10px); opacity: 0; } }
.aic-hd { display: flex; align-items: center; gap: 8px; padding: 12px 12px 12px 14px; color: #fff; background: linear-gradient(135deg, #7C3AED, #0891B2); flex-shrink: 0; }
.aic-av { width: 34px; height: 34px; border-radius: 11px; background: rgba(255, 255, 255, .2); display: grid; place-items: center; flex-shrink: 0; }
.aic-t { flex: 1; min-width: 0; display: flex; flex-direction: column; } .aic-t b { font-size: var(--fs-b); } .aic-t small { opacity: .85; font-size: var(--fs-xs); }
.aic-ib { width: 34px; height: 34px; border-radius: 10px; border: 0; background: rgba(255, 255, 255, .14); color: #fff; cursor: pointer; display: grid; place-items: center; flex-shrink: 0; }
.aic-ib:hover:not(:disabled) { background: rgba(255, 255, 255, .26); } .aic-ib:disabled { opacity: .45; cursor: default; }
.aic-list { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 14px 12px; display: flex; flex-direction: column; gap: 10px; background: color-mix(in srgb, #7C3AED 3%, var(--surface-2)); }
.aic-note { font-size: var(--fs-xs); padding: 8px 10px; border-radius: 10px; background: var(--warn-tint); } .aic-note a { color: var(--accent); font-weight: 700; }
.aic-empty p { margin: 0 0 10px; font-size: var(--fs-s); color: var(--ink-2); }
.aic-sug { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.aic-sug button { border: 1px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 12px; padding: 7px 11px; font: inherit; font-size: var(--fs-s); cursor: pointer; text-align: left; }
.aic-sug button:hover { border-color: #7C3AED; color: #7C3AED; }
.aic-m { display: flex; flex-direction: column; max-width: 88%; } .aic-m small { font-size: 10px; color: var(--muted); margin-top: 2px; padding: 0 4px; }
.aic-m.user { align-self: flex-end; align-items: flex-end; } .aic-m.ai { align-self: flex-start; }
.aic-b { padding: 9px 12px; border-radius: 16px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
.aic-m.user .aic-b { background: linear-gradient(135deg, #7C3AED, #6D28D9); color: #fff; border-bottom-right-radius: 4px; }
.aic-m.ai .aic-b { background: var(--surface); border: 1px solid var(--line); border-bottom-left-radius: 4px; }
.aic-m.err .aic-b { border-color: color-mix(in srgb, var(--danger) 40%, var(--line)); }
.aic-typing { display: flex; gap: 4px; padding: 12px 14px; } .aic-typing i { width: 7px; height: 7px; border-radius: 50%; background: #7C3AED; animation: aic-d 1s infinite ease-in-out; }
.aic-typing i:nth-child(2) { animation-delay: .15s; } .aic-typing i:nth-child(3) { animation-delay: .3s; }
@keyframes aic-d { 50% { transform: translateY(-4px); opacity: .5; } }
.aic-hint { margin: 0; padding: 7px 12px; font-size: var(--fs-xs); color: var(--ink-2); background: var(--surface-2); border-top: 1px solid var(--line); flex-shrink: 0; }
.aic-in { display: flex; gap: 8px; align-items: flex-end; padding: 10px; border-top: 1px solid var(--line); background: var(--surface); flex-shrink: 0; }
.aic-in textarea { flex: 1; min-width: 0; resize: none; max-height: 120px; min-height: 42px; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; font: inherit; font-size: 14px; background: var(--surface-2); color: var(--ink); field-sizing: content; }
.aic-mic, .aic-send { width: 42px; height: 42px; border-radius: 12px; border: 0; cursor: pointer; display: grid; place-items: center; flex-shrink: 0; position: relative; }
.aic-mic { background: var(--surface-2); color: var(--ink); border: 1px solid var(--line); }
.aic-mic.rec { background: var(--danger); color: #fff; border-color: transparent; animation: aic-p .8s infinite alternate; width: auto; padding: 0 10px; display: flex; gap: 4px; align-items: center; }
.aic-mic.wait { opacity: .6; } .aic-sec { font-size: 12px; font-weight: 800; }
.aic-send { background: #7C3AED; color: #fff; }
.aic-stop { background: var(--danger); } .aic-sq { width: 14px; height: 14px; border-radius: 3px; background: #fff; }
.aic-b.live::after { content: '▍'; animation: aic-bl 1s steps(2) infinite; color: #7C3AED; } @keyframes aic-bl { 50% { opacity: 0; } }
.aic-chart { display: block; margin-top: 6px; border-radius: 12px; overflow: hidden; border: 1px solid var(--line); background: #fff; max-width: 100%; }
.aic-chart img { display: block; width: 100%; height: auto; }
.aic-m.ai:has(.aic-chart) { max-width: 96%; } .aic-send:disabled, .aic-mic:disabled { opacity: .45; cursor: default; }
@media (max-width: 1024px) and (min-width: 601px) { .aic-fab { bottom: 20px; } }
@media (max-width: 600px) {
  .aic-fab { right: 14px; bottom: calc(78px + env(safe-area-inset-bottom)); width: 52px; height: 52px; }
  .lifted .aic-fab { bottom: calc(148px + env(safe-area-inset-bottom)); }
  .aic { inset: 0; width: 100%; height: 100dvh; border-radius: 0; border: 0; z-index: 60; }
  .aic-hd { padding-top: calc(12px + env(safe-area-inset-top)); }
  .aic-in { padding-bottom: calc(10px + env(safe-area-inset-bottom)); }
}
</style>
