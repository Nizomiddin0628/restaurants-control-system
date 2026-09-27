<script setup lang="ts">
/**
 * Xodimlar va kirish — oddiy sayt ko'rinishida:
 *   • ro'yxat: kim, qaysi lavozim(lar), qaysi filial, nimalarni ko'radi, Telegram/parol holati;
 *   • bosilsa — bitta oyna: ism, telefon, bir nechta rol, filial, AI Kotib, bo'limlar bo'yicha kirish (Yo'q / Ko'radi / Ishlaydi / To'liq);
 *   • «Rollar» — lavozim shablonlari (Kassir, Oshpaz…): bir marta sozlanadi, keyin xodimga bir bosishda beriladi.
 * Ierarxiya: Superadmin → Bosh menejer → Filial admini → xodim. Har kim faqat o'zidan pastdagilarni boshqaradi.
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiChip, UiDrawer, UiIcon, UiInput, UiToggle, toast } from '@restopos/ui'
import AccessMatrix from '@/components/users/AccessMatrix.vue'
import AccessDrawer from '@/components/users/AccessDrawer.vue'
import { type Meta, type Person, type RoleT, areaLevel, levelName, levelTone } from '@/components/users/perm'
import { useAuth } from '@/stores/auth'

const a = useAuth()
const meta = ref<Meta | null>(null), people = ref<Person[]>([]), loading = ref(true)
const tab = ref<'people' | 'roles'>('people'), q = ref(''), fRole = ref(''), fBranch = ref(''), showOff = ref(false)
async function load() {
  try { [meta.value, people.value] = await Promise.all([api.get<Meta>('/access/meta'), api.get<Person[]>('/access/users')]) }
  catch (e: any) { toast(e.detail ?? 'Yuklab bo\'lmadi', 'danger') } finally { loading.value = false }
}
onMounted(load)

const bname = (id: number) => meta.value?.branches.find(b => b.id === id)?.name ?? `#${id}`
const multiBranch = computed(() => (meta.value?.branches.length ?? 0) > 1)
const areaTitle = (c: string) => meta.value?.areas.find(x => x.code === c)?.title ?? c
function sees(p: Person) {
  const on = Object.entries(p.areas).filter(([c, l]) => l !== 'none' && c !== 'ai').map(([c]) => areaTitle(c).split(' (')[0])
  return on.length ? (on.length > 4 ? `${on.slice(0, 4).join(', ')} +${on.length - 4}` : on.join(', ')) : 'hech narsa'
}
const seen = (v: string | null) => (v ? new Date(v).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'hali kirmagan')
const filtered = computed(() => {
  const s = q.value.trim().toLowerCase().replace(/\s/g, '')
  return people.value.filter(p => (!s || (p.full_name + p.phone).toLowerCase().replace(/\s/g, '').includes(s))
    && (!fRole.value || p.roles.some(r => r.code === fRole.value))
    && (!fBranch.value || p.all_branches || p.branch_ids.includes(Number(fBranch.value))))
})
const groups = computed(() => [
  { key: 'lead', title: 'Rahbarlar', items: filtered.value.filter(p => p.is_active && p.level >= 60) },
  { key: 'staff', title: 'Xodimlar', items: filtered.value.filter(p => p.is_active && p.level < 60) },
].filter(g => g.items.length))
const inactive = computed(() => filtered.value.filter(p => !p.is_active))

// ------------------------------------------------------------------ xodim oynasi
type Form = { id: string; full_name: string; phone: string; role_codes: string[]; branch_ids: number[]; extra: string[]; editable: boolean; is_active: boolean; person: Person | null }
const f = ref<Form | null>(null), busy = ref(false), created = ref<Person | null>(null), showMatrix = ref(false)
function openNew() {
  const def = meta.value?.roles.find(r => r.code === 'cashier' && r.grantable) ?? meta.value?.roles.filter(r => r.grantable).slice(-1)[0]
  f.value = { id: '', full_name: '', phone: '+998 ', role_codes: def ? [def.code] : [], branch_ids: meta.value?.me.all_branches ? [] : (meta.value?.branches.map(b => b.id).slice(0, 1) ?? []), extra: [], editable: true, is_active: true, person: null }
  created.value = null; showMatrix.value = false
}
function openPerson(p: Person) {
  f.value = { id: p.id, full_name: p.full_name, phone: p.phone, role_codes: p.roles.map(r => r.code), branch_ids: [...p.branch_ids], extra: [...p.extra_permissions], editable: p.editable, is_active: p.is_active, person: p }
  created.value = null; showMatrix.value = p.extra_permissions.some(x => x !== 'ai.use')
}
const roleOf = (c: string) => meta.value?.roles.find(r => r.code === c)
const selRoles = computed(() => (f.value?.role_codes ?? []).map(roleOf).filter(Boolean) as RoleT[])
const basePerms = computed(() => [...new Set(selRoles.value.flatMap(r => r.permissions))])
const allBranchRole = computed(() => selRoles.value.some(r => r.level >= 80))
const roleChoices = computed(() => (meta.value?.roles ?? []).filter(r => r.grantable || f.value?.role_codes.includes(r.code)))
function toggleRole(r: RoleT) {
  if (!f.value || !f.value.editable || (!r.grantable)) return
  const has = f.value.role_codes.includes(r.code)
  f.value.role_codes = has ? f.value.role_codes.filter(x => x !== r.code) : [...f.value.role_codes, r.code]
}
function toggleBranch(id: number | null) {
  if (!f.value) return
  if (id === null) { f.value.branch_ids = []; return }
  const has = f.value.branch_ids.includes(id)
  f.value.branch_ids = has ? f.value.branch_ids.filter(x => x !== id) : [...f.value.branch_ids, id]
}
const aiArea = computed(() => meta.value?.areas.find(x => x.code === 'ai'))
const aiOn = computed(() => !!f.value && areaLevel([...basePerms.value, ...f.value.extra], aiArea.value!) !== 'none')
const aiByRole = computed(() => !!aiArea.value && areaLevel(basePerms.value, aiArea.value) !== 'none')
function setAi(v: boolean) { if (!f.value) return; f.value.extra = v ? [...new Set([...f.value.extra, 'ai.use'])] : f.value.extra.filter(x => x !== 'ai.use' && x !== 'ai.*') }
const seatsText = computed(() => {
  const s = meta.value?.ai; if (!s) return ''
  if (!s.enabled) return 'Tarifingizda AI Kotib yoqilmagan'
  return s.seats ? `Tarif: ${s.seats} kishi · band: ${s.used}` : `Band: ${s.used} kishi (cheklovsiz)`
})

async function save() {
  if (!f.value) return
  if (!f.value.role_codes.length) { toast('Kamida bitta lavozim (rol) tanlang', 'danger'); return }
  busy.value = true
  const body = { full_name: f.value.full_name, phone: f.value.phone, role_codes: f.value.role_codes, branch_ids: allBranchRole.value ? [] : f.value.branch_ids, extra_permissions: f.value.extra }
  try {
    if (f.value.id) { await api.put(`/access/users/${f.value.id}`, { ...body, is_active: f.value.is_active ? undefined : true }); f.value = null; toast('Saqlandi') }
    else { created.value = await api.post<Person>('/access/users', body); toast('Xodim qo\'shildi') }
    await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function deactivate() {
  if (!f.value?.id || !confirm(`${f.value.full_name || f.value.phone} tizimga kira olmaydi. Davom etasizmi?`)) return
  try { await api.put(`/access/users/${f.value.id}`, { role_codes: f.value.role_codes, is_active: false }); f.value = null; await load(); toast('Kirish o\'chirildi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const pwFor = ref<{ id: string; full_name?: string; phone?: string } | null>(null)
const loginUrl = computed(() => `${location.origin}/admin/login`)
const bot = computed(() => a.me?.bot_username ? `@${a.me.bot_username}` : 'restoran boti')

// ------------------------------------------------------------------ rollar
const rf = ref<{ id: number; name: string; description: string; permissions: string[]; editable: boolean; code: string; level: number } | null>(null)
function openRole(r?: RoleT) {
  rf.value = r ? { id: r.id, name: r.name, description: r.description, permissions: [...r.permissions], editable: r.editable, code: r.code, level: r.level }
    : { id: 0, name: '', description: '', permissions: ['tasks.view', 'training.view'], editable: true, code: '', level: 10 }
}
async function saveRole() {
  if (!rf.value) return
  try {
    const body = { name: rf.value.name, description: rf.value.description, permissions: rf.value.permissions }
    rf.value.id ? await api.put(`/access/roles/${rf.value.id}`, body) : await api.post('/access/roles', body)
    rf.value = null; await load(); toast('Rol saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function delRole() {
  if (!rf.value?.id || !confirm(`«${rf.value.name}» rolini o'chirasizmi?`)) return
  try { await api.del(`/access/roles/${rf.value.id}`); rf.value = null; await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div class="wrap">
    <header class="hd">
      <div class="tx">
        <h2>Xodimlar va kirish</h2>
        <p>Har bir xodim <b>telefon raqami</b> bilan kiradi va Telegram botda «✅ Ha» ni bosib tasdiqlaydi. Kim qaysi bo'limni ko'rishini shu yerda belgilaysiz.</p>
      </div>
      <UiButton @click="openNew()"><UiIcon name="plus" /> Xodim qo'shish</UiButton>
    </header>

    <div class="tabs" role="tablist">
      <button type="button" role="tab" :aria-selected="tab === 'people'" :class="{ on: tab === 'people' }" @click="tab = 'people'">👥 Xodimlar <small>{{ people.filter(p => p.is_active).length }}</small></button>
      <button type="button" role="tab" :aria-selected="tab === 'roles'" :class="{ on: tab === 'roles' }" @click="tab = 'roles'">🏷️ Lavozimlar (rollar) <small>{{ meta?.roles.length ?? 0 }}</small></button>
    </div>

    <template v-if="tab === 'people'">
      <div class="bar">
        <input v-model="q" class="inp" type="search" placeholder="🔍 Ism yoki telefon" aria-label="Qidirish" />
        <select v-model="fRole" class="inp" aria-label="Lavozim bo'yicha"><option value="">Barcha lavozimlar</option><option v-for="r in meta?.roles" :key="r.code" :value="r.code">{{ r.name }}</option></select>
        <select v-if="multiBranch" v-model="fBranch" class="inp" aria-label="Filial bo'yicha"><option value="">Barcha filiallar</option><option v-for="b in meta?.branches" :key="b.id" :value="String(b.id)">{{ b.name }}</option></select>
      </div>
      <p v-if="loading" class="muted">Yuklanmoqda…</p>
      <section v-for="g in groups" :key="g.key" class="grp">
        <h3>{{ g.title }} <small>{{ g.items.length }}</small></h3>
        <div class="list">
          <button v-for="p in g.items" :key="p.id" type="button" class="pc" :class="{ ro: !p.editable }" @click="openPerson(p)">
            <UiAvatar :name="p.full_name || p.phone" :src="p.avatar" :size="44" />
            <span class="who"><b>{{ p.full_name || 'Ismsiz' }}<em v-if="p.is_me"> (siz)</em></b><small>{{ p.phone }}</small></span>
            <span class="rl">
              <UiChip v-for="r in p.roles" :key="r.code" :tone="levelTone(r.level)">{{ r.name }}</UiChip>
              <UiChip v-if="p.ai" tone="accent">🤖 AI Kotib</UiChip>
            </span>
            <span class="sc"><small>Ko'radi:</small> {{ sees(p) }}<br /><small>Filial:</small> {{ p.all_branches ? 'barchasi' : p.branch_ids.map(bname).join(', ') }}</span>
            <span class="st">
              <span :class="p.telegram_linked ? 'ok' : 'wa'">{{ p.telegram_linked ? '✈️ Telegram ulangan' : '✈️ Telegram ulanmagan' }}</span>
              <span class="mu">{{ seen(p.last_seen_at) }}</span>
            </span>
          </button>
        </div>
      </section>
      <p v-if="!loading && !groups.length" class="muted">Hech kim topilmadi.</p>
      <div v-if="inactive.length" class="off">
        <button type="button" class="lnk" @click="showOff = !showOff">{{ showOff ? '▾' : '▸' }} Kirishi o'chirilganlar ({{ inactive.length }})</button>
        <div v-if="showOff" class="list">
          <button v-for="p in inactive" :key="p.id" type="button" class="pc dim" @click="openPerson(p)">
            <UiAvatar :name="p.full_name || p.phone" :src="p.avatar" :size="36" /><span class="who"><b>{{ p.full_name || 'Ismsiz' }}</b><small>{{ p.phone }}</small></span>
            <span class="rl"><UiChip tone="neutral">o'chirilgan</UiChip></span>
          </button>
        </div>
      </div>
    </template>

    <template v-else>
      <p class="muted">Lavozim — tayyor ruxsatlar to'plami. Xodimga bir nechta lavozim berish mumkin (masalan: <b>Kassir + Ofitsiant</b>), ustiga alohida ruxsat ham qo'shiladi.</p>
      <div class="roles">
        <button v-for="r in meta?.roles" :key="r.id" type="button" class="rc" @click="openRole(r)">
          <span class="rt"><b>{{ r.name }}</b><UiChip :tone="levelTone(r.level)">{{ levelName(r.level) }}</UiChip></span>
          <small>{{ r.description || (r.permissions.includes('*') ? 'Hamma bo\'limlar' : `${r.permissions.length} ta ruxsat`) }}</small>
          <span class="rm">👥 {{ r.members }} kishi</span>
        </button>
        <button v-if="meta?.me.can_roles" type="button" class="rc add" @click="openRole()"><UiIcon name="plus" /> Yangi lavozim</button>
      </div>
    </template>

    <!-- Xodim oynasi -->
    <UiDrawer :open="!!f" :title="f?.id ? (f.full_name || f.phone) : 'Yangi xodim'" width="760px" @close="f = null; created = null">
      <template v-if="f && created">
        <div class="done">
          <p class="big">✅ <b>{{ created.full_name || created.phone }}</b> qo'shildi</p>
          <p>Endi xodim o'zi kiradi — parol shart emas:</p>
          <ol>
            <li>Telegram'da <b>{{ bot }}</b> ni ochib <b>/start</b> bosadi va «📱 Telefonni ulashish» tugmasini bosadi.</li>
            <li>Saytga kiradi: <a :href="loginUrl" target="_blank" rel="noopener">{{ loginUrl.replace(/^https?:\/\//, '') }}</a> → telefon raqami → <b>«Telegram orqali kirish»</b>.</li>
            <li>Botda <b>«✅ Ha, men kiryapman»</b> ni bosadi — sayt o'zi ochiladi, faqat unga ruxsat berilgan bo'limlar bilan.</li>
          </ol>
          <p class="muted">Telegram'i yo'q xodimga parol bering:</p>
          <UiButton variant="secondary" @click="pwFor = { id: created.id, full_name: created.full_name, phone: created.phone }">🔑 Parol yaratish</UiButton>
        </div>
      </template>
      <template v-else-if="f">
        <p v-if="!f.editable && f.is_active" class="warn">👁 Faqat ko'rish: bu xodim sizdan yuqori darajada yoki boshqa filialda.</p>
        <div class="two">
          <UiInput v-model="f.full_name" label="Ism familiya" placeholder="Masalan: Aziz Karimov" :disabled="!f.editable" />
          <UiInput v-model="f.phone" label="Telefon (login)" type="tel" placeholder="+998 90 123 45 67" :disabled="!f.editable" />
        </div>

        <div class="blk">
          <h4>Lavozimi <small>— bir nechtasini tanlash mumkin</small></h4>
          <div class="chips">
            <button v-for="r in roleChoices" :key="r.code" type="button" class="ch" :class="{ on: f.role_codes.includes(r.code), dis: !r.grantable || !f.editable }"
                    :disabled="!r.grantable || !f.editable" :title="r.description" @click="toggleRole(r)">
              <span class="ck">{{ f.role_codes.includes(r.code) ? '✓' : '+' }}</span>{{ r.name }}
            </button>
          </div>
          <p v-if="selRoles.length" class="muted sm">{{ selRoles.map(r => r.description).filter(Boolean).join(' · ') }}</p>
        </div>

        <div v-if="multiBranch" class="blk">
          <h4>Filial</h4>
          <p v-if="allBranchRole" class="muted sm">Bu lavozim barcha filiallarni ko'radi.</p>
          <div v-else class="chips">
            <button v-if="meta?.me.all_branches" type="button" class="ch" :class="{ on: !f.branch_ids.length }" :disabled="!f.editable" @click="toggleBranch(null)"><span class="ck">{{ !f.branch_ids.length ? '✓' : '+' }}</span>Barcha filiallar</button>
            <button v-for="b in meta?.branches" :key="b.id" type="button" class="ch" :class="{ on: f.branch_ids.includes(b.id) }" :disabled="!f.editable" @click="toggleBranch(b.id)"><span class="ck">{{ f.branch_ids.includes(b.id) ? '✓' : '+' }}</span>{{ b.name }}</button>
          </div>
        </div>

        <div v-if="aiArea && meta?.ai" class="blk ai">
          <div class="air">
            <span><b>🤖 AI Kotib</b><small>Ertalabki hisobot, savol-javob, ovozli buyruq (Telegram va sayt). {{ seatsText }}</small></span>
            <UiToggle :model-value="aiOn" :disabled="!f.editable || aiByRole || !meta.ai.enabled" @update:model-value="setAi" />
          </div>
          <p v-if="aiByRole" class="muted sm">Lavozimi bo'yicha bor.</p>
        </div>

        <div class="blk">
          <button type="button" class="mh" :aria-expanded="showMatrix" @click="showMatrix = !showMatrix">
            <span><b>Qaysi bo'limlarni ko'radi</b><small>Lavozimidan tashqari qo'shimcha ruxsat (masalan kassirga «Ombor — Ko'radi»)</small></span><span>{{ showMatrix ? '▾' : '▸' }}</span>
          </button>
          <AccessMatrix v-if="showMatrix && meta" v-model="f.extra" :areas="meta.areas" :sections="meta.sections" :base="basePerms" :disabled="!f.editable" :skip="['ai']" />
        </div>

        <div v-if="f.person" class="blk login">
          <h4>Kirish</h4>
          <p class="sm"><span :class="f.person.telegram_linked ? 'ok' : 'wa'">{{ f.person.telegram_linked ? '✈️ Telegram botga ulangan — telefon + «Telegram orqali kirish»' : `✈️ Hali ulanmagan: xodim ${bot} da /start bosib telefonini ulashsin` }}</span>
            · {{ f.person.has_password ? '🔑 parol bor' : 'parol yo\'q' }}</p>
          <UiButton v-if="f.editable && f.is_active" size="s" variant="secondary" @click="pwFor = { id: f.id, full_name: f.full_name, phone: f.phone }">🔑 {{ f.person.has_password ? 'Yangi parol' : 'Parol berish' }}</UiButton>
        </div>
      </template>
      <template v-if="f && !created" #footer>
        <UiButton v-if="f.id && f.editable && f.is_active" variant="ghost" @click="deactivate()">Kirishni o'chirish</UiButton>
        <span class="sp"></span>
        <UiButton v-if="f.editable || !f.is_active" :loading="busy" @click="save()">{{ f.id ? (f.is_active ? 'Saqlash' : 'Qayta tiklash') : 'Qo\'shish' }}</UiButton>
      </template>
      <template v-else-if="created" #footer><UiButton @click="f = null; created = null">Tayyor</UiButton></template>
    </UiDrawer>

    <!-- Rol oynasi -->
    <UiDrawer :open="!!rf" :title="rf?.id ? rf.name : 'Yangi lavozim'" width="760px" @close="rf = null">
      <template v-if="rf && meta">
        <p v-if="!rf.editable && rf.id" class="warn">{{ rf.permissions.includes('*') ? 'Bu lavozim hamma bo\'limlarni ko\'radi — o\'zgartirilmaydi.' : 'Bu lavozimni o\'zgartira olmaysiz.' }}</p>
        <div class="two">
          <UiInput v-model="rf.name" label="Nomi" placeholder="Masalan: Katta kassir" :disabled="!rf.editable" />
          <UiInput v-model="rf.description" label="Qisqa tavsif" placeholder="Nima ish qiladi" :disabled="!rf.editable" />
        </div>
        <AccessMatrix v-if="!rf.permissions.includes('*')" v-model="rf.permissions" :areas="meta.areas" :sections="meta.sections" :disabled="!rf.editable" />
      </template>
      <template v-if="rf?.editable" #footer>
        <UiButton v-if="rf.id" variant="ghost" @click="delRole()">O'chirish</UiButton><span class="sp"></span>
        <UiButton @click="saveRole()">Saqlash</UiButton>
      </template>
    </UiDrawer>

    <AccessDrawer :user="pwFor" @close="pwFor = null" @done="load()" />
  </div>
</template>

<style scoped>
.wrap { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; gap: 14px; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l, 16px); padding: 16px 18px; }
.hd .tx { flex: 1; min-width: 240px; } .hd h2 { margin: 0 0 4px; font-size: var(--fs-l, 20px); } .hd p { margin: 0; color: var(--ink-2); font-size: var(--fs-s); max-width: 720px; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tabs button { border: 1px solid var(--line); background: var(--surface); border-radius: 12px; padding: 9px 14px; font: inherit; font-weight: 700; cursor: pointer; color: var(--ink-2); min-height: 42px; }
.tabs button.on { background: var(--ink); color: var(--surface); border-color: var(--ink); } .tabs small { opacity: .7; margin-left: 4px; }
.bar { display: flex; gap: 8px; flex-wrap: wrap; }
.inp { flex: 1 1 180px; min-width: 0; min-height: 42px; border: 1px solid var(--line); border-radius: 12px; padding: 0 12px; background: var(--surface); color: var(--ink); font: inherit; font-size: var(--fs-s); }
.grp h3 { margin: 6px 0 8px; font-size: var(--fs-b); } .grp h3 small { color: var(--muted); font-weight: 700; }
.list { display: flex; flex-direction: column; gap: 8px; }
.pc { display: grid; grid-template-columns: 44px minmax(150px, 1.1fr) minmax(0, 1.2fr) minmax(0, 1.6fr) 170px; gap: 12px; align-items: center; text-align: left; width: 100%;
  border: 1px solid var(--line); border-radius: 14px; background: var(--surface); padding: 10px 14px; font: inherit; color: var(--ink); cursor: pointer; }
.pc:hover { border-color: var(--accent); } .pc.dim { opacity: .7; grid-template-columns: 36px minmax(0, 1fr) auto; }
.who { display: flex; flex-direction: column; min-width: 0; } .who b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .who em { font-style: normal; color: var(--muted); font-weight: 600; } .who small { color: var(--muted); }
.rl { display: flex; gap: 4px; flex-wrap: wrap; }
.sc { font-size: var(--fs-xs); color: var(--ink-2); line-height: 1.5; min-width: 0; } .sc small { color: var(--muted); font-weight: 700; }
.st { display: flex; flex-direction: column; gap: 2px; font-size: var(--fs-xs); text-align: right; }
.ok { color: var(--ok); font-weight: 700; } .wa { color: var(--warn-ink); font-weight: 700; } .mu, .muted { color: var(--muted); }
.muted { margin: 0; font-size: var(--fs-s); } .sm { font-size: var(--fs-xs); margin: 6px 0 0; }
.off { margin-top: 4px; } .lnk { border: 0; background: none; color: var(--muted); font: inherit; font-weight: 700; cursor: pointer; padding: 6px 0; }
.roles { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.rc { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; text-align: left; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); padding: 14px; font: inherit; color: var(--ink); cursor: pointer; }
.rc:hover { border-color: var(--accent); } .rc small { color: var(--muted); font-size: var(--fs-xs); } .rc .rm { font-size: var(--fs-xs); font-weight: 700; color: var(--ink-2); margin-top: auto; }
.rt { display: flex; gap: 8px; align-items: center; justify-content: space-between; width: 100%; flex-wrap: wrap; }
.rc.add { align-items: center; justify-content: center; border-style: dashed; color: var(--accent); font-weight: 800; flex-direction: row; min-height: 96px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.blk { border-top: 1px solid var(--line-2); padding-top: 12px; } .blk h4 { margin: 0 0 8px; font-size: var(--fs-s); } .blk h4 small { color: var(--muted); font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.ch { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 7px 12px; min-height: 38px; font: inherit; font-size: var(--fs-s); font-weight: 700; cursor: pointer; color: var(--ink-2); }
.ch.on { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); } .ch.dis { opacity: .5; cursor: not-allowed; }
.ck { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; background: var(--surface-3); } .ch.on .ck { background: var(--accent); color: #fff; }
.ai .air { display: flex; gap: 12px; align-items: center; justify-content: space-between; } .air span { display: flex; flex-direction: column; } .air small { color: var(--muted); font-size: var(--fs-xs); }
.mh { display: flex; width: 100%; justify-content: space-between; align-items: center; gap: 10px; border: 0; background: none; padding: 0 0 8px; font: inherit; color: var(--ink); cursor: pointer; text-align: left; }
.mh span:first-child { display: flex; flex-direction: column; } .mh small { color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
.warn { margin: 0; padding: 8px 12px; border-radius: 10px; background: var(--warn-tint); color: var(--warn-ink); font-size: var(--fs-s); font-weight: 700; }
.done .big { font-size: var(--fs-b); margin: 0 0 6px; } .done ol { padding-left: 20px; display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); }
.sp { flex: 1; }
@media (max-width: 1100px) { .pc { grid-template-columns: 44px minmax(0, 1fr) minmax(0, 1.2fr); } .sc, .st { grid-column: 2 / -1; text-align: left; } .st { flex-direction: row; gap: 10px; flex-wrap: wrap; } }
@media (max-width: 640px) { .pc { grid-template-columns: 44px minmax(0, 1fr); } .rl, .sc, .st { grid-column: 2; } .two { grid-template-columns: 1fr; } }
</style>
