<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { UiButton, UiInput, UiCard, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth(), router = useRouter()
const phone = ref('+998 '), code = ref(''), step = ref<'phone' | 'code'>('phone'), loading = ref(false), err = ref(''), devCode = ref('')

async function sendOtp() {
  loading.value = true; err.value = ''
  try { const r = await a.requestOtp(phone.value); step.value = 'code'; if (r.dev_code) devCode.value = r.dev_code }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { loading.value = false }
}
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
      <form v-if="step === 'phone'" @submit.prevent="sendOtp">
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
.brand { display: flex; gap: 12px; align-items: center; } .brand p { margin: 2px 0 0; font-size: var(--fs-s); }
.logo { width: 44px; height: 44px; border-radius: 12px; background: var(--brand); color: var(--brand-ink); display: grid; place-items: center; font-family: var(--font-display); font-weight: 800; font-size: 20px; flex-shrink: 0; }
form { display: flex; flex-direction: column; gap: 12px; }
.muted { color: var(--muted); }
</style>
