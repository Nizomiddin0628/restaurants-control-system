<script setup lang="ts">
/**
 * Xodimning kirish ma'lumotlari (parol yaratilgandan keyin bir marta ko'rsatiladi):
 * manzil, login (telefon), parol + «Nusxalash» va «Telegram'da yuborish» (xodimga o'zingiz yuborasiz).
 * Xodim restoran botiga ulangan bo'lsa — tizim o'zi ham botga yuboradi.
 */
import { computed } from 'vue'
import { UiButton, toast } from '@restopos/ui'

import type { Access } from './access'
const props = defineProps<{ a: Access }>()

const text = computed(() => `${props.a.restaurant} — tizimga kirish\n\nManzil: ${props.a.login_url}\nLogin (telefon): ${props.a.phone}\nParol: ${props.a.password}\n\nKirgach «Sozlamalar»da parolni o'zingizniki qilib almashtiring.`)
const tgShare = computed(() => `https://t.me/share/url?url=${encodeURIComponent(props.a.login_url)}&text=${encodeURIComponent(text.value.replace(`Manzil: ${props.a.login_url}\n`, ''))}`)
async function copy() {
  try { await navigator.clipboard.writeText(text.value); toast('Nusxalandi') }
  catch { toast('Nusxalab bo\'lmadi — matnni qo\'lda belgilang', 'danger') }
}
</script>

<template>
  <div class="ac">
    <p class="ok">✅ {{ a.full_name || a.phone }} uchun kirish tayyor</p>
    <dl>
      <dt>Manzil</dt><dd><a :href="a.login_url" target="_blank" rel="noopener">{{ a.login_url.replace(/^https?:\/\//, '') }}</a></dd>
      <dt>Login</dt><dd><b>{{ a.phone }}</b></dd>
      <dt>Parol</dt><dd><b class="pw">{{ a.password }}</b></dd>
    </dl>
    <p v-if="a.telegram_sent" class="sent">✈️ Xodimning Telegram'iga (restoran boti orqali) yuborildi.</p>
    <p v-else class="note">Parolni xodimga yuboring — u faqat hozir ko'rinadi. Xodim restoran botiga ulansa, keyingi safar tizim o'zi yuboradi.</p>
    <div class="btns">
      <UiButton variant="brand" @click="copy()">📋 Nusxalash</UiButton>
      <a class="tg" :href="tgShare" target="_blank" rel="noopener">✈️ Telegram'da yuborish</a>
    </div>
  </div>
</template>

<style scoped>
.ac { display: flex; flex-direction: column; gap: 12px; }
.ok { margin: 0; font-weight: 800; font-size: var(--fs-b); }
dl { display: grid; grid-template-columns: 80px 1fr; gap: 8px 12px; margin: 0; padding: 14px; border-radius: 14px; background: var(--surface-2); border: 1px solid var(--line); }
dt { color: var(--muted); font-size: var(--fs-s); font-weight: 700; } dd { margin: 0; font-size: var(--fs-b); min-width: 0; overflow-wrap: anywhere; }
.pw { font-family: var(--font-display); font-size: 22px; letter-spacing: .12em; }
.sent { margin: 0; color: var(--ok); font-weight: 700; font-size: var(--fs-s); }
.note { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.btns { display: flex; gap: 8px; flex-wrap: wrap; }
.tg { display: inline-flex; align-items: center; justify-content: center; min-height: var(--touch); padding: 0 16px; border-radius: var(--radius); background: #229ED9; color: #fff; font-weight: 700; text-decoration: none; }
</style>
