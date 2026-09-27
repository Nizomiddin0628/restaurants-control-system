<script setup lang="ts">
/**
 * AI Kotib — rahbar va menejerlar uchun:
 *   • har kuni ertalab Telegram'ga hisobot (kecha + bugun + prognoz + «birinchi navbatda»);
 *   • Telegram'da «🤖 AI Kotib» → ovozli buyruq → tasdiq → javob;
 *   • shu sahifada: hisobotni ko'rish/yuborish, savol berish, sozlamalar (kalit, vaqt, chegara), jurnal.
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiEmpty, UiIcon, UiInput, UiToggle, toast } from '@restopos/ui'

const S = ref<any>(null)
const R = ref<any>(null)
const logs = ref<any[]>([])
const rLoading = ref(false)
const form = ref({ api_key: '', morning_enabled: true, morning_time: '08:30', daily_limit: 60 })
const saving = ref(false), testing = ref(false), sending = ref(false)
const q = ref(''), asking = ref(false), answer = ref<{ q: string; html: string; ok: boolean } | null>(null)
const EX = ['Kecha qancha savdo bo\'ldi, o\'tgan haftadan farqi qancha?', 'Omborda nima tugayapti va qancha xarid kerak?', 'Bugun kim smenada va nechta bron bor?', 'Shu oy foyda qancha, eng katta xarajat nima?']

async function loadStatus() {
  S.value = await api.get('/ai/status')
  form.value = { api_key: '', morning_enabled: S.value.morning_enabled, morning_time: S.value.morning_time, daily_limit: S.value.daily_limit }
}
async function loadReport(ai = false) {
  rLoading.value = true
  try { R.value = await api.get('/ai/report', { ai: ai ? 1 : 0 }) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { rLoading.value = false }
  if (ai) { loadLogs(); loadStatus() }
}
async function loadLogs() { logs.value = await api.get('/ai/logs') }
onMounted(async () => { await loadStatus(); loadReport(); loadLogs() })

async function save(extra: any = {}) {
  saving.value = true
  try {
    const body: any = { morning_enabled: form.value.morning_enabled, morning_time: form.value.morning_time, daily_limit: Number(form.value.daily_limit) || 60, ...extra }
    if (form.value.api_key.trim()) body.api_key = form.value.api_key.trim()
    S.value = await api.put('/ai/settings', body)
    form.value.api_key = ''
    toast('Saqlandi')
    if (body.api_key) testKey()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
async function testKey() {
  testing.value = true
  try {
    const r = await api.post('/ai/test')
    r.ok ? toast(`✅ AI ishlayapti (${r.model}, ${(r.ms / 1000).toFixed(1)} s)`) : toast(r.error, 'danger')
    loadLogs(); loadStatus()
  } finally { testing.value = false }
}
async function sendNow() {
  if (!confirm('Hisobot hozir Telegram\'dagi barcha oluvchilarga yuborilsinmi?')) return
  sending.value = true
  try { const r = await api.post('/ai/report/send'); toast(`Yuborildi: ${r.sent}${r.failed ? ` · xato: ${r.failed}` : ''}`); loadStatus(); loadLogs() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { sending.value = false }
}
/** Bitta so'rov qoidasi: javob kelmaguncha yangi savol yuborilmaydi (tugma o'chadi) */
async function ask(text?: string) {
  const question = (text ?? q.value).trim()
  if (!question || asking.value) return
  asking.value = true
  answer.value = { q: question, html: '', ok: true }
  try {
    const r = await api.post('/ai/ask', { question })
    answer.value = { q: question, html: r.ok ? r.answer : `⚠️ ${r.error}`, ok: r.ok }
    if (r.ok) q.value = ''
  } catch (e: any) { answer.value = { q: question, html: `⚠️ ${e.detail ?? 'Xato'}`, ok: false } } finally { asking.value = false; loadLogs(); loadStatus() }
}
const KIND: Record<string, string> = { ask: 'Savol', voice: 'Ovoz', report: 'Hisobot', test: 'Sinov' }
const CH: Record<string, string> = { telegram: 'Telegram', panel: 'Panel', morning: 'Ertalab' }
const ready = computed(() => S.value?.recipients?.filter((r: any) => r.telegram).length ?? 0)
</script>

<template>
  <div v-if="S" class="ai">
    <header class="ai-hd">
      <span class="ai-ic"><UiIcon name="spark" :size="26" /></span>
      <div class="ai-ht">
        <h2>AI Kotib</h2>
        <p>Har kuni ertalab Telegram'ga hisobot keladi. Botdagi «🤖 AI Kotib» tugmasi orqali ovozli buyruq berasiz — bot eshitadi, «bajaraymi?» deb so'raydi, keyin tahlil qiladi.</p>
      </div>
      <div class="ai-st">
        <UiChip :tone="S.has_key ? 'ok' : 'warn'">{{ S.has_key ? 'AI ulangan' : 'Kalit kerak' }}</UiChip>
        <small>Bugun: <b>{{ S.used_today }}</b> / {{ S.daily_limit }} so'rov</small>
      </div>
    </header>

    <!-- kalit yo'q: 3 qadam -->
    <UiCard v-if="!S.has_key" class="ai-setup">
      <h3>AI'ni ulash — 1 daqiqa</h3>
      <ol>
        <li><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener">aistudio.google.com</a> saytiga Google akkauntingiz bilan kiring.</li>
        <li><b>Create API key</b> (yoki borini) → yonidagi <b>nusxalash</b> belgisini bosing.</li>
        <li>Kalitni shu yerga qo'yib, <b>Saqlash</b>ni bosing — tizim o'zi tekshiradi.</li>
      </ol>
      <form v-if="S.can_manage" class="ai-key" @submit.prevent="save()">
        <UiInput v-model="form.api_key" type="password" placeholder="AIza…" />
        <UiButton type="submit" variant="brand" :loading="saving" :disabled="!form.api_key.trim()">Saqlash</UiButton>
      </form>
      <small>Bepul tarif restoraningiz uchun yetarli (kuniga bir necha o'nlab so'rov). Kalit maxfiy — uni hech kimga yubormang.</small>
    </UiCard>

    <div class="ai-grid">
      <!-- HISOBOT -->
      <UiCard :padded="false" class="ai-rep">
        <div class="ai-ch">
          <div><h3>Bugungi hisobot</h3><small>Telegram'da xuddi shunday ko'rinadi<template v-if="R"> · {{ R.generated_at }}</template></small></div>
          <div class="ai-acts">
            <UiButton size="s" variant="secondary" :loading="rLoading" :disabled="!S.has_key" @click="loadReport(true)"><UiIcon name="spark" :size="14" /> AI xulosasi bilan</UiButton>
            <UiButton v-if="S.can_manage" size="s" variant="brand" :loading="sending" :disabled="!S.bot_connected" @click="sendNow"><UiIcon name="send" :size="14" /> Telegramga yuborish</UiButton>
          </div>
        </div>
        <div class="ai-bubble-wrap">
          <div v-if="R" class="ai-bubble" v-html="R.html"></div>
          <div v-else class="ai-skel"></div>
        </div>
        <p v-if="R?.ai?.error && R.ai.error !== 'o\'chirilgan'" class="ai-warn">⚠️ AI xulosasi qo'shilmadi: {{ R.ai.error }} — «Birinchi navbatda» qoidalar bo'yicha tuzildi.</p>
      </UiCard>

      <div class="ai-side">
        <!-- SAVOL -->
        <UiCard title="Savol bering" subtitle="Telegram'dagidek — faqat yozma. Javob tizimdagi haqiqiy raqamlardan.">
          <div class="ai-ex">
            <button v-for="e in EX" :key="e" type="button" :disabled="asking || !S.has_key" @click="ask(e)">{{ e }}</button>
          </div>
          <form class="ai-ask" @submit.prevent="ask()">
            <textarea v-model="q" rows="2" :disabled="asking || !S.has_key" placeholder="Masalan: Rustamga ertaga 10:00 gacha muzlatgichni tozalash vazifasini ber" @keydown.enter.exact.prevent="ask()"></textarea>
            <UiButton type="submit" variant="brand" :loading="asking" :disabled="!q.trim() || !S.has_key">So'rash</UiButton>
          </form>
          <div v-if="answer" class="ai-ans" :class="{ bad: !answer.ok }">
            <small>❓ {{ answer.q }}</small>
            <div v-if="asking" class="ai-typing"><i></i><i></i><i></i> <span>Tahlil qilyapman… javob kelguncha yangi savol berilmaydi</span></div>
            <div v-else class="ai-bubble sm" v-html="answer.html"></div>
          </div>
        </UiCard>

        <!-- SOZLAMALAR -->
        <UiCard v-if="S.can_manage" title="Sozlamalar">
          <div class="ai-set">
            <UiInput v-model="form.api_key" type="password" :label="S.has_key ? `Gemini API kaliti (saqlangan: ${S.key_masked}${S.key_source === 'server' ? ' · serverniki' : ''})` : 'Gemini API kaliti'" placeholder="AIza…" hint="Yangi kalit kiritsangiz — eskisi almashadi" />
            <div class="ai-row">
              <UiButton variant="brand" :loading="saving" @click="save()">Saqlash</UiButton>
              <UiButton v-if="S.has_key" variant="secondary" :loading="testing" @click="testKey">Tekshirish</UiButton>
              <UiButton v-if="S.key_source === 'restoran'" variant="ghost" @click="save({ clear_key: true })">Kalitni o'chirish</UiButton>
            </div>
            <hr />
            <UiToggle v-model="form.morning_enabled" label="Har kuni ertalab hisobot yuborish" />
            <div class="ai-row two">
              <UiInput v-model="form.morning_time" type="time" label="Soat nechada" />
              <UiInput v-model="form.daily_limit" type="number" label="Kunlik so'rov chegarasi" hint="Bepul tarif uchun 60 yetarli" />
            </div>
            <UiButton variant="secondary" :loading="saving" @click="save()">Saqlash</UiButton>
          </div>
        </UiCard>
      </div>
    </div>

    <!-- OLUVCHILAR -->
    <UiCard :title="`Hisobot oluvchilar · ${ready}`" subtitle="Rahbar va menejerlar — Telegram botga telefon raqamini ulashganlar. Ruxsat: «Kirish va rollar»da «ai.use».">
      <div v-if="S.recipients.length" class="ai-rc">
        <div v-for="r in S.recipients" :key="r.id" class="ai-rc-i" :class="{ off: !r.telegram }">
          <b>{{ r.name }}</b><small>{{ r.role }}</small>
          <UiChip :tone="!r.telegram ? 'neutral' : r.sent_today === true ? 'ok' : r.sent_today === false ? 'danger' : 'info'">
            {{ !r.telegram ? 'Telegram ulanmagan' : r.sent_today === true ? 'Bugun oldi' : r.sent_today === false ? 'Yuborilmadi' : 'Telegram ✓' }}</UiChip>
        </div>
      </div>
      <UiEmpty v-else title="Hali oluvchi yo'q" text="Rahbar va menejerlar botga /start yozib, telefon raqamini ulashsin." />
      <p v-if="!S.bot_connected" class="ai-warn">⚠️ Telegram bot ulanmagan — «Telegram bot» sahifasida tokenni kiriting.</p>
    </UiCard>

    <!-- JURNAL -->
    <UiCard title="So'nggi so'rovlar" :padded="false">
      <div v-if="logs.length" class="ai-log">
        <div v-for="l in logs" :key="l.id" class="ai-log-i" :class="{ bad: !l.ok }">
          <span class="ai-log-k"><UiChip :tone="l.ok ? 'neutral' : 'danger'">{{ KIND[l.kind] ?? l.kind }}</UiChip><small>{{ CH[l.channel] ?? l.channel }}</small></span>
          <span class="ai-log-q"><b>{{ l.question }}</b><small v-if="l.answer">{{ l.answer.replace(/<[^>]+>/g, '') }}</small><small v-if="l.error" class="err">{{ l.error }}</small></span>
          <span class="ai-log-m"><small>{{ l.at }} · {{ l.user }}</small><small v-if="l.calls">{{ l.calls }} so'rov · {{ l.sec }} s</small></span>
        </div>
      </div>
      <UiEmpty v-else title="Hali so'rov yo'q" />
    </UiCard>
  </div>
</template>

<style scoped>
.ai { display: flex; flex-direction: column; gap: 14px; }
.ai-hd { display: flex; gap: 14px; align-items: center; padding: 16px 18px; border-radius: 18px; color: var(--ink);
  background: linear-gradient(135deg, color-mix(in srgb, #7C3AED 12%, var(--surface)), color-mix(in srgb, #0891B2 10%, var(--surface))); border: 1px solid color-mix(in srgb, #7C3AED 22%, var(--line)); }
.ai-ic { width: 52px; height: 52px; border-radius: 16px; display: grid; place-items: center; background: linear-gradient(135deg, #7C3AED, #0891B2); color: #fff; flex-shrink: 0; }
.ai-ht { flex: 1; min-width: 0; } .ai-ht h2 { margin: 0; font-family: var(--font-display); font-size: 22px; } .ai-ht p { margin: 2px 0 0; color: var(--ink-2); font-size: var(--fs-s); }
.ai-st { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0; } .ai-st small { color: var(--muted); font-size: var(--fs-xs); }
.ai-setup h3 { margin: 0 0 8px; } .ai-setup ol { margin: 0 0 8px; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; } .ai-setup a { color: var(--accent); font-weight: 700; }
.ai-setup small { color: var(--muted); }
.ai-key { display: flex; gap: 8px; align-items: flex-start; margin: 4px 0 10px; max-width: 560px; } .ai-key > :first-child { flex: 1; min-width: 0; }
.ai-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.ai-side { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.ai-ch { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; padding: 16px 18px 12px; }
.ai-ch h3 { margin: 0; font-size: var(--fs-b); } .ai-ch small { color: var(--muted); font-size: var(--fs-xs); }
.ai-acts { display: flex; gap: 8px; flex-wrap: wrap; }
.ai-bubble-wrap { padding: 4px 18px 18px; background: color-mix(in srgb, #0891B2 5%, var(--surface-2)); border-top: 1px solid var(--line); }
.ai-bubble { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.5; background: var(--surface); border-radius: 4px 16px 16px 16px; padding: 14px 16px; margin-top: 14px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .06); max-width: 640px; }
.ai-bubble.sm { margin-top: 6px; max-width: none; background: var(--surface-2); }
.ai-skel { height: 420px; margin-top: 14px; border-radius: 16px; background: var(--surface); animation: ai-pl 1.1s infinite alternate; }
@keyframes ai-pl { to { opacity: .5; } }
.ai-warn { margin: 0; padding: 10px 18px; font-size: var(--fs-xs); color: var(--warn-ink, #92400E); background: var(--warn-tint); }
.ai-ex { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.ai-ex button { border: 1px solid var(--line); background: var(--surface-2); color: var(--ink-2); border-radius: 99px; padding: 6px 12px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; text-align: left; }
.ai-ex button:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); } .ai-ex button:disabled { opacity: .5; cursor: default; }
.ai-ask { display: flex; gap: 8px; align-items: flex-end; }
.ai-ask textarea { flex: 1; min-width: 0; resize: vertical; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); min-height: 48px; }
.ai-ans { margin-top: 12px; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--line); } .ai-ans small { color: var(--muted); font-size: var(--fs-xs); }
.ai-ans.bad { border-color: color-mix(in srgb, var(--danger) 40%, var(--line)); }
.ai-typing { display: flex; align-items: center; gap: 4px; padding: 8px 0; color: var(--muted); font-size: var(--fs-xs); }
.ai-typing i { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: ai-dot 1s infinite ease-in-out; } .ai-typing i:nth-child(2) { animation-delay: .15s; } .ai-typing i:nth-child(3) { animation-delay: .3s; }
.ai-typing span { margin-left: 6px; }
@keyframes ai-dot { 50% { transform: translateY(-4px); opacity: .5; } }
.ai-set { display: flex; flex-direction: column; gap: 10px; } .ai-set hr { border: 0; border-top: 1px solid var(--line); margin: 4px 0; width: 100%; }
.ai-row { display: flex; gap: 8px; flex-wrap: wrap; } .ai-row.two > * { flex: 1 1 160px; }
.ai-rc { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr)); gap: 8px; }
.ai-rc-i { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px; min-width: 0; }
.ai-rc-i b { font-size: var(--fs-s); } .ai-rc-i small { color: var(--muted); font-size: var(--fs-xs); } .ai-rc-i > :last-child { align-self: flex-start; } .ai-rc-i.off { opacity: .7; }
.ai-log { display: flex; flex-direction: column; }
.ai-log-i { display: grid; grid-template-columns: 110px minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 10px 16px; border-top: 1px solid var(--line-2); }
.ai-log-i:first-child { border-top: 0; }
.ai-log-k { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; } .ai-log-k small { color: var(--muted); font-size: 11px; }
.ai-log-q { display: flex; flex-direction: column; min-width: 0; } .ai-log-q b { font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-log-q small { color: var(--ink-2); font-size: var(--fs-xs); overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.ai-log-q .err { color: var(--danger); }
.ai-log-m { display: flex; flex-direction: column; align-items: flex-end; } .ai-log-m small { color: var(--muted); font-size: 11px; white-space: nowrap; }
@media (max-width: 1100px) { .ai-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 600px) {
  .ai-hd { flex-wrap: wrap; padding: 14px; } .ai-st { flex-direction: row; align-items: center; width: 100%; justify-content: space-between; }
  .ai-ic { width: 44px; height: 44px; } .ai-ht h2 { font-size: 19px; }
  .ai-ch { padding: 14px 14px 10px; } .ai-acts { width: 100%; } .ai-acts > * { flex: 1 1 auto; }
  .ai-bubble-wrap { padding: 2px 10px 12px; } .ai-bubble { padding: 12px; font-size: 13.5px; }
  .ai-ask { flex-direction: column; align-items: stretch; }
  .ai-log-i { grid-template-columns: minmax(0, 1fr); gap: 4px; } .ai-log-k { flex-direction: row; gap: 8px; align-items: center; } .ai-log-m { align-items: flex-start; flex-direction: row; gap: 8px; }
}
</style>
