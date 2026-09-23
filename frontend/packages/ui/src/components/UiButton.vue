<script setup lang="ts">
withDefaults(defineProps<{ variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'brand'; size?: 's' | 'm' | 'l'; loading?: boolean; block?: boolean; type?: 'button' | 'submit' }>(), { variant: 'primary', size: 'm', type: 'button' })
</script>
<template>
  <button :type="type" class="ui-btn" :class="[variant, size, { block }]" :disabled="loading || ($attrs.disabled as boolean)" v-bind="$attrs">
    <span v-if="loading" class="spin" aria-hidden="true"></span>
    <slot />
  </button>
</template>
<style scoped>
.ui-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: var(--touch); padding: 0 16px; border-radius: var(--radius); border: 1px solid transparent; font-weight: 700; cursor: pointer; white-space: nowrap; transition: background .15s, transform .05s; }
.ui-btn:active { transform: translateY(1px); }
.ui-btn:disabled { opacity: .55; cursor: not-allowed; }
.primary { background: var(--accent); color: var(--accent-ink); }
.primary:hover:not(:disabled) { background: var(--accent-hover); }
.secondary { background: var(--surface); color: var(--ink); border-color: var(--line); }
.secondary:hover:not(:disabled) { background: var(--surface-2); }
.ghost { background: transparent; color: var(--ink-2); }
.ghost:hover:not(:disabled) { background: var(--surface-3); }
.danger { background: var(--danger-tint); color: var(--danger); }
.brand { background: var(--brand); color: var(--brand-ink); }
.s { min-height: calc(var(--touch) - 8px); padding: 0 12px; font-size: var(--fs-s); }
.l { min-height: calc(var(--touch) + 8px); padding: 0 22px; font-size: var(--fs-l); }
.block { width: 100%; }
.spin { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: r .7s linear infinite; }
@keyframes r { to { transform: rotate(360deg); } }
</style>
