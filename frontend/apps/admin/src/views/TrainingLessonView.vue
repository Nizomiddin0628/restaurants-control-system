<script setup lang="ts">
/**
 * Dars: video (yuklangan fayl yoki YouTube) + tavsif + dars mazmuni + fayllar.
 * Nazorat: har 5 soniyada serverga "beat" (qayerda turibdi, qancha ko'rdi). Oldinga surish taqiqlangan bo'lsa —
 * video ko'rilgan eng uzoq nuqtaga qaytariladi. Foizni server hisoblaydi (brauzerga ishonmaydi).
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, auth } from '@restopos/api'
import { UiIcon, toast } from '@restopos/ui'
import { youtubeId } from '@/components/training/upload'
import '@/components/training/tr.css'

const route = useRoute(), router = useRouter()
const L = ref<any>(null)
const tab = ref<'desc' | 'files'>('desc')
const percent = ref(0)
const done = ref(false)
const videoEl = ref<HTMLVideoElement | null>(null)
const ytBox = ref<HTMLDivElement | null>(null)
let maxPos = 0, lastWall = 0, played = 0, playing = false, timer: number | undefined, ytPoll: number | undefined, yt: any = null, duration = 0

const ytId = computed(() => (L.value && !L.value.video ? youtubeId(L.value.video_url) : null))
const otherUrl = computed(() => (L.value && !L.value.video && L.value.video_url && !ytId.value ? L.value.video_url : null))
const need = computed(() => L.value?.rules.min_watch_percent ?? 90)

async function load() {
  stop(); yt?.destroy?.(); yt = null
  try { L.value = await api.get(`/training/my/lessons/${route.params.id}`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); router.back(); return }
  tab.value = 'desc'
  percent.value = L.value.progress.percent; done.value = L.value.progress.done
  maxPos = L.value.progress.max_position || 0; played = 0; duration = L.value.duration_seconds || 0
  if (ytId.value) setTimeout(initYoutube, 0)
}
onMounted(load)
watch(() => route.params.id, () => { if (route.name === 'training-lesson') load() })

// ---------- serverga yurak urishi
function tick() {
  const now = performance.now()
  if (playing && lastWall) played += (now - lastWall) / 1000
  lastWall = now
}
async function send(keepalive = false) {
  tick()
  const pos = currentTime()
  if (!L.value || (!played && !keepalive)) return
  const body = { position: pos, duration: duration || 0, played }
  played = 0
  if (keepalive) {
    fetch(`/api/v1/training/my/lessons/${L.value.id}/beat`, { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}` }, body: JSON.stringify(body) }).catch(() => {})
    return
  }
  try {
    const r = await api.post(`/training/my/lessons/${L.value.id}/beat`, body)
    percent.value = r.percent
    if (r.done && !done.value) { done.value = true; toast('Dars ko\'rildi ✓ Keyingisiga o\'tishingiz mumkin') }
  } catch { /* tarmoq xatosi — keyingi urinishda */ }
}
function start() { playing = true; lastWall = performance.now(); if (!timer) timer = window.setInterval(() => send(), 5000) }
function pause() { tick(); playing = false; send() }
function stop() { if (timer) clearInterval(timer); timer = undefined; if (ytPoll) clearInterval(ytPoll); ytPoll = undefined; if (playing || played) send(true); playing = false }
const onHide = () => stop()
onMounted(() => window.addEventListener('pagehide', onHide))
onBeforeUnmount(() => { window.removeEventListener('pagehide', onHide); stop(); yt?.destroy?.() })

function currentTime() { return videoEl.value ? videoEl.value.currentTime : yt?.getCurrentTime ? yt.getCurrentTime() : 0 }

// ---------- HTML5 video
function onMeta() {
  const v = videoEl.value!; duration = v.duration || 0
  const resume = L.value.progress.last_position
  if (resume && resume < duration - 3) v.currentTime = Math.min(resume, maxPos || resume)
}
function onTime() {
  const v = videoEl.value!
  if (!v.seeking && v.currentTime <= maxPos + 2) maxPos = Math.max(maxPos, v.currentTime)
}
function onSeeking() {
  const v = videoEl.value!
  if (L.value.rules.block_seek && !done.value && v.currentTime > maxPos + 2) {
    v.currentTime = maxPos
    toast('Videoni oldinga o\'tkazib bo\'lmaydi — oxirigacha ko\'ring', 'info')
  }
}

// ---------- YouTube
function initYoutube() {
  const make = () => {
    const w = window as any
    yt = new w.YT.Player(ytBox.value, {
      videoId: ytId.value, playerVars: { rel: 0, modestbranding: 1, playsinline: 1, start: Math.floor(Math.min(L.value.progress.last_position || 0, maxPos)) },
      events: {
        onReady: () => { duration = yt.getDuration() || duration },
        onStateChange: (e: any) => { if (e.data === 1) { duration = yt.getDuration() || duration; start() } else if (e.data === 2 || e.data === 0) pause() },
      },
    })
    ytPoll = window.setInterval(() => {
      if (!yt?.getCurrentTime) return
      const t = yt.getCurrentTime()
      if (L.value.rules.block_seek && !done.value && t > maxPos + 3) { yt.seekTo(maxPos, true); toast('Videoni oldinga o\'tkazib bo\'lmaydi', 'info') }
      else if (t <= maxPos + 3) maxPos = Math.max(maxPos, t)
    }, 1000)
  }
  const w = window as any
  if (w.YT?.Player) return make()
  const prev = w.onYouTubeIframeAPIReady
  w.onYouTubeIframeAPIReady = () => { prev?.(); make() }
  if (!document.getElementById('yt-api')) { const s = document.createElement('script'); s.id = 'yt-api'; s.src = 'https://www.youtube.com/iframe_api'; document.head.appendChild(s) }
}

// ---------- tugatish / keyingi
async function next() {
  if (!L.value.has_video && !done.value) {
    try { await api.post(`/training/my/lessons/${L.value.id}/complete`); done.value = true } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); return }
  }
  if (!done.value) { toast(`Videoni kamida ${need.value}% ko'ring (hozir ${percent.value}%)`, 'info'); return }
  if (L.value.quizzes.length) return router.push(`/training/quiz/${L.value.quizzes[0].id}`)
  if (L.value.next_id) return router.push(`/training/lesson/${L.value.next_id}`)
  if (L.value.final_quiz_id) return router.push(`/training/quiz/${L.value.final_quiz_id}`)
  router.push(`/training/course/${L.value.course_id}`)
}
const nextLabel = computed(() => {
  if (!L.value) return ''
  const after = L.value.quizzes.length ? 'testga o\'tish' : L.value.next_id ? 'keyingi dars' : L.value.final_quiz_id ? 'yakuniy test' : 'tugatish'
  if (!L.value.has_video && !done.value) return `O'qidim — ${after}`
  return after.charAt(0).toUpperCase() + after.slice(1)
})
</script>

<template>
  <div v-if="L" class="lv">
    <div class="topbar">
      <RouterLink :to="`/training/course/${L.course_id}`" class="tr-back"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /> {{ L.course_title }}</RouterLink>
    </div>

    <div class="player" :class="{ novideo: !L.has_video && !L.image }">
      <video v-if="L.video" ref="videoEl" :src="L.video" controls playsinline controlslist="nodownload noplaybackrate" disablepictureinpicture
             @loadedmetadata="onMeta" @timeupdate="onTime" @seeking="onSeeking" @play="start" @pause="pause" @ended="pause"></video>
      <div v-else-if="ytId" class="yt"><div ref="ytBox"></div></div>
      <a v-else-if="otherUrl" :href="otherUrl" target="_blank" rel="noopener" class="ext">▶ Videoni ochish</a>
      <img v-else-if="L.image" :src="L.image" alt="" />
      <div v-else class="ph"><UiIcon name="book" :size="40" /></div>
    </div>

    <div class="body">
      <div class="head">
        <div><h2>{{ L.title }}</h2><span class="tr-muted">Dars {{ L.number }}/{{ L.total }}</span></div>
        <span v-if="done" class="ok">✓ Ko'rildi</span>
      </div>
      <div v-if="L.has_video" class="watch">
        <div class="tr-bar"><i :style="{ width: percent + '%' }"></i></div>
        <small>{{ percent }}% ko'rildi · dars hisoblanishi uchun {{ need }}%<template v-if="L.rules.block_seek"> · oldinga o'tkazib bo'lmaydi</template></small>
      </div>

      <nav class="tabs">
        <button :class="{ on: tab === 'desc' }" @click="tab = 'desc'">Tavsif</button>
        <button :class="{ on: tab === 'files' }" @click="tab = 'files'">Fayllar<span v-if="L.files.length"> ({{ L.files.length }})</span></button>
      </nav>

      <div v-if="tab === 'desc'" class="desc">
        <img v-if="L.image && L.has_video" :src="L.image" alt="" class="inline" />
        <p v-if="L.body">{{ L.body }}</p>
        <template v-if="L.checklist.length">
          <h4>Dars mazmuni</h4>
          <ul class="check"><li v-for="(c, i) in L.checklist" :key="i"><span class="cb">✓</span>{{ c }}</li></ul>
        </template>
      </div>
      <div v-else class="files">
        <a v-for="f in L.files" :key="f.id" :href="f.url" target="_blank" rel="noopener" class="file">
          <img v-if="f.is_image" :src="f.url" alt="" /><span v-else class="fi"><UiIcon name="paperclip" :size="18" /></span>
          <span class="fn">{{ f.title }}<small>{{ (f.size_bytes / 1024 / 1024).toFixed(1) }} MB</small></span>
        </a>
        <p v-if="!L.files.length" class="tr-muted">Bu darsda qo'shimcha fayl yo'q.</p>
      </div>

      <div class="nav">
        <button v-if="L.prev_id" class="tr-btn ghost" type="button" @click="router.push(`/training/lesson/${L.prev_id}`)">←</button>
        <button class="tr-btn block" type="button" :disabled="L.has_video && !done" @click="next">{{ nextLabel }} →</button>
      </div>
      <p v-if="L.has_video && !done" class="hint tr-muted">Tugma video {{ need }}% ko'rilganda ochiladi.</p>
    </div>
  </div>
</template>

<style scoped>
.lv { display: flex; flex-direction: column; gap: 12px; max-width: 900px; width: 100%; margin: 0 auto; }
.player { border-radius: 16px; overflow: hidden; background: #000; aspect-ratio: 16 / 9; display: grid; place-items: center; }
.player.novideo { background: var(--tr-gold-tint); aspect-ratio: 16 / 5; }
.player video, .player img { width: 100%; height: 100%; object-fit: contain; display: block; }
.yt { width: 100%; height: 100%; } .yt :deep(iframe), .yt > div { width: 100%; height: 100%; }
.ext { color: #fff; font-weight: 800; font-size: 18px; text-decoration: none; }
.ph { color: var(--tr-gold); }
.body { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.head h2 { margin: 0; font-size: 20px; font-weight: 800; }
.ok { color: var(--tr-green); font-weight: 800; white-space: nowrap; }
.watch { display: flex; flex-direction: column; gap: 6px; } .watch small { color: var(--muted); }
.tabs { display: flex; border-bottom: 1px solid var(--line); gap: 4px; }
.tabs button { flex: 1; min-height: 44px; border: 0; background: none; font: inherit; font-weight: 700; color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tabs button.on { color: var(--ink); border-bottom-color: var(--tr-gold); }
.desc p { margin: 0 0 6px; line-height: 1.6; color: var(--ink-2); white-space: pre-line; }
.desc h4 { margin: 12px 0 8px; font-size: 16px; font-weight: 800; }
.inline { width: 100%; border-radius: 12px; margin-bottom: 10px; }
.check { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.check li { display: flex; align-items: center; gap: 10px; font-size: 15px; }
.cb { width: 22px; height: 22px; border-radius: 6px; background: var(--tr-green); color: #fff; display: grid; place-items: center; font-size: 13px; font-weight: 900; flex-shrink: 0; }
.files { display: flex; flex-direction: column; gap: 8px; }
.file { display: flex; align-items: center; gap: 12px; padding: 10px; border: 1px solid var(--line); border-radius: 12px; color: inherit; text-decoration: none; }
.file img { width: 48px; height: 48px; object-fit: cover; border-radius: 8px; }
.fi { width: 48px; height: 48px; border-radius: 8px; background: var(--surface-3); display: grid; place-items: center; }
.fn { display: flex; flex-direction: column; font-weight: 700; } .fn small { color: var(--muted); font-weight: 500; }
.nav { display: flex; gap: 8px; } .nav .ghost { flex: 0 0 56px; }
.hint { margin: -6px 0 0; font-size: 12px; text-align: center; }
@media (max-width: 600px) { .player { border-radius: 12px; margin: 0 calc(-1 * var(--gutter)); border-radius: 0; } .body { padding: 14px; } }
</style>
