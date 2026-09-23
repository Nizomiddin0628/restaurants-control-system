<script setup lang="ts">
/** Foydalanuvchilar va rollar matritsasi (rol × ruxsat). Egasi rolini o'zgartirib bo'lmaydi. */
import { onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiIcon, UiInput, UiSelect, UiTable, toast } from '@restopos/ui'

type Role = { id: number; code: string; name: string; permissions: string[]; is_system: boolean }
type U = { id: string; phone: string; full_name: string; roles: string[]; branch_ids: number[]; is_active: boolean; last_seen_at: string | null }
const users = ref<U[]>([]), roles = ref<Role[]>([]), perms = ref<string[]>([])
const open = ref(false), u = ref({ phone: '+998 ', full_name: '', role_code: 'cashier' }), roleOpen = ref(false), r = ref<Role | null>(null)
const load = async () => { [users.value, roles.value, perms.value] = await Promise.all([api.get('/users'), api.get('/roles'), api.get('/permissions')]) }
onMounted(load)
const columns = [{ key: 'full_name', label: 'Ism' }, { key: 'phone', label: 'Telefon' }, { key: 'roles', label: 'Rol', format: (v: string[]) => v.join(', ') }, { key: 'last_seen_at', label: 'Oxirgi kirish', hideOnPhone: true, format: (v: string | null) => (v ? new Date(v).toLocaleString('uz-UZ') : '—') }] as any
async function save() { try { await api.post('/users', u.value); open.value = false; await load(); toast('Hodim qo\'shildi — telefon raqami bilan kiradi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
async function deactivate(x: U) { if (!confirm(`${x.full_name || x.phone} ni o'chirasizmi?`)) return; try { await api.del(`/users/${x.id}`); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
function togglePerm(p: string) { if (!r.value) return; r.value.permissions = r.value.permissions.includes(p) ? r.value.permissions.filter(x => x !== p) : [...r.value.permissions, p] }
async function saveRole() { if (!r.value) return; try { r.value.id ? await api.put(`/roles/${r.value.id}`, r.value) : await api.post('/roles', r.value); roleOpen.value = false; await load(); toast('Rol saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
</script>
<template>
  <div class="wrap">
    <UiCard title="Foydalanuvchilar" subtitle="Telefon raqam = login. Kod SMS/Telegram orqali keladi, parol kerak emas.">
      <template #actions><UiButton size="s" @click="open = true"><UiIcon name="plus" /> Hodim</UiButton></template>
      <UiTable :rows="users" :columns="columns" @row="deactivate($event as U)" />
      <p class="hint">Qatorni bosib hodimni o'chirish (nofaol qilish) mumkin.</p>
    </UiCard>
    <UiCard title="Rollar va ruxsatlar" subtitle="Rolga ruxsatlar biriktiriladi; `modul.*` — modulning hammasi">
      <template #actions><UiButton size="s" variant="secondary" @click="r = { id: 0, code: '', name: '', permissions: [], is_system: false }; roleOpen = true"><UiIcon name="plus" /> Rol</UiButton></template>
      <div class="roles"><button v-for="x in roles" :key="x.id" type="button" class="role" @click="r = { ...x }; roleOpen = true"><b>{{ x.name }}</b><span>{{ x.permissions.includes('*') ? 'hamma narsa' : x.permissions.length + ' ruxsat' }}</span><UiChip v-if="x.is_system" tone="neutral">tizim</UiChip></button></div>
    </UiCard>
    <UiDrawer :open="open" title="Yangi hodim" width="420px" @close="open = false">
      <UiInput v-model="u.phone" label="Telefon" type="tel" /><UiInput v-model="u.full_name" label="Ism familiya" />
      <UiSelect v-model="u.role_code" label="Rol" :options="roles.map(x => ({ value: x.code, label: x.name }))" />
      <template #footer><UiButton @click="save()">Qo'shish</UiButton></template>
    </UiDrawer>
    <UiDrawer :open="roleOpen" :title="r?.id ? 'Rol: ' + r.name : 'Yangi rol'" @close="roleOpen = false">
      <template v-if="r">
        <UiInput v-model="r.name" label="Nomi" /><UiInput v-model="r.code" label="Kodi" :disabled="!!r.id" hint="masalan: senior_cashier" />
        <div class="perms"><label v-for="p in perms" :key="p" class="p"><input type="checkbox" :checked="r.permissions.includes(p) || r.permissions.includes('*')" :disabled="r.code === 'owner'" @change="togglePerm(p)" /><code>{{ p }}</code></label></div>
      </template>
      <template #footer><UiButton :disabled="r?.code === 'owner'" @click="saveRole()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>
<style scoped>
.wrap { display: flex; flex-direction: column; gap: 16px; }
.hint { margin: 0; font-size: var(--fs-xs); color: var(--muted); }
.roles { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.role { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); cursor: pointer; text-align: left; }
.role span { font-size: var(--fs-xs); color: var(--muted); }
.perms { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 4px; } .p { display: flex; gap: 8px; align-items: center; min-height: 32px; font-size: var(--fs-xs); }
</style>
