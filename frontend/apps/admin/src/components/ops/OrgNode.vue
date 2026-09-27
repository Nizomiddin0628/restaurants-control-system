<script setup lang="ts">
/**
 * Tashkiliy tuzilma tuguni (rekursiv). mode='tree' — klassik org chart (kompyuter/planshet),
 * mode='list' — ichma-ich ro'yxat (telefon). Lavozimni boshqasining ustiga sudrab tashlash = kimga bo'ysunishini o'zgartirish.
 */
import { computed, ref } from 'vue'
import { UiAvatar } from '@restopos/ui'

defineOptions({ name: 'OrgNode' })
const props = defineProps<{ n: any; mode: 'tree' | 'list'; selected?: number | null; canEdit?: boolean; depth?: number; collapse?: boolean }>()
const emit = defineEmits<{ (e: 'pick', n: any): void; (e: 'move', v: { id: number; to: number }): void }>()
const open = ref((props.depth ?? 0) < 3 && !(props.n.type === 'branch' && props.collapse))
// barg tugunlar (qo'l ostida hech kim yo'q) 3+ bo'lsa — ustma-ust ixcham ro'yxat: daraxt juda enli bo'lib ketmasin
const stack = computed(() => props.n.type === 'position' && props.n.children.length > 2 && props.n.children.every((c: any) => c.type === 'position' && !c.children.length))
const over = ref(false)
const isPos = computed(() => props.n.type === 'position')
const short = computed(() => isPos.value && props.n.headcount > 0 && props.n.count < props.n.headcount)
const color = computed(() => props.n.department?.color ?? 'var(--line)')

function onDrag(e: DragEvent) { if (!isPos.value || !props.canEdit) return; e.dataTransfer?.setData('text/plain', String(props.n.id)); e.dataTransfer!.effectAllowed = 'move' }
function onDrop(e: DragEvent) {
  over.value = false
  const id = Number(e.dataTransfer?.getData('text/plain'))
  if (id && isPos.value && id !== props.n.id) emit('move', { id, to: props.n.id })
}
</script>

<template>
  <!-- DARAXT -->
  <li v-if="mode === 'tree'" class="t-li">
    <div v-if="isPos" class="card" :class="{ sel: selected === n.id, over, short }" :style="{ '--c': color }"
         :draggable="canEdit" @dragstart="onDrag" @dragover.prevent="canEdit && (over = true)" @dragleave="over = false" @drop.prevent="onDrop"
         role="button" tabindex="0" @click="emit('pick', n)" @keydown.enter="emit('pick', n)">
      <span class="ic">{{ n.icon }}</span>
      <b class="nm">{{ n.name }}</b>
      <small v-if="n.department" class="dp">{{ n.department.name }}</small>
      <span class="ft">
        <span class="av"><UiAvatar v-for="p in n.people.slice(0, 3)" :key="p.id" :name="p.name" :src="p.avatar" :size="22" /></span>
        <span class="hc" :class="{ bad: short }" :title="n.headcount ? 'Bor / shtat' : 'Xodimlar'">{{ n.count }}<template v-if="n.headcount">/{{ n.headcount }}</template></span>
      </span>
    </div>
    <div v-else class="br" role="button" tabindex="0" @click="open = !open" @keydown.enter="open = !open">🏪 <b>{{ n.name }}</b><small>{{ n.count }} xodim</small><span class="cv">{{ open ? '▾' : '▸' }}</span></div>
    <div v-if="stack" class="stk">
      <button v-for="c in n.children" :key="`s${c.id}-${c.branch_id ?? ''}`" type="button" class="sc" :class="{ sel: selected === c.id, short: c.headcount && c.count < c.headcount }"
              :style="{ '--c': c.department?.color ?? 'var(--line)' }" @click="emit('pick', c)">
        <span>{{ c.icon }}</span><b>{{ c.name }}</b><i>{{ c.count }}<template v-if="c.headcount">/{{ c.headcount }}</template></i>
      </button>
    </div>
    <ul v-else-if="n.children.length && (open || isPos)" class="t-ul">
      <OrgNode v-for="c in n.children" :key="`${c.type}${c.id}-${c.branch_id ?? ''}`" :n="c" mode="tree" :selected="selected" :can-edit="canEdit" :depth="(depth ?? 0) + 1" :collapse="collapse"
               @pick="emit('pick', $event)" @move="emit('move', $event)" />
    </ul>
  </li>

  <!-- RO'YXAT (telefon) -->
  <li v-else class="l-li">
    <div class="row" :class="{ sel: selected === n.id, isbr: !isPos }" :style="{ '--c': color, paddingLeft: `${10 + (depth ?? 0) * 14}px` }">
      <button v-if="n.children.length" type="button" class="tg" :aria-label="open ? 'Yopish' : 'Ochish'" @click="open = !open">{{ open ? '▾' : '▸' }}</button>
      <span v-else class="tg"></span>
      <button type="button" class="rb" @click="isPos ? emit('pick', n) : (open = !open)">
        <span class="ic">{{ isPos ? n.icon : '🏪' }}</span>
        <span class="tx"><b>{{ n.name }}</b><small>{{ isPos ? (n.department?.name ?? 'Bo\'limsiz') : `${n.count} xodim` }}</small></span>
        <span v-if="isPos" class="hc" :class="{ bad: short }">{{ n.count }}<template v-if="n.headcount">/{{ n.headcount }}</template></span>
      </button>
    </div>
    <ul v-if="n.children.length && open" class="l-ul">
      <OrgNode v-for="c in n.children" :key="`${c.type}${c.id}-${c.branch_id ?? ''}`" :n="c" mode="list" :selected="selected" :depth="(depth ?? 0) + 1"
               @pick="emit('pick', $event)" @move="emit('move', $event)" />
    </ul>
  </li>
</template>

<style scoped>
/* ---- daraxt: klassik org chart chiziqlari */
.t-ul { display: flex; justify-content: center; padding: 22px 0 0; margin: 0; position: relative; list-style: none; }
.t-ul::before { content: ''; position: absolute; top: 0; left: 50%; height: 22px; border-left: 2px solid var(--line); }
.t-li { display: flex; flex-direction: column; align-items: center; position: relative; padding: 22px 8px 0; list-style: none; }
.t-li::before, .t-li::after { content: ''; position: absolute; top: 0; right: 50%; width: 50%; height: 22px; border-top: 2px solid var(--line); }
.t-li::after { right: auto; left: 50%; border-left: 2px solid var(--line); }
.t-li:only-child::before, .t-li:only-child::after { display: none; }
.t-li:only-child { padding-top: 0; }
.t-li:first-child::before, .t-li:last-child::after { border: 0 none; }
.t-li:last-child::before { border-right: 2px solid var(--line); border-radius: 0 8px 0 0; }
.t-li:first-child::after { border-radius: 8px 0 0 0; }
.card { width: 168px; background: var(--surface); border: 1px solid var(--line); border-top: 4px solid var(--c); border-radius: 12px; padding: 10px 10px 8px;
  display: flex; flex-direction: column; align-items: center; gap: 2px; cursor: pointer; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,.04); transition: box-shadow .15s, transform .15s; }
.card:hover { box-shadow: var(--shadow); transform: translateY(-1px); }
.card.sel { outline: 3px solid color-mix(in srgb, var(--accent) 45%, transparent); }
.card.over { outline: 3px dashed var(--accent); }
.card .ic { font-size: 22px; line-height: 1.1; }
.card .nm { font-size: var(--fs-s); line-height: 1.2; }
.card .dp { font-size: 11px; color: var(--muted); }
.ft { display: flex; align-items: center; justify-content: space-between; width: 100%; margin-top: 6px; min-height: 22px; }
.av { display: flex; } .av > * + * { margin-left: -6px; }
.hc { font-size: 11px; font-weight: 800; padding: 1px 7px; border-radius: 99px; background: var(--surface-2); color: var(--ink-2); font-variant-numeric: tabular-nums; }
.hc.bad { background: var(--warn-tint); color: var(--warn-ink); }
.br { display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 99px; background: var(--ink); color: var(--surface); font-size: var(--fs-s); cursor: pointer; white-space: nowrap; }
.br small { opacity: .7; font-size: 11px; } .br .cv { opacity: .7; }
.stk { display: flex; flex-direction: column; gap: 6px; padding-top: 22px; position: relative; }
.stk::before { content: ''; position: absolute; top: 0; left: 50%; height: 22px; border-left: 2px solid var(--line); }
.sc { width: 168px; display: grid; grid-template-columns: 24px 1fr auto; gap: 6px; align-items: center; padding: 7px 9px; border: 1px solid var(--line); border-left: 4px solid var(--c); border-radius: 10px; background: var(--surface); font: inherit; text-align: left; cursor: pointer; color: var(--ink); }
.sc:hover { box-shadow: var(--shadow); } .sc.sel { outline: 3px solid color-mix(in srgb, var(--accent) 45%, transparent); }
.sc span { font-size: 17px; } .sc b { font-size: 12px; line-height: 1.2; } .sc i { font-style: normal; font-size: 11px; font-weight: 800; padding: 1px 6px; border-radius: 99px; background: var(--surface-2); }
.sc.short i { background: var(--warn-tint); color: var(--warn-ink); }
/* ---- ro'yxat */
.l-ul { list-style: none; margin: 0; padding: 0; }
.l-li { list-style: none; }
.row { display: flex; align-items: center; gap: 4px; border-bottom: 1px solid var(--line-2); border-left: 4px solid var(--c); }
.row.isbr { background: var(--surface-2); border-left-color: var(--ink); }
.row.sel { background: var(--accent-tint); }
.tg { width: 28px; height: 44px; border: 0; background: transparent; color: var(--muted); font-size: 14px; cursor: pointer; flex-shrink: 0; }
.rb { flex: 1; display: flex; align-items: center; gap: 10px; min-height: 52px; border: 0; background: transparent; text-align: left; font: inherit; color: var(--ink); cursor: pointer; padding: 6px 12px 6px 0; min-width: 0; }
.rb .ic { font-size: 22px; } .tx { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.tx b { font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .tx small { font-size: var(--fs-xs); color: var(--muted); }
</style>
