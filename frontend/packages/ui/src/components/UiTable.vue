<script setup lang="ts" generic="T extends { id: number | string }">
/**
 * Jadval: ustunlar, inline tahrir (tahrirlanadigan katakni bir marta bosish — telefonda ham ishlaydi), tanlash (ommaviy amallar), telefonda karta ko'rinishi.
 * columns: { key, label, width?, editable?: 'text'|'number'|'boolean', align?, format? }
 */
import { ref, shallowRef, triggerRef } from 'vue'
export type Col<T> = { key: keyof T & string; label: string; width?: string; editable?: 'text' | 'number' | 'boolean'; align?: 'left' | 'right'; format?: (v: any, row: T) => string; hideOnPhone?: boolean }
const props = defineProps<{ rows: T[]; columns: Col<T>[]; selectable?: boolean; loading?: boolean; rowKey?: string }>()
const emit = defineEmits<{ (e: 'edit', payload: { id: T['id']; key: string; value: any }): void; (e: 'select', ids: T['id'][]): void; (e: 'row', row: T): void }>()
const editing = ref<{ id: T['id']; key: string } | null>(null)
const draft = ref<any>('')
/** `autofocus` faqat sahifa yuklanganda ishlaydi — inline input paydo bo'lganda fokus va tanlashni o'zimiz qilamiz. */
const vFocus = { mounted: (el: HTMLInputElement) => { el.focus(); el.select() } }
const selected = shallowRef(new Set<string | number>())
const start = (row: T, c: Col<T>) => { if (!c.editable || c.editable === 'boolean') return; editing.value = { id: row.id, key: c.key }; draft.value = (row as any)[c.key] }
const commit = (row: T, c: Col<T>) => {
  if (!editing.value) return
  const v = c.editable === 'number' ? Number(draft.value) : draft.value
  if (v !== (row as any)[c.key]) emit('edit', { id: row.id, key: c.key, value: v })
  editing.value = null
}
const toggleSel = (id: T['id']) => { selected.value.has(id) ? selected.value.delete(id) : selected.value.add(id); triggerRef(selected); emit('select', [...selected.value] as T['id'][]) }
const toggleAll = () => { selected.value = selected.value.size === props.rows.length ? new Set() : new Set<string | number>(props.rows.map(r => r.id)); emit('select', [...selected.value] as T['id'][]) }
const cell = (row: T, c: Col<T>) => c.format ? c.format((row as any)[c.key], row) : (row as any)[c.key]
</script>
<template>
  <div class="tbl" :class="{ loading }">
    <div class="head">
      <span v-if="selectable" class="c chk"><input type="checkbox" :checked="selected.size > 0 && selected.size === rows.length" @change="toggleAll" aria-label="Hammasi" /></span>
      <span v-for="c in columns" :key="c.key" class="c" :class="[c.align, { hp: c.hideOnPhone }]" :style="{ flex: c.width ?? '1 1 0' }">{{ c.label }}</span>
    </div>
    <div v-for="row in rows" :key="row.id" class="row" :class="{ sel: selected.has(row.id) }" @click="emit('row', row)">
      <span v-if="selectable" class="c chk" @click.stop><input type="checkbox" :checked="selected.has(row.id)" @change="toggleSel(row.id)" /></span>
      <span v-for="c in columns" :key="c.key" class="c" :class="[c.align, { ed: !!c.editable, hp: c.hideOnPhone }]" :style="{ flex: c.width ?? '1 1 0' }" :data-label="c.label" @click="c.editable ? ($event.stopPropagation(), start(row, c)) : undefined">
        <template v-if="editing && editing.id === row.id && editing.key === c.key">
          <input v-if="c.editable !== 'boolean'" v-model="draft" :type="c.editable === 'number' ? 'number' : 'text'" class="inl" v-focus @blur="commit(row, c)" @keydown.enter="commit(row, c)" @keydown.esc="editing = null" @click.stop />
        </template>
        <template v-else-if="c.editable === 'boolean'">
          <input type="checkbox" :checked="!!(row as any)[c.key]" @click.stop @change="emit('edit', { id: row.id, key: c.key, value: ($event.target as HTMLInputElement).checked })" />
        </template>
        <template v-else><slot :name="c.key" :row="row" :value="(row as any)[c.key]">{{ cell(row, c) }}</slot></template>
      </span>
    </div>
    <div v-if="!rows.length && !loading" class="empty"><slot name="empty">Hozircha ma'lumot yo'q</slot></div>
  </div>
</template>
<style scoped>
.tbl { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: var(--radius-l); background: var(--surface); overflow: hidden; }
.tbl.loading { opacity: .6; }
.head, .row { display: flex; align-items: center; gap: 8px; padding: 8px 14px; }
.head { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.row { border-top: 1px solid var(--line-2); min-height: var(--touch); cursor: default; }
.row:hover { background: var(--surface-2); }
.row.sel { background: var(--accent-tint); }
.c { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.c.right { text-align: right; }
.c.ed { cursor: text; border-radius: 6px; }
.c.ed:hover { box-shadow: inset 0 0 0 1px var(--line); }
.chk { flex: 0 0 28px; }
.inl { width: 100%; border: 1px solid var(--accent); border-radius: 6px; padding: 4px 6px; background: var(--surface); }
.empty { padding: 32px; text-align: center; color: var(--muted); }
@media (max-width: 600px) {
  .head { display: none; }
  /* telefon: har qator — karta. Birinchi ustun (nomi) to'liq kenglikda, qolganlari 2 ustunda, belgilash katagi burchakda */
  .row { position: relative; flex-wrap: wrap; padding: 12px 14px; gap: 6px 12px; }
  .row:has(.chk) { padding-right: 48px; }
  .c { flex: 1 1 40% !important; white-space: normal; font-size: var(--fs-s); }
  .c::before { content: attr(data-label); display: block; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
  .row > .chk + .c, .row > .c:first-child { flex: 1 1 100% !important; font-size: var(--fs-b); }
  .row > .chk + .c::before, .row > .c:first-child::before { content: none; }
  .c.hp { display: none; }
  .chk { position: absolute; top: 12px; right: 14px; flex: none !important; }
  .chk::before { content: none; }
}
</style>
