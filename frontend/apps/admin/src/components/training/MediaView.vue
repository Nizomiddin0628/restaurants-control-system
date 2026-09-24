<script setup lang="ts">
/** Yuklangan fayl yoki havola — bir xil ko'rinish: rasm, video, YouTube/Drive/Vimeo oynasi yoki "Ochish" tugmasi. */
type Media = { kind: string; src: string; embed?: string; thumb?: string } | null | undefined
defineProps<{ media: Media; label?: string }>()
</script>

<template>
  <template v-if="media">
    <img v-if="media.kind === 'image'" :src="media.src" class="mv img" alt="" loading="lazy" />
    <video v-else-if="media.kind === 'video'" :src="media.src" class="mv" controls playsinline preload="metadata"></video>
    <div v-else-if="media.embed" class="mv frame"><iframe :src="media.embed" allow="autoplay; encrypted-media; fullscreen" allowfullscreen loading="lazy" title="Material"></iframe></div>
    <a v-else :href="media.src" target="_blank" rel="noopener" class="open">{{ media.kind === 'pdf' ? '📄' : '🔗' }} {{ label ?? 'Materialni ochish' }}</a>
  </template>
</template>

<style scoped>
.mv { width: 100%; max-height: 360px; border-radius: 12px; background: #000; display: block; }
.img { object-fit: contain; background: var(--surface-3); }
.frame { aspect-ratio: 16 / 9; max-height: none; overflow: hidden; }
.frame iframe { width: 100%; height: 100%; border: 0; display: block; }
.open { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 14px; border-radius: 10px; border: 1px solid var(--line); color: var(--accent); font-weight: 700; text-decoration: none; background: var(--surface); }
</style>
