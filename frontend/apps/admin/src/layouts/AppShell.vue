<script setup lang="ts">
/**
 * Panel qobig'i: yon menyu modul registridan (me.nav), rol bo'yicha.
 * Telefon: pastki tab-bar + drawer; planshet: ikonkali tor menyu; kompyuter: to'liq; TV: katta zichlik.
 */
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { UiIcon } from '@restopos/ui'
import { t } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi(), route = useRoute()
const core = [
  { route: '/', label: { uz: 'Boshqaruv paneli', ru: 'Панель', en: 'Dashboard' }, icon: 'home', order: 0 },
]
const tail = [
  { route: '/branches', label: { uz: 'Filiallar', ru: 'Филиалы', en: 'Branches' }, icon: 'store', order: 80, perm: 'core.branches.manage' },
  { route: '/users', label: { uz: 'Foydalanuvchilar', ru: 'Пользователи', en: 'Users' }, icon: 'users', order: 85, perm: 'core.users.manage' },
  { route: '/modules', label: { uz: 'Modullar', ru: 'Модули', en: 'Modules' }, icon: 'sliders', order: 95, perm: 'core.modules.manage' },
  { route: '/settings', label: { uz: 'Sozlamalar', ru: 'Настройки', en: 'Settings' }, icon: 'bars', order: 96, perm: 'core.settings.view' },
]
const nav = computed(() => [...core, ...(a.me?.nav ?? []), ...tail.filter(i => !i.perm || a.can(i.perm))].sort((x, y) => x.order - y.order))
// telefon pastki paneli: 4 ta band; «O'qitish» bo'lsa — doim ko'rinadi (xodim eng ko'p shu yerga kiradi)
const phoneNav = computed(() => {
  const pin = nav.value.filter(n => n.route === '/training')
  return [...nav.value.filter(n => n.route !== '/training').slice(0, 4 - pin.length), ...pin]
})
/** Ichki sahifalar ham (masalan /training/lesson/5) o'z bo'limini belgilaydi */
const isOn = (r: string) => (r === '/' ? route.path === '/' : route.path === r || route.path.startsWith(r + '/'))
const title = computed(() => t(nav.value.find(n => isOn(n.route))?.label ?? { uz: (route.meta.title as string) ?? '' }, ui.lang))
const trialDays = computed(() => { const d = a.me?.tenant.trial_ends_at; if (!d) return null; return Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000)) })
</script>
<template>
  <div class="shell">
    <aside class="side" :class="{ open: ui.sidebarOpen }">
      <div class="brand">
        <span class="logo">{{ (a.me?.tenant.name ?? 'R').slice(0, 1) }}</span>
        <div class="bt"><b>{{ a.me?.tenant.name }}</b><span>{{ a.me?.roles.includes('owner') ? 'Egasi · superadmin' : a.me?.roles.join(', ') }}</span></div>
      </div>
      <nav class="nav">
        <RouterLink v-for="n in nav" :key="n.route" :to="n.route" class="item" :class="{ on: isOn(n.route) }" @click="ui.sidebarOpen = false">
          <UiIcon :name="n.icon" /><span class="lbl" :title="t(n.label, ui.lang)">{{ t(n.label, ui.lang) }}</span>
        </RouterLink>
      </nav>
      <div class="foot">
        <a class="item ponly" href="/" target="_blank" rel="noopener"><UiIcon name="globe" /><span class="lbl">Saytni ochish</span></a>
        <a class="item ponly" href="/tv/menu-board/" target="_blank" rel="noopener"><UiIcon name="tv" /><span class="lbl">TV menyu</span></a>
        <div v-if="trialDays !== null" class="trial">Sinov: <b>{{ trialDays }} kun</b></div>
        <button class="item" type="button" @click="ui.cycleTheme()"><UiIcon :name="ui.theme === 'dark' ? 'moon' : 'sun'" /><span class="lbl">{{ ui.theme === 'auto' ? 'Tema: avto' : ui.theme === 'dark' ? 'Tema: dark' : 'Tema: light' }}</span></button>
        <button class="item" type="button" @click="a.logout()"><UiIcon name="logout" /><span class="lbl">Chiqish</span></button>
      </div>
    </aside>
    <div v-if="ui.sidebarOpen" class="scrim" @click="ui.sidebarOpen = false"></div>

    <div class="main">
      <header class="top">
        <button class="burger" type="button" aria-label="Menyu" @click="ui.sidebarOpen = !ui.sidebarOpen"><UiIcon name="menu" /></button>
        <h1>{{ title }}</h1>
        <div class="sp"></div>
        <a class="link" :href="`/`" target="_blank" rel="noopener"><UiIcon name="globe" /><span class="hp">Sayt</span></a>
        <a class="link" :href="`/tv/menu-board/`" target="_blank" rel="noopener"><UiIcon name="tv" /><span class="hp">TV</span></a>
        <span class="avatar" :title="a.me?.phone">{{ (a.me?.full_name || 'E').slice(0, 2).toUpperCase() }}</span>
      </header>
      <main class="content"><RouterView /></main>
      <nav class="tabbar">
        <RouterLink v-for="n in phoneNav" :key="n.route" :to="n.route" class="tab" :class="{ on: isOn(n.route) }"><UiIcon :name="n.icon" :size="22" /><span>{{ t(n.label, ui.lang).split(' ')[0] }}</span></RouterLink>
        <button class="tab" type="button" @click="ui.sidebarOpen = true"><UiIcon name="menu" :size="22" /><span>Yana</span></button>
      </nav>
    </div>
  </div>
</template>
<style scoped>
.shell { display: flex; min-height: 100vh; }
.side { width: var(--sidebar-w); flex-shrink: 0; background: var(--surface); border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 16px 12px; gap: 4px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
.brand { display: flex; align-items: center; gap: 10px; padding: 4px 8px 14px; }
.logo { width: 34px; height: 34px; border-radius: 10px; background: var(--brand); color: var(--brand-ink); display: grid; place-items: center; font-family: var(--font-display); font-weight: 800; flex-shrink: 0; }
.bt { display: flex; flex-direction: column; min-width: 0; } .bt b { font-size: var(--fs-b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .bt span { font-size: var(--fs-xs); color: var(--muted); }
.nav { display: flex; flex-direction: column; gap: 4px; }
.item { display: flex; align-items: center; gap: 10px; min-height: var(--touch); padding: 0 12px; border-radius: var(--radius); color: var(--ink-2); text-decoration: none; font-weight: 600; font-size: var(--fs-b); border: 0; background: transparent; cursor: pointer; text-align: left; flex-shrink: 0; }
.item .lbl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.ponly { display: none; }
.item:hover { background: var(--surface-3); }
.item.on { background: var(--accent-tint); color: var(--accent); font-weight: 700; }
.foot { margin-top: auto; display: flex; flex-direction: column; gap: 4px; }
.trial { font-size: var(--fs-xs); color: var(--muted); padding: 8px 12px; border-radius: var(--radius); background: var(--surface-2); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.top { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 10px; min-height: var(--topbar-h); padding: 0 var(--gutter); background: var(--surface); border-bottom: 1px solid var(--line); }
.top h1 { margin: 0; font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp { flex: 1; }
.link { display: inline-flex; align-items: center; gap: 6px; min-height: var(--touch); padding: 0 10px; border-radius: var(--radius); border: 1px solid var(--line); color: var(--ink-2); text-decoration: none; font-size: var(--fs-s); font-weight: 700; }
.avatar { width: 34px; height: 34px; border-radius: 10px; background: var(--accent); color: var(--accent-ink); display: grid; place-items: center; font-size: var(--fs-xs); font-weight: 800; }
.burger { display: none; width: var(--touch); height: var(--touch); border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
.content { padding: var(--gutter); display: flex; flex-direction: column; gap: 16px; }
.tabbar { display: none; }
.scrim { display: none; }
/* planshet: tor ikonkali menyu */
@media (min-width: 601px) and (max-width: 1024px) { .side { padding: 12px 8px; } .lbl, .bt, .trial { display: none; } .item { justify-content: center; padding: 0; } .brand { justify-content: center; padding-bottom: 10px; } }
/* telefon: drawer + tab-bar */
@media (max-width: 600px) {
  .side { position: fixed; left: 0; top: 0; z-index: 40; width: min(300px, 86vw); transform: translateX(-100%); transition: transform .2s; box-shadow: var(--shadow); }
  .side.open { transform: none; }
  .scrim { display: block; position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 30; }
  .burger { display: grid; place-items: center; }
  .content { padding-bottom: calc(var(--gutter) + 64px); }
  .hp, .top .link { display: none; }
  .ponly { display: flex; }
  .top h1 { font-size: var(--fs-l); }
  .tabbar { display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; background: var(--surface); border-top: 1px solid var(--line); padding: 6px 4px calc(6px + env(safe-area-inset-bottom)); }
  .tab { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 2px; font-size: 10px; font-weight: 700; color: var(--muted); text-decoration: none; border: 0; background: transparent; }
  .tab.on { color: var(--accent); }
}
</style>
