<script setup lang="ts">
/**
 * Panel qobig'i. Menyu ikki bosqichli:
 *   1) Asosiy menyu — «Asosiy sahifa» va bo'limlar (Savdo, Menyu va mijozlar, Ombor va xarid, Xodimlar, …);
 *   2) bo'limga kirilganda — faqat shu bo'lim modullari, pastida «Asosiy sahifaga qaytish».
 * Telefon: pastki tab-bar + drawer; planshet: ikonkali tor menyu; kompyuter: to'liq.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { UiAvatar, UiIcon } from '@restopos/ui'
import { t } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import { HOME, matches, useNav } from '@/nav/sections'
import AccountSwitcher from '@/components/shell/AccountSwitcher.vue'
import AiChat from '@/components/ai/AiChat.vue'

const a = useAuth(), ui = useUi(), route = useRoute(), router = useRouter()
const { items, sections, current, currentItem, sectionLink } = useNav()
/** Platforma yordami rejimi — egasi bergan ruxsat bilan kirilgan; tepada ogohlantirish */
const supportMode = computed(() => (a.me?.roles ?? []).includes('platform_support'))

/** Menyuda qaysi daraja ko'rinadi: odatda joriy sahifa bo'limi; «Bo'limlar» tugmasi bilan asosiy menyuni ko'rish mumkin */
const browse = ref<string | null | undefined>(undefined)     // undefined — sahifaga qarab; '' — asosiy menyu; kod — shu bo'lim
watch(() => route.fullPath, () => { browse.value = undefined })
const shown = computed(() => (browse.value === undefined ? current.value : browse.value ? sections.value.find(s => s.code === browse.value) ?? null : null))

/** Bosh sahifa: rahbarlar — boshqaruv paneli, xodimlar — «Mening sahifam» */
const home = computed(() => a.me?.home || '/')
const homeLabel = computed(() => (home.value === '/' ? 'Boshqaruv paneli' : 'Mening sahifam'))
function goHome() { ui.sidebarOpen = false; browse.value = undefined; router.push(home.value) }
function openRoot() { browse.value = ''; ui.sidebarOpen = true }
const close = () => { ui.sidebarOpen = false }

// telefon pastki paneli: Asosiy + eng ko'p ishlatiladigan 3 ta modul + «Bo'limlar»
const PIN = ['/pos', '/tasks', '/training', '/market', '/projects', '/inventory', '/hr', '/reports']   // Kassa · Vazifalar · O'qitish (rolga qarab)
const phoneNav = computed(() => PIN.map(r => items.value.find(i => i.route === r)).filter(Boolean).slice(0, 3) as typeof items.value)
const title = computed(() => {
  if (route.path.startsWith('/s/') && current.value) return current.value.title
  const it = currentItem.value ?? items.value.find(i => matches(i.route, route.path))
  return it ? t(it.label, ui.lang) : ((route.meta.title as string) ?? (route.path === '/' ? 'Boshqaruv paneli' : ''))
})
/** AI Kotib chati — rahbar/menejer (ai.use) uchun o'ng pastki burchakda; kassa va oshxona ekranida yashirin */
const showAi = computed(() => a.hasModule('ai') && a.can('ai.use') && !['/pos', '/kds'].some(r => route.path.startsWith(r)))
const trialDays = computed(() => { const d = a.me?.tenant.trial_ends_at; if (!d) return null; return Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000)) })
</script>
<template>
  <div class="shell">
    <aside class="side" :class="{ open: ui.sidebarOpen }">
      <AccountSwitcher />
      <!-- 1-daraja: asosiy menyu -->
      <nav v-if="!shown" class="nav">
        <RouterLink :to="home" class="item" :class="{ on: route.path === home }" @click="close"><UiIcon :name="HOME.icon" /><span class="lbl">{{ homeLabel }}</span></RouterLink>
        <div class="grp">Bo'limlar</div>
        <RouterLink v-for="s in sections" :key="s.code" :to="sectionLink(s)" class="item sec" :style="{ '--sc': s.color }" :title="s.title" @click="s.items.length === 1 && close()">
          <span class="si"><UiIcon :name="s.icon" :size="18" /></span><span class="lbl">{{ s.title }}</span>
          <UiIcon v-if="s.items.length > 1" name="chevron" :size="14" class="chev" />
        </RouterLink>
      </nav>
      <!-- 2-daraja: bo'lim ichi -->
      <nav v-else class="nav in" :style="{ '--sc': shown.color }">
        <RouterLink :to="`/s/${shown.code}`" class="sh" :title="shown.title" @click="close"><span class="si"><UiIcon :name="shown.icon" :size="18" /></span><span class="lbl"><small>Bo'lim</small>{{ shown.title }}</span></RouterLink>
        <RouterLink v-for="n in shown.items" :key="n.route" :to="n.route" class="item" :class="{ on: matches(n.route, route.path) }" :title="t(n.label, ui.lang)" @click="close">
          <UiIcon :name="n.icon" /><span class="lbl">{{ t(n.label, ui.lang) }}</span>
        </RouterLink>
        <div class="navsp"></div>
        <RouterLink v-if="route.path !== `/s/${shown.code}`" :to="`/s/${shown.code}`" class="item sback" :title="`${shown.title} — bo'lim paneli`" @click="close">
          <UiIcon name="chart" /><span class="lbl">Bosh bo'limga qaytish</span></RouterLink>
        <button type="button" class="item back" title="Asosiy sahifaga qaytish" @click="goHome"><UiIcon name="home" /><span class="lbl">Asosiy sahifaga qaytish</span></button>
      </nav>
      <div class="foot">
        <a class="item ponly" href="/" target="_blank" rel="noopener"><UiIcon name="globe" /><span class="lbl">Saytni ochish</span></a>
        <a class="item ponly" href="/tv/menu-board/" target="_blank" rel="noopener"><UiIcon name="tv" /><span class="lbl">TV menyu</span></a>
        <div v-if="trialDays" class="trial">Sinov: <b>{{ trialDays }} kun</b></div>
        <button class="item" type="button" @click="ui.cycleTheme()"><UiIcon :name="ui.theme === 'dark' ? 'moon' : 'sun'" /><span class="lbl">{{ ui.theme === 'auto' ? 'Tema: avto' : ui.theme === 'dark' ? 'Tema: dark' : 'Tema: light' }}</span></button>
        <button class="item" type="button" @click="a.logout()"><UiIcon name="logout" /><span class="lbl">Chiqish</span></button>
      </div>
    </aside>
    <div v-if="ui.sidebarOpen" class="scrim" @click="ui.sidebarOpen = false"></div>

    <div class="main">
      <header class="top">
        <button class="burger" type="button" aria-label="Menyu" @click="ui.sidebarOpen = !ui.sidebarOpen"><UiIcon name="menu" /></button>
        <div class="ttl">
          <RouterLink v-if="current && !route.path.startsWith('/s/') && current.items.length > 1" :to="`/s/${current.code}`" class="crumb">{{ current.title }} ›</RouterLink>
          <h1>{{ title }}</h1>
        </div>
        <div class="sp"></div>
        <AccountSwitcher variant="chip" />
        <a class="link" :href="`/`" target="_blank" rel="noopener"><UiIcon name="globe" /><span class="hp">Sayt</span></a>
        <a class="link" :href="`/tv/menu-board/`" target="_blank" rel="noopener"><UiIcon name="tv" /><span class="hp">TV</span></a>
        <RouterLink to="/settings" class="me" :title="`${a.me?.full_name ?? ''} · ${a.me?.phone ?? ''} — profil`"><UiAvatar :name="a.me?.full_name || a.me?.phone" :src="a.me?.avatar" :size="36" /></RouterLink>
      </header>
      <div v-if="supportMode" class="sup">🛟 Platforma yordami rejimi — egasi bergan ruxsat bilan. Barcha harakatlar «O'zgarishlar tarixi»ga yoziladi. <button type="button" @click="a.logout()">Chiqish</button></div>
      <main class="content"><RouterView /></main>
      <AiChat v-if="showAi" />
      <nav class="tabbar">
        <RouterLink :to="home" class="tab" :class="{ on: route.path === home }"><UiIcon name="home" :size="22" /><span>{{ home === '/' ? 'Panel' : 'Men' }}</span></RouterLink>
        <RouterLink v-for="n in phoneNav" :key="n.route" :to="n.route" class="tab" :class="{ on: matches(n.route, route.path) }"><UiIcon :name="n.icon" :size="22" /><span>{{ t(n.label, ui.lang).split(' ')[0] }}</span></RouterLink>
        <button class="tab" type="button" @click="openRoot()"><UiIcon name="menu" :size="22" /><span>Bo'limlar</span></button>
      </nav>
    </div>
  </div>
</template>
<style scoped>
.sup { background: #1D4ED8; color: #fff; padding: 8px 16px; font-size: var(--fs-s); font-weight: 700; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sup button { border: 1px solid rgba(255,255,255,.6); background: transparent; color: #fff; border-radius: 8px; padding: 4px 10px; font: inherit; cursor: pointer; }
.shell { display: flex; min-height: 100vh; min-height: 100dvh; }
.side { width: var(--sidebar-w); flex-shrink: 0; background: var(--surface); border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 16px 12px; gap: 4px; position: sticky; top: 0; height: 100vh; height: 100dvh; overflow-y: auto; overscroll-behavior: contain; }
.nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.grp { font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); padding: 14px 12px 4px; }
.si { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 14%, transparent); color: var(--sc); }
.sec .cnt { margin-left: auto; font-size: 11px; font-weight: 800; color: var(--muted); background: var(--surface-2); border-radius: 99px; padding: 1px 7px; }
.sec .chev { transform: rotate(-90deg); color: var(--muted); flex-shrink: 0; margin-left: auto; }
.sh { display: flex; align-items: center; gap: 10px; padding: 10px 12px; margin-bottom: 6px; border-radius: var(--radius); text-decoration: none; color: var(--ink);
  background: color-mix(in srgb, var(--sc) 10%, var(--surface)); border: 1px solid color-mix(in srgb, var(--sc) 30%, transparent); }
.sh .lbl { display: flex; flex-direction: column; font-weight: 800; font-size: var(--fs-b); } .sh small { font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.in .item.on { background: color-mix(in srgb, var(--sc) 14%, var(--surface)); color: var(--sc); }
.navsp { flex: 1; min-height: 12px; }
.item.sback { color: var(--sc); font-weight: 700; background: color-mix(in srgb, var(--sc) 8%, transparent); }
.item.back { border: 1px dashed var(--line); color: var(--ink); font-weight: 700; }
.item.back:hover { border-color: var(--accent); color: var(--accent); }
.ttl { display: flex; flex-direction: column; min-width: 0; }
.crumb { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); text-decoration: none; line-height: 1.1; margin-top: 4px; }
.crumb:hover { color: var(--accent); }
.item { display: flex; align-items: center; gap: 10px; min-height: var(--touch); padding: 0 12px; border-radius: var(--radius); color: var(--ink-2); text-decoration: none; font-weight: 600; font-size: var(--fs-b); border: 0; background: transparent; cursor: pointer; text-align: left; flex-shrink: 0; }
.item .lbl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.ponly { display: none; }
.item:hover { background: var(--surface-3); }
.item.on { background: var(--accent-tint); color: var(--accent); font-weight: 700; }
.foot { display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--line-2); padding-top: 8px; margin-top: 8px; }
.trial { font-size: var(--fs-xs); color: var(--muted); padding: 8px 12px; border-radius: var(--radius); background: var(--surface-2); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.top { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 10px; min-height: var(--topbar-h); padding: 0 var(--gutter); background: var(--surface); border-bottom: 1px solid var(--line); }
.top h1 { margin: 0; font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp { flex: 1; }
.link { display: inline-flex; align-items: center; gap: 6px; min-height: var(--touch); padding: 0 10px; border-radius: var(--radius); border: 1px solid var(--line); color: var(--ink-2); text-decoration: none; font-size: var(--fs-s); font-weight: 700; }
.me { display: inline-flex; border-radius: 12px; text-decoration: none; }
.me:hover { box-shadow: 0 0 0 3px var(--accent-tint); }
.burger { display: none; width: var(--touch); height: var(--touch); border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
.content { padding: var(--gutter); display: flex; flex-direction: column; gap: 16px; }
.tabbar { display: none; }
.scrim { display: none; }
/* planshet: tor ikonkali menyu */
@media (min-width: 601px) and (max-width: 1024px) { .side { padding: 12px 8px; } .lbl, .sh .lbl, .trial, .grp, .cnt, .chev, .crumb { display: none; } .sh { border: 0; background: transparent; } .item, .sh { justify-content: center; padding: 0; } .sh { min-height: var(--touch); } }
/* telefon: drawer + tab-bar */
@media (max-width: 600px) {
  .side { position: fixed; left: 0; top: 0; bottom: 0; z-index: 40; width: min(300px, 86vw); height: auto; transform: translateX(-100%); transition: transform .2s, visibility .2s; box-shadow: var(--shadow); padding-bottom: calc(16px + env(safe-area-inset-bottom)); visibility: hidden; }
  .side.open { visibility: visible; }
  .side.open { transform: none; }
  .scrim { display: block; position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 30; }
  .burger { display: grid; place-items: center; }
  .content { padding-bottom: calc(var(--gutter) + 88px + env(safe-area-inset-bottom)); }
  .hp, .top .link { display: none; }
  .ponly { display: flex; }
  .top h1 { font-size: var(--fs-l); } .crumb { display: none; }
  .tabbar { display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; background: var(--surface); border-top: 1px solid var(--line); padding: 6px 4px calc(6px + env(safe-area-inset-bottom)); }
  .tab { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 2px; font-size: 10px; font-weight: 700; color: var(--muted); text-decoration: none; border: 0; background: transparent; }
  .tab.on { color: var(--accent); }
}
</style>
