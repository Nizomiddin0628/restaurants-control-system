<script setup lang="ts">
/** HQ qobig'i: to'q rangli yon menyu (telefonda — ochiladigan), tepada qidiruv va xodim. */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiIcon } from '@restopos/ui'
import { useHq } from './store'

const s = useHq(), route = useRoute(), router = useRouter()
const open = ref(false)
const q = ref('')
const NAV = [
  { to: '/', label: 'Bosh sahifa', icon: 'home' },
  { to: '/tenants', label: 'Mijozlar', icon: 'store' },
  { to: '/billing', label: 'Billing', icon: 'receipt' },
  { to: '/tickets', label: 'Vazifalar doskasi', icon: 'columns', badge: true },
  { to: '/site', label: 'Sayt va narxlar', icon: 'globe' },
  { to: '/health', label: 'Tizim holati', icon: 'pulse' },
  { to: '/system', label: 'Funksiyalar va jamoa', icon: 'flag' },
]
const title = computed(() => (route.meta.title as string) ?? '')
const active = (to: string) => to === '/' ? route.path === '/' : route.path.startsWith(to)
onMounted(async () => { try { const t = await api.get('/hq/tickets', { status: 'open' }); s.openTickets = t.counts.open } catch { /* jim */ } })
watch(() => route.fullPath, () => { open.value = false })
function search() { if (q.value.trim()) router.push({ path: '/tenants', query: { q: q.value.trim() } }) }
</script>

<template>
  <div class="hq" :class="{ open }">
    <aside class="side">
      <div class="brand"><span class="lg">R</span><div><b>{{ s.me?.platform?.toUpperCase() }} HQ</b><small>Platforma boshqaruvi</small></div></div>
      <nav>
        <RouterLink v-for="n in NAV" :key="n.to" :to="n.to" class="ni" :class="{ on: active(n.to) }">
          <UiIcon :name="n.icon" :size="18" /><span>{{ n.label }}</span><i v-if="n.badge && s.openTickets">{{ s.openTickets }}</i>
        </RouterLink>
      </nav>
      <div class="me">
        <UiAvatar :name="s.me?.name" :size="34" />
        <div><b>{{ s.me?.name }}</b><small>{{ s.me?.role_label }}</small></div>
        <button type="button" aria-label="Chiqish" title="Chiqish" @click="s.logout()"><UiIcon name="logout" :size="16" /></button>
      </div>
    </aside>
    <div class="scrim" @click="open = false"></div>
    <main>
      <header class="top">
        <button type="button" class="burger" aria-label="Menyu" @click="open = true"><UiIcon name="menu" :size="20" /></button>
        <h1>{{ title }}</h1>
        <form class="srch" role="search" @submit.prevent="search()"><UiIcon name="search" :size="16" /><input v-model="q" placeholder="Restoran qidirish…" aria-label="Restoran qidirish" /></form>
      </header>
      <div class="page"><RouterView /></div>
    </main>
  </div>
</template>

<style scoped>
.hq { --side: #0E1726; --side-2: #16223A; --side-ink: #C8D2E3; display: grid; grid-template-columns: 250px minmax(0, 1fr); min-height: 100vh; background: var(--bg); }
.side { background: var(--side); color: var(--side-ink); display: flex; flex-direction: column; padding: 16px 12px; position: sticky; top: 0; height: 100vh; }
.brand { display: flex; gap: 10px; align-items: center; padding: 4px 8px 18px; }
.lg { width: 38px; height: 38px; border-radius: 10px; background: linear-gradient(135deg, #3B82F6, #1D4ED8); color: #fff; display: grid; place-items: center; font-weight: 900; font-size: 20px; }
.brand b { color: #fff; font-family: var(--font-display); letter-spacing: .02em; display: block; } .brand small { font-size: 11px; opacity: .7; }
nav { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.ni { display: flex; align-items: center; gap: 12px; padding: 11px 12px; border-radius: 10px; color: var(--side-ink); text-decoration: none; font-weight: 600; font-size: var(--fs-s); }
.ni:hover { background: var(--side-2); color: #fff; } .ni.on { background: #2563EB; color: #fff; }
.ni span { flex: 1; } .ni i { font-style: normal; font-size: 11px; font-weight: 800; background: #EF4444; color: #fff; border-radius: 99px; padding: 1px 7px; }
.me { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 12px; background: var(--side-2); }
.me div { flex: 1; min-width: 0; display: flex; flex-direction: column; } .me b { color: #fff; font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .me small { font-size: 11px; opacity: .7; }
.me button { border: 0; background: transparent; color: var(--side-ink); cursor: pointer; }
main { min-width: 0; display: flex; flex-direction: column; }
.top { display: flex; align-items: center; gap: 14px; padding: 14px 24px; background: var(--surface); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5; }
.top h1 { margin: 0; flex: 1; font-family: var(--font-display); font-size: var(--fs-xl); }
.burger { display: none; border: 1px solid var(--line); background: var(--surface); border-radius: 10px; width: 40px; height: 40px; place-items: center; cursor: pointer; }
.srch { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; min-height: 40px; width: 280px; background: var(--surface-2); color: var(--muted); }
.srch input { border: 0; background: transparent; font: inherit; flex: 1; min-width: 0; color: var(--ink); outline: none; }
.page { padding: 20px 24px 40px; }
.scrim { display: none; }
@media (max-width: 1000px) {
  .hq { grid-template-columns: minmax(0, 1fr); }
  .side { position: fixed; z-index: 40; left: 0; top: 0; width: 270px; transform: translateX(-100%); transition: transform .2s, visibility .2s; visibility: hidden; }
  .hq.open .side { transform: none; visibility: visible; } .hq.open .scrim { display: block; position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 30; }
  .burger { display: grid; } .top { padding: 10px 16px; } .page { padding: 16px 16px 40px; }
  .srch { width: auto; flex: 0 1 200px; }
}
@media (max-width: 560px) { .srch { display: none; } }
</style>
