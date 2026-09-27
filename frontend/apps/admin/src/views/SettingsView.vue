<script setup lang="ts">
/** Tenant sozlamalari (tillar, soliq rejimi, chek matni) va shaxsiy sozlamalar (profil rasmi, ism, PIN, tema). */
import { ref } from 'vue'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiInput, UiSelect, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
const name = ref(a.me?.tenant.name ?? ''), settings = ref({ ...(a.me?.tenant.settings ?? {}) }), me = ref({ full_name: a.me?.full_name ?? '', language: a.me?.language ?? 'uz', pin: '' })
async function saveTenant() { try { await api.put('/tenant', { name: name.value, settings: settings.value }); await a.load(); toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
const photoInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
async function pickPhoto(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]; (e.target as HTMLInputElement).value = ''
  if (!f) return
  uploading.value = true
  try { a.me = await api.upload('/me/avatar', f); toast('Rasm saqlandi') } catch (x: any) { toast(x.detail ?? 'Rasm yuklanmadi', 'danger') } finally { uploading.value = false }
}
async function removePhoto() { a.me = await api.del('/me/avatar'); toast('Rasm olib tashlandi') }
// parol: keyingi safar SMS'siz, telefon + parol bilan kirish
const pw = ref({ old: '', n1: '', n2: '' }), pwBusy = ref(false), pwErr = ref('')
async function savePw() {
  pwErr.value = ''
  if (pw.value.n1.length < 6) { pwErr.value = 'Kamida 6 ta belgi'; return }
  if (pw.value.n1 !== pw.value.n2) { pwErr.value = 'Ikkala parol bir xil emas'; return }
  pwBusy.value = true
  try { await api.post('/me/password', { old_password: pw.value.old, new_password: pw.value.n1 }); await a.load(); pw.value = { old: '', n1: '', n2: '' }; toast('Parol saqlandi — endi telefon + parol bilan kirasiz') }
  catch (e: any) { pwErr.value = e.detail ?? 'Xato' } finally { pwBusy.value = false }
}
async function saveMe() { await api.patch('/me', { full_name: me.value.full_name, language: me.value.language, pin: me.value.pin || undefined }); await a.load(); me.value.pin = ''; toast('Saqlandi') }
</script>
<template>
  <div class="wrap">
    <UiCard v-if="a.can('core.settings.edit')" title="Restoran sozlamalari" subtitle="Har modulning o'z sozlamalari o'sha modul sahifasida">
      <div class="g">
        <UiInput v-model="name" label="Tarmoq / restoran nomi" />
        <UiSelect v-model="settings.tax_mode" label="Soliq rejimi" :options="[{ value: 'turnover', label: 'Aylanma solig\'i' }, { value: 'vat6', label: 'QQS 6% (ixtiyoriy, umumiy ovqatlanish)' }, { value: 'vat12', label: 'QQS 12%' }]" />
        <UiSelect v-model="settings.default_language" label="Asosiy til" :options="[{ value: 'uz', label: 'O\'zbekcha' }, { value: 'ru', label: 'Русский' }, { value: 'en', label: 'English' }]" />
        <UiInput v-model="settings.receipt_footer" label="Chek pastki matni" />
        <UiInput v-model="settings.menu_board_rotate_seconds" type="number" label="TV menyu-bord: kategoriya almashish" suffix="soniya" />
      </div>
      <div><UiButton @click="saveTenant()">Saqlash</UiButton></div>
    </UiCard>
    <UiCard title="Shaxsiy" subtitle="Profil rasmi, ism, til, kassa/tasdiqlash PIN kodi, tema">
      <div class="photo">
        <UiAvatar :name="a.me?.full_name || a.me?.phone" :src="a.me?.avatar" :size="88" />
        <div class="pa">
          <b>{{ a.me?.full_name || a.me?.phone }}</b>
          <span class="muted">Rasm hamkasblaringizga vazifalar, xodimlar va o'qitish sahifalarida ko'rinadi.</span>
          <div class="btns">
            <UiButton size="s" :loading="uploading" @click="photoInput?.click()">📷 {{ a.me?.avatar ? 'Rasmni almashtirish' : 'Rasm qo\'yish' }}</UiButton>
            <UiButton v-if="a.me?.avatar" size="s" variant="ghost" @click="removePhoto()">Olib tashlash</UiButton>
          </div>
          <input ref="photoInput" type="file" accept="image/*" hidden @change="pickPhoto" />
        </div>
      </div>
      <div class="g">
        <UiInput v-model="me.full_name" label="Ism" />
        <UiSelect v-model="me.language" label="Til" :options="[{ value: 'uz', label: 'O\'zbekcha' }, { value: 'ru', label: 'Русский' }, { value: 'en', label: 'English' }]" />
        <UiInput v-model="me.pin" label="Yangi PIN (4–6 raqam)" type="password" inputmode="numeric" />
        <UiSelect :model-value="ui.theme" label="Tema" :options="[{ value: 'auto', label: 'Avto (qurilma)' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]" @update:model-value="ui.setTheme($event as any)" />
      </div>
      <div><UiButton @click="saveMe()">Saqlash</UiButton></div>
    </UiCard>
    <UiCard title="Kirish paroli" :subtitle="a.me?.has_password ? 'Parol o\'rnatilgan. Almashtirish uchun joriy parolni kiriting.' : 'Parol qo\'ying — keyingi safar SMS kod kutmasdan telefon + parol bilan kirasiz.'">
      <form class="g" @submit.prevent="savePw">
        <input type="text" name="username" autocomplete="username" :value="a.me?.phone" hidden />
        <UiInput v-if="a.me?.has_password" v-model="pw.old" label="Joriy parol" type="password" autocomplete="current-password" />
        <UiInput v-model="pw.n1" label="Yangi parol (kamida 6 belgi)" type="password" autocomplete="new-password" />
        <UiInput v-model="pw.n2" label="Yangi parolni takrorlang" type="password" autocomplete="new-password" :error="pwErr" />
      </form>
      <div><UiButton :loading="pwBusy" @click="savePw()">{{ a.me?.has_password ? 'Parolni almashtirish' : 'Parol o\'rnatish' }}</UiButton></div>
    </UiCard>
  </div>
</template>
<style scoped>
.wrap { display: flex; flex-direction: column; gap: 16px; }
.g { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.photo { display: flex; align-items: center; gap: 16px; padding: 12px; border-radius: var(--radius); background: var(--surface-2); }
.pa { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.muted { color: var(--muted); font-size: var(--fs-s); }
.btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
@media (max-width: 600px) { .photo { flex-direction: column; text-align: center; } .btns { justify-content: center; } }
</style>
