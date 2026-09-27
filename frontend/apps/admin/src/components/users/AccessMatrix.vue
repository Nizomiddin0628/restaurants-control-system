<script setup lang="ts">
/**
 * Bo'limlar bo'yicha kirish: har qatorda — Yo'q / Ko'radi / Ishlaydi / To'liq.
 * base — roldan kelgan ruxsatlar (o'zgarmaydi, «rol» belgisi bilan), modelValue — shaxsiy qo'shimchalar.
 * «Batafsil» — bo'lim ichidagi alohida ruxsatlar (masalan: faqat «Qaytarish»).
 */
import { computed, ref } from 'vue'
import { type Area, type Level, RANK, areaLevel, covers, setLevel, LEVEL_HINT } from './perm'

const props = defineProps<{ areas: Area[]; sections: { code: string; title: string }[]; modelValue: string[]; base?: string[]; disabled?: boolean; skip?: string[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string[]): void }>()
const base = computed(() => props.base ?? [])
const all = computed(() => [...base.value, ...props.modelValue])
const groups = computed(() => props.sections.map(s => ({ ...s, areas: props.areas.filter(a => a.section === s.code && !(props.skip ?? []).includes(a.code)) })).filter(g => g.areas.length))
const open = ref<string | null>(null)

const cur = (a: Area) => areaLevel(all.value, a)
const fromRole = (a: Area) => areaLevel(base.value, a)
function pick(a: Area, lv: Level) {
  if (props.disabled) return
  const r = fromRole(a)
  const next = RANK[lv] <= RANK[r] && r !== 'custom' ? setLevel(props.modelValue, a, 'none') : setLevel(props.modelValue, a, lv)
  emit('update:modelValue', next)
}
function lockedBelow(a: Area, lv: Level) { const r = fromRole(a); return r !== 'none' && r !== 'custom' && RANK[lv] < RANK[r] }
function togglePerm(code: string) {
  if (props.disabled) return
  const has = props.modelValue.includes(code)
  emit('update:modelValue', has ? props.modelValue.filter(x => x !== code) : [...props.modelValue, code])
}
</script>
<template>
  <div class="mx">
    <section v-for="g in groups" :key="g.code" class="grp">
      <h4>{{ g.title }}</h4>
      <div v-for="a in g.areas" :key="a.code" class="row" :class="{ off: cur(a) === 'none' }">
        <div class="nm">
          <b>{{ a.title }}</b>
          <small>{{ LEVEL_HINT[cur(a)] }}<template v-if="fromRole(a) !== 'none'"> · rol orqali</template></small>
        </div>
        <div class="seg" role="radiogroup" :aria-label="a.title">
          <button v-for="l in a.levels" :key="l.key" type="button" role="radio" :aria-checked="cur(a) === l.key"
                  :class="['s-' + l.key, { on: cur(a) === l.key, lock: lockedBelow(a, l.key) }]" :disabled="disabled || lockedBelow(a, l.key)"
                  :title="lockedBelow(a, l.key) ? 'Roli bo\'yicha bundan yuqori — rolini o\'zgartiring' : ''" @click="pick(a, l.key)">
            {{ l.label }}<span v-if="fromRole(a) === l.key" class="rb">rol</span>
          </button>
          <button v-if="a.perms.length > 1" type="button" class="more" :class="{ on: open === a.code || cur(a) === 'custom' }" :aria-expanded="open === a.code" @click="open = open === a.code ? null : a.code">
            {{ cur(a) === 'custom' ? 'Tanlangan' : 'Batafsil' }} ▾
          </button>
        </div>
        <div v-if="open === a.code" class="det">
          <label v-for="p in a.perms" :key="p.code" class="pc" :class="{ dis: covers(base, p.code) }">
            <input type="checkbox" :checked="covers(all, p.code)" :disabled="disabled || covers(base, p.code)" @change="togglePerm(p.code)" />
            <span>{{ p.label }}</span>
          </label>
        </div>
      </div>
    </section>
  </div>
</template>
<style scoped>
.mx { display: flex; flex-direction: column; gap: 14px; }
.grp h4 { margin: 0 0 6px; font-size: var(--fs-s); font-weight: 800; color: var(--ink-2); }
.row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; align-items: center; padding: 8px 10px; border: 1px solid var(--line-2); border-radius: 12px; margin-bottom: 6px; background: var(--surface); }
.row.off .nm b { color: var(--muted); }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { font-size: var(--fs-s); } .nm small { font-size: var(--fs-xs); color: var(--muted); }
.seg { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.seg button { position: relative; border: 1px solid var(--line); background: var(--surface-2); color: var(--ink-2); border-radius: 9px; padding: 6px 10px; min-height: 34px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; }
.seg button.on { color: #fff; border-color: transparent; }
.seg .s-none.on { background: #64748B; } .seg .s-view.on { background: #0891B2; } .seg .s-edit.on { background: #2563EB; } .seg .s-full.on { background: #7C3AED; }
.seg button.lock { opacity: .45; cursor: not-allowed; }
.seg .more { background: transparent; border-style: dashed; } .seg .more.on { border-color: var(--accent); color: var(--accent); }
.rb { position: absolute; top: -7px; right: -4px; font-size: 9px; background: var(--warn-tint); color: var(--warn-ink); border-radius: 6px; padding: 0 4px; font-weight: 800; }
.det { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 2px 10px; padding: 6px 2px 2px; border-top: 1px dashed var(--line-2); }
.pc { display: flex; gap: 8px; align-items: center; min-height: 32px; font-size: var(--fs-xs); font-weight: 600; cursor: pointer; } .pc.dis { color: var(--muted); }
@media (max-width: 640px) { .row { grid-template-columns: 1fr; } .seg { justify-content: flex-start; } }
</style>
