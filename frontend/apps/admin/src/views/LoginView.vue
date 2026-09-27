<script setup lang="ts">
/**
 * Kirish: asosiy usul — telefon + parol (har safar SMS shart emas).
 * Parol hali qo'yilmagan bo'lsa yoki esdan chiqqan bo'lsa — «SMS kod bilan kirish».
 * Boshqa restorandan o'tish havolasi (?switch=...) — hech narsa so'ramasdan kiradi.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UiButton, UiInput, UiCard, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter(), route = useRoute()
const LAST = 'restopos.phone'
const saved = (() => { try { return localStorage.getItem(LAST) || '' } catch { return '' } })()
const mode = ref<'password' | 'otp'>('password')
const forgot = ref(false)
const phone = ref(saved || '+998 '), password = ref(''), showPw = ref(false)
const via = ref(''), code = ref(''), step = ref<'phone' | 'code'>('phone'), loading = ref(false), err = ref(''), devCode = ref('')

function remember() { try { localStorage.setItem(LAST, phone.value) } catch { /* private */ } }
function done() { remember(); toast('Xush kelibsiz!'); router.push('/') }

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
  : devCode.value ? `Sinov rejimi — kod: ${devCode.value}` : 'SMS xizmati hali ulanmagan. Rahbaringizdan parol so\'rang yoki restoran botiga ulaning.')
function setMode(m: 'password' | 'otp') { mode.value = m; err.value = ''; step.value = 'phone'; code.value = '' }

const switching = ref(false)
onMounted(async () => {
  const c = route.query.switch
  if (typeof c !== 'string' || !c) return
  switching.value = true
  try { await a.switchIn(c); router.replace('/') }
  catch (e: any) { err.value = e.detail ?? 'Havola eskirgan — qaytadan kiring'; switching.value = false; router.replace('/login') }
})
</script>
<template>
  <div class="login">
    <UiCard class="box">
      <div class="brand"><span class="logo">R</span><div><b>Boshqaruv paneli</b><p class="muted">Login (telefon raqam) va parol bilan kiring</p></div></div>
      <p v-if="switching" class="sw">Restoranga o'tilmoqda…</p>
      <template v-else>

        <form v-if="mode === 'password'" @submit.prevent="loginPw">
          <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" autocomplete="username" />
          <div class="pw">
            <UiInput v-model="password" label="Parol" :type="showPw ? 'text' : 'password'" autocomplete="current-password" :error="err" />
            <button type="button" class="eye" :aria-label="showPw ? 'Parolni yashirish' : 'Parolni ko\'rsatish'" @click="showPw = !showPw">{{ showPw ? '🙈' : '👁' }}</button>
          </div>
          <UiButton type="submit" :loading="loading" :disabled="!password" block size="l">Kirish</UiButton>
          <button type="button" class="lnk" @click="forgot = !forgot">Parolni unutdingizmi?</button>
          <p v-if="forgot" class="fg"><span>Rahbaringiz (menejer) «Xodimlar» sahifasida sizga <b>yangi parol</b> berib yuboradi — unga ayting.</span>
            <button type="button" class="lnk2" @click="setMode('otp')">Yoki telefon kodi bilan kirish →</button></p>
        </form>

        <template v-else>
        <p class="otp-h"><button type="button" class="lnk2" @click="setMode('password')">← Parol bilan kirish</button> Telefon kodi bilan kirish</p>
        <form v-if="step === 'phone'" @submit.prevent="sendOtp">
          <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" :error="err" autocomplete="tel" />
          <UiButton type="submit" :loading="loading" block size="l">Kod olish</UiButton>
          <p class="muted sm">Kod restoran Telegram botiga (ulangan bo'lsangiz) yoki SMS bilan keladi.</p>
        </form>
        <form v-else @submit.prevent="verify">
          <UiInput v-model="code" label="SMS kod" inputmode="numeric" placeholder="123456" :error="err" :hint="hint" autocomplete="one-time-code" />
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
.tabs { display: flex; background: var(--surface-2); border-radius: 12px; padding: 3px; }
.tabs button { flex: 1; border: 0; background: transparent; padding: 10px 8px; border-radius: 9px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; }
.tabs button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0, 0, 0, .12); }
form { display: flex; flex-direction: column; gap: 12px; }
.pw { position: relative; }
.eye { position: absolute; right: 8px; top: 28px; width: 36px; height: 36px; border: 0; background: transparent; cursor: pointer; font-size: 18px; border-radius: 8px; }
.lnk { border: 0; background: transparent; color: var(--accent); font: inherit; font-size: var(--fs-s); font-weight: 600; cursor: pointer; padding: 4px; }
.muted { color: var(--muted); }
.fg { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); font-size: var(--fs-s); color: var(--ink-2); display: flex; flex-direction: column; gap: 6px; }
.lnk2 { border: 0; background: transparent; color: var(--muted); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; padding: 2px 0; text-align: left; text-decoration: underline; }
.otp-h { margin: 0; display: flex; flex-direction: column; gap: 4px; font-weight: 800; } .sm { font-size: var(--fs-xs); margin: 0; text-align: center; }
</style>
