<script setup lang="ts">
/** Bo'lim sahifasi: shu bo'limdagi modullar katta kartalarda; pastida — asosiy sahifaga qaytish va boshqa bo'limlar. */
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { UiButton, UiEmpty, UiIcon, t } from '@restopos/ui'
import { useUi } from '@/stores/ui'
import { useNav } from '@/nav/sections'

const route = useRoute(), router = useRouter(), ui = useUi()
const { sections, sectionLink } = useNav()
const S = computed(() => sections.value.find(s => s.code === route.params.code))
const others = computed(() => sections.value.filter(s => s.code !== route.params.code))
</script>

<template>
  <div class="sv">
    <template v-if="S">
      <header class="hd" :style="{ '--sc': S.color }">
        <span class="em">{{ S.emoji }}</span>
        <div><h2>{{ S.title }}</h2><p>{{ S.desc }}</p></div>
      </header>
      <div class="grid">
        <RouterLink v-for="m in S.items" :key="m.route" :to="m.route" class="card" :style="{ '--sc': S.color }">
          <span class="ic"><UiIcon :name="m.icon" :size="24" /></span>
          <span class="tx"><b>{{ t(m.label, ui.lang) }}</b><small>{{ m.desc }}</small></span>
          <UiIcon name="chevron" :size="16" class="go" />
        </RouterLink>
      </div>
      <UiButton variant="ghost" class="home" @click="router.push('/')"><UiIcon name="home" :size="16" /> Asosiy sahifaga qaytish</UiButton>
      <div v-if="others.length" class="oth">
        <small>Boshqa bo'limlar</small>
        <div class="chips"><RouterLink v-for="o in others" :key="o.code" :to="sectionLink(o)" :style="{ '--sc': o.color }">{{ o.emoji }} {{ o.title }}</RouterLink></div>
      </div>
    </template>
    <UiEmpty v-else title="Bo'lim topilmadi" text="Bu bo'lim yoqilmagan yoki sizga ruxsat berilmagan.">
      <UiButton variant="brand" @click="router.push('/')">Asosiy sahifa</UiButton>
    </UiEmpty>
  </div>
</template>

<style scoped>
.sv { display: flex; flex-direction: column; gap: 18px; max-width: 1100px; }
.hd { display: flex; gap: 16px; align-items: center; padding: 18px 20px; border-radius: 18px; background: color-mix(in srgb, var(--sc) 9%, var(--surface)); border: 1px solid color-mix(in srgb, var(--sc) 25%, transparent); }
.em { width: 60px; height: 60px; border-radius: 16px; display: grid; place-items: center; font-size: 32px; background: var(--surface); flex-shrink: 0; }
h2 { margin: 0; font-family: var(--font-display); font-size: 24px; } p { margin: 4px 0 0; color: var(--ink-2); font-size: var(--fs-s); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.card { display: flex; align-items: center; gap: 14px; padding: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; text-decoration: none; color: var(--ink); min-height: 88px; transition: border-color .15s, transform .15s; }
.card:hover { border-color: var(--sc); transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0,0,0,.06); }
.ic { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 14%, transparent); color: var(--sc); }
.tx { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; } .tx b { font-size: var(--fs-m); } .tx small { color: var(--muted); font-size: var(--fs-s); line-height: 1.35; }
.go { transform: rotate(-90deg); color: var(--muted); flex-shrink: 0; }
.home { align-self: flex-start; }
.oth small { display: block; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips a { padding: 8px 12px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); text-decoration: none; font-size: var(--fs-s); font-weight: 700; }
.chips a:hover { border-color: var(--sc); color: var(--sc); }
@media (max-width: 640px) { .grid { grid-template-columns: minmax(0, 1fr); } .hd { padding: 14px; } .em { width: 48px; height: 48px; font-size: 26px; } h2 { font-size: 20px; } .home { align-self: stretch; } }
</style>
