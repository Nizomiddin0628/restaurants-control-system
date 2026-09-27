<script setup lang="ts">
/**
 * Xodimning bosh sahifasi (umumiy savdo raqamlarini ko'rmaydiganlar uchun): oddiy sayt kabi —
 * salom, bugungi smena (Keldim/Ketdim), mening vazifalarim va menga ochiq bo'limlar (katta tugmalar).
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiIcon, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import { DESC, useNav } from '@/nav/sections'

type Home = { tasks: { id: number; number: number; title: string; column: string; due_at: string | null; overdue: boolean }[]; tasks_open: number; tasks_overdue: number
  shift: { on: boolean; since: string | null; plan: string | null; can: boolean } | null }
const a = useAuth(), ui = useUi()
const { items } = useNav()
const h = ref<Home | null>(null), busy = ref(false)
const load = async () => { try { h.value = await api.get<Home>('/me/home') } catch { h.value = null } }
onMounted(load)
const first = computed(() => (a.me?.full_name || '').split(' ')[0] || 'xush kelibsiz')
const hello = computed(() => { const hr = new Date().getHours(); return hr < 11 ? 'Xayrli tong' : hr < 17 ? 'Xayrli kun' : 'Xayrli kech' })
const branch = computed(() => (a.me?.branch_all && (a.me?.branches ?? []).length > 1 ? 'barcha filiallar' : (a.me?.branches ?? []).map(b => b.name).join(', ')))
const tiles = computed(() => items.value.filter(i => i.route !== '/settings'))
const botUrl = computed(() => a.me?.bot_username ? `https://t.me/${a.me.bot_username}` : '')
async function shift(on: boolean) {
  busy.value = true
  try { await api.post(on ? '/hr/attendance/check-in' : '/hr/attendance/check-out'); toast(on ? 'Smena boshlandi' : 'Smena yopildi'); await load() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
const due = (d: string | null) => (d ? new Date(d).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')
</script>

<template>
  <div class="my">
    <section class="hi">
      <div>
        <h2>{{ hello }}, {{ first }}!</h2>
        <p>{{ (a.me?.role_names ?? []).join(' · ') }}<template v-if="branch"> — {{ branch }}</template></p>
      </div>
      <div v-if="h?.shift" class="sh" :class="{ on: h.shift.on }">
        <span><b>{{ h.shift.on ? `🟢 Smenadasiz (${h.shift.since} dan)` : '⚪ Smenada emassiz' }}</b><small v-if="h.shift.plan">Bugungi jadval: {{ h.shift.plan }}</small></span>
        <UiButton v-if="h.shift.can" :variant="h.shift.on ? 'secondary' : 'brand'" :loading="busy" @click="shift(!h.shift.on)">{{ h.shift.on ? '🏁 Ketdim' : '🕘 Keldim' }}</UiButton>
      </div>
    </section>

    <a v-if="!a.me?.telegram_linked && botUrl" class="tg" :href="botUrl" target="_blank" rel="noopener">
      <span class="ic">✈️</span>
      <span><b>Telegram botga ulaning</b><small>Botda /start → «📱 Telefonni ulashish». Keyin saytga parolsiz kirasiz, vazifalar Telegram'ga keladi.</small></span>
      <UiIcon name="chevron" :size="16" class="chev" />
    </a>

    <section v-if="h && h.tasks.length" class="card">
      <header><h3>📋 Mening vazifalarim <small>{{ h.tasks_open }} ta ochiq<template v-if="h.tasks_overdue"> · <em>{{ h.tasks_overdue }} ta kechikkan</em></template></small></h3>
        <RouterLink to="/tasks" class="all">Hammasi →</RouterLink></header>
      <RouterLink v-for="x in h.tasks" :key="x.id" :to="`/tasks?open=${x.id}`" class="task" :class="{ late: x.overdue }">
        <span class="n">#{{ x.number }}</span><span class="tt">{{ x.title }}</span><span class="cl">{{ x.column }}</span><span v-if="x.due_at" class="d">{{ due(x.due_at) }}</span>
      </RouterLink>
    </section>

    <section class="card">
      <header><h3>Mening bo'limlarim</h3></header>
      <div class="tiles">
        <RouterLink v-for="i in tiles" :key="i.route" :to="i.route" class="tile">
          <span class="ti"><UiIcon :name="i.icon" :size="22" /></span>
          <b>{{ t(i.label, ui.lang) }}</b><small>{{ DESC[i.route] ?? '' }}</small>
        </RouterLink>
        <RouterLink to="/settings" class="tile"><span class="ti"><UiIcon name="bars" :size="22" /></span><b>Profilim</b><small>Rasm, parol, til</small></RouterLink>
      </div>
      <p v-if="!tiles.length" class="muted">Sizga hali bo'lim ochilmagan — rahbaringizga ayting.</p>
    </section>
  </div>
</template>

<style scoped>
.my { display: flex; flex-direction: column; gap: 14px; max-width: 1200px; }
.hi { display: flex; gap: 14px; align-items: center; justify-content: space-between; flex-wrap: wrap; padding: 18px 20px; border-radius: var(--radius-l, 16px);
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 16%, var(--surface)), var(--surface)); border: 1px solid var(--line); }
.hi h2 { margin: 0; font-size: var(--fs-xl, 24px); } .hi p { margin: 4px 0 0; color: var(--ink-2); font-size: var(--fs-s); }
.sh { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; }
.sh span { display: flex; flex-direction: column; } .sh small { color: var(--muted); font-size: var(--fs-xs); }
.tg { display: flex; gap: 12px; align-items: center; padding: 12px 16px; border-radius: 14px; background: color-mix(in srgb, #229ED9 12%, var(--surface)); border: 1px solid color-mix(in srgb, #229ED9 40%, transparent); color: var(--ink); text-decoration: none; }
.tg .ic { font-size: 24px; } .tg span:nth-child(2) { display: flex; flex-direction: column; flex: 1; } .tg small { color: var(--ink-2); font-size: var(--fs-xs); } .chev { transform: rotate(-90deg); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l, 16px); padding: 14px 16px; }
.card header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.card h3 { margin: 0; font-size: var(--fs-b); } .card h3 small { color: var(--muted); font-weight: 600; font-size: var(--fs-xs); margin-left: 6px; } .card h3 em { color: var(--danger); font-style: normal; }
.all { font-size: var(--fs-s); font-weight: 700; color: var(--accent); text-decoration: none; }
.task { display: grid; grid-template-columns: 52px minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 10px 4px; border-top: 1px solid var(--line-2); color: var(--ink); text-decoration: none; font-size: var(--fs-s); }
.task .n { color: var(--muted); font-weight: 700; } .task .tt { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .task .cl, .task .d { font-size: var(--fs-xs); color: var(--muted); }
.task.late .d { color: var(--danger); font-weight: 800; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.tile { display: flex; flex-direction: column; gap: 4px; padding: 16px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface-2); color: var(--ink); text-decoration: none; min-height: 118px; }
.tile:hover { border-color: var(--accent); background: var(--surface); }
.ti { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; background: var(--accent-tint); color: var(--accent); margin-bottom: 4px; }
.tile small { color: var(--muted); font-size: var(--fs-xs); } .muted { color: var(--muted); margin: 0; }
@media (max-width: 640px) { .task { grid-template-columns: 44px minmax(0, 1fr); } .task .cl, .task .d { grid-column: 2; } .tiles { grid-template-columns: 1fr 1fr; } .tile { min-height: 100px; padding: 12px; } }
</style>
