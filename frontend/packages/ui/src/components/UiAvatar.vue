<script setup lang="ts">
/** Profil rasmi: rasm bo'lsa — rasm, bo'lmasa ismdan bosh harflar (rangi ismga qarab doim bir xil). */
import { computed } from 'vue'
const props = withDefaults(defineProps<{ name?: string | null; src?: string | null; size?: number; online?: boolean }>(), { size: 34 })
const initials = computed(() => (props.name || '?').trim().split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase())
const PALETTE = ['#0F6E63', '#1F5FBF', '#8A5A12', '#6C5CA8', '#B8321B', '#1E7F4F', '#3E3D38']
const bg = computed(() => { let h = 0; for (const c of props.name || '') h = (h * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[h % PALETTE.length] })
</script>
<template>
  <span class="av" :class="{ on: online }" :style="{ width: size + 'px', height: size + 'px', fontSize: Math.round(size * 0.36) + 'px', background: src ? 'var(--surface-3)' : bg }">
    <img v-if="src" :src="src" :alt="name ?? ''" loading="lazy" />
    <template v-else>{{ initials }}</template>
  </span>
</template>
<style scoped>
.av { position: relative; display: inline-grid; place-items: center; flex-shrink: 0; border-radius: 30%; color: #fff; font-weight: 800; letter-spacing: .02em; }
.av img { width: 100%; height: 100%; object-fit: cover; border-radius: inherit; display: block; }
.av.on::after { content: ''; position: absolute; right: -2px; bottom: -2px; width: 28%; height: 28%; min-width: 8px; min-height: 8px; border-radius: 50%; background: var(--ok); border: 2px solid var(--surface); }
</style>
