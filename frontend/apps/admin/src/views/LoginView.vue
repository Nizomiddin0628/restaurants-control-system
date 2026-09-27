<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { UiButton, UiInput, UiCard, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter(), route = useRoute()
const phone = ref('+998 '), code = ref(''), step = ref<'phone' | 'code'>('phone'), loading = ref(false), err = ref(''), devCode = ref('')

async function sendOtp() {
  loading.value = true; err.value = ''
  try { const r = await a.requestOtp(phone.value); step.value = 'code'; if (r.dev_code) devCode.value = r.dev_code }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
/** Boshqa restorandan o'tish havolasi (?switch=...) — kod so'ramasdan kirish */
const switching = ref(false)
onMounted(async () => {
  const c = route.query.switch
  if (typeof c !== 'string' || !c) return
  switching.value = true
  try { await a.switchIn(c); router.replace('/') }
  catch (e: any) { err.value = e.detail ?? "Havola eskirgan — telefon raqam bilan kiring"; switching.value = false; router.replace('/login') }
})
async function verify() {
  loading.value = true; err.value = ''
  try { await a.verify(phone.value, code.value); toast('Xush kelibsiz!'); router.push('/') }
  catch (e: any) { err.value = e.detail ?? 'Kod noto\'g\'ri' } finally { loading.value = false }
}
</script>
<template>
  <div class="login">
    <UiCard class="box">
      <div class="brand"><span class="logo">R</span><div><b>Boshqaruv paneli</b><p class="muted">Telefon raqam bilan kiring — kod SMS yoki Telegram orqali keladi</p></div></div>
      <p v-if="switching" class="sw">Restoranga o'tilmoqda…</p>
      <form v-else-if="step === 'phone'" @submit.prevent="sendOtp">
        <UiInput v-model="phone" label="Telefon" type="tel" placeholder="+998 90 123 45 67" :error="err" autocomplete="tel" />
        <UiButton type="submit" :loading="loading" block size="l">Kod olish</UiButton>
      </form>
      <form v-else @submit.prevent="verify">
        <UiInput v-model="code" label="SMS kod" inputmode="numeric" placeholder="123456" :error="err" :hint="devCode ? `Dev rejim — kod: ${devCode}` : `${phone} raqamiga yuborildi`" autocomplete="one-time-code" />
        <UiButton type="submit" :loading="loading" block size="l">Kirish</UiButton>
        <UiButton variant="ghost" block @click="step = 'phone'">Raqamni o'zgartirish</UiButton>
      </form>
    </UiCard>
  </div>
</template>
<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
.box { width: min(440px, 100%); }
.sw { text-align: center; font-weight: 700; color: var(--muted); padding: 18px 0 6px; margin: 0; }
.brand { display: flex; gap: 12px; align-items: center; } .brand p { margin: 2px 0 0; font-size: var(--fs-s); }
.logo { width: 44px; height: 44px; border-radius: 12px; background: var(--brand); color: var(--brand-ink); display: grid; place-items: center; font-family: var(--font-display); font-weight: 800; font-size: 20px; flex-shrink: 0; }
form { display: flex; flex-direction: column; gap: 12px; }
.muted { color: var(--muted); }
</style>
