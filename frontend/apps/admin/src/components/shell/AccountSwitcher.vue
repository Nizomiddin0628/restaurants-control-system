<script setup lang="ts">
/**
 * Restoran va filial almashtirgich (Telegram akkauntlari kabi).
 * Restoran nomini bosing → ro'yxat:
 *   • Filiallar — «Barcha filiallar» yoki bittasi: butun panel (asosiy sahifa, bo'lim panellari) shu filial bo'yicha ko'rsatiladi;
 *   • Restoranlarim — shu telefon raqami a'zo bo'lgan boshqa restoranlar: bir bosishda, kod so'ramasdan o'tiladi.
 * variant="brand" — chap menyu tepasi; variant="chip" — yuqori paneldagi kichik tugma (telefonda qulay).
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiIcon, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const props = withDefaults(defineProps<{ variant?: 'brand' | 'chip' }>(), { variant: 'brand' })
const a = useAuth(), ui = useUi(), router = useRouter()

type Rest = { slug: string; name: string; current: boolean; url: string | null }
const rests = ref<Rest[] | null>(null)
const open = ref(false)
const going = ref('')
const btn = ref<HTMLElement | null>(null)
const pos = ref<Record<string, string>>({})

const branches = computed(() => a.me?.branches ?? [])
const multi = computed(() => branches.value.length > 1)
const cur = computed(() => branches.value.find(b => String(b.id) === ui.branch))
const role = computed(() => a.me?.roles.includes('owner') ? 'Egasi' : (a.me?.role_names?.length ? a.me.role_names : a.me?.roles ?? []).join(', '))
const sub = computed(() => multi.value ? (cur.value ? cur.value.name : `Barcha filiallar · ${branches.value.length}`) : role.value)
const canAdd = computed(() => a.can('core.branches.manage'))

// tanlangan filial o'chirilgan / ruxsat yo'q bo'lsa — «Barcha filiallar»
watch(branches, (bs) => { if (ui.branch && !bs.some(b => String(b.id) === ui.branch)) ui.setBranch(null) }, { immediate: true })

async function toggle() {
  if (open.value) { open.value = false; return }
  const r = btn.value?.getBoundingClientRect()
  if (r) {
    const narrow = window.innerWidth > 600 && window.innerWidth <= 1024 && props.variant === 'brand'
    const w = Math.min(300, window.innerWidth - 16)
    const left = narrow ? r.right + 8 : Math.max(8, Math.min(r.left, window.innerWidth - w - 8))
    pos.value = { top: `${narrow ? r.top : r.bottom + 6}px`, left: `${left}px`, width: `${w}px` }
  }
  open.value = true
  await nextTick()
  if (rests.value === null) rests.value = await api.get<Rest[]>('/me/restaurants').catch(() => [])
}
function pick(id: number | null) {
  ui.setBranch(id)
  open.value = false
  toast(id ? `Filial: ${cur.value?.name}` : 'Barcha filiallar')
}
async function go(r: Rest) {
  if (r.current) { open.value = false; return }
  going.value = r.slug
  try { const x = await api.post<{ url: string }>('/me/switch', { slug: r.slug }); location.href = x.url }
  catch (e: any) { toast(e?.detail ?? "O'tib bo'lmadi", 'danger'); going.value = '' }
}
function addBranch() { open.value = false; ui.sidebarOpen = false; router.push('/branches') }
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') open.value = false }
watch(open, (v) => (v ? window.addEventListener('keydown', onKey) : window.removeEventListener('keydown', onKey)))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
const initial = (s?: string) => (s ?? 'R').trim().slice(0, 1).toUpperCase()
</script>

<template>
  <button v-if="variant === 'brand'" ref="btn" type="button" class="brand" :class="{ on: open }" :aria-expanded="open" aria-haspopup="menu" title="Restoran va filialni almashtirish" @click="toggle">
    <span class="logo">{{ initial(a.me?.tenant.name) }}</span>
    <span class="bt"><b>{{ a.me?.tenant.name }}</b><span>{{ multi && cur ? '📍 ' : '' }}{{ sub }}</span></span>
    <UiIcon name="chevron" :size="16" class="cv" />
  </button>
  <button v-else-if="multi" ref="btn" type="button" class="chip" :class="{ on: open, sel: !!cur }" :aria-expanded="open" aria-haspopup="menu" title="Filialni almashtirish" @click="toggle">
    <UiIcon name="store" :size="16" /><span class="cf">{{ cur ? cur.name : 'Barcha filiallar' }}</span><span class="cs">{{ cur ? cur.name.replace(/\s*filiali$/i, '') : 'Hammasi' }}</span><UiIcon name="chevron" :size="14" />
  </button>

  <Teleport to="body">
    <template v-if="open">
      <div class="sw-scrim" @click="open = false"></div>
      <div class="sw" role="menu" :style="pos">
        <div class="sw-h">
          <span class="logo big">{{ initial(a.me?.tenant.name) }}</span>
          <span class="bt"><b>{{ a.me?.tenant.name }}</b><span>{{ a.me?.full_name || a.me?.phone }} · {{ role }}</span></span>
        </div>

        <div class="sw-g">Filiallar</div>
        <button v-if="multi" type="button" class="sw-i" role="menuitemradio" :aria-checked="!ui.branch" @click="pick(null)">
          <span class="rd" :class="{ on: !ui.branch }"></span><span class="tx"><b>Barcha filiallar</b><small>{{ branches.length }} ta filial birga</small></span>
        </button>
        <button v-for="b in branches" :key="b.id" type="button" class="sw-i" role="menuitemradio" :aria-checked="String(b.id) === ui.branch || !multi" @click="multi ? pick(b.id) : (open = false)">
          <span class="rd" :class="{ on: String(b.id) === ui.branch || !multi }"></span><span class="tx"><b>{{ b.name }}</b><small v-if="b.address">{{ b.address }}</small></span>
        </button>
        <button v-if="canAdd" type="button" class="sw-i add" @click="addBranch"><span class="pl"><UiIcon name="plus" :size="16" /></span><span class="tx"><b>Filial qo'shish</b></span></button>

        <div class="sw-g">Restoranlarim</div>
        <div v-if="rests === null" class="sw-l">Yuklanmoqda…</div>
        <template v-else>
          <button v-for="r in rests" :key="r.slug" type="button" class="sw-i" role="menuitem" :disabled="!!going" @click="go(r)">
            <span class="logo sm" :class="{ cur: r.current }">{{ initial(r.name) }}</span>
            <span class="tx"><b>{{ r.name }}</b><small>{{ r.current ? 'hozir shu yerdasiz' : going === r.slug ? "o'tilmoqda…" : "bosing — shu restoranga o'tish" }}</small></span>
            <UiIcon v-if="r.current" name="check" :size="18" class="ck" />
          </button>
          <p v-if="rests.length <= 1" class="sw-n">Boshqa restoranda ham ishlasangiz (shu telefon raqami bilan), u shu yerda chiqadi.</p>
        </template>
      </div>
    </template>
  </Teleport>
</template>

<style scoped>
.brand { display: flex; align-items: center; gap: 10px; padding: 8px; margin: 0 0 10px; width: 100%; border: 1px solid transparent; border-radius: 12px; background: transparent; cursor: pointer; text-align: left; font: inherit; color: var(--ink); }
.brand:hover, .brand.on { background: var(--surface-2); border-color: var(--line); }
.logo { width: 34px; height: 34px; border-radius: 10px; background: var(--brand); color: var(--brand-ink); display: grid; place-items: center; font-family: var(--font-display); font-weight: 800; flex-shrink: 0; }
.logo.big { width: 42px; height: 42px; font-size: 18px; border-radius: 12px; }
.logo.sm { width: 30px; height: 30px; border-radius: 9px; background: var(--surface-3); color: var(--ink-2); }
.logo.sm.cur { background: var(--brand); color: var(--brand-ink); }
.bt { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.bt b { font-size: var(--fs-b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bt span { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cv { color: var(--muted); flex-shrink: 0; transition: transform .15s; }
.brand.on .cv { transform: rotate(180deg); }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; max-width: 220px; padding: 0 10px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); font: inherit; font-size: var(--fs-s); font-weight: 700; cursor: pointer; }
.chip span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chip.sel { border-color: var(--accent); color: var(--accent); background: var(--accent-tint); }
.chip:hover { border-color: var(--accent); }
.sw-scrim { position: fixed; inset: 0; z-index: 60; }
.sw { position: fixed; z-index: 61; max-height: calc(100vh - 24px); overflow-y: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 18px 50px rgba(0, 0, 0, .18); padding: 8px; display: flex; flex-direction: column; gap: 2px; }
.sw-h { display: flex; gap: 10px; align-items: center; padding: 8px 8px 12px; border-bottom: 1px solid var(--line-2); margin-bottom: 4px; }
.sw-g { font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); padding: 10px 10px 4px; }
.sw-i { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 48px; padding: 6px 10px; border: 0; border-radius: 10px; background: transparent; font: inherit; color: var(--ink); cursor: pointer; text-align: left; }
.sw-i:hover:not(:disabled) { background: var(--surface-2); }
.sw-i:disabled { opacity: .6; cursor: wait; }
.tx { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.tx b { font-size: var(--fs-b); font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tx small { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rd { width: 20px; height: 20px; border-radius: 50%; border: 2px solid var(--line); flex-shrink: 0; margin: 0 5px; position: relative; }
.rd.on { border-color: var(--accent); }
.rd.on::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: var(--accent); }
.pl { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: var(--accent-tint); color: var(--accent); flex-shrink: 0; }
.add b { color: var(--accent); }
.ck { color: var(--accent); flex-shrink: 0; }
.sw-l, .sw-n { font-size: var(--fs-xs); color: var(--muted); padding: 6px 10px 8px; margin: 0; }
@media (min-width: 601px) and (max-width: 1024px) { .brand .bt, .brand .cv { display: none; } .brand { justify-content: center; padding: 6px 0; } }
.chip .cs { display: none; }
@media (max-width: 600px) { .chip { max-width: 124px; padding: 0 8px; gap: 4px; } .chip .cf { display: none; } .chip .cs { display: inline; } }
</style>
