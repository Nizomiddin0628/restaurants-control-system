<script setup lang="ts">
/**
 * Umumiy oyna (v28): kompyuter va planshetda — ekran o'rtasida modal (ichi skroll bo'ladi),
 * telefonda — pastdan chiqadigan to'liq ekran oyna. Nomi eski (UiDrawer) — 35+ joyda ishlatiladi.
 * v37: oyna chetini (fonni) bosganda YOPILMAYDI — faqat ✕, ESC yoki saqlash/bekor tugmasi bilan.
 *      Ichida biror narsa yozilgan bo'lsa (o'zgartirilgan), ✕ yoki ESC bosilganda «Chiqib ketasizmi?» deb so'raydi.
 *      Bir nechta oyna ustma-ust ochilsa — ESC faqat eng ustidagisini yopadi.
 */
import { onBeforeUnmount, ref, watch } from 'vue'
const props = defineProps<{ open: boolean; title?: string; width?: string; noGuard?: boolean; state?: 'clean' | 'dirty' }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const STACK: number[] = ((globalThis as any).__uimStack ??= [])
const seq = ((globalThis as any).__uimSeq = ((globalThis as any).__uimSeq ?? 0) + 1)
const dirty = ref(false)
let locked = false
function lock(on: boolean) {
  if (on === locked) return
  locked = on
  const b = document.body
  const n = Number(b.dataset.uiModals || 0) + (on ? 1 : -1)
  b.dataset.uiModals = String(Math.max(0, n))
  b.style.overflow = n > 0 ? 'hidden' : ''
}
function tryClose() {
  const d = props.state ? props.state === 'dirty' : dirty.value     // state berilsa — ota komponent o'zi hisoblaydi
  if (d && !props.noGuard && !confirm('Kiritgan ma\'lumotlaringiz saqlanmagan. Oynani yopasizmi?')) return
  emit('close')
}
function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || STACK[STACK.length - 1] !== seq) return
  e.preventDefault(); tryClose()
}
function onEdit(e: Event) {
  const t = e.target as HTMLInputElement | null
  if (!t || t.type === 'search' || t.dataset?.noGuard !== undefined) return
  dirty.value = true
}
watch(() => props.open, (o) => {
  lock(o)
  const i = STACK.indexOf(seq); if (i >= 0) STACK.splice(i, 1)
  if (o) { dirty.value = false; STACK.push(seq); window.addEventListener('keydown', onKey) }
  else window.removeEventListener('keydown', onKey)
}, { immediate: true })
onBeforeUnmount(() => { lock(false); const i = STACK.indexOf(seq); if (i >= 0) STACK.splice(i, 1); window.removeEventListener('keydown', onKey) })
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="uim-ov">
      <section class="uim" :style="{ '--w': width ?? '520px' }" role="dialog" aria-modal="true" :aria-label="title">
        <header class="uim-hd"><h3>{{ title }}</h3><button class="uim-x" type="button" aria-label="Yopish" title="Yopish (Esc)" @click="tryClose">✕</button></header>
        <div class="uim-bd" @input="onEdit" @change="onEdit"><slot /></div>
        <footer v-if="$slots.footer" class="uim-ft"><slot name="footer" /></footer>
      </section>
    </div>
  </Teleport>
</template>
<style scoped>
.uim-ov { position: fixed; inset: 0; background: rgba(15, 23, 42, .45); backdrop-filter: blur(2px); z-index: 50;
  display: flex; align-items: center; justify-content: center; padding: 24px; animation: uim-fade .15s ease-out; }
.uim { width: min(var(--w), 100%); max-height: min(calc(100dvh - 48px), 920px); background: var(--surface); display: flex; flex-direction: column;
  border-radius: 20px; box-shadow: 0 24px 70px rgba(0, 0, 0, .28); animation: uim-in .18s ease-out; overflow: hidden; min-height: 0; }
@keyframes uim-fade { from { opacity: 0; } }
@keyframes uim-in { from { transform: translateY(12px) scale(.98); opacity: 0; } }
.uim-hd { flex-shrink: 0; display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 16px 20px; border-bottom: 1px solid var(--line); }
.uim-hd h3 { margin: 0; font-size: var(--fs-l); font-weight: 800; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.uim-x { flex-shrink: 0; width: 36px; height: 36px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); cursor: pointer; }
.uim-x:hover { background: var(--surface-2, var(--bg)); }
.uim-bd { flex: 1 1 auto; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
.uim-bd > :deep(*) { flex-shrink: 0; }
.uim-ft { flex-shrink: 0; display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid var(--line); }
@media (max-width: 600px) {
  .uim-ov { padding: 0; align-items: flex-end; }
  .uim { width: 100%; max-height: none; height: 100dvh; border-radius: 0; animation: uim-up .22s ease-out; }
  .uim-hd { padding: calc(12px + env(safe-area-inset-top)) 16px 12px; }
  .uim-bd { padding: 16px; }
  .uim-ft { padding: 12px 16px calc(12px + env(safe-area-inset-bottom)); }
  .uim-ft > :deep(*) { flex: 1 1 auto; }
  @keyframes uim-up { from { transform: translateY(40px); opacity: 0; } }
}
</style>
