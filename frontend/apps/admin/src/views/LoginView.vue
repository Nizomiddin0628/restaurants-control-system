<script setup lang="ts">
/**
 * Kirish — oddiy sayt kabi. Asosiy usul: telefon raqam → «Telegram orqali kirish» → botda «✅ Ha» → sayt o'zi ochiladi.
 * Muqobil: parol bilan (rahbar bergan) yoki bir martalik kod bilan.
 * Boshqa restorandan o'tish havolasi (?switch=...) — hech narsa so'ramasdan kiradi.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UiButton, UiInput, UiCard, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter(), route = useRoute()
const LAST = 'restopos.phone'
const saved = (() => { try { return localStorage.getItem(LAST) || '' } catch { return '' } })()
type Mode = 'tg' | 'wait' | 'link' | 'password' | 'otp'
const mode = ref<Mode>('tg')
const phone = ref(saved || '+998 '), password = ref(''), showPw = ref(false), forgot = ref(false)
const via = ref(''), code = ref(''), step = ref<'phone' | 'code'>('phone'), loading = ref(false), err = ref(''), devCode = ref('')
const bot = ref(''), left = ref(0)
let timer: ReturnType<typeof setInterval> | null = null, req: { id: string; secret: string } | null = null

function remember() { try { localStorage.setItem(LAST, phone.value) } catch { /* private */ } }
function done() { remember(); stop(); toast('Xush kelibsiz!'); router.push(a.me?.home || '/') }
function stop() { if (timer) clearInterval(timer); timer = null; req = null }
onBeforeUnmount(stop)
const botUrl = computed(() => (bot.value ? `https://t.me/${bot.value}` : ''))

async function tgStart() {
  loading.value = true; err.value = ''
  try {
    const r = await a.tgStart(phone.value)
    bot.value = r.bot_username || ''
    remember()
    if (!r.ok) { mode.value = 'link'; if (r.reason === 'bot_off') err.value = 'Restoran boti hozir ishlamayapti — parol bilan kiring yoki rahbaringizga ayting.'; return }
    req = { id: r.id!, secret: r.secret! }; left.value = r.ttl ?? 180; mode.value = 'wait'
    let tick = 0
    timer = setInterval(async () => {
      left.value = Math.max(0, left.value - 1)
      if (left.value === 0) { stop(); err.value = 'Vaqt tugadi — qaytadan bosing.'; mode.value = 'tg'; return }
      if (++tick % 2 || !req) return
      try {
        const st = await a.tgPoll(req.id, req.secret)
        if (st === 'ok') done()
        else if (st === 'no') { stop(); mode.value = 'tg'; err.value = 'Kirish rad etildi.' }
        else if (st === 'expired') { stop(); mode.value = 'tg'; err.value = 'So\'rov eskirdi — qaytadan bosing.' }
      } catch { /* tarmoq — keyingi urinishda */ }
    }, 1000)
  } catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
function cancel() { stop(); mode.value = 'tg'; err.value = '' }

async function loginPw() {
  loading.value = true; err.value = ''
  try { await a.login(phone.value, password.value); done() }
  catch (e: any) { err.value = e.detail ?? 'Telefon yoki parol noto\'g\'ri' } finally { loading.value = false }
}
async function sendOtp() {
  loading.value = true; err.value = ''
  try { const r = await a.requestOtp(phone.value); step.value = 'code'; via.value = r.via ?? ''; if (r.dev_code) devCode.value = r.dev_code }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
async function verify() {
  loading.value = true; err.value = ''
  try { await a.verify(phone.value, code.value); done() }
  catch (e: any) { err.value = e.detail ?? 'Kod noto\'g\'ri' } finally { loading.value = false }
}
const hint = computed(() => via.value === 'telegram' ? '✈️ Kod Telegram\'ingizga (restoran boti) yuborildi'
  : via.value === 'sms' ? `💬 ${phone.value} raqamiga SMS yuborildi`
  : devCode.value ? `Sinov rejimi — kod: ${devCode.value}` : 'SMS xizmati hali ulanmagan. Telegram orqali yoki parol bilan kiring.')
function setMode(m: Mode) { stop(); mode.value = m; err.value = ''; step.value = 'phone'; code.value = '' }

const switching = ref(false)
onMounted(async () => {
  const c = route.query.switch
  if (typeof c !== 'string' || !c) return
  switching.value = true
  try { await a.switchIn(c); router.replace(a.me?.home || '/') }
  catch (e: any) { err.value = e.detail ?? 'Havola eskirgan — qaytadan kiring'; switching.value = false; router.replace('/login') }
})
</script>
<template>
  <div class="login">
    <UiCard class="box">
      <div class="brand"><span class="logo">R</span><div><b>Boshqaruv paneli</b><p class="muted">Telefon raqamingiz bilan kiring</p></div></div>
      <p v-if="switching" class="sw">Restoranga o'tilmoqda…</p>
      <template v-else>

        <!-- 1) Telegram orqali (asosiy) -->
        <form v-if="mode === 'tg'" @submit.prevent="tgStart">
          <UiInput v-model="phone" label="Telefon raqamingiz" type="tel" placeholder="+998 90 123 45 67" autocomplete="username" :error="err" />
          <UiButton type="submit" :loading="loading" block size="l" class="tgb">✈️ Telegram orqali kirish</UiButton>
          <p class="muted sm">Restoran botiga «Kirishni tasdiqlaysizmi?» xabari keladi — «✅ Ha» ni bosing, bo'ldi.</p>
          <div class="alt"><button type="button" class="lnk" @click="setMode('password')">🔑 Parol bilan kirish</button><button type="button" class="lnk" @click="setMode('otp')">🔢 Kod bilan kirish</button></div>
        </form>

        <!-- 2) Telegram'da tasdiqlashni kutish -->
        <div v-else-if="mode === 'wait'" class="wait">
          <div class="pulse">✈️</div>
          <b>Telegram'ni oching va «✅ Ha, men kiryapman» ni bosing</b>
          <p class="muted sm">{{ phone }} · {{ Math.floor(left / 60) }}:{{ String(left % 60).padStart(2, '0') }}</p>
          <a v-if="botUrl" class="open" :href="botUrl" target="_blank" rel="noopener">Telegram'da botni ochish</a>
          <UiButton variant="ghost" block @click="cancel()">Bekor qilish</UiButton>
        </div>

        <!-- 3) Botga hali ulanmagan -->
        <div v-else-if="mode === 'link'" class="link">
          <p v-if="err" class="er">{{ err }}</p>
          <template v-else>
            <b>Avval restoran botiga ulaning (bir marta):</b>
            <ol>
              <li>Telegram'da <a v-if="botUrl" :href="botUrl" target="_blank" rel="noopener">@{{ bot }}</a><span v-else>restoran botini</span> oching va <b>/start</b> bosing.</li>
              <li><b>«📱 Telefonni ulashish»</b> tugmasini bosing ({{ phone }}).</li>
              <li>Shu sahifaga qaytib, qaytadan <b>«Telegram orqali kirish»</b>ni bosing.</li>
            </ol>
            <a v-if="botUrl" class="open" :href="botUrl" target="_blank" rel="noopener">Botni ochish</a>
          </template>
          <UiButton block @click="setMode('tg')">Qaytadan urinish</UiButton>
          <button type="button" class="lnk" @click="setMode('password')">🔑 Parol bilan kirish</button>
        </div>

        <!-- 4) Parol bilan -->
        <form v-else-if="mode === 'password'" @submit.prevent="loginPw">
          <p class="otp-h"><button type="button" class="lnk2" @click="setMode('tg')">← Telegram orqali kirish</button> Parol bilan kirish</p>
          <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" autocomplete="username" />
          <div class="pw">
            <UiInput v-model="password" label="Parol" :type="showPw ? 'text' : 'password'" autocomplete="current-password" :error="err" />
            <button type="button" class="eye" :aria-label="showPw ? 'Parolni yashirish' : 'Parolni ko\'rsatish'" @click="showPw = !showPw">{{ showPw ? '🙈' : '👁' }}</button>
          </div>
          <UiButton type="submit" :loading="loading" :disabled="!password" block size="l">Kirish</UiButton>
          <button type="button" class="lnk" @click="forgot = !forgot">Parolni unutdingizmi?</button>
          <p v-if="forgot" class="fg">Telegram orqali kiring yoki rahbaringiz «Xodimlar va kirish» sahifasida sizga yangi parol beradi.</p>
        </form>

        <!-- 5) Bir martalik kod -->
        <template v-else>
          <p class="otp-h"><button type="button" class="lnk2" @click="setMode('tg')">← Telegram orqali kirish</button> Kod bilan kirish</p>
          <form v-if="step === 'phone'" @submit.prevent="sendOtp">
            <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" :error="err" autocomplete="tel" />
            <UiButton type="submit" :loading="loading" block size="l">Kod olish</UiButton>
          </form>
          <form v-else @submit.prevent="verify">
            <UiInput v-model="code" label="Kod" inputmode="numeric" placeholder="123456" :error="err" :hint="hint" autocomplete="one-time-code" />
            <UiButton type="submit" :loading="loading" block size="l">Kirish</UiButton>
            <UiButton variant="ghost" block @click="step = 'phone'">Raqamni o'zgartirish</UiButton>
          </form>
        </template>
      </template>
    </UiCard>
  </div>
</template>
<style scoped>
.login { min-height: 100vh; min-height: 100dvh; display: grid; place-items: center; padding: 16px; }
.box { width: min(440px, 100%); }
.sw { text-align: center; font-weight: 700; color: var(--muted); padding: 18px 0 6px; margin: 0; }
.brand { display: flex; gap: 12px; align-items: center; } .brand p { margin: 2px 0 0; font-size: var(--fs-s); }
.logo { width: 44px; height: 44px; border-radius: 12px; background: var(--brand); color: var(--brand-ink); display: grid; place-items: center; font-family: var(--font-display); font-weight: 800; font-size: 20px; flex-shrink: 0; }
form, .wait, .link { display: flex; flex-direction: column; gap: 12px; }
.tgb { background: #229ED9 !important; border-color: #229ED9 !important; color: #fff !important; }
.alt { display: flex; justify-content: center; gap: 14px; flex-wrap: wrap; }
.pw { position: relative; }
.eye { position: absolute; right: 8px; top: 28px; width: 36px; height: 36px; border: 0; background: transparent; cursor: pointer; font-size: 18px; border-radius: 8px; }
.lnk { border: 0; background: transparent; color: var(--accent); font: inherit; font-size: var(--fs-s); font-weight: 700; cursor: pointer; padding: 6px 4px; }
.muted { color: var(--muted); } .sm { font-size: var(--fs-xs); margin: 0; text-align: center; }
.fg { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); font-size: var(--fs-s); color: var(--ink-2); }
.lnk2 { border: 0; background: transparent; color: var(--muted); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; padding: 2px 0; text-align: left; text-decoration: underline; }
.otp-h { margin: 0; display: flex; flex-direction: column; gap: 4px; font-weight: 800; }
.wait { align-items: center; text-align: center; padding-top: 8px; }
.pulse { width: 72px; height: 72px; border-radius: 50%; display: grid; place-items: center; font-size: 34px; background: color-mix(in srgb, #229ED9 16%, transparent); animation: p 1.6s ease-in-out infinite; }
@keyframes p { 50% { transform: scale(1.08); box-shadow: 0 0 0 12px color-mix(in srgb, #229ED9 10%, transparent); } }
.open { display: inline-flex; justify-content: center; align-items: center; min-height: 44px; padding: 0 18px; border-radius: 12px; background: #229ED9; color: #fff; font-weight: 800; text-decoration: none; width: 100%; box-sizing: border-box; }
.link ol { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); }
.er { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--danger-tint); color: var(--danger); font-weight: 700; font-size: var(--fs-s); }
</style>
