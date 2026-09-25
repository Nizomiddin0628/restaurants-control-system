<script setup lang="ts">
/** Foydalanuvchilar (rasm, rol, oxirgi kirish) va rollar matritsasi (rol × ruxsat). Egasi rolini o'zgartirib bo'lmaydi. */
import { onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiCard, UiChip, UiDrawer, UiIcon, UiInput, UiSelect, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

type Role = { id: number; code: string; name: string; permissions: string[]; is_system: boolean }
type U = { id: string; phone: string; full_name: string; avatar: string | null; roles: string[]; branch_ids: number[]; is_active: boolean; last_seen_at: string | null }
const users = ref<U[]>([]), roles = ref<Role[]>([]), perms = ref<string[]>([])
const open = ref(false), u = ref({ phone: '+998 ', full_name: '', role_code: 'cashier' }), roleOpen = ref(false), r = ref<Role | null>(null)
const load = async () => { [users.value, roles.value, perms.value] = await Promise.all([api.get('/users'), api.get('/roles'), api.get('/permissions')]) }
onMounted(load)
const a = useAuth()
const roleName = (c: string) => roles.value.find(x => x.code === c)?.name ?? c
const seen = (v: string | null) => (v ? new Date(v).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'hali kirmagan')
const photoFor = ref<U | null>(null)
const photoInput = ref<HTMLInputElement | null>(null)
function askPhoto(x: U) { photoFor.value = x; photoInput.value?.click() }
async function pickPhoto(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]; (e.target as HTMLInputElement).value = ''
  const x = photoFor.value; if (!f || !x) return
  try { const r = await api.upload<U>(`/users/${x.id}/avatar`, f); Object.assign(x, r); if (x.id === a.me?.id) await a.load(); toast('Rasm saqlandi') }
  catch (err: any) { toast(err.detail ?? 'Rasm yuklanmadi', 'danger') }
}
async function removePhoto(x: U) { Object.assign(x, await api.del<U>(`/users/${x.id}/avatar`)); if (x.id === a.me?.id) await a.load() }
async function save() { try { await api.post('/users', u.value); open.value = false; await load(); toast('Xodim qo\'shildi — telefon raqami bilan kiradi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
async function deactivate(x: U) { if (!confirm(`${x.full_name || x.phone} ni o'chirasizmi?`)) return; try { await api.del(`/users/${x.id}`); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
function togglePerm(p: string) { if (!r.value) return; r.value.permissions = r.value.permissions.includes(p) ? r.value.permissions.filter(x => x !== p) : [...r.value.permissions, p] }
async function saveRole() { if (!r.value) return; try { r.value.id ? await api.put(`/roles/${r.value.id}`, r.value) : await api.post('/roles', r.value); roleOpen.value = false; await load(); toast('Rol saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
</script>
<template>
  <div class="wrap">
    <UiCard title="Foydalanuvchilar" subtitle="Telefon raqam = login. Kod SMS/Telegram orqali keladi, parol kerak emas.">
      <template #actions><UiButton size="s" @click="open = true"><UiIcon name="plus" /> Xodim</UiButton></template>
      <div class="ul">
        <div v-for="x in users" :key="x.id" class="ur">
          <button type="button" class="ph" :title="x.avatar ? 'Rasmni almashtirish' : 'Rasm qo\'yish'" @click="askPhoto(x)">
            <UiAvatar :name="x.full_name || x.phone" :src="x.avatar" :size="44" /><span class="cam">📷</span>
          </button>
          <span class="nm"><b>{{ x.full_name || 'Ismsiz' }}</b><small>{{ x.phone }}</small></span>
          <span class="rl"><UiChip v-for="r in x.roles" :key="r" :tone="r === 'owner' ? 'accent' : 'neutral'">{{ roleName(r) }}</UiChip></span>
          <span class="ls">{{ seen(x.last_seen_at) }}</span>
          <span class="act">
            <UiButton v-if="x.avatar" size="s" variant="ghost" @click="removePhoto(x)">Rasmni o'chirish</UiButton>
            <UiButton v-if="x.id !== a.me?.id" size="s" variant="ghost" @click="deactivate(x)"><UiIcon name="trash" :size="14" /></UiButton>
          </span>
        </div>
      </div>
      <input ref="photoInput" type="file" accept="image/*" hidden @change="pickPhoto" />
      <p class="hint">Rasmni bosing — xodimga rasm qo'ying yoki almashtiring. Xodimning o'zi ham «Sozlamalar»da rasm qo'ya oladi.</p>
    </UiCard>
    <UiCard title="Rollar va ruxsatlar" subtitle="Rolga ruxsatlar biriktiriladi; `modul.*` — modulning hammasi">
      <template #actions><UiButton size="s" variant="secondary" @click="r = { id: 0, code: '', name: '', permissions: [], is_system: false }; roleOpen = true"><UiIcon name="plus" /> Rol</UiButton></template>
      <div class="roles"><button v-for="x in roles" :key="x.id" type="button" class="role" @click="r = { ...x }; roleOpen = true"><b>{{ x.name }}</b><span>{{ x.permissions.includes('*') ? 'hamma narsa' : x.permissions.length + ' ruxsat' }}</span><UiChip v-if="x.is_system" tone="neutral">tizim</UiChip></button></div>
    </UiCard>
    <UiDrawer :open="open" title="Yangi xodim" width="420px" @close="open = false">
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
.ul { display: flex; flex-direction: column; }
.ur { display: grid; grid-template-columns: 44px minmax(0, 1.4fr) minmax(0, 1fr) 120px 200px; gap: 12px; align-items: center; padding: 10px 0; border-top: 1px solid var(--line-2); }
.ur:first-child { border-top: 0; }
.ph { position: relative; border: 0; padding: 0; background: none; cursor: pointer; border-radius: 14px; }
.ph .cam { position: absolute; right: -4px; bottom: -4px; width: 20px; height: 20px; border-radius: 50%; background: var(--surface); box-shadow: var(--shadow); display: grid; place-items: center; font-size: 11px; }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { color: var(--muted); }
.rl { display: flex; gap: 4px; flex-wrap: wrap; }
.ls { font-size: var(--fs-xs); color: var(--muted); }
.act { display: flex; gap: 4px; justify-content: flex-end; }
@media (max-width: 700px) { .ur { grid-template-columns: auto 1fr auto; } .rl { grid-column: 2 / -1; } .ls { grid-column: 2 / 3; } }
.roles { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.role { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); cursor: pointer; text-align: left; }
.role span { font-size: var(--fs-xs); color: var(--muted); }
.perms { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 4px; } .p { display: flex; gap: 8px; align-items: center; min-height: 32px; font-size: var(--fs-xs); }
</style>
