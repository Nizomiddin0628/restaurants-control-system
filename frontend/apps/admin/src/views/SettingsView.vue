<script setup lang="ts">
/** Tenant sozlamalari (tillar, soliq rejimi, chek matni) va shaxsiy sozlamalar (ism, PIN, tema). */
import { ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiInput, UiSelect, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
const name = ref(a.me?.tenant.name ?? ''), settings = ref({ ...(a.me?.tenant.settings ?? {}) }), me = ref({ full_name: a.me?.full_name ?? '', language: a.me?.language ?? 'uz', pin: '' })
async function saveTenant() { try { await api.put('/tenant', { name: name.value, settings: settings.value }); await a.load(); toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
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
    <UiCard title="Shaxsiy" subtitle="Ism, til, kassa/tasdiqlash PIN kodi, tema">
      <div class="g">
        <UiInput v-model="me.full_name" label="Ism" />
        <UiSelect v-model="me.language" label="Til" :options="[{ value: 'uz', label: 'O\'zbekcha' }, { value: 'ru', label: 'Русский' }, { value: 'en', label: 'English' }]" />
        <UiInput v-model="me.pin" label="Yangi PIN (4–6 raqam)" type="password" inputmode="numeric" />
        <UiSelect :model-value="ui.theme" label="Tema" :options="[{ value: 'auto', label: 'Avto (qurilma)' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]" @update:model-value="ui.setTheme($event as any)" />
      </div>
      <div><UiButton @click="saveMe()">Saqlash</UiButton></div>
    </UiCard>
  </div>
</template>
<style scoped>.wrap { display: flex; flex-direction: column; gap: 16px; } .g { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }</style>
