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
.ui-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: var(--touch); padding: 0 16px; border-radius: var(--radius); border: 1px solid transparent; font-weight: 700; cursor: pointer; white-space: nowrap; transition: background .2s, box-shadow .2s, border-color .2s, transform .05s; }
.ui-btn:active { transform: translateY(1px); }
.ui-btn:disabled { opacity: .55; cursor: not-allowed; }
.primary { background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 86%, #fff), var(--accent)); color: var(--accent-ink); box-shadow: 0 8px 20px -10px color-mix(in srgb, var(--accent) 80%, transparent), inset 0 1px 0 rgba(255, 255, 255, .22); }
.primary:hover:not(:disabled) { background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 76%, #fff), color-mix(in srgb, var(--accent) 92%, #fff)); box-shadow: 0 12px 26px -10px color-mix(in srgb, var(--accent) 90%, transparent), inset 0 1px 0 rgba(255, 255, 255, .3); }
.secondary { background: var(--surface); color: var(--ink); border-color: var(--line); }
.secondary:hover:not(:disabled) { background: var(--surface-2); border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
.ghost { background: transparent; color: var(--ink-2); }
.ghost:hover:not(:disabled) { background: var(--surface-3); }
.danger { background: var(--danger-tint); color: var(--danger); }
.brand { background: var(--grad); color: #fff; }
.s { min-height: calc(var(--touch) - 8px); padding: 0 12px; font-size: var(--fs-s); }
.l { min-height: calc(var(--touch) + 8px); padding: 0 22px; font-size: var(--fs-l); }
.block { width: 100%; }
.spin { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: r .7s linear infinite; }
@keyframes r { to { transform: rotate(360deg); } }
</style>
