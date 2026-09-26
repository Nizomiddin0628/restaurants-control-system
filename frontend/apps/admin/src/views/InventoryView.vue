<script setup lang="ts">
/**
 * Ombor va tannarx: Xomashyo (narx/qoldiq) · Kirim (bozorlik) · Tex-karta (taom → xomashyo → tannarx jonli) · Harakatlar.
 * Bozor narxi o'zgardi → kirim kiritiladi → barcha taomlar tannarxi o'zi yangilanadi (backend).
 * «Xarid rejasi» (forecast moduli): bayram/ob-havo/hafta kuni hisobga olingan ehtiyoj → bir bosishda kirimga.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import { useRoute } from 'vue-router'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'

const a = useAuth(), ui = useUi(), route = useRoute()
type Tab = 'ingredients' | 'purchase' | 'recipes' | 'movements' | 'plan'
const TAB_Q: Record<string, Tab> = { plan: 'plan', purchase: 'purchase', purchases: 'purchase', stock: 'ingredients', ingredients: 'ingredients', recipes: 'recipes', movements: 'movements' }
const hasFc = computed(() => a.hasModule('forecast') && a.can('forecast.view'))
const tab = ref<Tab>(TAB_Q[String(route.query.tab ?? '')] ?? 'recipes')
if (tab.value === 'plan' && !hasFc.value) tab.value = 'recipes'
const summary = ref<any>(null)
const ingredients = ref<any[]>([])
const recipes = ref<any[]>([])
const purchases = ref<any[]>([])
const movements = ref<any[]>([])
const suppliers = ref<any[]>([])
const q = ref('')
const onlyLow = ref(false)
const canEdit = computed(() => a.can('inventory.edit'))

const UNIT: Record<string, string> = { kg: 'kg', l: 'l', dona: 'dona' }
const SUB: Record<string, string> = { kg: 'g', l: 'ml', dona: 'dona' }

async function load() {
  summary.value = await api.get('/inventory/summary')
  ingredients.value = await api.get('/inventory/ingredients', { q: q.value || undefined, low: onlyLow.value || undefined })
  if (tab.value === 'recipes') recipes.value = await api.get('/inventory/recipes')
  if (tab.value === 'purchase') { purchases.value = await api.get('/inventory/purchases'); suppliers.value = await api.get('/inventory/suppliers') }
  if (tab.value === 'movements') movements.value = await api.get('/inventory/movements')
  if (tab.value === 'plan') await loadPlan()
}
onMounted(async () => {
  if (hasFc.value) fc.value = await api.get('/forecast/overview').catch(() => null)
  await load()
})
watch([tab, onlyLow], load)

// ---- xarid rejasi (bayram / ob-havo prognozi)
const fc = ref<any>(null)
const planSel = ref<string>(route.query.holiday ? `h${route.query.holiday}` : '7')
const plan = ref<any>(null)
const planLoading = ref(false)
const onlyBuy = ref(true)
const planOpts = computed(() => [
  { value: '7', label: 'Keyingi 7 kun' }, { value: '14', label: 'Keyingi 14 kun' },
  ...(fc.value?.upcoming ?? []).filter((h: any) => !h.is_past).map((h: any) => ({ value: `h${h.id}`, label: `🎉 ${h.name.uz} — ${h.date.split('-').reverse().join('.')}` })),
])
async function loadPlan() {
  planLoading.value = true
  try {
    const v = planSel.value
    plan.value = await api.get('/forecast/plan', v.startsWith('h') ? { holiday_id: Number(v.slice(1)) } : { days: Number(v) })
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); plan.value = null } finally { planLoading.value = false }
}
watch(planSel, () => { if (tab.value === 'plan') loadPlan() })
function openPlan(id: number) { planSel.value = `h${id}`; if (tab.value !== 'plan') tab.value = 'plan'; else loadPlan() }
const planLines = computed(() => (plan.value?.lines ?? []).filter((l: any) => !onlyBuy.value || l.buy > 0))
const fmtD = (x: string) => x.split('-').reverse().join('.')
const WD = ['Ya', 'Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh']
const wd = (x: string) => WD[new Date(x + 'T00:00:00').getDay()]
const num = (v: number) => String(+v.toFixed(2)).replace('.', ',')
function toPurchase(supplierId?: number | null, all = true) {
  const src = (plan.value?.lines ?? []).filter((l: any) => l.buy > 0 && (all || (l.supplier_id ?? null) === (supplierId ?? null)))
  if (!src.length) return
  pur.value = {
    supplier_id: !all && supplierId ? String(supplierId) : '',
    note: plan.value.holiday ? `${plan.value.holiday.name.uz} uchun xarid` : `Xarid rejasi ${fmtD(plan.value.start)}–${fmtD(plan.value.end)}`,
    lines: src.map((l: any) => ({ ingredient_id: String(l.ingredient_id), qty: l.buy, unit_price: l.price })),
  }
  tab.value = 'purchase'
  toast('Qatorlar kirim formasiga qo\'yildi — narxni tekshirib, «Kirimni o\'tkazish»ni bosing')
}
async function copyList() {
  const lines = (plan.value?.lines ?? []).filter((l: any) => l.buy > 0)
  const txt = [`🛒 Xarid ro'yxati${plan.value.holiday ? ` — ${plan.value.holiday.name.uz}` : ''} (${fmtD(plan.value.buy_by)} gacha)`,
    ...lines.map((l: any) => `• ${t(l.name, ui.lang)} — ${num(l.buy)} ${UNIT[l.unit]}`)].join('\n')
  try { await navigator.clipboard.writeText(txt); toast('Ro\'yxat nusxalandi — Telegram\'da ta\'minotchiga yuboring') } catch { toast('Nusxalab bo\'lmadi', 'danger') }
}

// ---- xomashyo
const ingDrawer = ref(false)
const ing = ref<any>(null)
function openIng(i?: any) {
  ing.value = i ? { ...i, name: { ...i.name } } : { name: { uz: '', ru: '', en: '' }, category: '', unit: 'kg', price: 0, min_stock: 0, is_active: true }
  ingDrawer.value = true
}
async function saveIng() {
  const body = { ...ing.value, price: Number(ing.value.price), min_stock: Number(ing.value.min_stock) }
  try {
    ing.value.id ? await api.put(`/inventory/ingredients/${ing.value.id}`, body) : await api.post('/inventory/ingredients', body)
    ingDrawer.value = false; await load(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function removeIng(i: any) {
  if (!confirm(`«${t(i.name, ui.lang)}» o'chirilsinmi?`)) return
  try { await api.del(`/inventory/ingredients/${i.id}`); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const adj = ref<any>(null)
async function saveAdjust() {
  try { await api.post(`/inventory/ingredients/${adj.value.id}/adjust`, { qty: Number(adj.value.qty), kind: adj.value.kind, note: adj.value.note }); adj.value = null; await load(); toast('Qoldiq yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- kirim
const pur = ref<{ supplier_id: string; note: string; lines: { ingredient_id: string; qty: number; unit_price: number }[] }>({ supplier_id: '', note: '', lines: [{ ingredient_id: '', qty: 0, unit_price: 0 }] })
const purTotal = computed(() => pur.value.lines.reduce((s, l) => s + Number(l.qty) * Number(l.unit_price), 0))
function onLineIng(l: any) { const i = ingredients.value.find(x => String(x.id) === String(l.ingredient_id)); if (i && !l.unit_price) l.unit_price = i.price }
async function savePurchase() {
  const lines = pur.value.lines.filter(l => l.ingredient_id && Number(l.qty) > 0).map(l => ({ ingredient_id: Number(l.ingredient_id), qty: Number(l.qty), unit_price: Number(l.unit_price) }))
  if (!lines.length) { toast('Kamida bitta qator kiriting', 'danger'); return }
  try {
    await api.post('/inventory/purchases', { lines, supplier_id: pur.value.supplier_id ? Number(pur.value.supplier_id) : null, note: pur.value.note })
    pur.value = { supplier_id: '', note: '', lines: [{ ingredient_id: '', qty: 0, unit_price: 0 }] }
    await load(); toast('Kirim o\'tkazildi — tannarxlar yangilandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- tex-karta
const recipe = ref<any>(null)
const recipeSaving = ref(false)
async function openRecipe(productId: number) { recipe.value = await api.get(`/inventory/recipes/${productId}`) }
const liveCost = computed(() => {
  if (!recipe.value) return 0
  const total = recipe.value.lines.reduce((s: number, l: any) => {
    const i = ingredients.value.find(x => x.id === Number(l.ingredient_id)); if (!i) return s
    const base = i.unit === 'dona' ? Number(l.qty) : Number(l.qty) / 1000
    return s + base * Number(i.price) * (1 + Number(l.waste_percent || 0) / 100)
  }, 0)
  return Math.round(total / (Number(recipe.value.yield_qty) || 1))
})
const liveFc = computed(() => recipe.value?.price ? Math.round(1000 * liveCost.value / recipe.value.price) / 10 : null)
function addLine() { recipe.value.lines.push({ ingredient_id: ingredients.value[0]?.id ?? '', qty: 0, waste_percent: 0 }) }
async function saveRecipe() {
  recipeSaving.value = true
  try {
    const lines = recipe.value.lines.filter((l: any) => l.ingredient_id && Number(l.qty) > 0).map((l: any) => ({ ingredient_id: Number(l.ingredient_id), qty: Number(l.qty), waste_percent: Number(l.waste_percent || 0) }))
    recipe.value = await api.put(`/inventory/recipes/${recipe.value.product_id}`, { yield_qty: Number(recipe.value.yield_qty) || 1, note: recipe.value.note, lines })
    recipes.value = await api.get('/inventory/recipes'); toast(`Tannarx: ${money(recipe.value.cost)}`)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { recipeSaving.value = false }
}
const fcTone = (v: number | null) => v == null ? 'neutral' : v <= 32 ? 'ok' : v <= 40 ? 'warn' : 'danger'
const fmtDT = (s: string) => new Date(s).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <div class="inv">
    <div v-if="summary" class="kpis">
      <div class="kpi"><b>{{ summary.ingredients }}</b><span>Xomashyo turi</span></div>
      <div class="kpi" :class="{ warn: summary.low }"><b>{{ summary.low }}</b><span>Tugayapti</span></div>
      <div class="kpi"><b>{{ money(summary.stock_value) }}</b><span>Ombor qiymati</span></div>
      <div class="kpi"><b>{{ summary.recipes }}</b><span>Tex-karta</span></div>
      <div class="kpi" :class="{ warn: summary.products_without_recipe }"><b>{{ summary.products_without_recipe }}</b><span>Tex-kartasiz taom</span></div>
    </div>

    <HolidayAlert v-for="al in (fc?.alerts ?? [])" :key="al.id" :a="al" @plan="openPlan" />

    <nav class="tabs">
      <button v-if="hasFc" :class="{ on: tab === 'plan' }" @click="tab = 'plan'"><UiIcon name="calendar" :size="15" /> Xarid rejasi</button>
      <button :class="{ on: tab === 'recipes' }" @click="tab = 'recipes'"><UiIcon name="book" :size="15" /> Tex-karta va tannarx</button>
      <button :class="{ on: tab === 'ingredients' }" @click="tab = 'ingredients'"><UiIcon name="box" :size="15" /> Xomashyo va qoldiq</button>
      <button :class="{ on: tab === 'purchase' }" @click="tab = 'purchase'"><UiIcon name="truck" :size="15" /> Kirim (bozorlik)</button>
      <button :class="{ on: tab === 'movements' }" @click="tab = 'movements'"><UiIcon name="list" :size="15" /> Harakatlar</button>
    </nav>

    <!-- XARID REJASI -->
    <div v-if="tab === 'plan'" class="plan">
      <div class="p-top">
        <div class="seg-sel"><UiSelect v-model="planSel" :options="planOpts" /></div>
        <p class="p-how">Prognoz: oxirgi {{ plan?.history.days ?? '…' }} kunlik savdo × hafta kuni × bayram × ob-havo → tex-karta bo'yicha xomashyo.</p>
      </div>
      <UiEmpty v-if="plan && !plan.history.enough" title="Savdo tarixi yetarli emas" text="Prognoz uchun kamida 7 kunlik savdo va tex-kartalar kerak. Hozircha faqat minimal qoldiqdan kam xomashyolar ko'rsatiladi." />
      <template v-if="plan">
        <div class="kpis p-k">
          <div class="kpi"><b>{{ fmtD(plan.start) }} – {{ fmtD(plan.end) }}</b><span>{{ plan.days }} kun{{ plan.holiday ? ' · ' + plan.holiday.name.uz : '' }}</span></div>
          <div class="kpi"><b>{{ money(plan.revenue_forecast) }}</b><span>Kutilayotgan savdo · odatdagidan {{ plan.revenue_normal ? ((plan.revenue_forecast >= plan.revenue_normal ? '+' : '') + Math.round(100 * (plan.revenue_forecast - plan.revenue_normal) / plan.revenue_normal)) : 0 }}%</span></div>
          <div class="kpi" :class="{ warn: plan.short_count }"><b>{{ plan.short_count }}</b><span>Xomashyo xarid qilinadi</span></div>
          <div class="kpi"><b>{{ money(plan.total_cost) }}</b><span>Taxminiy xarid summasi</span></div>
          <div class="kpi"><b>{{ fmtD(plan.buy_by) }}</b><span>Qachongacha xarid qilish</span></div>
        </div>
        <div class="days">
          <div v-for="d in plan.daily" :key="d.date" class="day" :class="{ hol: d.holiday }" :title="d.holiday ?? ''">
            <small>{{ wd(d.date) }} {{ d.date.slice(8) }}</small>
            <span class="e">{{ d.holiday ? '🎉' : (d.weather ?? '·') }}</span>
            <b :class="d.factor > 1.05 ? 'up' : d.factor < 0.95 ? 'dn' : ''">{{ d.factor > 1 ? '+' : '' }}{{ Math.round((d.factor - 1) * 100) }}%</b>
          </div>
        </div>
        <div class="split">
          <UiCard title="Nima xarid qilish kerak" :subtitle="`Kerak = prognoz sarfi + minimal qoldiq − hozirgi qoldiq`" :padded="false">
            <template #actions>
              <button class="chip-btn" :class="{ on: onlyBuy }" @click="onlyBuy = !onlyBuy">Faqat xarid kerak</button>
            </template>
            <div class="lst">
              <div class="l-h pl"><span>Xomashyo</span><span>Qoldiq</span><span>Kerak bo'ladi</span><span>Yetadi</span><span>Xarid</span><span>Summa</span></div>
              <div v-for="l in planLines" :key="l.ingredient_id" class="l-r pl" :class="{ buy: l.buy > 0 }">
                <span class="nm"><b>{{ t(l.name, ui.lang) }}</b><small>{{ l.supplier ?? 'bozor' }}{{ l.category ? ' · ' + l.category : '' }}</small></span>
                <span>{{ num(l.stock) }} {{ UNIT[l.unit] }}</span>
                <span class="mut">{{ num(l.need) }} {{ UNIT[l.unit] }}</span>
                <span :class="{ danger: l.days_left != null && l.days_left < plan.days }">{{ l.days_left != null ? `${num(l.days_left)} kun` : '—' }}</span>
                <span><b v-if="l.buy > 0" class="acc">{{ num(l.buy) }} {{ UNIT[l.unit] }}</b><span v-else class="ok">✓ yetarli</span></span>
                <span>{{ l.cost ? money(l.cost) : '' }}</span>
              </div>
              <UiEmpty v-if="!planLines.length" title="Hammasi yetarli" text="Bu davr uchun ombordagi qoldiq yetadi." />
            </div>
          </UiCard>
          <div class="side">
            <UiCard title="Ta'minotchilar bo'yicha" subtitle="Har biriga alohida kirim ochish mumkin">
              <ul class="sup">
                <li v-for="sp in plan.suppliers" :key="sp.name">
                  <span class="nm"><b>{{ sp.name }}</b><small>{{ sp.count }} ta xomashyo</small></span>
                  <b>{{ money(sp.total) }}</b>
                  <UiButton v-if="a.can('inventory.purchase')" size="s" variant="ghost" @click="toPurchase(sp.supplier_id, false)">Kirim</UiButton>
                </li>
              </ul>
              <p v-if="!plan.suppliers.length" class="mut">Xarid kerak emas.</p>
              <div v-if="plan.short_count" class="r-foot">
                <UiButton variant="ghost" size="s" @click="copyList()">📋 Ro'yxatni nusxalash</UiButton>
                <div class="sp"></div>
                <UiButton v-if="a.can('inventory.purchase')" variant="brand" @click="toPurchase(null, true)">Hammasini kirimga</UiButton>
              </div>
            </UiCard>
            <UiCard v-if="plan.products.length" :title="plan.holiday ? 'Bayram kunlari ko\'p ketadi' : 'Ko\'p ketadigan taomlar'" subtitle="Prognoz, porsiya">
              <ul class="sup">
                <li v-for="p in plan.products" :key="p.product_id"><span class="nm"><b>{{ t(p.name, ui.lang) }}</b></span><b>{{ p.qty }}</b><span class="mut">porsiya</span></li>
              </ul>
            </UiCard>
          </div>
        </div>
      </template>
      <p v-else-if="planLoading" class="mut">Hisoblanmoqda…</p>
    </div>

    <!-- TEX-KARTA -->
    <div v-else-if="tab === 'recipes'" class="split">
      <UiCard title="Taomlar" subtitle="Bosing — tex-kartani oching. Food cost: ≤32% yaxshi · 33–40% e'tibor · >40% narx yoki retseptni ko'ring" :padded="false">
        <div class="lst">
          <div class="l-h"><span>Taom</span><span>Narx</span><span>Tannarx</span><span>Food cost</span><span>Marja</span></div>
          <button v-for="r in recipes" :key="r.product_id" class="l-r" :class="{ sel: recipe?.product_id === r.product_id }" @click="openRecipe(r.product_id)">
            <span class="nm"><b>{{ t(r.name, ui.lang) }}</b><small>{{ t(r.category, ui.lang) }}{{ r.has_recipe ? ` · ${r.lines} xomashyo` : ' · tex-karta yo\'q' }}</small></span>
            <span>{{ money(r.price) }}</span>
            <span>{{ money(r.cost) }}</span>
            <span><UiChip :tone="fcTone(r.food_cost_percent)">{{ r.food_cost_percent ?? '—' }}%</UiChip></span>
            <span>{{ r.margin_percent ?? '—' }}%</span>
          </button>
        </div>
      </UiCard>

      <UiCard v-if="recipe" :title="t(recipe.product_name, ui.lang)" subtitle="Bir porsiyaga ketadigan xomashyo — g / ml / dona">
        <template #actions><UiChip :tone="fcTone(liveFc)">Food cost {{ liveFc ?? '—' }}%</UiChip></template>
        <div class="cost-row">
          <div><span>Sotuv narxi</span><b>{{ money(recipe.price) }}</b></div>
          <div><span>Tannarx (jonli)</span><b class="acc">{{ money(liveCost) }}</b></div>
          <div><span>Marja</span><b>{{ money(recipe.price - liveCost) }}</b></div>
          <div><span>Tavsiya narx (FC 32%)</span><b>{{ money(Math.ceil(liveCost / 0.32 / 500) * 500) }}</b></div>
        </div>
        <table class="rl">
          <thead><tr><th>Xomashyo</th><th>Miqdor</th><th>Chiqindi %</th><th>Narx</th><th>Summa</th><th></th></tr></thead>
          <tbody>
            <tr v-for="(l, i) in recipe.lines" :key="i">
              <td><select v-model="l.ingredient_id"><option v-for="ig in ingredients" :key="ig.id" :value="ig.id">{{ t(ig.name, ui.lang) }} ({{ SUB[ig.unit] }})</option></select></td>
              <td><input v-model="l.qty" type="number" min="0" step="1" /> <small>{{ SUB[ingredients.find(x => x.id === Number(l.ingredient_id))?.unit ?? 'kg'] }}</small></td>
              <td><input v-model="l.waste_percent" type="number" min="0" max="90" /></td>
              <td class="mut">{{ money(ingredients.find(x => x.id === Number(l.ingredient_id))?.price ?? 0) }}/{{ UNIT[ingredients.find(x => x.id === Number(l.ingredient_id))?.unit ?? 'kg'] }}</td>
              <td><b>{{ money(Math.round(((ingredients.find(x => x.id === Number(l.ingredient_id))?.unit === 'dona' ? Number(l.qty) : Number(l.qty) / 1000) * (ingredients.find(x => x.id === Number(l.ingredient_id))?.price ?? 0)) * (1 + Number(l.waste_percent || 0) / 100))) }}</b></td>
              <td><button class="x" @click="recipe.lines.splice(i, 1)"><UiIcon name="x" :size="13" /></button></td>
            </tr>
          </tbody>
        </table>
        <div class="r-foot">
          <UiButton variant="ghost" size="s" @click="addLine()"><UiIcon name="plus" :size="14" /> Xomashyo qo'shish</UiButton>
          <label class="yld">Chiqadi: <input v-model="recipe.yield_qty" type="number" min="0.5" step="0.5" /> porsiya</label>
          <div class="sp"></div>
          <UiButton v-if="a.can('inventory.recipe')" variant="brand" :loading="recipeSaving" @click="saveRecipe()">Saqlash va tannarxni yozish</UiButton>
        </div>
        <label class="fl"><span>Tayyorlash tartibi (oshpaz uchun)</span><textarea v-model="recipe.note" rows="3" placeholder="1. Go'shtni 180° da 4 daqiqa… 2. Nonni qizdiring…"></textarea></label>
      </UiCard>
      <UiEmpty v-else title="Taomni tanlang" text="Chapdagi ro'yxatdan taomni bosing — tex-kartani kiriting, tannarx o'zi hisoblanadi." />
    </div>

    <!-- XOMASHYO -->
    <UiCard v-else-if="tab === 'ingredients'" :padded="false">
      <template #actions>
        <UiInput v-model="q" placeholder="Qidirish" @keydown.enter="load()" />
        <button class="chip-btn" :class="{ on: onlyLow }" @click="onlyLow = !onlyLow"><UiIcon name="alert" :size="14" /> Tugayotganlar</button>
        <UiButton v-if="canEdit" variant="brand" size="s" @click="openIng()"><UiIcon name="plus" :size="14" /> Xomashyo</UiButton>
      </template>
      <div class="lst">
        <div class="l-h ing"><span>Nomi</span><span>Narx</span><span>Qoldiq</span><span>Min</span><span>Qiymat</span><span>Tex-karta</span><span></span></div>
        <div v-for="i in ingredients" :key="i.id" class="l-r ing" :class="{ low: i.is_low }">
          <span class="nm"><b>{{ t(i.name, ui.lang) }}</b><small>{{ i.category }}</small></span>
          <span>{{ money(i.price) }}<small>/{{ UNIT[i.unit] }}</small></span>
          <span :class="{ danger: i.is_low }"><b>{{ i.stock }}</b> {{ UNIT[i.unit] }}</span>
          <span class="mut">{{ i.min_stock }} {{ UNIT[i.unit] }}</span>
          <span>{{ money(i.stock_value) }}</span>
          <span class="mut">{{ i.used_in }} taomda</span>
          <span class="acts">
            <UiButton size="s" variant="ghost" @click="adj = { id: i.id, name: t(i.name, ui.lang), qty: i.stock, unit: UNIT[i.unit], kind: 'adjust', note: '' }" title="Inventarizatsiya"><UiIcon name="edit" :size="14" /></UiButton>
            <UiButton v-if="canEdit" size="s" variant="ghost" @click="openIng(i)"><UiIcon name="sliders" :size="14" /></UiButton>
            <UiButton v-if="canEdit" size="s" variant="ghost" @click="removeIng(i)"><UiIcon name="trash" :size="14" /></UiButton>
          </span>
        </div>
        <UiEmpty v-if="!ingredients.length" title="Xomashyo yo'q" text="«Xomashyo» tugmasi bilan qo'shing yoki kirim kiriting." />
      </div>
    </UiCard>

    <!-- KIRIM -->
    <div v-else-if="tab === 'purchase'" class="split">
      <UiCard title="Yangi kirim (bozorlik)" subtitle="Narx bazaviy birlik uchun: so'm/kg, so'm/l, so'm/dona. Saqlangach — qoldiq oshadi, tannarxlar yangilanadi">
        <div class="grid2">
          <UiSelect v-model="pur.supplier_id" label="Yetkazib beruvchi" :options="[{ value: '', label: '— bozor / boshqa —' }, ...suppliers.map(s => ({ value: String(s.id), label: s.name }))]" />
          <UiInput v-model="pur.note" label="Izoh" placeholder="Chorsu, ertalab" />
        </div>
        <table class="rl">
          <thead><tr><th>Xomashyo</th><th>Miqdor</th><th>Narx / birlik</th><th>Summa</th><th></th></tr></thead>
          <tbody>
            <tr v-for="(l, i) in pur.lines" :key="i">
              <td><select v-model="l.ingredient_id" @change="onLineIng(l)"><option value="">— tanlang —</option><option v-for="ig in ingredients" :key="ig.id" :value="String(ig.id)">{{ t(ig.name, ui.lang) }} ({{ UNIT[ig.unit] }})</option></select></td>
              <td><input v-model="l.qty" type="number" min="0" step="0.1" /></td>
              <td><input v-model="l.unit_price" type="number" min="0" step="100" /></td>
              <td><b>{{ money(Number(l.qty) * Number(l.unit_price)) }}</b></td>
              <td><button class="x" @click="pur.lines.splice(i, 1)"><UiIcon name="x" :size="13" /></button></td>
            </tr>
          </tbody>
        </table>
        <div class="r-foot">
          <UiButton variant="ghost" size="s" @click="pur.lines.push({ ingredient_id: '', qty: 0, unit_price: 0 })"><UiIcon name="plus" :size="14" /> Qator</UiButton>
          <div class="sp"></div>
          <b class="tot">Jami: {{ money(purTotal) }}</b>
          <UiButton v-if="a.can('inventory.purchase')" variant="brand" @click="savePurchase()">Kirimni o'tkazish</UiButton>
        </div>
      </UiCard>
      <UiCard title="So'nggi kirimlar" :padded="false">
        <div class="lst">
          <div v-for="p in purchases" :key="p.id" class="l-r pur">
            <span class="nm"><b>Kirim #{{ p.number }}</b><small>{{ p.date }} · {{ p.supplier ?? 'bozor' }} · {{ p.lines.length }} qator</small></span>
            <span><b>{{ money(p.total) }}</b></span>
          </div>
          <UiEmpty v-if="!purchases.length" title="Hali kirim yo'q" />
        </div>
      </UiCard>
    </div>

    <!-- HARAKATLAR -->
    <UiCard v-else :padded="false" title="Ombor harakatlari" subtitle="Kirim +, savdo −, chiqindi, inventarizatsiya — kim, qachon">
      <div class="lst">
        <div v-for="m in movements" :key="m.id" class="l-r mv">
          <span class="mut">{{ fmtDT(m.at) }}</span>
          <span><b>{{ t(m.ingredient.name, ui.lang) }}</b></span>
          <span><UiChip :tone="m.kind === 'purchase' ? 'ok' : m.kind === 'sale' ? 'info' : m.kind === 'waste' ? 'danger' : 'neutral'">{{ ({ purchase: 'Kirim', sale: 'Savdo', waste: 'Chiqindi', adjust: 'Inventarizatsiya', transfer: 'O\'tkazish' } as Record<string, string>)[m.kind] ?? m.kind }}</UiChip></span>
          <span :class="m.qty >= 0 ? 'ok' : 'danger'"><b>{{ m.qty > 0 ? '+' : '' }}{{ m.qty }}</b> {{ UNIT[m.ingredient.unit] }}</span>
          <span class="mut">{{ m.ref || m.note }}</span>
          <span class="mut">{{ m.actor ?? '' }}</span>
        </div>
        <UiEmpty v-if="!movements.length" title="Harakat yo'q" />
      </div>
    </UiCard>

    <!-- xomashyo formasi -->
    <UiDrawer :open="ingDrawer" :title="ing?.id ? 'Xomashyo' : 'Yangi xomashyo'" @close="ingDrawer = false">
      <template v-if="ing">
        <UiInput v-model="ing.name.uz" label="Nomi (uz)" />
        <div class="grid2">
          <UiInput v-model="ing.name.ru" label="Nomi (ru)" /><UiInput v-model="ing.name.en" label="Nomi (en)" />
          <UiInput v-model="ing.category" label="Kategoriya" placeholder="Go'sht, Sabzavot…" />
          <UiSelect v-model="ing.unit" label="Birlik" :options="[{ value: 'kg', label: 'kg (retseptda gramm)' }, { value: 'l', label: 'litr (retseptda ml)' }, { value: 'dona', label: 'dona' }]" />
          <UiInput v-model="ing.price" type="number" label="Narx (so'm / birlik)" suffix="so'm" />
          <UiInput v-model="ing.min_stock" type="number" label="Minimal qoldiq (ogohlantirish)" />
        </div>
        <p class="tip"><UiIcon name="alert" :size="14" /> Narxni bu yerda o'zgartirsangiz — shu xomashyo bor barcha taomlar tannarxi darhol qayta hisoblanadi.</p>
      </template>
      <template #footer><UiButton variant="ghost" @click="ingDrawer = false">Bekor</UiButton><UiButton variant="brand" @click="saveIng()">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!adj" title="Qoldiqni yangilash" width="420px" @close="adj = null">
      <template v-if="adj">
        <p><b>{{ adj.name }}</b></p>
        <UiInput v-model="adj.qty" type="number" :label="`Haqiqiy qoldiq (${adj.unit})`" />
        <UiSelect v-model="adj.kind" label="Sabab" :options="[{ value: 'adjust', label: 'Inventarizatsiya' }, { value: 'waste', label: 'Chiqindi / yaroqsiz' }, { value: 'transfer', label: 'Boshqa filialga' }]" />
        <UiInput v-model="adj.note" label="Izoh" />
      </template>
      <template #footer><UiButton variant="ghost" @click="adj = null">Bekor</UiButton><UiButton variant="brand" @click="saveAdjust()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.inv { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px 14px; display: flex; flex-direction: column; }
.kpi b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; } .kpi span { font-size: var(--fs-xs); color: var(--muted); }
.kpi.warn { border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 9px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.split { display: grid; grid-template-columns: 1fr 1.2fr; gap: 14px; align-items: start; }
.lst { display: flex; flex-direction: column; }
.l-h, .l-r { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr; gap: 10px; align-items: center; padding: 9px 14px; text-align: left; font-size: var(--fs-s); }
.l-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.l-r { border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; }
button.l-r { cursor: pointer; } button.l-r:hover, .l-r.sel { background: var(--accent-tint); }
.l-r.ing, .l-h.ing { grid-template-columns: 2fr 1fr 1fr .8fr 1fr 1fr 130px; }
.l-r.low { background: var(--danger-tint); }
.l-r.pur { grid-template-columns: 1fr auto; } .l-r.mv { grid-template-columns: 110px 1.5fr 1fr 1fr 1fr 1fr; }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { color: var(--muted); font-size: var(--fs-xs); }
.mut { color: var(--muted); } .danger { color: var(--danger); } .ok { color: var(--ok); }
.acts { display: flex; gap: 2px; justify-content: flex-end; }
.cost-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 12px; }
.cost-row div { background: var(--surface-2); border-radius: var(--radius); padding: 10px 12px; display: flex; flex-direction: column; }
.cost-row span { font-size: var(--fs-xs); color: var(--muted); } .cost-row b { font-family: var(--font-display); font-size: var(--fs-l); } .cost-row .acc { color: var(--accent); }
.rl { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
.rl th { text-align: left; font-size: var(--fs-xs); color: var(--muted); padding: 6px 4px; border-bottom: 1px solid var(--line); }
.rl td { padding: 5px 4px; border-bottom: 1px solid var(--line-2); }
.rl select, .rl input { width: 100%; min-width: 60px; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 6px 8px; background: var(--surface); font-size: var(--fs-s); }
.rl input[type=number] { max-width: 90px; }
.x { border: 0; background: transparent; cursor: pointer; color: var(--muted); }
.r-foot { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.yld { font-size: var(--fs-s); color: var(--muted); } .yld input { width: 60px; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 4px 6px; }
.tot { font-family: var(--font-display); font-size: var(--fs-l); }
.fl { display: flex; flex-direction: column; gap: 4px; margin-top: 12px; } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.fl textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; background: var(--surface); font: inherit; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.chip-btn { display: inline-flex; align-items: center; gap: 6px; min-height: var(--touch); padding: 0 12px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); font-weight: 700; font-size: var(--fs-s); cursor: pointer; }
.chip-btn.on { background: var(--danger-tint); color: var(--danger); border-color: var(--danger); }
.tip { display: flex; gap: 6px; font-size: var(--fs-xs); color: var(--muted); background: var(--surface-2); border-radius: var(--radius); padding: 8px 10px; margin: 0; }
.plan { display: flex; flex-direction: column; gap: 14px; }
.p-top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; } .seg-sel { min-width: 260px; } .p-how { margin: 0; font-size: var(--fs-xs); color: var(--muted); flex: 1; min-width: 200px; }
.p-k .kpi b { font-size: var(--fs-l); }
.days { display: grid; grid-template-columns: repeat(auto-fit, minmax(62px, 1fr)); gap: 6px; }
.day { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 4px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line); }
.day.hol { background: var(--warn-tint); border-color: color-mix(in srgb, var(--warn) 45%, var(--line)); }
.day small { font-size: 11px; color: var(--muted); font-weight: 700; } .day .e { font-size: 20px; } .day b { font-size: var(--fs-xs); }
.day b.up { color: var(--ok); } .day b.dn { color: var(--danger); }
.plan .split { grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr); }
.l-r.pl, .l-h.pl { grid-template-columns: minmax(0, 2fr) 1fr 1fr .8fr 1fr 1fr; } .l-r.pl > span:not(.nm) { white-space: nowrap; }
.chip-btn { white-space: nowrap; } .l-r.buy { background: color-mix(in srgb, var(--warn-tint) 60%, transparent); }
.acc { color: var(--accent); }
.side { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.sup { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.sup li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .sup li:last-child { border-bottom: 0; }
@media (max-width: 1100px) { .plan .split { grid-template-columns: minmax(0, 1fr); } .split { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, 1fr); } .cost-row { grid-template-columns: 1fr 1fr; } }
@media (max-width: 600px) {
  .kpis { grid-template-columns: 1fr 1fr; } .grid2 { grid-template-columns: 1fr; }
  /* telefon: har qator — nomi (to'liq kenglik) + qolgan qiymatlar ixcham qatorda, sarlavha yashirin */
  .l-h { display: none; }
  .l-r { grid-template-columns: repeat(4, minmax(0, 1fr)) !important; gap: 4px 8px; padding: 10px 14px; }
  .l-r > .nm { grid-column: 1 / -1; }
  .l-r > span:not(.nm):not(.acts) { font-size: var(--fs-xs); color: var(--ink-2); }
  .l-r > .acts { grid-column: 1 / -1; justify-content: flex-start; }
  .l-r.pur { grid-template-columns: 1fr auto !important; }
  .l-r.pl { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
  .seg-sel { min-width: 0; width: 100%; } .days { grid-template-columns: repeat(auto-fit, minmax(44px, 1fr)); gap: 4px; }
  .cost-row { grid-template-columns: 1fr 1fr; }
}
</style>
