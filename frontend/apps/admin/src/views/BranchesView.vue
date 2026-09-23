<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type Branch } from '@restopos/api'
import { UiButton, UiCard, UiDrawer, UiIcon, UiInput, UiTable, UiToggle, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth()
const rows = ref<Branch[]>([]), open = ref(false), b = ref<Partial<Branch> | null>(null), saving = ref(false)
const load = async () => { rows.value = await api.get('/branches') }
onMounted(load)
const columns = [
  { key: 'name', label: 'Filial', width: '1.4 1 0' }, { key: 'address', label: 'Manzil', width: '2 1 0', hideOnPhone: true },
  { key: 'phone', label: 'Telefon', editable: 'text' }, { key: 'is_active', label: 'Faol', editable: 'boolean', width: '0 0 60px' },
] as any
function openNew() { b.value = { name: '', address: '', phone: '', lat: null, lng: null, working_hours: {}, is_active: true, settings: {}, disabled_modules: [] }; open.value = true }
async function onEdit({ id, key, value }: any) { const r = rows.value.find(x => x.id === id)!; await api.put(`/branches/${id}`, { ...r, [key]: value }); await load(); toast('Saqlandi') }
async function save() {
  if (!b.value) return
  saving.value = true
  try { b.value.id ? await api.put(`/branches/${b.value.id}`, b.value) : await api.post('/branches', b.value); open.value = false; await load(); toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
async function remove() { if (!b.value?.id || !confirm('Filialni o\'chirasizmi?')) return; await api.del(`/branches/${b.value.id}`); open.value = false; await load() }
</script>
<template>
  <UiCard title="Filiallar" subtitle="Har filial o'z kassalari, ombori va hodimlariga ega. Modullarni filial bo'yicha ham o'chirish mumkin.">
    <template #actions><UiButton v-if="a.can('core.branches.manage')" size="s" @click="openNew()"><UiIcon name="plus" /> Filial</UiButton></template>
    <UiTable :rows="rows" :columns="columns" @edit="onEdit" @row="b = { ...$event }; open = true" />
    <UiDrawer :open="open" :title="b?.id ? 'Filial' : 'Yangi filial'" @close="open = false">
      <template v-if="b">
        <UiInput v-model="b.name" label="Nomi" /><UiInput v-model="b.address" label="Manzil" /><UiInput v-model="b.phone" label="Telefon" type="tel" />
        <div class="g"><UiInput v-model="b.lat" type="number" label="Kenglik (lat)" hint="41.2995" /><UiInput v-model="b.lng" type="number" label="Uzunlik (lng)" hint="69.2401" /></div>
        <UiToggle v-model="b.is_active" label="Faol" />
      </template>
      <template #footer><UiButton v-if="b?.id" variant="danger" @click="remove()">O'chirish</UiButton><UiButton :loading="saving" @click="save()">Saqlash</UiButton></template>
    </UiDrawer>
  </UiCard>
</template>
<style scoped>.g { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }</style>
