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
import { UiAvatar, UiButton, UiChip, UiDrawer, UiIcon, UiInput, toast } from '@restopos/ui'
import AccessMatrix from '@/components/users/AccessMatrix.vue'
import AccessPanel from '@/components/users/AccessPanel.vue'
import { type Meta, type Person, type RoleT, levelName, levelTone } from '@/components/users/perm'

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

// ------------------------------------------------------------------ xodim oynasi (umumiy AccessPanel)
const panel = ref<{ id: string | null; create: boolean; tab?: 'access' | 'login' } | null>(null)
function openNew() { panel.value = { id: null, create: true } }
function openPerson(p: Person, tab: 'access' | 'login' = 'access') { panel.value = { id: p.id, create: false, tab } }

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
              <span :class="p.has_password ? 'mu' : 'mu'">{{ p.has_password ? '🔑 parol bor' : 'parolsiz' }}</span>
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

    <!-- Xodim oynasi: lavozim va ruxsatlar + kirish va xavfsizlik -->
    <AccessPanel :user-id="panel?.id ?? null" :create="!!panel?.create" :tab="panel?.tab" @close="panel = null" @saved="load()" />

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
