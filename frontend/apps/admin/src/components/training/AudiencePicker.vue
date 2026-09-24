<script setup lang="ts">
/** Kim ko'radi: hamma · rollar · lavozimlar · aniq xodimlar. */
import { computed, ref } from 'vue'
import { UiToggle } from '@restopos/ui'

type Aud = { roles: string[]; positions: number[]; user_ids: string[]; everyone: boolean }
const props = defineProps<{ modelValue: Aud; meta: any }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: Aud): void }>()
const q = ref('')
const v = computed(() => props.modelValue)
const set = (patch: Partial<Aud>) => emit('update:modelValue', { ...v.value, ...patch })
const toggle = <T,>(arr: T[], x: T) => (arr.includes(x) ? arr.filter(a => a !== x) : [...arr, x])
const found = computed(() => {
  const s = q.value.trim().toLowerCase()
  return s ? props.meta.users.filter((u: any) => !v.value.user_ids.includes(u.id) && (u.full_name.toLowerCase().includes(s) || u.phone.includes(s))).slice(0, 6) : []
})
const picked = computed(() => props.meta.users.filter((u: any) => v.value.user_ids.includes(u.id)))
</script>

<template>
  <div class="aud">
    <UiToggle :model-value="v.everyone" label="Barcha xodimlar" @update:model-value="(x) => set({ everyone: x })" />
    <template v-if="!v.everyone">
      <div class="grp"><small>Rollar</small>
        <div class="chips"><button v-for="r in meta.roles" :key="r.code" type="button" class="ch" :class="{ on: v.roles.includes(r.code) }" @click="set({ roles: toggle(v.roles, r.code) })">{{ r.name }}</button></div>
      </div>
      <div v-if="meta.positions.length" class="grp"><small>Lavozimlar</small>
        <div class="chips"><button v-for="p in meta.positions" :key="p.id" type="button" class="ch" :class="{ on: v.positions.includes(p.id) }" @click="set({ positions: toggle(v.positions, p.id) })">{{ p.name }}</button></div>
      </div>
    </template>
    <div class="grp"><small>Aniq xodimlar {{ v.everyone ? '' : '(qo\'shimcha)' }}</small>
      <div class="chips">
        <span v-for="u in picked" :key="u.id" class="ch on">{{ u.full_name }} <button type="button" aria-label="Olib tashlash" @click="set({ user_ids: v.user_ids.filter(x => x !== u.id) })">✕</button></span>
      </div>
      <input v-model="q" class="in" placeholder="Ism yoki telefon bo'yicha qidirish" />
      <div v-if="found.length" class="drop">
        <button v-for="u in found" :key="u.id" type="button" @click="set({ user_ids: [...v.user_ids, u.id] }); q = ''">{{ u.full_name }} <small>{{ u.phone }}</small></button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aud { display: flex; flex-direction: column; gap: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-2); }
.grp { display: flex; flex-direction: column; gap: 6px; position: relative; } .grp > small { font-weight: 700; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.ch { min-height: 34px; padding: 0 12px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface); font: inherit; font-size: 13px; font-weight: 700; color: var(--ink-2); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.ch.on { background: var(--tr-gold-tint, #F6F0E4); border-color: var(--tr-gold, #A8894F); color: var(--ink); }
.ch button { border: 0; background: none; cursor: pointer; color: var(--muted); padding: 0; }
.in { min-height: 40px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); }
.drop { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); overflow: hidden; }
.drop button { text-align: left; padding: 10px 12px; border: 0; background: none; font: inherit; cursor: pointer; color: var(--ink); display: flex; justify-content: space-between; }
.drop button:hover { background: var(--surface-3); } .drop small { color: var(--muted); }
</style>
