<script setup lang="ts">
const props = defineProps<{ modelValue: string | number | null | undefined; label?: string; hint?: string; error?: string; type?: string; placeholder?: string; suffix?: string; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string | number): void }>()
const onInput = (e: Event) => {
  const el = e.target as HTMLInputElement
  emit('update:modelValue', props.type === 'number' ? (el.value === '' ? '' : Number(el.value)) : el.value)
}
</script>
<template>
  <label class="ui-field">
    <span v-if="label" class="lbl">{{ label }}</span>
    <span class="box" :class="{ err: !!error, dis: disabled }">
      <input :type="type ?? 'text'" :value="modelValue ?? ''" :placeholder="placeholder" :disabled="disabled" @input="onInput" v-bind="$attrs" />
      <span v-if="suffix" class="sfx">{{ suffix }}</span>
    </span>
    <span v-if="error" class="msg err">{{ error }}</span>
    <span v-else-if="hint" class="msg">{{ hint }}</span>
  </label>
</template>
<style scoped>
.ui-field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.box { display: flex; align-items: center; min-height: var(--touch); padding: 0 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.box:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-tint); }
.box.err { border-color: var(--danger); }
.box.dis { opacity: .6; }
input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; }
.sfx { color: var(--muted); font-size: var(--fs-s); padding-left: 8px; }
.msg { font-size: var(--fs-xs); color: var(--muted); }
.msg.err { color: var(--danger); }
</style>
