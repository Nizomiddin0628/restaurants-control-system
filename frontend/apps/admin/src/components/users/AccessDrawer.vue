<script setup lang="ts">
/** Xodimga kirish (parol) berish: «Parol yaratish» yoki o'zi yozadi → AccessCard (nusxalash / Telegram'da yuborish). */
import { ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiDrawer, UiInput } from '@restopos/ui'
import AccessCard from './AccessCard.vue'
import type { Access } from './access'

const props = defineProps<{ user: { id: string; full_name?: string; phone?: string } | null; auto?: boolean }>()
const emit = defineEmits<{ close: []; done: [Access] }>()
const access = ref<Access | null>(null), pw = ref(''), err = ref(''), busy = ref(false)

async function save(generate: boolean) {
  if (!props.user) return
  if (!generate && pw.value.length < 6) { err.value = 'Kamida 6 ta belgi'; return }
  busy.value = true; err.value = ''
  try { access.value = await api.post<Access>(`/users/${props.user.id}/password`, generate ? { generate: true } : { password: pw.value }); emit('done', access.value) }
  catch (e: any) { err.value = e.detail ?? 'Xato' } finally { busy.value = false }
}
watch(() => props.user?.id, (id) => { access.value = null; pw.value = ''; err.value = ''; if (id && props.auto) save(true) }, { immediate: true })
function close() { access.value = null; emit('close') }
</script>

<template>
  <UiDrawer :open="!!user" :title="`Kirish: ${user?.full_name || user?.phone || ''}`" width="400px" @close="close">
    <AccessCard v-if="access" :a="access" />
    <p v-else-if="busy && auto" class="hint">Parol yaratilmoqda…</p>
    <template v-else>
      <p class="hint">Xodim <b>{{ user?.phone }}</b> raqami va parol bilan kiradi. Eng osoni — tizim parol yaratsin, siz uni xodimga Telegram'da yuborasiz.</p>
      <UiButton variant="brand" :loading="busy" @click="save(true)">🎲 Parol yaratish</UiButton>
      <p class="or">yoki o'zingiz yozing</p>
      <UiInput v-model="pw" label="Parol (kamida 6 belgi)" type="text" autocomplete="off" :error="err" @keyup.enter="save(false)" />
      <UiButton variant="secondary" :loading="busy" @click="save(false)">Saqlash</UiButton>
    </template>
    <template v-if="access" #footer><UiButton @click="close">Tayyor</UiButton></template>
  </UiDrawer>
</template>

<style scoped>
.hint { margin: 0; color: var(--ink-2); font-size: var(--fs-s); }
.or { text-align: center; color: var(--muted); font-size: var(--fs-xs); margin: 4px 0; }
</style>
