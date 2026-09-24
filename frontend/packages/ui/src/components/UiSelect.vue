<script setup lang="ts">
defineProps<{ modelValue: string | number | null | undefined; label?: string; options: { value: string | number; label: string }[]; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()
</script>
<template>
  <label class="ui-field">
    <span v-if="label" class="lbl">{{ label }}</span>
    <span class="box"><select :value="modelValue ?? ''" :disabled="disabled" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"><option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option></select></span>
  </label>
</template>
<style scoped>
.ui-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lbl { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.box { display: flex; min-height: var(--touch); padding: 0 8px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.box:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-tint); }
select { flex: 1; min-width: 0; width: 100%; border: 0; outline: 0; background: transparent; font: inherit; color: var(--ink); text-overflow: ellipsis; }
</style>
