<script setup lang="ts">
/** Fayl tashlash zonasi — rasm/video/PDF/Excel; telefonda kamera (capture). */
import { ref } from 'vue'
const props = defineProps<{ accept?: string; multiple?: boolean; label?: string; hint?: string; capture?: boolean }>()
const emit = defineEmits<{ (e: 'files', files: File[]): void }>()
const over = ref(false)
const input = ref<HTMLInputElement | null>(null)
const pick = (list: FileList | null) => { if (!list) return; emit('files', Array.from(list).slice(0, props.multiple ? 50 : 1)) }
</script>
<template>
  <div class="dz" :class="{ over }" tabindex="0" role="button" @click="input?.click()" @keydown.enter="input?.click()"
       @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="over = false; pick($event.dataTransfer?.files ?? null)">
    <input ref="input" type="file" :accept="accept" :multiple="multiple" :capture="capture ? 'environment' : undefined" hidden @change="pick(($event.target as HTMLInputElement).files); ($event.target as HTMLInputElement).value = ''" />
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></svg>
    <b>{{ label ?? 'Faylni bu yerga tashlang yoki bosing' }}</b>
    <span v-if="hint" class="h">{{ hint }}</span>
  </div>
</template>
<style scoped>
.dz { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 20px; border: 2px dashed var(--line); border-radius: var(--radius-l); color: var(--muted); cursor: pointer; text-align: center; font-size: var(--fs-s); transition: border-color .15s, background .15s; }
.dz.over, .dz:hover { border-color: var(--accent); background: var(--accent-tint); color: var(--accent); }
b { color: var(--ink); } .h { font-size: var(--fs-xs); }
</style>
