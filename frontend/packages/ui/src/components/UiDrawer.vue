<script setup lang="ts">
import { watch } from 'vue'
const props = defineProps<{ open: boolean; title?: string; width?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
watch(() => props.open, (o) => { document.body.style.overflow = o ? 'hidden' : '' })
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="ov" @click.self="emit('close')" @keydown.esc="emit('close')">
      <aside class="dr" :style="{ '--w': width ?? '520px' }" role="dialog" aria-modal="true">
        <header class="hd"><h3>{{ title }}</h3><button class="x" type="button" aria-label="Yopish" @click="emit('close')">✕</button></header>
        <div class="bd"><slot /></div>
        <footer v-if="$slots.footer" class="ft"><slot name="footer" /></footer>
      </aside>
    </div>
  </Teleport>
</template>
<style scoped>
.ov { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 50; display: flex; justify-content: flex-end; }
.dr { width: min(var(--w), 100%); height: 100%; background: var(--surface); display: flex; flex-direction: column; box-shadow: var(--shadow); animation: in .18s ease-out; }
@keyframes in { from { transform: translateX(24px); opacity: 0; } }
.hd { display: flex; justify-content: space-between; align-items: center; padding: 16px var(--gutter); border-bottom: 1px solid var(--line); }
.hd h3 { margin: 0; font-size: var(--fs-l); font-weight: 800; }
.x { width: 36px; height: 36px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
.bd { flex: 1; overflow: auto; padding: 16px var(--gutter); display: flex; flex-direction: column; gap: 14px; }
.ft { display: flex; gap: 8px; justify-content: flex-end; padding: 12px var(--gutter); border-top: 1px solid var(--line); }
@media (max-width: 600px) { .ov { align-items: flex-end; } .dr { width: 100%; height: 92%; border-radius: 20px 20px 0 0; animation: up .2s ease-out; } @keyframes up { from { transform: translateY(24px); opacity: 0; } } }
</style>
