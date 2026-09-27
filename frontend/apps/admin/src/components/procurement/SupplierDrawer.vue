<script setup lang="ts">
/** Ta'minotchi: tahrirlash formasi yoki kartasi (narxlari, buyurtmalari, to'lovlari, qarzi). */
import { ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiInput, UiSelect, UiToggle, money, toast } from '@restopos/ui'

const props = defineProps<{ open: boolean; id?: number | null; edit?: boolean; meta: any }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void; (e: 'order', v: any): void; (e: 'pay', v: any): void }>()
const S = ref<any>(null)
const f = ref<any>(null)
const busy = ref(false)
const blank = () => ({ name: '', phone: '+998', note: '', is_active: true, kind: 'company', categories: [] as string[], market_id: '', contact_name: '', telegram: '', address: '',
  delivers: false, min_order: '', terms: 'cash', credit_days: 0, photo_url: '' })

watch(() => [props.open, props.id, props.edit], async () => {
  if (!props.open) return
  S.value = null; f.value = null
  if (props.id) S.value = await api.get(`/procurement/suppliers/${props.id}`)
  if (props.edit) f.value = S.value ? { ...blank(), ...S.value, market_id: S.value.market?.id ? String(S.value.market.id) : '', categories: S.value.categories.map((c: any) => c.code) } : blank()
}, { immediate: true })

function toggleCat(c: string) { const s = new Set(f.value.categories); s.has(c) ? s.delete(c) : s.add(c); f.value.categories = [...s] }
async function save() {
  busy.value = true
  const b = { ...f.value, market_id: f.value.market_id ? Number(f.value.market_id) : null, credit_days: Number(f.value.credit_days) || 0 }
  try { S.value?.id ? await api.put(`/procurement/suppliers/${S.value.id}`, b) : await api.post('/procurement/suppliers', b); toast('Saqlandi'); emit('changed'); emit('close') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
const d = (s: string) => s.split('-').reverse().join('.')
</script>

<template>
  <UiDrawer :open="open" :title="edit ? (S ? 'Ta\'minotchini tahrirlash' : 'Yangi ta\'minotchi') : (S?.name ?? '')" width="600px" @close="emit('close')">
    <template v-if="f">
      <UiInput v-model="f.name" label="Nomi" placeholder="Masalan: Aziz aka — mol go'shti" />
      <div class="kinds"><button v-for="k in meta.supplier_kinds" :key="k.code" type="button" :class="{ on: f.kind === k.code }" @click="f.kind = k.code">{{ k.label }}</button></div>
      <div class="fl"><span>Nima sotadi?</span>
        <div class="cats"><button v-for="c in meta.categories" :key="c.code" type="button" :class="{ on: f.categories.includes(c.code) }" @click="toggleCat(c.code)">{{ c.emoji }} {{ c.name }}</button></div></div>
      <div class="g2">
        <UiInput v-model="f.phone" label="Telefon" type="tel" />
        <UiInput v-model="f.telegram" label="Telegram" placeholder="@username" />
        <UiInput v-model="f.contact_name" label="Kontakt shaxs" />
        <UiSelect v-model="f.market_id" label="Qaysi bozorda" :options="[{ value: '', label: '— bozorda emas —' }, ...meta.markets.map((m: any) => ({ value: String(m.id), label: m.name }))]" />
        <UiSelect v-model="f.terms" label="To'lov sharti" :options="meta.terms.map((t: any) => ({ value: t.code, label: t.label }))" />
        <UiInput v-if="f.terms === 'credit'" v-model="f.credit_days" type="number" label="Nasiya muddati (kun)" />
        <UiInput v-model="f.min_order" label="Eng kam buyurtma" placeholder="20 kg dan" />
        <UiInput v-model="f.address" label="Manzil / joy" placeholder="Go'sht qatori, 12-do'kon" />
      </div>
      <div class="tg2"><UiToggle v-model="f.delivers" label="O'zi yetkazib beradi" /><UiToggle v-model="f.is_active" label="Faol" /></div>
      <UiInput v-model="f.note" label="Izoh" />
    </template>

    <template v-else-if="S">
      <div class="hd">
        <div class="cc"><UiChip tone="info">{{ S.kind_label }}</UiChip><UiChip v-for="c in S.categories" :key="c.code" tone="neutral">{{ c.emoji }} {{ c.name }}</UiChip></div>
        <p>{{ S.rating ? `★ ${S.rating} (${S.reviews} baho)` : 'Hali baholanmagan' }} · {{ S.delivers ? '🚚 yetkazib beradi' : '🧍 o\'zimiz olib kelamiz' }}{{ S.market ? ` · 📍 ${S.market.name}` : '' }}</p>
      </div>
      <div class="acts">
        <a v-if="S.phone" class="btn" :href="`tel:${S.phone}`">📞 {{ S.phone }}</a>
        <a v-if="S.telegram_url" class="btn tg" :href="S.telegram_url" target="_blank" rel="noopener">✈️ Telegram</a>
        <UiButton v-if="meta.can_edit" size="s" variant="brand" @click="emit('order', { supplier_id: S.id })">+ Buyurtma</UiButton>
        <UiButton v-if="meta.can_pay && S.debt" size="s" variant="ghost" @click="emit('pay', { supplier_id: S.id, amount: S.debt })">To'lash</UiButton>
      </div>
      <div v-if="S.debt" class="debt" :class="{ bad: S.overdue }">Qarzimiz: <b>{{ money(S.debt) }} so'm</b>{{ S.overdue ? ' — muddati o\'tgan!' : '' }}</div>
      <h4>Narxlari</h4>
      <ul class="pl"><li v-for="p in S.prices" :key="p.ingredient_id"><span>{{ p.ingredient }}</span><b>{{ money(p.price) }}/{{ p.unit }}</b><small>{{ d(p.date) }}</small></li></ul>
      <p v-if="!S.prices.length" class="mut">Narx kiritilmagan.</p>
      <h4>Buyurtmalar</h4>
      <ul class="pl"><li v-for="o in S.orders" :key="o.id"><span>#{{ o.number }} · {{ o.status_label }}</span><b>{{ money(o.total) }}</b><small>{{ d(o.created_at.slice(0, 10)) }}</small></li></ul>
      <h4 v-if="S.payments.length">To'lovlar</h4>
      <ul class="pl"><li v-for="p in S.payments" :key="p.id"><span>{{ p.method }}{{ p.note ? ` · ${p.note}` : '' }}</span><b>{{ money(p.amount) }}</b><small>{{ d(p.date) }}</small></li></ul>
    </template>
    <template #footer>
      <template v-if="f"><UiButton variant="ghost" @click="emit('close')">Bekor</UiButton><UiButton variant="brand" :loading="busy" @click="save()">Saqlash</UiButton></template>
    </template>
  </UiDrawer>
</template>

<style scoped>
.kinds { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 12px 0; }
.kinds button, .cats button { min-height: 40px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink); padding: 0 8px; }
.kinds button.on, .cats button.on { border-color: var(--accent); background: var(--accent-tint); color: var(--accent); }
.fl { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; } .fl > span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.cats { display: flex; flex-wrap: wrap; gap: 6px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tg2 { display: flex; gap: 20px; margin: 12px 0; flex-wrap: wrap; }
.hd p { margin: 8px 0; color: var(--ink-2); font-size: var(--fs-s); } .cc { display: flex; gap: 6px; flex-wrap: wrap; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; }
.btn { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; border: 1px solid var(--line); border-radius: 10px; color: var(--ink); text-decoration: none; font-weight: 700; font-size: var(--fs-s); }
.btn.tg { background: #229ED9; color: #fff; border-color: #229ED9; }
.debt { margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: var(--warn-tint); font-size: var(--fs-s); } .debt.bad { background: var(--danger-tint); }
h4 { margin: 16px 0 6px; font-size: var(--fs-s); }
.pl { list-style: none; margin: 0; padding: 0; } .pl li { display: grid; grid-template-columns: 1fr auto 80px; gap: 8px; padding: 7px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); }
.pl small { color: var(--muted); text-align: right; } .mut { color: var(--muted); font-size: var(--fs-s); }
@media (max-width: 600px) { .g2, .kinds { grid-template-columns: 1fr 1fr; } }
</style>
