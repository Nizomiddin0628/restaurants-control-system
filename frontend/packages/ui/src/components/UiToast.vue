<script lang="ts">
import { reactive } from 'vue'
type Toast = { id: number; text: string; tone: 'ok' | 'danger' | 'info' }
const state = reactive<{ items: Toast[] }>({ items: [] })
let n = 0
/** toast('Saqlandi') · toast('Xato', 'danger') */
export const toast = (text: string, tone: Toast['tone'] = 'ok') => {
  const id = ++n
  state.items.push({ id, text, tone })
  setTimeout(() => { state.items = state.items.filter(t => t.id !== id) }, 3200)
}
</script>
<script setup lang="ts">
const s = state
</script>
<template>
  <Teleport to="body">
    <div class="toasts" aria-live="polite">
      <div v-for="t in s.items" :key="t.id" class="t" :class="t.tone">{{ t.text }}</div>
    </div>
  </Teleport>
</template>
<style scoped>
.toasts { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); display: flex; flex-direction: column; gap: 8px; z-index: 100; pointer-events: none; width: min(92vw, 420px); }
.t { padding: 12px 16px; border-radius: var(--radius); background: var(--ink); color: var(--ink-inv); font-weight: 700; font-size: var(--fs-m); box-shadow: var(--shadow); animation: up .2s ease-out; }
.t.danger { background: var(--danger); color: #fff; } .t.info { background: var(--info); color: #fff; }
@keyframes up { from { transform: translateY(12px); opacity: 0; } }
</style>
