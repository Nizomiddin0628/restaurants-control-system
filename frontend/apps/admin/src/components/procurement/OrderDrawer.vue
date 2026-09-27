<script setup lang="ts">
/**
 * Buyurtma: yangi (ta'minotchi, sana, mahsulotlar — oxirgi narx o'zi qo'yiladi) yoki mavjudini ko'rish:
 * Telegram/qo'ng'iroq bilan yuborish, tasdiqlash, qabul qilish (haqiqiy miqdor → omborga kirim), baholash.
 */
import { computed, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiIcon, UiInput, UiSelect, money, toast } from '@restopos/ui'

const props = defineProps<{ open: boolean; id?: number | null; preset?: any; meta: any }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void }>()
const O = ref<any>(null)      // mavjud buyurtma
const f = ref<any>(null)      // yangi / tahrir
const rcv = ref<Record<string, number>>({})
const busy = ref(false)
const TONE: Record<string, any> = { draft: 'neutral', sent: 'info', confirmed: 'accent', received: 'ok', cancelled: 'danger' }
const ingMap = computed(() => Object.fromEntries((props.meta?.ingredients ?? []).map((i: any) => [i.id, i])))

watch(() => [props.open, props.id], async () => {
  if (!props.open) return
  O.value = null; f.value = null
  if (props.id) { O.value = await api.get(`/procurement/orders/${props.id}`); rcv.value = Object.fromEntries(O.value.lines.map((l: any) => [l.id, l.qty])) }
  else f.value = { supplier_id: String(props.preset?.supplier_id ?? ''), branch_id: '', expected_date: props.preset?.expected_date ?? '', note: props.preset?.note ?? '',
    lines: (props.preset?.lines ?? [{ ingredient_id: '', qty: 0, price: 0 }]).map((l: any) => ({ ingredient_id: String(l.ingredient_id ?? ''), qty: l.qty ?? 0, price: l.price ?? 0 })) }
}, { immediate: true })

const total = computed(() => (f.value?.lines ?? []).reduce((s: number, l: any) => s + Number(l.qty || 0) * Number(l.price || ingMap.value[l.ingredient_id]?.price || 0), 0))
async function create() {
  busy.value = true
  try {
    const body = { ...f.value, supplier_id: Number(f.value.supplier_id), branch_id: f.value.branch_id ? Number(f.value.branch_id) : null, expected_date: f.value.expected_date || null,
      lines: f.value.lines.filter((l: any) => l.ingredient_id && Number(l.qty) > 0).map((l: any) => ({ ingredient_id: Number(l.ingredient_id), qty: Number(l.qty), price: Number(l.price) || 0 })) }
    if (!body.supplier_id) throw { detail: 'Ta\'minotchini tanlang' }
    O.value = await api.post('/procurement/orders', body); f.value = null; toast(`Buyurtma #${O.value.number} yaratildi`); emit('changed')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function status(st: string) {
  busy.value = true
  try { O.value = await api.post(`/procurement/orders/${O.value.id}/status`, { status: st }); emit('changed') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function copySend() {
  try { await navigator.clipboard.writeText(O.value.text); toast('Matn nusxalandi — Telegram yoki SMS ga qo\'ying') } catch { /* ruxsat yo'q */ }
  if (O.value.status === 'draft') await status('sent')
}
const shareUrl = computed(() => O.value ? `https://t.me/share/url?url=${encodeURIComponent(' ')}&text=${encodeURIComponent(O.value.text)}` : '#')
async function receive() {
  if (!confirm('Mahsulotlar omborga kirim qilinsinmi? Qoldiq va tannarx yangilanadi.')) return
  busy.value = true
  try { O.value = await api.post(`/procurement/orders/${O.value.id}/receive`, { lines: rcv.value }); toast('Qabul qilindi — omborga kirim qilindi'); emit('changed') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function rate(n: number) {
  try { await api.post(`/procurement/orders/${O.value.id}/rate`, { rating: n }); O.value.rating = n; toast('Baho saqlandi'); emit('changed') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function onIng(l: any) { const i = ingMap.value[l.ingredient_id]; if (i && !Number(l.price)) l.price = Math.round(i.price) }
</script>

<template>
  <UiDrawer :open="open" :title="O ? `Buyurtma #${O.number}` : 'Yangi buyurtma'" width="600px" @close="emit('close')">
    <!-- YANGI -->
    <template v-if="f">
      <div class="g2">
        <UiSelect v-model="f.supplier_id" label="Ta'minotchi" :options="[{ value: '', label: '— tanlang —' }, ...meta.suppliers.map((s: any) => ({ value: String(s.id), label: s.name }))]" />
        <UiInput v-model="f.expected_date" type="date" label="Qachon kerak" />
        <UiSelect v-if="meta.branches.length > 1" v-model="f.branch_id" label="Qaysi filialga" :options="[{ value: '', label: '— asosiy —' }, ...meta.branches.map((b: any) => ({ value: String(b.id), label: b.name }))]" />
      </div>
      <table class="ln">
        <thead><tr><th>Mahsulot</th><th>Miqdor</th><th>Narx</th><th></th></tr></thead>
        <tbody>
          <tr v-for="(l, i) in f.lines" :key="i">
            <td><select v-model="l.ingredient_id" @change="onIng(l)"><option value="">— tanlang —</option><option v-for="ig in meta.ingredients" :key="ig.id" :value="String(ig.id)">{{ ig.name }} ({{ ig.unit }})</option></select></td>
            <td><input v-model="l.qty" type="number" min="0" step="0.5" /></td>
            <td><input v-model="l.price" type="number" min="0" step="100" :placeholder="String(Math.round(ingMap[l.ingredient_id]?.price ?? 0))" /></td>
            <td><button type="button" class="x" aria-label="O'chirish" @click="f.lines.splice(i, 1)"><UiIcon name="x" :size="14" /></button></td>
          </tr>
        </tbody>
      </table>
      <UiButton size="s" variant="ghost" @click="f.lines.push({ ingredient_id: '', qty: 0, price: 0 })"><UiIcon name="plus" :size="14" /> Mahsulot</UiButton>
      <UiInput v-model="f.note" label="Izoh" placeholder="Ertalab 9 gacha olib keling" style="margin-top: 10px" />
      <p class="tot">Taxminiy summa: <b>{{ money(total) }} so'm</b></p>
    </template>

    <!-- MAVJUD -->
    <template v-else-if="O">
      <div class="hd"><b>{{ O.supplier }}</b><UiChip :tone="TONE[O.status]">{{ O.status_label }}</UiChip></div>
      <p class="mut">{{ O.expected_date ? `Kerak: ${O.expected_date.split('-').reverse().join('.')}` : '' }}{{ O.branch ? ` · ${O.branch}` : '' }}</p>
      <div class="steps">
        <span v-for="(s, i) in ['draft', 'sent', 'confirmed', 'received']" :key="s" :class="{ on: ['draft', 'sent', 'confirmed', 'received'].indexOf(O.status) >= i, x: O.status === 'cancelled' }">{{ ['Qoralama', 'Yuborildi', 'Tasdiqlandi', 'Qabul qilindi'][i] }}</span>
      </div>
      <table class="ln">
        <thead><tr><th>Mahsulot</th><th>Buyurtma</th><th v-if="['sent', 'confirmed'].includes(O.status)">Keldi</th><th v-else-if="O.status === 'received'">Qabul</th><th>Narx</th></tr></thead>
        <tbody>
          <tr v-for="l in O.lines" :key="l.id">
            <td>{{ l.name }}</td><td>{{ l.qty }} {{ l.unit }}</td>
            <td v-if="['sent', 'confirmed'].includes(O.status)"><input v-model.number="rcv[l.id]" type="number" min="0" step="0.5" /></td>
            <td v-else-if="O.status === 'received'">{{ l.received_qty }} {{ l.unit }}</td>
            <td>{{ money(l.price) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="tot">Jami: <b>{{ money(O.total) }} so'm</b><template v-if="O.status === 'received'"> · to'langan {{ money(O.paid) }}</template></p>
      <details class="txt"><summary>Ta'minotchiga yuboriladigan matn</summary><pre>{{ O.text }}</pre></details>
      <div class="acts">
        <template v-if="['draft', 'sent'].includes(O.status)">
          <a class="btn tg" :href="shareUrl" target="_blank" rel="noopener" @click="O.status === 'draft' && status('sent')">✈️ Telegram</a>
          <a v-if="O.phone" class="btn" :href="`tel:${O.phone}`">📞 Qo'ng'iroq</a>
          <UiButton size="s" variant="ghost" @click="copySend()">📋 Nusxalash</UiButton>
        </template>
        <UiButton v-if="O.status === 'sent'" size="s" variant="ghost" :disabled="busy" @click="status('confirmed')">✓ Tasdiqladi</UiButton>
        <UiButton v-if="['sent', 'confirmed'].includes(O.status)" variant="brand" :loading="busy" @click="receive()">📦 Qabul qilish (omborga)</UiButton>
        <UiButton v-if="['draft', 'sent', 'confirmed'].includes(O.status)" size="s" variant="danger" :disabled="busy" @click="status('cancelled')">Bekor</UiButton>
      </div>
      <div v-if="O.status === 'received'" class="rate"><span>Sifat va o'z vaqtida kelishi:</span>
        <button v-for="n in 5" :key="n" type="button" :class="{ on: (O.rating ?? 0) >= n }" :aria-label="`${n} yulduz`" @click="rate(n)">★</button></div>
    </template>
    <template v-if="f" #footer><UiButton variant="ghost" @click="emit('close')">Bekor</UiButton><UiButton variant="brand" :loading="busy" @click="create()">Buyurtma yaratish</UiButton></template>
  </UiDrawer>
</template>

<style scoped>
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ln { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: var(--fs-s); }
.ln th { text-align: left; font-size: var(--fs-xs); color: var(--muted); padding: 6px 4px; border-bottom: 1px solid var(--line); }
.ln td { padding: 6px 4px; border-bottom: 1px solid var(--line-2); }
.ln select, .ln input { width: 100%; min-height: 38px; border: 1px solid var(--line); border-radius: 8px; padding: 0 8px; font: inherit; font-size: var(--fs-s); background: var(--surface); color: var(--ink); box-sizing: border-box; }
.ln input { max-width: 110px; }
.x { border: 0; background: transparent; color: var(--muted); cursor: pointer; }
.tot { margin: 8px 0; font-size: var(--fs-s); } .mut { color: var(--muted); font-size: var(--fs-s); margin: 4px 0 10px; }
.hd { display: flex; justify-content: space-between; align-items: center; gap: 10px; } .hd b { font-size: var(--fs-l); }
.steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
.steps span { text-align: center; padding: 6px 4px; border-radius: 8px; background: var(--surface-2); font-size: 11px; font-weight: 700; color: var(--muted); }
.steps span.on { background: var(--ok-tint); color: var(--ok); } .steps span.x { text-decoration: line-through; }
.txt summary { cursor: pointer; color: var(--accent); font-weight: 700; font-size: var(--fs-s); } .txt pre { white-space: pre-wrap; background: var(--surface-2); padding: 10px; border-radius: 10px; font: inherit; font-size: var(--fs-s); }
.acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.btn { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; border: 1px solid var(--line); border-radius: 10px; color: var(--ink); text-decoration: none; font-weight: 700; font-size: var(--fs-s); }
.btn.tg { background: #229ED9; color: #fff; border-color: #229ED9; }
.rate { display: flex; align-items: center; gap: 4px; margin-top: 14px; font-size: var(--fs-s); } .rate span { margin-right: 6px; color: var(--muted); }
.rate button { border: 0; background: transparent; font-size: 26px; color: var(--line); cursor: pointer; padding: 0 2px; } .rate button.on { color: #F5B301; }
@media (max-width: 600px) { .g2 { grid-template-columns: 1fr; } }
</style>
