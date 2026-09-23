<script setup lang="ts">
defineProps<{ modelValue: boolean | undefined; label?: string; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()
</script>
<template>
  <label class="ui-toggle" :class="{ dis: disabled }">
    <input type="checkbox" role="switch" :checked="!!modelValue" :disabled="disabled" @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)" />
    <span class="track" :class="{ on: !!modelValue }"><span class="knob"></span></span>
    <span v-if="label" class="lbl">{{ label }}</span>
  </label>
</template>
<style scoped>
.ui-toggle { display: inline-flex; align-items: center; gap: 10px; cursor: pointer; min-height: var(--touch); }
.ui-toggle.dis { opacity: .5; cursor: not-allowed; }
input { position: absolute; opacity: 0; width: 0; height: 0; }
.track { width: 42px; height: 24px; border-radius: 999px; background: var(--surface-3); border: 1px solid var(--line); position: relative; transition: background .15s; flex-shrink: 0; }
.track.on { background: var(--accent); border-color: var(--accent); }
.knob { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: left .15s; box-shadow: 0 1px 2px rgba(0,0,0,.2); }
.track.on .knob { left: 20px; }
input:focus-visible + .track { outline: 3px solid var(--accent-tint); }
.lbl { font-size: var(--fs-m); font-weight: 600; }
</style>
