<script setup lang="ts">
/**
 * Kirish: asosiy usul — telefon + parol (har safar SMS shart emas).
 * Parol hali qo'yilmagan bo'lsa yoki esdan chiqqan bo'lsa — «SMS kod bilan kirish».
 * Boshqa restorandan o'tish havolasi (?switch=...) — hech narsa so'ramasdan kiradi.
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UiButton, UiInput, UiCard, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter(), route = useRoute()
const LAST = 'restopos.phone'
const saved = (() => { try { return localStorage.getItem(LAST) || '' } catch { return '' } })()
const mode = ref<'password' | 'otp'>('password')
const phone = ref(saved || '+998 '), password = ref(''), showPw = ref(false)
const code = ref(''), step = ref<'phone' | 'code'>('phone'), loading = ref(false), err = ref(''), devCode = ref('')

function remember() { try { localStorage.setItem(LAST, phone.value) } catch { /* private */ } }
function done() { remember(); toast('Xush kelibsiz!'); router.push('/') }

async function loginPw() {
  loading.value = true; err.value = ''
  try { await a.login(phone.value, password.value); done() }
  catch (e: any) { err.value = e.detail ?? 'Telefon yoki parol noto\'g\'ri' } finally { loading.value = false }
}
async function sendOtp() {
  loading.value = true; err.value = ''
  try { const r = await a.requestOtp(phone.value); step.value = 'code'; if (r.dev_code) devCode.value = r.dev_code }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
async function verify() {
  loading.value = true; err.value = ''
  try { await a.verify(phone.value, code.value); done() }
  catch (e: any) { err.value = e.detail ?? 'Kod noto\'g\'ri' } finally { loading.value = false }
}
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
      <div class="brand"><span class="logo">R</span><div><b>Boshqaruv paneli</b><p class="muted">Telefon raqam va parol bilan kiring</p></div></div>
      <p v-if="switching" class="sw">Restoranga o'tilmoqda…</p>
      <template v-else>
        <div class="tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="mode === 'password'" :class="{ on: mode === 'password' }" @click="setMode('password')">🔑 Parol bilan</button>
          <button type="button" role="tab" :aria-selected="mode === 'otp'" :class="{ on: mode === 'otp' }" @click="setMode('otp')">💬 SMS kod bilan</button>
        </div>

        <form v-if="mode === 'password'" @submit.prevent="loginPw">
          <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" autocomplete="username" />
          <div class="pw">
            <UiInput v-model="password" label="Parol" :type="showPw ? 'text' : 'password'" autocomplete="current-password" :error="err" />
            <button type="button" class="eye" :aria-label="showPw ? 'Parolni yashirish' : 'Parolni ko\'rsatish'" @click="showPw = !showPw">{{ showPw ? '🙈' : '👁' }}</button>
          </div>
          <UiButton type="submit" :loading="loading" :disabled="!password" block size="l">Kirish</UiButton>
          <button type="button" class="lnk" @click="setMode('otp')">Parol yo'qmi yoki esdan chiqdimi? SMS kod bilan kiring</button>
        </form>

        <form v-else-if="step === 'phone'" @submit.prevent="sendOtp">
          <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" :error="err" autocomplete="tel" />
          <UiButton type="submit" :loading="loading" block size="l">Kod olish</UiButton>
          <p class="muted sm">Kirgandan keyin «Sozlamalar»da parol qo'ying — keyingi safar SMS kerak bo'lmaydi.</p>
        </form>
        <form v-else @submit.prevent="verify">
          <UiInput v-model="code" label="SMS kod" inputmode="numeric" placeholder="123456" :error="err" :hint="devCode ? `Sinov rejimi — kod: ${devCode}` : `${phone} raqamiga yuborildi`" autocomplete="one-time-code" />
          <UiButton type="submit" :loading="loading" block size="l">Kirish</UiButton>
          <UiButton variant="ghost" block @click="step = 'phone'">Raqamni o'zgartirish</UiButton>
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
.tabs button { flex: 1; border: 0; background: transparent; padding: 10px 8px; border-radius: 9px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; }
.tabs button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0, 0, 0, .12); }
form { display: flex; flex-direction: column; gap: 12px; }
.pw { position: relative; }
.eye { position: absolute; right: 8px; top: 28px; width: 36px; height: 36px; border: 0; background: transparent; cursor: pointer; font-size: 18px; border-radius: 8px; }
.lnk { border: 0; background: transparent; color: var(--accent); font: inherit; font-size: var(--fs-s); font-weight: 600; cursor: pointer; padding: 4px; }
.muted { color: var(--muted); } .sm { font-size: var(--fs-xs); margin: 0; text-align: center; }
</style>
