<script setup lang="ts">
/**
 * Xodimning kirishi — bitta oyna, hamma joyda bir xil («Xodimlar va kirish», HR ro'yxati, xodim profili):
 *   1) «Lavozim va ruxsatlar» — ism, telefon, bir nechta lavozim, filial, AI Kotib, bo'limlar (Yo'q/Ko'radi/Ishlaydi/To'liq);
 *   2) «Kirish va xavfsizlik» — Telegram (taklif havolasi: bir bosishda ulanadi), parol (yaratish/o'chirish),
 *      hamma qurilmalardan chiqarish, bloklash, kirish tarixi.
 * userId = null va create = true — yangi xodim; saqlangach o'zi 2-bo'limga o'tadi (taklif havolasi tayyor).
 */
import { computed, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiAvatar, UiButton, UiChip, UiDrawer, UiInput, UiToggle, toast } from '@restopos/ui'
import AccessMatrix from './AccessMatrix.vue'
import AccessCard from './AccessCard.vue'
import type { Access } from './access'
import { type Meta, type Person, type RoleT, areaLevel, levelName, levelTone } from './perm'

type Login = { history: { at: string; method: string; method_label: string; device: string; ip: string }[]; bot: string; login_url: string; invite: { link: string; expires: string } | null }
type Full = Person & { login?: Login }
const props = defineProps<{ userId: string | null; create?: boolean; tab?: 'access' | 'login' }>()
const emit = defineEmits<{ close: []; saved: [] }>()

let metaCache: Meta | null = null
const meta = ref<Meta | null>(null), p = ref<Full | null>(null), busy = ref(false), loading = ref(false)
const tab = ref<'access' | 'login'>('access'), justCreated = ref(false), showMatrix = ref(false)
type Form = { full_name: string; phone: string; role_codes: string[]; branch_ids: number[]; extra: string[] }
const f = ref<Form>({ full_name: '', phone: '+998 ', role_codes: [], branch_ids: [], extra: [] })
const open = computed(() => !!props.userId || !!props.create)
/** O'zgartirilganmi — ✕/ESC bosilganda «saqlanmagan» deb so'rash uchun */
const initial = ref('')
const snap = () => JSON.stringify({ ...f.value, role_codes: [...f.value.role_codes].sort(), branch_ids: [...f.value.branch_ids].sort(), extra: [...f.value.extra].sort() })
const changed = computed(() => !!initial.value && snap() !== initial.value && (tab.value === 'access' || !p.value))

async function loadMeta() { if (!metaCache) metaCache = await api.get<Meta>('/access/meta'); meta.value = metaCache }
async function loadPerson(id: string) {
  p.value = await api.get<Full>(`/access/users/${id}`)
  f.value = { full_name: p.value.full_name, phone: p.value.phone, role_codes: p.value.roles.map(r => r.code), branch_ids: [...p.value.branch_ids], extra: [...p.value.extra_permissions] }
  showMatrix.value = p.value.extra_permissions.some(x => x !== 'ai.use')
  initial.value = snap()
}
watch(() => [props.userId, props.create] as const, async ([id, cr]) => {
  if (!id && !cr) return
  loading.value = true; justCreated.value = false; access.value = null; pwMode.value = false; invite.value = null
  try {
    metaCache = null; await loadMeta()
    tab.value = props.tab ?? 'access'
    if (id) await loadPerson(id)
    else {
      p.value = null
      const def = meta.value?.roles.find(r => r.code === 'cashier' && r.grantable) ?? meta.value?.roles.filter(r => r.grantable).slice(-1)[0]
      f.value = { full_name: '', phone: '+998 ', role_codes: def ? [def.code] : [], branch_ids: meta.value?.me.all_branches ? [] : (meta.value?.branches.map(b => b.id).slice(0, 1) ?? []), extra: [] }
      showMatrix.value = false
      initial.value = snap()
    }
  } catch (e: any) { toast(e.detail ?? 'Yuklab bo\'lmadi', 'danger'); emit('close') } finally { loading.value = false }
}, { immediate: true })

const editable = computed(() => !p.value || p.value.editable)
const roleOf = (c: string) => meta.value?.roles.find(r => r.code === c)
const selRoles = computed(() => f.value.role_codes.map(roleOf).filter(Boolean) as RoleT[])
const basePerms = computed(() => [...new Set(selRoles.value.flatMap(r => r.permissions))])
const allBranchRole = computed(() => selRoles.value.some(r => r.level >= 80))
const roleChoices = computed(() => (meta.value?.roles ?? []).filter(r => r.grantable || f.value.role_codes.includes(r.code)))
const multiBranch = computed(() => (meta.value?.branches.length ?? 0) > 1)
/** Rol nimalarni ochadi — oddiy tilda (kartada) */
function roleSees(r: RoleT): string {
  if (r.permissions.includes('*')) return 'Hamma bo\'limlar, barcha filiallar'
  const on = (meta.value?.areas ?? []).filter(x => x.code !== 'ai' && areaLevel(r.permissions, x) !== 'none').map(x => x.title.split(' (')[0])
  return on.length ? (on.length > 5 ? `${on.slice(0, 5).join(', ')} +${on.length - 5}` : on.join(', ')) : 'Faqat o\'z vazifalari'
}
const roleGroups = computed(() => [
  { title: 'Rahbarlar', items: roleChoices.value.filter(r => r.level >= 60) },
  { title: 'Xodimlar', items: roleChoices.value.filter(r => r.level < 60) },
].filter(g => g.items.length))
/** Hozirgi tanlov bo'yicha xodim nimalarni ko'radi (rol + qo'shimcha) — pastda jonli xulosa */
const LV: Record<string, string> = { view: 'ko\'radi', edit: 'ishlaydi', full: 'to\'liq', custom: 'qisman' }
const sees = computed(() => {
  const all = [...basePerms.value, ...f.value.extra]
  if (all.includes('*')) return [{ t: 'Hamma bo\'limlar', l: 'to\'liq' }]
  return (meta.value?.areas ?? []).map(x => ({ t: x.title.split(' (')[0], lv: areaLevel(all, x) })).filter(x => x.lv !== 'none').map(x => ({ t: x.t, l: LV[x.lv] ?? '' }))
})
function toggleRole(r: RoleT) {
  if (!editable.value || !r.grantable) return
  f.value.role_codes = f.value.role_codes.includes(r.code) ? f.value.role_codes.filter(x => x !== r.code) : [...f.value.role_codes, r.code]
}
function toggleBranch(id: number | null) {
  if (id === null) { f.value.branch_ids = []; return }
  f.value.branch_ids = f.value.branch_ids.includes(id) ? f.value.branch_ids.filter(x => x !== id) : [...f.value.branch_ids, id]
}
const aiArea = computed(() => meta.value?.areas.find(x => x.code === 'ai'))
const aiOn = computed(() => !!aiArea.value && areaLevel([...basePerms.value, ...f.value.extra], aiArea.value) !== 'none')
const aiByRole = computed(() => !!aiArea.value && areaLevel(basePerms.value, aiArea.value) !== 'none')
function setAi(v: boolean) { f.value.extra = v ? [...new Set([...f.value.extra, 'ai.use'])] : f.value.extra.filter(x => x !== 'ai.use' && x !== 'ai.*') }
const seatsText = computed(() => {
  const s = meta.value?.ai; if (!s) return ''
  if (!s.enabled) return 'Tarifingizda AI Kotib yoqilmagan'
  return s.seats ? `Tarif: ${s.seats} kishi · band: ${s.used}` : `Band: ${s.used} kishi`
})

async function save() {
  if (!f.value.role_codes.length) { toast('Kamida bitta lavozim tanlang', 'danger'); return }
  busy.value = true
  const body = { full_name: f.value.full_name, phone: f.value.phone, role_codes: f.value.role_codes, branch_ids: allBranchRole.value ? [] : f.value.branch_ids, extra_permissions: f.value.extra }
  try {
    if (p.value) {
      await api.put(`/access/users/${p.value.id}`, { ...body, is_active: p.value.is_active ? undefined : true })
      await loadPerson(p.value.id); toast('Saqlandi'); emit('saved')
    } else {
      const x = await api.post<Person>('/access/users', body)
      await loadPerson(x.id); justCreated.value = true; tab.value = 'login'; emit('saved')
      const cur = p.value as Full | null
      if (cur && !cur.telegram_linked && cur.login?.bot) makeInvite(true)
    }
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}

// ------------------------------------------------------------------ kirish va xavfsizlik
const invite = ref<{ link: string; expires: string } | null>(null)
const inv = computed(() => invite.value ?? p.value?.login?.invite ?? null)
async function makeInvite(quiet = false) {
  if (!p.value) return
  try { invite.value = await api.post(`/access/users/${p.value.id}/invite`); if (!quiet) toast('Taklif havolasi tayyor') }
  catch (e: any) { if (!quiet) toast(e.detail ?? 'Xato', 'danger') }
}
const shareText = computed(() => `${p.value?.full_name || ''}, ${a0()} tizimiga kirish uchun shu havolani bosing — Telegram bot sizni o'zi taniydi:`)
function a0() { return document.title.split('·')[0].trim() || 'restoran' }
const shareUrl = computed(() => inv.value?.link ? `https://t.me/share/url?url=${encodeURIComponent(inv.value.link)}&text=${encodeURIComponent(shareText.value)}` : '')
async function copy(t: string) { try { await navigator.clipboard.writeText(t); toast('Nusxalandi') } catch { toast('Nusxalab bo\'lmadi', 'danger') } }
async function act(url: string, ok: string, method: 'post' | 'del' = 'post', confirmText = '') {
  if (!p.value || (confirmText && !confirm(confirmText))) return
  try { method === 'post' ? await api.post(url) : await api.del(url); toast(ok); await loadPerson(p.value.id); emit('saved') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const logoutAll = () => act(`/access/users/${p.value!.id}/logout-all`, 'Hamma qurilmalardan chiqarildi', 'post', 'Xodim barcha qurilmalardan chiqariladi. Davom etasizmi?')
const unlinkTg = () => act(`/access/users/${p.value!.id}/telegram-unlink`, 'Telegram uzildi', 'post', 'Telegram uzilsa, xodim botdan xabar olmaydi va Telegram orqali kira olmaydi. Uzasizmi?')
const pwOff = () => act(`/access/users/${p.value!.id}/password`, 'Parol o\'chirildi — endi faqat Telegram orqali kiradi', 'del', 'Parol bilan kirish o\'chirilsinmi?')
async function block(on: boolean) {
  if (!p.value) return
  if (on && !confirm(`${p.value.full_name || p.value.phone} tizimga kira olmaydi (hamma qurilmalardan chiqariladi). Davom etasizmi?`)) return
  try {
    await api.put(`/access/users/${p.value.id}`, { role_codes: p.value.roles.map(r => r.code), branch_ids: p.value.branch_ids, extra_permissions: p.value.extra_permissions, is_active: !on })
    toast(on ? 'Kirish bloklandi' : 'Kirish tiklandi'); await loadPerson(p.value.id); emit('saved')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
// parol
const access = ref<Access | null>(null), pwMode = ref(false), pwVal = ref(''), pwErr = ref('')
async function setPw(generate: boolean) {
  if (!p.value) return
  if (!generate && pwVal.value.length < 6) { pwErr.value = 'Kamida 6 ta belgi'; return }
  try { access.value = await api.post<Access>(`/users/${p.value.id}/password`, generate ? { generate: true } : { password: pwVal.value }); pwMode.value = false; pwVal.value = ''; await loadPerson(p.value.id) }
  catch (e: any) { pwErr.value = e.detail ?? 'Xato' }
}
const dt = (v: string | null) => (v ? new Date(v).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '')
const title = computed(() => (p.value ? (p.value.full_name || p.value.phone) : 'Yangi xodim'))
</script>

<template>
  <UiDrawer :open="open" :title="title" width="820px" :state="changed ? 'dirty' : 'clean'" @close="emit('close')">
    <p v-if="loading" class="mu">Yuklanmoqda…</p>
    <template v-else-if="meta">
      <!-- holat sarlavhasi -->
      <div v-if="p" class="hd">
        <UiAvatar :name="p.full_name || p.phone" :src="p.avatar" :size="52" />
        <div class="hi">
          <b>{{ p.full_name || 'Ismsiz' }}</b><span>{{ p.phone }}</span>
          <div class="chips">
            <UiChip :tone="levelTone(p.level)">{{ levelName(p.level) }}</UiChip>
            <UiChip :tone="p.is_active ? 'ok' : 'danger'">{{ p.is_active ? 'Kirish faol' : 'Bloklangan' }}</UiChip>
            <UiChip :tone="p.telegram_linked ? 'info' : 'warn'">{{ p.telegram_linked ? '✈️ Telegram ulangan' : '✈️ Telegram ulanmagan' }}</UiChip>
            <UiChip :tone="p.has_password ? 'ok' : 'neutral'">{{ p.has_password ? '🔑 Parol bor' : 'Parolsiz' }}</UiChip>
            <UiChip v-if="p.ai" tone="accent">🤖 AI Kotib</UiChip>
          </div>
        </div>
        <small class="last">{{ p.last_seen_at ? 'Oxirgi kirish: ' + dt(p.last_seen_at) : 'Hali kirmagan' }}</small>
      </div>
      <p v-if="justCreated" class="okb">✅ Xodim qo'shildi. Endi kirishini sozlang — eng osoni Telegram taklif havolasi.</p>
      <p v-if="p && !p.editable" class="warn">👁 Faqat ko'rish: bu xodim sizdan yuqori darajada yoki boshqa filialda.</p>

      <div v-if="p" class="tabs" role="tablist">
        <button type="button" role="tab" :aria-selected="tab === 'access'" :class="{ on: tab === 'access' }" @click="tab = 'access'">👤 <span class="lg">Lavozim va ruxsatlar</span><span class="sh">Ruxsatlar</span></button>
        <button type="button" role="tab" :aria-selected="tab === 'login'" :class="{ on: tab === 'login' }" @click="tab = 'login'">🔐 <span class="lg">Kirish va xavfsizlik</span><span class="sh">Kirish</span></button>
      </div>

      <!-- 1) LAVOZIM VA RUXSATLAR -->
      <div v-if="tab === 'access' || !p" class="pane">
        <div class="two">
          <UiInput v-model="f.full_name" label="Ism familiya" placeholder="Masalan: Aziz Karimov" :disabled="!editable" />
          <UiInput v-model="f.phone" label="Telefon (login)" type="tel" placeholder="+998 90 123 45 67" :disabled="!editable" />
        </div>
        <div class="blk">
          <h4>Lavozimi <small>— kerakli kartani bosing (bir nechtasini tanlash mumkin)</small></h4>
          <div v-for="g in roleGroups" :key="g.title" class="rg">
            <h5>{{ g.title }}</h5>
            <div class="rcards">
              <button v-for="r in g.items" :key="r.code" type="button" class="rcard" :class="{ on: f.role_codes.includes(r.code) }" :disabled="!r.grantable || !editable" @click="toggleRole(r)">
                <span class="ck">{{ f.role_codes.includes(r.code) ? '✓' : '' }}</span>
                <b>{{ r.name }}</b>
                <small>{{ r.description || roleSees(r) }}</small>
                <em v-if="r.description">{{ roleSees(r) }}</em>
              </button>
            </div>
          </div>
        </div>
        <div v-if="multiBranch" class="blk">
          <h4>Filial</h4>
          <p v-if="allBranchRole" class="mu sm">Bu lavozim barcha filiallarni ko'radi.</p>
          <div v-else class="chips">
            <button v-if="meta.me.all_branches" type="button" class="ch" :class="{ on: !f.branch_ids.length }" :disabled="!editable" @click="toggleBranch(null)"><span class="ck">{{ !f.branch_ids.length ? '✓' : '+' }}</span>Barcha filiallar</button>
            <button v-for="b in meta.branches" :key="b.id" type="button" class="ch" :class="{ on: f.branch_ids.includes(b.id) }" :disabled="!editable" @click="toggleBranch(b.id)"><span class="ck">{{ f.branch_ids.includes(b.id) ? '✓' : '+' }}</span>{{ b.name }}</button>
          </div>
        </div>
        <div v-if="aiArea && meta.ai" class="blk row">
          <span><b>🤖 AI Kotib</b><small>Ertalabki hisobot, savol-javob, ovozli buyruq, 🌐 global qidiruv. {{ seatsText }}</small></span>
          <UiToggle :model-value="aiOn" :disabled="!editable || aiByRole || !meta.ai.enabled" @update:model-value="setAi" />
        </div>
        <div class="blk sum">
          <h4>👁 Bu xodim ko'radi:</h4>
          <div class="sees"><span v-for="x in sees" :key="x.t">{{ x.t }} <i>{{ x.l }}</i></span><span v-if="!sees.length" class="mu">hali hech narsa — lavozim tanlang</span></div>
        </div>
        <div class="blk">
          <button type="button" class="mh" :aria-expanded="showMatrix" @click="showMatrix = !showMatrix">
            <span><b>➕ Qo'shimcha ruxsat (ixtiyoriy)</b><small>Lavozimidan tashqari biror bo'lim kerak bo'lsa — masalan kassirga «Ombor — ko'radi»</small></span><span>{{ showMatrix ? '▾' : '▸' }}</span>
          </button>
          <AccessMatrix v-if="showMatrix" v-model="f.extra" :areas="meta.areas" :sections="meta.sections" :base="basePerms" :disabled="!editable" :skip="['ai']" />
        </div>
      </div>

      <!-- 2) KIRISH VA XAVFSIZLIK -->
      <div v-else-if="p" class="pane">
        <section class="card">
          <header><span class="ic tg">✈️</span><div><span class="tt"><b>Telegram orqali kirish</b><UiChip tone="ok">tavsiya etiladi</UiChip></span><small>Saytda telefon raqam → «Telegram orqali kirish» → botda «✅ Ha». Parol kerak emas, vazifa va hisobotlar ham botga keladi.</small></div></header>
          <template v-if="p.telegram_linked">
            <p class="okl">✅ Botga ulangan.</p>
            <div class="acts"><UiButton v-if="p.editable" size="s" variant="ghost" @click="unlinkTg">Telegram'ni uzish</UiButton></div>
          </template>
          <template v-else>
            <ol class="steps">
              <li><b>Taklif havolasini</b> xodimga yuboring (Telegram yoki SMS orqali).</li>
              <li>Xodim havolani bosadi → bot ochiladi → <b>Start</b>. Bot uni o'zi taniydi — telefon ulashish shart emas.</li>
            </ol>
            <div v-if="inv?.link" class="inv">
              <code>{{ inv.link }}</code>
              <div class="acts">
                <UiButton size="s" @click="copy(inv.link)">📋 Nusxalash</UiButton>
                <a class="tgbtn" :href="shareUrl" target="_blank" rel="noopener">✈️ Telegram'da yuborish</a>
              </div>
              <small class="mu">{{ dt(inv.expires) }} gacha amal qiladi · bir marta ishlatiladi</small>
            </div>
            <UiButton v-else-if="p.editable" variant="brand" @click="makeInvite()">🔗 Taklif havolasini yaratish</UiButton>
            <p v-if="!p.login?.bot" class="warn sm">Telegram bot ulanmagan — «Telegram bot» sahifasida tokenni kiriting. Unda xodim botga /start bosib telefonini ulashadi.</p>
          </template>
        </section>

        <section class="card">
          <header><span class="ic">🔑</span><div><b>Parol bilan kirish</b><small>Telegram'i yo'q xodimlar uchun. Parol faqat bir marta ko'rsatiladi.</small></div></header>
          <AccessCard v-if="access" :a="access" />
          <template v-else-if="p.editable">
            <p class="sm">{{ p.has_password ? '🔑 Parol o\'rnatilgan.' : 'Parol yo\'q — xodim faqat Telegram orqali kiradi.' }}</p>
            <div v-if="pwMode" class="pwf">
              <UiInput v-model="pwVal" label="Yangi parol (kamida 6 belgi)" type="text" autocomplete="off" :error="pwErr" @keyup.enter="setPw(false)" />
              <UiButton @click="setPw(false)">Saqlash</UiButton><UiButton variant="ghost" @click="pwMode = false">Bekor</UiButton>
            </div>
            <div v-else class="acts">
              <UiButton size="s" variant="brand" @click="setPw(true)">🎲 {{ p.has_password ? 'Yangi parol yaratish' : 'Parol yaratish' }}</UiButton>
              <UiButton size="s" variant="secondary" @click="pwMode = true; pwErr = ''">✏️ O'zim yozaman</UiButton>
              <UiButton v-if="p.has_password" size="s" variant="ghost" @click="pwOff">Parolni o'chirish</UiButton>
            </div>
          </template>
        </section>

        <section class="card">
          <header><span class="ic">🛡️</span><div><b>Xavfsizlik</b><small>Telefon yo'qolsa yoki xodim ishdan ketsa — shu yerdan.</small></div></header>
          <div v-if="p.editable" class="acts">
            <UiButton size="s" variant="secondary" :disabled="!p.is_active" @click="logoutAll">🚪 Hamma qurilmalardan chiqarish</UiButton>
            <UiButton v-if="p.is_active" size="s" variant="danger" @click="block(true)">⛔ Kirishni bloklash</UiButton>
            <UiButton v-else size="s" variant="brand" @click="block(false)">✅ Kirishni tiklash</UiButton>
          </div>
          <h5>Kirish tarixi</h5>
          <ul v-if="p.login?.history.length" class="hist">
            <li v-for="(h, i) in p.login.history" :key="i"><b>{{ dt(h.at) }}</b><span>{{ h.method_label }}</span><small>{{ h.device }}{{ h.ip ? ' · ' + h.ip : '' }}</small></li>
          </ul>
          <p v-else class="mu sm">Hali kirmagan.</p>
        </section>
      </div>
    </template>
    <template #footer>
      <template v-if="(tab === 'access' || !p) && editable">
        <span class="sp"></span>
        <UiButton :loading="busy" @click="save()">{{ p ? (p.is_active ? 'Saqlash' : 'Saqlash va tiklash') : 'Qo\'shish' }}</UiButton>
      </template>
      <template v-else><span class="sp"></span><UiButton variant="secondary" @click="emit('close')">Tayyor</UiButton></template>
    </template>
  </UiDrawer>
</template>

<style scoped>
.mu { color: var(--muted); margin: 0; } .sm { font-size: var(--fs-xs); margin: 6px 0 0; }
.hd { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding-bottom: 12px; border-bottom: 1px solid var(--line-2); }
.hi { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 200px; } .hi b { font-size: var(--fs-b); } .hi > span { color: var(--muted); font-size: var(--fs-s); }
.hi .chips { margin-top: 6px; } .last { color: var(--muted); font-size: var(--fs-xs); }
.okb { margin: 0; padding: 10px 12px; border-radius: 12px; background: var(--ok-tint); color: var(--ok); font-weight: 700; font-size: var(--fs-s); }
.warn { margin: 0; padding: 8px 12px; border-radius: 10px; background: var(--warn-tint); color: var(--warn-ink); font-size: var(--fs-s); font-weight: 700; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tabs button { flex: 1; min-width: 180px; border: 1px solid var(--line); background: var(--surface-2); border-radius: 12px; padding: 10px 12px; font: inherit; font-weight: 800; cursor: pointer; color: var(--ink-2); }
.tabs button.on { background: var(--ink); color: var(--surface); border-color: var(--ink); }
.pane { display: flex; flex-direction: column; gap: 12px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.blk { border-top: 1px solid var(--line-2); padding-top: 12px; } .blk h4 { margin: 0 0 8px; font-size: var(--fs-s); } .blk h4 small { color: var(--muted); font-weight: 600; }
.blk.row { display: flex; gap: 12px; align-items: center; justify-content: space-between; } .blk.row span { display: flex; flex-direction: column; } .blk.row small { color: var(--muted); font-size: var(--fs-xs); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.rg h5 { margin: 6px 0 6px; font-size: var(--fs-xs); color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.rcards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.rcard { position: relative; display: flex; flex-direction: column; gap: 3px; align-items: flex-start; text-align: left; padding: 12px 36px 12px 12px; border: 1.5px solid var(--line); border-radius: 14px; background: var(--surface); font: inherit; color: var(--ink); cursor: pointer; min-height: 74px; }
.rcard:hover:not(:disabled) { border-color: var(--accent); }
.rcard.on { border-color: var(--accent); background: var(--accent-tint); }
.rcard:disabled { opacity: .45; cursor: not-allowed; }
.rcard small { color: var(--ink-2); font-size: var(--fs-xs); line-height: 1.35; } .rcard em { font-style: normal; color: var(--muted); font-size: 11px; line-height: 1.35; }
.rcard .ck { position: absolute; top: 10px; right: 10px; width: 20px; height: 20px; border-radius: 50%; border: 1.5px solid var(--line); display: grid; place-items: center; font-size: 12px; background: var(--surface); }
.rcard.on .ck { background: var(--accent); border-color: var(--accent); color: #fff; }
.sum { background: var(--surface-2); border-radius: 12px; padding: 12px; border-top: 0; }
.sees { display: flex; flex-wrap: wrap; gap: 6px; } .sees span { font-size: var(--fs-xs); font-weight: 700; padding: 4px 10px; border-radius: 99px; background: var(--surface); border: 1px solid var(--line); }
.sees i { font-style: normal; color: var(--muted); font-weight: 600; }
.ch { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 7px 12px; min-height: 38px; font: inherit; font-size: var(--fs-s); font-weight: 700; cursor: pointer; color: var(--ink-2); }
.ch.on { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); } .ch:disabled { opacity: .5; cursor: not-allowed; }
.ck { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; background: var(--surface-3); } .ch.on .ck { background: var(--accent); color: #fff; }
.mh { display: flex; width: 100%; justify-content: space-between; align-items: center; gap: 10px; border: 0; background: none; padding: 0 0 8px; font: inherit; color: var(--ink); cursor: pointer; text-align: left; }
.mh span:first-child { display: flex; flex-direction: column; } .mh small { color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
.card { border: 1px solid var(--line); border-radius: 14px; padding: 14px; display: flex; flex-direction: column; gap: 10px; background: var(--surface); }
.card header { display: flex; gap: 12px; align-items: flex-start; } .card header div { display: flex; flex-direction: column; gap: 2px; } .card header small { color: var(--muted); font-size: var(--fs-xs); }
.tt { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tabs .sh { display: none; }
.ic { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; background: var(--surface-2); font-size: 18px; flex-shrink: 0; } .ic.tg { background: color-mix(in srgb, #229ED9 16%, transparent); }
.okl { margin: 0; color: var(--ok); font-weight: 700; font-size: var(--fs-s); }
.steps { margin: 0; padding-left: 20px; font-size: var(--fs-s); display: flex; flex-direction: column; gap: 4px; }
.inv { display: flex; flex-direction: column; gap: 8px; padding: 10px; border-radius: 12px; background: var(--surface-2); }
.inv code { font-size: var(--fs-s); word-break: break-all; user-select: all; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.tgbtn { display: inline-flex; align-items: center; min-height: 34px; padding: 0 12px; border-radius: 10px; background: #229ED9; color: #fff; font-weight: 800; font-size: var(--fs-s); text-decoration: none; }
.pwf { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; } .pwf > :first-child { flex: 1; min-width: 200px; }
h5 { margin: 4px 0 0; font-size: var(--fs-s); }
.hist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.hist li { display: grid; grid-template-columns: 150px 150px minmax(0, 1fr); gap: 8px; padding: 7px 0; border-top: 1px solid var(--line-2); font-size: var(--fs-s); align-items: center; }
.hist small { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp { flex: 1; }
@media (max-width: 640px) { .tabs .lg { display: none; } .tabs .sh { display: inline; } .two { grid-template-columns: 1fr; } .hist li { grid-template-columns: 1fr; gap: 0; } .tabs button { min-width: 0; } }
</style>
