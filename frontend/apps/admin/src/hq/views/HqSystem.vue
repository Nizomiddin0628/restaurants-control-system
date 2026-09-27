<script setup lang="ts">
/** Funksiya bayroqlari (beta → hammaga), relizlar, platforma jamoasi, harakatlar jurnali. */
import { onMounted, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiEmpty, UiInput, UiToggle, toast } from '@restopos/ui'
import { useHq } from '../store'
import { ACTION, dt } from '../fmt'

const s = useHq()
const tab = ref<'flags' | 'releases' | 'staff' | 'audit'>('flags')
const F = ref<any>(null), S = ref<any>(null), A = ref<any[]>([])
const nf = ref({ code: '', name: '', description: '' })
const nr = ref({ version: '', title: '', notes: '' })
const ns = ref({ phone: '+998', full_name: '', role: 'support' })
async function load() {
  if (tab.value === 'flags' || tab.value === 'releases') F.value = await api.get('/hq/flags')
  if (tab.value === 'staff') S.value = await api.get('/hq/staff')
  if (tab.value === 'audit') A.value = await api.get('/hq/audit')
}
onMounted(load)
watch(tab, load)
async function saveFlag(f: any) {
  try { await api.post('/hq/flags', { code: f.code, name: f.name, description: f.description, enabled_all: f.enabled_all, tenants: f.tenants }); toast('Saqlandi'); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function toggleTenant(f: any, id: number) { f.tenants = f.tenants.includes(id) ? f.tenants.filter((x: number) => x !== id) : [...f.tenants, id]; saveFlag(f) }
async function addFlag() { await saveFlag({ ...nf.value, enabled_all: false, tenants: [] }); nf.value = { code: '', name: '', description: '' } }
async function addRelease() {
  try { await api.post('/hq/releases', { ...nr.value, publish: true }); nr.value = { version: '', title: '', notes: '' }; toast('Reliz qo\'shildi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function addStaff() {
  try { await api.post('/hq/staff', ns.value); ns.value = { phone: '+998', full_name: '', role: 'support' }; toast('Qo\'shildi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div class="sy">
    <nav class="tabs" role="tablist">
      <button :class="{ on: tab === 'flags' }" @click="tab = 'flags'">Funksiya bayroqlari</button>
      <button :class="{ on: tab === 'releases' }" @click="tab = 'releases'">Relizlar</button>
      <button :class="{ on: tab === 'staff' }" @click="tab = 'staff'">Jamoa</button>
      <button :class="{ on: tab === 'audit' }" @click="tab = 'audit'">Harakatlar jurnali</button>
    </nav>

    <template v-if="tab === 'flags' && F">
      <p class="note">Yangi imkoniyatni avval 2–3 restoranda sinang (beta), keyin «Hammaga» ni yoqing. Kod o'zgarmaydi.</p>
      <UiCard v-for="f in F.items" :key="f.id">
        <div class="fh"><div><b>{{ f.name }}</b> <code>{{ f.code }}</code><p>{{ f.description }}</p></div>
          <UiToggle :model-value="f.enabled_all" :disabled="!s.isAdmin" label="Hammaga" @update:model-value="(v: boolean) => { f.enabled_all = v; saveFlag(f) }" /></div>
        <div v-if="!f.enabled_all" class="bt"><span>Beta:</span>
          <button v-for="t in F.tenants" :key="t.id" type="button" :class="{ on: f.tenants.includes(t.id) }" :disabled="!s.isAdmin" @click="toggleTenant(f, t.id)">{{ t.name }}</button></div>
      </UiCard>
      <UiCard v-if="s.isAdmin" title="Yangi bayroq">
        <div class="g3"><UiInput v-model="nf.code" label="Kod" placeholder="ai_assistant" /><UiInput v-model="nf.name" label="Nomi" /><UiInput v-model="nf.description" label="Izoh" /></div>
        <UiButton variant="brand" size="s" style="margin-top: 10px" @click="addFlag()">Qo'shish</UiButton>
      </UiCard>
    </template>

    <template v-else-if="tab === 'releases' && F">
      <UiCard v-if="s.isAdmin" title="Yangi reliz">
        <div class="g3"><UiInput v-model="nr.version" label="Versiya" placeholder="v15" /><UiInput v-model="nr.title" label="Sarlavha" /><UiInput v-model="nr.notes" label="Nima o'zgardi" /></div>
        <UiButton variant="brand" size="s" style="margin-top: 10px" @click="addRelease()">E'lon qilish</UiButton>
      </UiCard>
      <UiCard :padded="false">
        <div v-for="r in F.releases" :key="r.id" class="rl"><UiChip tone="info">{{ r.version }}</UiChip><b>{{ r.title }}</b><span>{{ r.notes }}</span><small>{{ dt(r.published_at) }}</small></div>
        <UiEmpty v-if="!F.releases.length" title="Reliz yo'q" />
      </UiCard>
    </template>

    <template v-else-if="tab === 'staff' && S">
      <UiCard :padded="false">
        <div v-for="m in S.items" :key="m.id" class="rl"><b>{{ m.name }}</b><span>{{ m.phone }}</span><UiChip :tone="['founder', 'developer', 'superadmin'].includes(m.role) ? 'accent' : 'neutral'">{{ m.role_label }}</UiChip></div>
      </UiCard>
      <UiCard v-if="s.isAdmin" title="Jamoaga qo'shish">
        <div class="g3"><UiInput v-model="ns.phone" label="Telefon" /><UiInput v-model="ns.full_name" label="Ism" />
          <label class="fl"><span>Rol</span><select v-model="ns.role"><option v-for="r in S.roles" :key="r.code" :value="r.code">{{ r.label }}</option></select></label></div>
        <UiButton variant="brand" size="s" style="margin-top: 10px" @click="addStaff()">Qo'shish</UiButton>
      </UiCard>
    </template>

    <UiCard v-else-if="tab === 'audit'" :padded="false">
      <div v-for="(a, i) in A" :key="i" class="rl"><small>{{ dt(a.at) }}</small><b>{{ a.who }}</b><span>{{ ACTION[a.action] ?? a.action }}{{ a.tenant ? ` · ${a.tenant}` : '' }}</span></div>
      <UiEmpty v-if="!A.length" title="Jurnal bo'sh" />
    </UiCard>
  </div>
</template>

<style scoped>
.sy { display: flex; flex-direction: column; gap: 12px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: #2563EB; border-bottom-color: #2563EB; }
.note { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.fh { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; } .fh p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); }
code { font-size: 11px; background: var(--surface-2); padding: 1px 6px; border-radius: 6px; }
.bt { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 10px; font-size: var(--fs-s); color: var(--muted); }
.bt button { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 5px 12px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink); } .bt button.on { background: #2563EB; border-color: #2563EB; color: #fff; }
.g3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.rl { display: grid; grid-template-columns: auto auto 1fr auto; gap: 12px; align-items: center; padding: 12px 16px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.rl:first-child { border-top: 0; } .rl span { color: var(--ink-2); } .rl small { color: var(--muted); }
.fl { display: flex; flex-direction: column; gap: 6px; } .fl span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
select { min-height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); padding: 0 10px; font: inherit; background: var(--surface); color: var(--ink); }
@media (max-width: 700px) { .g3 { grid-template-columns: 1fr; } .rl { grid-template-columns: 1fr auto; } }
</style>
