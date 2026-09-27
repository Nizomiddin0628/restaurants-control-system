<script setup lang="ts">
/** Tizim holati: baza, kesh, disk, fayl saqlash, statistika yig'ish, kod yuborish — javob vaqti bilan. */
import { onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiIcon } from '@restopos/ui'
import { dt } from '../fmt'

const H = ref<any>(null)
async function load() { H.value = await api.get('/hq/health') }
onMounted(load)
</script>

<template>
  <div v-if="H" class="hh">
    <div class="big" :class="H.percent === 100 ? 'ok' : 'bad'">
      <b>{{ H.percent }}%</b><span>{{ H.ok }}/{{ H.total }} tekshiruv yaxshi · {{ H.version }} · {{ dt(H.time) }}</span>
      <UiButton size="s" variant="ghost" @click="load()"><UiIcon name="repeat" :size="14" /> Qayta tekshirish</UiButton>
    </div>
    <UiCard :padded="false">
      <div v-for="c in H.checks" :key="c.name" class="ck">
        <span class="dot" :class="c.ok ? 'ok' : 'bad'"></span>
        <b>{{ c.name }}</b>
        <span class="dt">{{ c.detail }}</span>
        <span class="st" :class="c.ok ? 'ok' : 'bad'">{{ c.ok ? 'Normal' : 'Muammo' }}</span>
        <small>{{ c.ms }} ms</small>
      </div>
    </UiCard>
    <p class="note">Keyingi bosqichda: Telegram webhook xatolari, fon vazifalari navbati, har restoran bo'yicha API tezligi va avtomatik Telegram ogohlantirishi.</p>
  </div>
</template>

<style scoped>
.hh { display: flex; flex-direction: column; gap: 14px; }
.big { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 16px 18px; border-radius: 16px; background: var(--ok-tint); }
.big.bad { background: var(--danger-tint); } .big b { font-family: var(--font-display); font-size: 36px; } .big span { flex: 1; color: var(--ink-2); font-size: var(--fs-s); }
.ck { display: grid; grid-template-columns: 14px 1.2fr 2fr auto 60px; gap: 12px; align-items: center; padding: 14px 16px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.ck:first-child { border-top: 0; }
.dot { width: 10px; height: 10px; border-radius: 50%; } .dot.ok { background: #16A34A; } .dot.bad { background: #EF4444; }
.dt { color: var(--muted); } .st { font-weight: 800; } .st.ok { color: #16A34A; } .st.bad { color: #DC2626; } .ck small { color: var(--muted); text-align: right; }
.note { margin: 0; color: var(--muted); font-size: var(--fs-s); }
@media (max-width: 700px) { .ck { grid-template-columns: 14px 1fr auto; } .ck .dt { grid-column: 2 / -1; } .ck small { display: none; } }
</style>
