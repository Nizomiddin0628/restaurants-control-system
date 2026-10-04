<script setup lang="ts">
/**
 * Bayram ogohlantirishi: nomi, necha kun qoldi, kutilayotgan savdo, xarid summasi va «qachongacha».
 * Boshqaruv paneli, Ombor va «Bayram va ob-havo» sahifasida bir xil ko'rinadi.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { UiIcon, money } from '@restopos/ui'

const props = defineProps<{ a: any; compact?: boolean; showLink?: boolean }>()
const emit = defineEmits<{ (e: 'plan', id: number): void }>()
const when = computed(() => props.a.is_now ? 'Bugun bayram' : props.a.days_left === 1 ? 'Ertaga' : `${props.a.days_left} kun qoldi`)
const fmt = (s: string) => s.split('-').reverse().join('.')
const up = computed(() => `${props.a.uplift_percent >= 0 ? '+' : ''}${props.a.uplift_percent}%`)
</script>

<template>
  <div class="ha" :class="{ now: a.is_now, compact }">
    <div class="ic">🎉</div>
    <div class="bd">
      <div class="t">
        <b>{{ a.name.uz }}</b>
        <span class="pill">{{ when }}</span>
        <span v-if="a.is_approx" class="pill mute" title="Sana Diniy idora e'lonidan keyin aniqlanadi">taxminiy sana</span>
      </div>
      <p class="d">{{ fmt(a.date) }}<template v-if="a.days > 1"> – {{ fmt(a.end) }}</template> · kutilayotgan savdo <b>{{ up }}</b><template v-if="a.note"> · {{ a.note }}</template></p>
      <div class="st">
        <div><span>Xarid kerak</span><b :class="{ bad: a.short_count }">{{ a.short_count ? `${a.short_count} ta xomashyo` : 'Ombor yetarli' }}</b></div>
        <div v-if="a.short_count"><span>Taxminiy summa</span><b>{{ money(a.total_cost) }} so'm</b></div>
        <div v-if="a.short_count"><span>Qachongacha</span><b>{{ fmt(a.buy_by) }}</b></div>
        <div v-if="!compact && a.revenue_holiday"><span>Bayram savdosi (prognoz)</span><b>{{ money(a.revenue_holiday) }} so'm</b></div>
      </div>
      <p v-if="a.top_short?.length && !compact" class="ts">Birinchi navbatda: <b>{{ a.top_short.join(', ') }}</b></p>
    </div>
    <div class="ac">
      <RouterLink v-if="showLink" :to="`/inventory?tab=plan&holiday=${a.id}`" class="btn">Xarid rejasi <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" /></RouterLink>
      <button v-else type="button" class="btn" @click="emit('plan', a.id)">Xarid rejasi <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" /></button>
    </div>
    <div v-if="$slots.default" class="ex"><slot /></div>
  </div>
</template>

<style scoped>
.ha { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 14px 16px; border-radius: 16px;
  background: var(--warn-tint); border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--line)); color: var(--ink); }
.ha.now { background: var(--ok-tint); border-color: color-mix(in srgb, var(--ok) 40%, var(--line)); }
.ic { width: 44px; height: 44px; border-radius: 12px; background: var(--surface); display: grid; place-items: center; font-size: 22px; }
.bd { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.t { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .t b { font-family: var(--font-display); font-size: var(--fs-l); font-weight: 800; }
.pill { font-size: var(--fs-xs); font-weight: 800; padding: 2px 8px; border-radius: 99px; background: var(--warn); color: #fff; white-space: nowrap; }
.now .pill { background: var(--ok); } .pill.mute { background: var(--surface); color: var(--muted); border: 1px solid var(--line); }
.d { margin: 0; font-size: var(--fs-s); color: var(--ink-2); }
.st { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 4px; }
.st div { display: flex; flex-direction: column; } .st span { font-size: var(--fs-xs); color: var(--muted); } .st b { font-size: var(--fs-s); font-variant-numeric: tabular-nums; } .st b.bad { color: var(--danger); }
.ts { margin: 2px 0 0; font-size: var(--fs-xs); color: var(--ink-2); }
.btn { display: inline-flex; align-items: center; gap: 4px; min-height: var(--touch); padding: 0 14px; border-radius: 10px; border: 0; background: var(--accent); color: #fff;
  font: inherit; font-weight: 800; font-size: var(--fs-s); text-decoration: none; cursor: pointer; white-space: nowrap; }
.compact { padding: 12px 14px; }
.ex { grid-column: 1 / -1; min-width: 0; padding-top: 12px; border-top: 1px dashed color-mix(in srgb, var(--warn) 45%, var(--line)); }
.now .ex { border-top-color: color-mix(in srgb, var(--ok) 45%, var(--line)); }
.ha:not(.compact) .btn { min-height: 48px; padding: 0 22px; font-size: var(--fs-b); border-radius: 12px; }
@media (max-width: 720px) {
  .ha { grid-template-columns: 40px minmax(0, 1fr); } .ic { width: 40px; height: 40px; align-self: start; }
  .ac { grid-column: 1 / -1; } .btn { width: 100%; justify-content: center; }
  .st { gap: 12px; }
}
</style>
