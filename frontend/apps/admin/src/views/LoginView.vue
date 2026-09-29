<script setup lang="ts">
/**
 * Kirish sahifasi — oddiy sayt kabi, ikki bo'lim:
 *   «Kirish»: telefon → parol bo'lsa parol; unutgan bo'lsa → Telegram yoki kod bilan tasdiqlab yangi parol.
 *             Paroli yo'q xodim → raqamini tasdiqlaydi (Telegram / kod) → parol qo'yadi (yoki keyinroq).
 *   «Ro'yxatdan o'tish»: rahbar qo'shgan xodim birinchi marta — raqamini tasdiqlaydi va parol o'ylab topadi.
 *             Paroli bor bo'lsa — kod yuborilmaydi, «Kirish» ga yo'naltiriladi.
 * Telegram orqali: botga «Ha/Yo'q» keladi; bot hali ulanmagan bo'lsa — havola botni ochadi → «📱 Telefonni ulashish» → sayt o'zi kiradi.
 * Boshqa restorandan o'tish havolasi (?switch=...) — hech narsa so'ramasdan kiradi.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UiButton, UiInput, UiCard, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter(), route = useRoute()
const LAST = 'restopos.phone'
const saved = (() => { try { return localStorage.getItem(LAST) || '' } catch { return '' } })()
type Tab = 'login' | 'register'
type Step = 'phone' | 'password' | 'verify' | 'tg' | 'code' | 'setpw' | 'registered'
type Purpose = 'login' | 'first' | 'register' | 'reset'
const tab = ref<Tab>('login'), step = ref<Step>('phone'), purpose = ref<Purpose>('login')
const phone = ref(saved || '+998 '), password = ref(''), showPw = ref(false)
const pw1 = ref(''), pw2 = ref(''), resetToken = ref('')
const code = ref(''), via = ref(''), devCode = ref('')
const loading = ref(false), err = ref('')
const info = ref<{ has_password: boolean; telegram: boolean; bot: string } | null>(null)
const tg = ref<{ id: string; secret: string; link: string; linked: boolean } | null>(null), left = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

function remember() { try { localStorage.setItem(LAST, phone.value) } catch { /* private */ } }
function stop() { if (timer) clearInterval(timer); timer = null }
onBeforeUnmount(stop)
function reset(t?: Tab) { stop(); if (t) tab.value = t; step.value = 'phone'; err.value = ''; password.value = ''; code.value = ''; pw1.value = ''; pw2.value = ''; tg.value = null }
function finish() { remember(); stop(); toast('Xush kelibsiz!'); router.push(a.me?.home || '/') }

// 1) telefon → holatga qarab keyingi qadam
async function next() {
  loading.value = true; err.value = ''
  try {
    info.value = await a.check(phone.value)
    remember()
    if (tab.value === 'register') {
      if (info.value.has_password) { step.value = 'registered'; return }
      purpose.value = 'register'; step.value = 'verify'
    } else if (info.value.has_password) { purpose.value = 'login'; step.value = 'password' }
    else { purpose.value = 'first'; step.value = 'verify' }
  } catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
// 2a) parol bilan
async function loginPw() {
  loading.value = true; err.value = ''
  try { await a.login(phone.value, password.value); finish() }
  catch (e: any) { err.value = e.detail ?? 'Parol noto\'g\'ri' } finally { loading.value = false }
}
function forgot() { purpose.value = 'reset'; step.value = 'verify'; err.value = '' }
function viaTelegram() { purpose.value = purpose.value === 'login' ? 'login' : purpose.value; startTg() }
// 2b) Telegram orqali tasdiqlash / kirish
async function startTg() {
  loading.value = true; err.value = ''
  try {
    const r = await a.tgStart(phone.value)
    if (!r.ok) { err.value = 'Restoran Telegram boti hozir ulanmagan — kod bilan tasdiqlang yoki rahbaringizga ayting.'; return }
    tg.value = { id: r.id!, secret: r.secret!, link: r.link || '', linked: !!r.linked }; left.value = r.ttl ?? 300; step.value = 'tg'
    stop(); let tick = 0
    timer = setInterval(async () => {
      left.value = Math.max(0, left.value - 1)
      if (!left.value) { stop(); err.value = 'Vaqt tugadi — qaytadan urinib ko\'ring'; step.value = 'verify'; return }
      if (++tick % 2 || !tg.value) return
      try {
        const x = await a.tgPoll(tg.value.id, tg.value.secret)
        if (x.status === 'ok') { stop(); afterVerified(x.reset_token || '') }
        else if (x.status === 'no') { stop(); err.value = 'Kirish rad etildi'; step.value = 'verify' }
        else if (x.status === 'expired') { stop(); err.value = 'So\'rov eskirdi — qaytadan bosing'; step.value = 'verify' }
      } catch { /* tarmoq — keyingi urinish */ }
    }, 1000)
  } catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
// 2c) kod bilan
async function sendCode() {
  loading.value = true; err.value = ''
  try { const r = await a.requestOtp(phone.value); via.value = r.via ?? ''; devCode.value = r.dev_code ?? ''; step.value = 'code' }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
async function checkCode() {
  loading.value = true; err.value = ''
  try { const rt = await a.verify(phone.value, code.value); afterVerified(rt) }
  catch (e: any) { err.value = e.detail ?? 'Kod noto\'g\'ri' } finally { loading.value = false }
}
function afterVerified(rt: string) {
  resetToken.value = rt
  if (purpose.value === 'login') { finish(); return }
  step.value = 'setpw'; err.value = ''
}
// 3) parol qo'yish
async function savePw() {
  err.value = ''
  if (pw1.value.length < 6) { err.value = 'Kamida 6 ta belgi'; return }
  if (pw1.value !== pw2.value) { err.value = 'Ikkala parol bir xil emas'; return }
  loading.value = true
  try { await a.setPassword(pw1.value, resetToken.value); toast('Parol saqlandi'); finish() }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}

const codeHint = computed(() => via.value === 'telegram' ? '✈️ Kod Telegram\'ingizga (restoran boti) yuborildi'
  : via.value === 'sms' ? `💬 ${phone.value} raqamiga SMS yuborildi`
  : devCode.value ? `Sinov rejimi — kod: ${devCode.value}` : 'SMS xizmati hali ulanmagan — Telegram orqali tasdiqlang.')
const verifyTitle = computed(() => ({ first: 'Birinchi marta kiryapsiz', register: 'Ro\'yxatdan o\'tish', reset: 'Parolni tiklash', login: 'Kirish' }[purpose.value]))
const verifyText = computed(() => ({
  first: 'Sizda hali parol yo\'q. Raqamingiz sizniki ekanini tasdiqlang — keyin parol o\'ylab topasiz.',
  register: 'Raqamingiz sizniki ekanini tasdiqlang — keyin parol o\'ylab topasiz.',
  reset: 'Raqamingizni tasdiqlang — keyin yangi parol qo\'yasiz.',
  login: 'Qanday kirasiz?',
}[purpose.value]))
const mmss = computed(() => `${Math.floor(left.value / 60)}:${String(left.value % 60).padStart(2, '0')}`)

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
      <div class="brand"><span class="logo">R</span><div><b>Boshqaruv paneli</b><p class="muted">Restoran xodimlari uchun</p></div></div>
      <p v-if="switching" class="sw">Restoranga o'tilmoqda…</p>
      <template v-else>
        <div v-if="step === 'phone' || step === 'registered'" class="tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="tab === 'login'" :class="{ on: tab === 'login' }" @click="reset('login')">Kirish</button>
          <button type="button" role="tab" :aria-selected="tab === 'register'" :class="{ on: tab === 'register' }" @click="reset('register')">Ro'yxatdan o'tish</button>
        </div>
        <button v-else type="button" class="back" @click="reset()">← {{ phone }} · raqamni o'zgartirish</button>

        <!-- 1. TELEFON -->
        <form v-if="step === 'phone'" @submit.prevent="next">
          <p v-if="tab === 'register'" class="note">Rahbaringiz sizni tizimga qo'shgan bo'lsa — raqamingizni yozing, tasdiqlang va o'zingizga parol qo'ying.</p>
          <UiInput v-model="phone" label="Telefon raqamingiz" type="tel" placeholder="+998 90 123 45 67" autocomplete="username" :error="err" />
          <UiButton type="submit" :loading="loading" block size="l">Davom etish</UiButton>
        </form>

        <!-- Allaqachon ro'yxatdan o'tgan -->
        <div v-else-if="step === 'registered'" class="col">
          <p class="okb">✅ Siz allaqachon ro'yxatdan o'tgansiz — parolingiz bor.</p>
          <UiButton block size="l" @click="tab = 'login'; purpose = 'login'; step = 'password'">Parol bilan kirish</UiButton>
          <button type="button" class="lnk" @click="tab = 'login'; forgot()">Parolni unutdim</button>
        </div>

        <!-- 2a. PAROL -->
        <form v-else-if="step === 'password'" @submit.prevent="loginPw">
          <input type="text" name="username" autocomplete="username" :value="phone" hidden />
          <div class="pw">
            <UiInput v-model="password" label="Parol" :type="showPw ? 'text' : 'password'" autocomplete="current-password" :error="err" />
            <button type="button" class="eye" :aria-label="showPw ? 'Parolni yashirish' : 'Parolni ko\'rsatish'" @click="showPw = !showPw">{{ showPw ? '🙈' : '👁' }}</button>
          </div>
          <UiButton type="submit" :loading="loading" :disabled="!password" block size="l">Kirish</UiButton>
          <div class="alt"><button type="button" class="lnk" @click="forgot">Parolni unutdim</button><button type="button" class="lnk" @click="purpose = 'login'; viaTelegram()">✈️ Telegram orqali kirish</button></div>
        </form>

        <!-- 2b. TASDIQLASH USULI -->
        <div v-else-if="step === 'verify'" class="col">
          <h3>{{ verifyTitle }}</h3>
          <p class="muted sm">{{ verifyText }}</p>
          <p v-if="err" class="er">{{ err }}</p>
          <button type="button" class="opt tg" :disabled="loading" @click="startTg"><span>✈️</span><div><b>Telegram orqali</b><small>{{ info?.telegram ? 'Botga «Ha» tugmasi keladi — bir bosish' : 'Bot ochiladi → «📱 Telefonni ulashish» — tamom' }}</small></div><em>tavsiya</em></button>
          <button type="button" class="opt" :disabled="loading" @click="sendCode"><span>🔢</span><div><b>Kod bilan</b><small>6 xonali kod Telegram yoki SMS orqali keladi</small></div></button>
        </div>

        <!-- 2c. TELEGRAM KUTISH -->
        <div v-else-if="step === 'tg'" class="col center">
          <div class="pulse">✈️</div>
          <b v-if="tg?.linked">Telegram'da «✅ Ha, men kiryapman» ni bosing</b>
          <b v-else>Botni oching va «📱 Telefonni ulashish» ni bosing</b>
          <p class="muted sm">{{ tg?.linked ? 'Xabar kelmasa — pastdagi tugma bilan botni oching.' : 'Raqamingiz mos kelsa, sayt o\'zi ochiladi.' }} · {{ mmss }}</p>
          <a v-if="tg?.link" class="open" :href="tg.link" target="_blank" rel="noopener">Telegram'da botni ochish</a>
          <UiButton variant="ghost" block @click="stop(); step = 'verify'">Boshqa usul</UiButton>
        </div>

        <!-- 2d. KOD -->
        <form v-else-if="step === 'code'" @submit.prevent="checkCode">
          <UiInput v-model="code" label="Kod" inputmode="numeric" placeholder="123456" :error="err" :hint="codeHint" autocomplete="one-time-code" />
          <UiButton type="submit" :loading="loading" :disabled="code.length < 4" block size="l">Tasdiqlash</UiButton>
          <div class="alt"><button type="button" class="lnk" @click="sendCode">Kodni qayta yuborish</button><button type="button" class="lnk" @click="step = 'verify'">Boshqa usul</button></div>
        </form>

        <!-- 3. PAROL QO'YISH -->
        <form v-else-if="step === 'setpw'" @submit.prevent="savePw">
          <p class="okb">✅ Raqam tasdiqlandi. {{ purpose === 'reset' ? 'Yangi parol qo\'ying:' : 'Endi o\'zingizga parol o\'ylab toping:' }}</p>
          <input type="text" name="username" autocomplete="username" :value="phone" hidden />
          <UiInput v-model="pw1" label="Yangi parol (kamida 6 belgi)" :type="showPw ? 'text' : 'password'" autocomplete="new-password" />
          <UiInput v-model="pw2" label="Parolni takrorlang" :type="showPw ? 'text' : 'password'" autocomplete="new-password" :error="err" />
          <label class="chk"><input v-model="showPw" type="checkbox" /> Parolni ko'rsatish</label>
          <UiButton type="submit" :loading="loading" block size="l">Saqlash va kirish</UiButton>
          <button v-if="purpose === 'first'" type="button" class="lnk" @click="finish">Keyinroq (hozircha parolsiz kirish)</button>
        </form>
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
.tabs { display: flex; background: var(--surface-2); border-radius: 12px; padding: 3px; }
.tabs button { flex: 1; border: 0; background: transparent; padding: 10px 8px; border-radius: 9px; font: inherit; font-weight: 800; font-size: var(--fs-s); color: var(--muted); cursor: pointer; }
.tabs button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0, 0, 0, .12); }
.back { border: 0; background: none; color: var(--muted); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; text-align: left; padding: 2px 0; }
form, .col { display: flex; flex-direction: column; gap: 12px; } .center { align-items: center; text-align: center; }
h3 { margin: 0; font-size: var(--fs-l); }
.pw { position: relative; }
.eye { position: absolute; right: 8px; top: 28px; width: 36px; height: 36px; border: 0; background: transparent; cursor: pointer; font-size: 18px; border-radius: 8px; }
.alt { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.lnk { border: 0; background: transparent; color: var(--accent); font: inherit; font-size: var(--fs-s); font-weight: 700; cursor: pointer; padding: 6px 2px; }
.muted { color: var(--muted); } .sm { font-size: var(--fs-s); margin: 0; }
.note { margin: 0; font-size: var(--fs-s); color: var(--ink-2); padding: 10px 12px; border-radius: 12px; background: var(--surface-2); }
.okb { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--ok-tint); color: var(--ok); font-weight: 700; font-size: var(--fs-s); }
.er { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--danger-tint); color: var(--danger); font-weight: 700; font-size: var(--fs-s); }
.opt { display: flex; gap: 12px; align-items: center; text-align: left; width: 100%; border: 1px solid var(--line); background: var(--surface); border-radius: 14px; padding: 14px; font: inherit; color: var(--ink); cursor: pointer; }
.opt:hover:not(:disabled) { border-color: var(--accent); } .opt > span { font-size: 24px; } .opt div { flex: 1; display: flex; flex-direction: column; } .opt small { color: var(--muted); font-size: var(--fs-xs); }
.opt em { font-style: normal; font-size: 11px; font-weight: 800; color: var(--ok); background: var(--ok-tint); padding: 2px 8px; border-radius: 99px; }
.opt.tg { border-color: color-mix(in srgb, #229ED9 50%, var(--line)); background: color-mix(in srgb, #229ED9 6%, var(--surface)); }
.pulse { width: 72px; height: 72px; border-radius: 50%; display: grid; place-items: center; font-size: 34px; background: color-mix(in srgb, #229ED9 16%, transparent); animation: p 1.6s ease-in-out infinite; }
@keyframes p { 50% { transform: scale(1.08); box-shadow: 0 0 0 12px color-mix(in srgb, #229ED9 10%, transparent); } }
.open { display: inline-flex; justify-content: center; align-items: center; min-height: 46px; padding: 0 18px; border-radius: 12px; background: #229ED9; color: #fff; font-weight: 800; text-decoration: none; width: 100%; box-sizing: border-box; }
.chk { display: flex; gap: 8px; align-items: center; font-size: var(--fs-s); color: var(--ink-2); }
</style>
