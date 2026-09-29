<script setup lang="ts">
/** HQ kirish: telefon + parol (asosiy). Kod bilan — faqat SMS ulangan yoki sinov rejimida. */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, auth as tokenStore } from '@restopos/api'
import { UiButton, UiInput, toast } from '@restopos/ui'
import { useHq } from '../store'

const s = useHq(), router = useRouter()
const phone = ref('+998'), password = ref(''), code = ref('')
const mode = ref<'pw' | 'code'>('pw'), step = ref<1 | 2>(1), dev = ref(''), busy = ref(false), canCode = ref(false)
onMounted(async () => { try { canCode.value = (await api.get<{ code: boolean }>('/hq/auth/methods')).code } catch { canCode.value = false } })
async function login() {
  busy.value = true
  try { const r = await api.post('/hq/auth/login', { phone: phone.value, password: password.value }); tokenStore.set(r.token); s.me = r.staff; router.replace('/') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function send() {
  busy.value = true
  try { const r = await api.post('/hq/auth/otp', { phone: phone.value }); dev.value = r.dev_code ?? ''; step.value = 2 }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function verify() {
  busy.value = true
  try { await s.verify(phone.value, code.value); router.replace('/') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
function submit() { if (mode.value === 'pw') login(); else if (step.value === 1) send(); else verify() }
</script>

<template>
  <div class="lg">
    <form class="box" @submit.prevent="submit">
      <div class="br"><span>R</span><b>Platforma HQ</b></div>
      <h1>Platforma jamoasi uchun kirish</h1>
      <p>Barcha restoranlar, billing va texnik yordam bitta joyda. Faqat jamoa a'zolari kira oladi.</p>
      <UiInput v-if="mode === 'pw' || step === 1" v-model="phone" label="Telefon raqam" type="tel" autocomplete="username" />
      <UiInput v-if="mode === 'pw'" v-model="password" label="Parol" type="password" autocomplete="current-password" />
      <template v-else-if="step === 2">
        <UiInput v-model="code" label="Kod" inputmode="numeric" autocomplete="one-time-code" />
        <small v-if="dev" class="dev">Sinov rejimi: kod <b>{{ dev }}</b></small>
      </template>
      <UiButton type="submit" variant="brand" block :loading="busy">{{ mode === 'pw' ? 'Kirish' : step === 1 ? 'Kod olish' : 'Kirish' }}</UiButton>
      <button v-if="canCode" type="button" class="bk" @click="mode = mode === 'pw' ? 'code' : 'pw'; step = 1">{{ mode === 'pw' ? 'Kod bilan kirish' : '← Parol bilan kirish' }}</button>
      <small v-if="mode === 'pw'" class="dev">Parolni server administratori beradi.</small>
    </form>
  </div>
</template>

<style scoped>
.lg { min-height: 100vh; display: grid; place-items: center; padding: 16px; background: radial-gradient(1200px 600px at 20% 10%, #1D4ED8 0%, #0E1726 60%); }
.box { width: 100%; max-width: 400px; background: var(--surface); border-radius: 20px; padding: 28px; display: flex; flex-direction: column; gap: 14px; box-shadow: 0 30px 60px rgba(0,0,0,.35); }
.br { display: flex; align-items: center; gap: 10px; } .br span { width: 36px; height: 36px; border-radius: 10px; background: #2563EB; color: #fff; display: grid; place-items: center; font-weight: 900; } .br b { font-family: var(--font-display); }
h1 { margin: 0; font-family: var(--font-display); font-size: 22px; } p { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.dev { color: var(--muted); } .bk { border: 0; background: transparent; color: var(--accent); cursor: pointer; font: inherit; font-weight: 700; }
</style>
