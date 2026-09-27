<script setup lang="ts">
/** Aylana progress: foiz markazda; rang sog'lomlikka qarab. */
import { computed } from 'vue'
const props = withDefaults(defineProps<{ value: number; size?: number; color?: string; stroke?: number }>(), { size: 56, stroke: 7 })
const r = computed(() => (props.size - props.stroke) / 2)
const c = computed(() => 2 * Math.PI * r.value)
</script>

<template>
  <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" class="pr" role="img" :aria-label="`${value}%`">
    <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" stroke="var(--surface-3)" :stroke-width="stroke" />
    <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" :stroke="color ?? 'var(--ok)'" :stroke-width="stroke" stroke-linecap="round"
            :stroke-dasharray="`${(c * Math.min(100, value)) / 100} ${c}`" :transform="`rotate(-90 ${size / 2} ${size / 2})`" />
    <text :x="size / 2" :y="size / 2 + size * 0.08" text-anchor="middle" :style="{ fontSize: `${Math.round(size * 0.26)}px` }">{{ value }}%</text>
  </svg>
</template>

<style scoped>
.pr { flex-shrink: 0; } text { font-weight: 800; fill: var(--ink); font-family: var(--font-display); }
</style>
