<script setup lang="ts">
/** Bo'limlar: nomi, ikonka, rang, izoh. Lavozimi bor bo'limni o'chirib bo'lmaydi. */
import { ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiDrawer, UiIcon, toast } from '@restopos/ui'

const props = defineProps<{ open: boolean; departments: any[] }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void }>()
const rows = ref<any[]>([])
const COLORS = ['#374151', '#E4572E', '#2F80ED', '#F2994A', '#27AE60', '#9B51E0', '#C9A227', '#219653', '#56A3C9', '#D0485A']
watch(() => [props.open, props.departments], () => { rows.value = props.departments.map(d => ({ ...d })) }, { immediate: true })

async function save(d: any) {
  try {
    const b = { name: d.name, icon: d.icon, color: d.color, description: d.description ?? '' }
    const r = d.id ? await api.put(`/ops/departments/${d.id}`, b) : await api.post('/ops/departments', b)
    Object.assign(d, r); toast('Saqlandi'); emit('changed')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function remove(d: any, i: number) {
  if (!d.id) { rows.value.splice(i, 1); return }
  if (!confirm(`«${d.name}» bo'limi o'chirilsinmi?`)) return
  try { await api.del(`/ops/departments/${d.id}`); rows.value.splice(i, 1); emit('changed') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <UiDrawer :open="open" title="Bo'limlar" width="520px" @close="emit('close')">
    <p class="tip">Bo'lim — lavozimlar guruhi (Oshxona, Zal va servis, Kassa…). Rangi tuzilmada va kartochkalarda ko'rinadi.</p>
    <div v-for="(d, i) in rows" :key="d.id ?? `n${i}`" class="dr" :style="{ '--c': d.color }">
      <input v-model="d.icon" class="ic" maxlength="4" aria-label="Ikonka" />
      <div class="mid">
        <input v-model="d.name" class="nm" placeholder="Bo'lim nomi" />
        <input v-model="d.description" class="ds" placeholder="Qisqa izoh (ixtiyoriy)" />
        <div class="cl"><button v-for="c in COLORS" :key="c" type="button" :style="{ background: c }" :class="{ on: d.color === c }" :aria-label="c" @click="d.color = c"></button></div>
      </div>
      <div class="bt">
        <UiButton size="s" variant="brand" @click="save(d)">Saqlash</UiButton>
        <button type="button" class="x" aria-label="O'chirish" @click="remove(d, i)"><UiIcon name="trash" :size="15" /></button>
      </div>
      <small v-if="d.positions" class="cnt">{{ d.positions }} lavozim</small>
    </div>
    <UiButton variant="ghost" @click="rows.push({ name: '', icon: '🏢', color: COLORS[rows.length % COLORS.length], description: '' })"><UiIcon name="plus" :size="14" /> Bo'lim qo'shish</UiButton>
  </UiDrawer>
</template>

<style scoped>
.tip { margin: 0 0 12px; font-size: var(--fs-xs); color: var(--muted); }
.dr { display: grid; grid-template-columns: 48px 1fr auto; gap: 10px; padding: 12px; border: 1px solid var(--line); border-left: 5px solid var(--c); border-radius: 12px; margin-bottom: 10px; position: relative; }
.ic { width: 48px; height: 48px; font-size: 24px; text-align: center; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.mid { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.nm, .ds { border: 1px solid var(--line); border-radius: 8px; padding: 0 10px; min-height: 36px; font: inherit; background: var(--surface); color: var(--ink); min-width: 0; }
.nm { font-weight: 700; } .ds { font-size: var(--fs-s); }
.cl { display: flex; gap: 6px; flex-wrap: wrap; } .cl button { width: 22px; height: 22px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; } .cl button.on { border-color: var(--ink); }
.bt { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }
.x { border: 0; background: transparent; color: var(--muted); cursor: pointer; }
.cnt { position: absolute; right: 12px; bottom: 8px; font-size: 11px; color: var(--muted); }
</style>
