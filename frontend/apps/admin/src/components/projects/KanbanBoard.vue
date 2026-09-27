<script setup lang="ts">
/** Loyiha vazifalari kanbani: 4 ustun, sudrab tashlash (telefonda — ustunlar yonma-yon suriladi). */
import { ref, watch } from 'vue'
import draggable from 'vuedraggable'
import { api } from '@restopos/api'
import { UiAvatar, UiChip, toast } from '@restopos/ui'
import { COLS, PRIO, dShort, left } from './pm'

const props = defineProps<{ tasks: any[]; showProject?: boolean; canAdd?: boolean }>()
const emit = defineEmits<{ (e: 'open', t: any): void; (e: 'moved'): void; (e: 'add', status: string): void }>()
const cols = ref<Record<string, any[]>>({})
watch(() => props.tasks, (ts) => {
  const c: Record<string, any[]> = {}
  for (const k of COLS) c[k.code] = []
  for (const t of ts ?? []) (c[t.status] ??= []).push(t)
  cols.value = c
}, { immediate: true, deep: true })

async function onChange(status: string, evt: any) {
  const el = evt?.added?.element ?? evt?.moved?.element
  if (!el) return
  try {
    await api.post(`/projects/tasks/${el.id}/move`, { status, order: cols.value[status].map((x: any) => x.id) })
    if (evt.added) { el.status = status; toast(status === 'done' ? '✅ Bajarildi' : `→ ${COLS.find(c => c.code === status)?.label}`) }
    emit('moved')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); emit('moved') }
}
const canDrag = (e: any) => e.draggedContext.element.can_move !== false
</script>

<template>
  <div class="kb">
    <section v-for="c in COLS" :key="c.code" class="col">
      <header :style="{ '--c': c.color }"><i></i><b>{{ c.label }}</b><span>{{ cols[c.code]?.length ?? 0 }}</span></header>
      <draggable v-model="cols[c.code]" group="ptasks" item-key="id" class="cards" :animation="150" ghost-class="ghost" :move="canDrag"
                 :delay="120" :delay-on-touch-only="true" @change="onChange(c.code, $event)">
        <template #item="{ element: t }">
          <article class="card" :class="{ late: t.overdue, locked: t.can_move === false }" @click="emit('open', t)">
            <div v-if="showProject" class="pj"><i :style="{ background: t.color }"></i>{{ t.project_code }} · {{ t.project }}</div>
            <h4>{{ t.title }}</h4>
            <div class="meta">
              <UiChip v-if="t.priority === 'high' || t.priority === 'critical'" :tone="PRIO[t.priority].tone">{{ PRIO[t.priority].label }}</UiChip>
              <span v-if="t.due" :class="{ bad: t.overdue }">📅 {{ dShort(t.due) }} · {{ left(t.days_left, t.status === 'done') }}</span>
              <span v-if="t.check_total">☑ {{ t.check_done }}/{{ t.check_total }}</span>
            </div>
            <div class="ft">
              <UiAvatar :name="t.assignee?.name" :src="t.assignee?.avatar" :size="22" />
              <span>{{ t.assignee?.name?.split(' ')[0] ?? 'Tayinlanmagan' }}</span>
            </div>
          </article>
        </template>
      </draggable>
      <button v-if="canAdd" type="button" class="add" @click="emit('add', c.code)">＋ Vazifa</button>
    </section>
  </div>
</template>

<style scoped>
.kb { display: grid; grid-template-columns: repeat(4, minmax(220px, 1fr)); gap: 12px; align-items: start; overflow-x: auto; padding-bottom: 6px; }
.col { background: var(--surface-2); border-radius: 16px; padding: 10px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
header { display: flex; align-items: center; gap: 8px; padding: 2px 4px; font-size: var(--fs-s); }
header i { width: 10px; height: 10px; border-radius: 50%; background: var(--c); } header span { margin-left: auto; color: var(--muted); font-weight: 700; }
.cards { display: flex; flex-direction: column; gap: 8px; min-height: 60px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; cursor: grab; display: flex; flex-direction: column; gap: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
.card:hover { border-color: var(--accent); } .card.late { border-left: 3px solid var(--danger); } .card.locked { cursor: pointer; }
.pj { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted); font-weight: 700; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.pj i { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
h4 { margin: 0; font-size: var(--fs-s); line-height: 1.35; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 11px; color: var(--muted); } .bad { color: var(--danger); font-weight: 700; }
.ft { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--ink-2); }
.ghost { opacity: .4; }
.add { border: 1px dashed var(--line); background: transparent; border-radius: 10px; min-height: 36px; font: inherit; font-size: var(--fs-s); color: var(--muted); cursor: pointer; font-weight: 700; }
.add:hover { color: var(--accent); border-color: var(--accent); }
@media (max-width: 900px) { .kb { grid-template-columns: repeat(4, 80%); scroll-snap-type: x mandatory; } .col { scroll-snap-align: start; } }
</style>
