<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiInput, toast } from '@restopos/ui'
import { useHq } from '../store'

const s = useHq(), router = useRouter()
const phone = ref('+998')
const code = ref('')
const step = ref<1 | 2>(1)
const dev = ref('')
const busy = ref(false)
async function send() {
  busy.value = true
  try { const r = await api.post('/hq/auth/otp', { phone: phone.value }); dev.value = r.dev_code ?? ''; step.value = 2 }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function verify() {
  busy.value = true
  try { await s.verify(phone.value, code.value); router.replace('/') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
</script>

<template>
  <div class="lg">
    <form class="box" @submit.prevent="step === 1 ? send() : verify()">
      <div class="br"><span>R</span><b>Platforma HQ</b></div>
      <h1>Platforma jamoasi uchun kirish</h1>
      <p>Barcha restoranlar, billing va texnik yordam bitta joyda. Faqat jamoa a'zolari kira oladi.</p>
      <UiInput v-if="step === 1" v-model="phone" label="Telefon raqam" type="tel" autocomplete="tel" />
      <template v-else>
        <UiInput v-model="code" label="SMS kod" inputmode="numeric" autocomplete="one-time-code" />
        <small v-if="dev" class="dev">Dev rejim: kod <b>{{ dev }}</b></small>
      </template>
      <UiButton type="submit" variant="brand" block :loading="busy">{{ step === 1 ? 'Kod olish' : 'Kirish' }}</UiButton>
      <button v-if="step === 2" type="button" class="bk" @click="step = 1">← Raqamni o'zgartirish</button>
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
