<script setup lang="ts">
/**
 * Zakup (xarid): «Nima kerak?» qidiruvi va toifalar; ta'minotchilar (qo'ng'iroq / Telegram), bozorlar — yuk olish joylari,
 * narx taqqoslash, buyurtmalar (yuborish → tasdiq → qabul = omborga kirim), qarzdorlik va to'lovlar.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, UiToggle, money, toast } from '@restopos/ui'
import OrderDrawer from '@/components/procurement/OrderDrawer.vue'
import SupplierDrawer from '@/components/procurement/SupplierDrawer.vue'

const route = useRoute(), router = useRouter()
type Tab = 'home' | 'suppliers' | 'markets' | 'prices' | 'orders' | 'debts'
const tab = ref<Tab>((route.query.tab as Tab) || 'home')
const M = ref<any>(null), O = ref<any>(null)
const q = ref(''), cat = ref('')
const R = ref<any>(null)
const sup = ref<any>(null), kind = ref('')
const markets = ref<any[]>([])
const priceIng = ref(''), P = ref<any>(null), np = ref({ who: '', price: 0 })
const orders = ref<any>(null), ost = ref('')
const D = ref<any>(null)
const od = ref({ open: false, id: null as number | null, preset: null as any })
const sd = ref({ open: false, id: null as number | null, edit: false })
const pay = ref<any>(null)
const mk = ref<any>(null)

async function loadTab() {
  if (tab.value === 'home') O.value = await api.get('/procurement/overview')
  if (tab.value === 'suppliers') sup.value = await api.get('/procurement/suppliers', { cat: cat.value || undefined, kind: kind.value || undefined })
  if (tab.value === 'markets') markets.value = await api.get('/procurement/markets', { cat: cat.value || undefined })
  if (tab.value === 'orders') orders.value = await api.get('/procurement/orders', { status: ost.value || undefined })
  if (tab.value === 'debts') D.value = await api.get('/procurement/debts')
  if (tab.value === 'prices' && priceIng.value) P.value = await api.get('/procurement/prices', { ingredient_id: priceIng.value })
}
onMounted(async () => {
  M.value = await api.get('/procurement/meta')
  if (route.query.order) { try { od.value = { open: true, id: null, preset: JSON.parse(String(route.query.order)) } } catch { /* noto'g'ri havola */ } router.replace({ query: { tab: tab.value } }) }
  await loadTab()
})
watch(tab, (t) => { router.replace({ query: { tab: t } }); loadTab() })
async function reloadMeta() { M.value = await api.get('/procurement/meta') }
watch([kind, ost], loadTab)
watch(priceIng, loadTab)
watch(cat, () => { if (tab.value === 'home') doSearch(); else loadTab() })
let tm: number | undefined
watch(q, () => { clearTimeout(tm); tm = window.setTimeout(doSearch, 300) })
async function doSearch() {
  if (!q.value.trim() && !cat.value) { R.value = null; return }
  if (tab.value !== 'home') tab.value = 'home'
  R.value = await api.get('/procurement/search', { q: q.value.trim() || undefined, cat: cat.value || undefined })
}
const K = computed(() => O.value?.kpis)
const topMax = computed(() => Math.max(1, ...(O.value?.top ?? []).map((t: any) => t.qty)))
const TONE: Record<string, any> = { draft: 'neutral', sent: 'info', confirmed: 'accent', received: 'ok', cancelled: 'danger' }
const KIND_EMOJI: Record<string, string> = { company: '🏢', bazaar: '🧺', farmer: '🌾', producer: '🏭' }
const d = (s?: string | null) => s ? s.slice(0, 10).split('-').reverse().join('.') : '—'
const short = (v: number) => v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1).replace('.', ',')} mln` : money(v)
const stars = (r: number | null) => r ? '★'.repeat(Math.round(r)) + '☆'.repeat(5 - Math.round(r)) : ''

function openOrder(id: number | null, preset: any = null) { od.value = { open: true, id, preset } }
function openSup(id: number | null, edit = false) { sd.value = { open: true, id, edit } }
async function addPrice() {
  const [kindW, id] = np.value.who.split(':')
  try { P.value.board = (await api.post('/procurement/prices', { ingredient_id: Number(priceIng.value), price: Number(np.value.price), supplier_id: kindW === 's' ? Number(id) : null, market_id: kindW === 'm' ? Number(id) : null })).board; np.value.price = 0; toast('Narx qo\'shildi'); loadTab() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function savePay() {
  try { await api.post('/procurement/payments', { ...pay.value, amount: Number(pay.value.amount) }); toast('To\'lov yozildi'); pay.value = null; loadTab() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function editMarket(m?: any) {
  mk.value = m ? { ...m, categories: m.categories.map((c: any) => c.code) } : { name: '', kind: 'bazaar', city: 'Toshkent', district: '', address: '', landmark: '', hours: '', days: 'har kuni', categories: [], tips: '', phone: '', is_active: true }
}
async function saveMarket() {
  try { mk.value.id ? await api.put(`/procurement/markets/${mk.value.id}`, mk.value) : await api.post('/procurement/markets', mk.value); mk.value = null; toast('Saqlandi'); loadTab(); reloadMeta() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function toggleMkCat(c: string) { const s = new Set(mk.value.categories); s.has(c) ? s.delete(c) : s.add(c); mk.value.categories = [...s] }
</script>

<template>
  <div v-if="M" class="pr">
    <!-- KPI -->
    <section v-if="K && tab === 'home'" class="kpis">
      <button type="button" class="kpi kpi-click" @click="tab = 'suppliers'"><span class="ki g">🧾</span><div><small>Ta'minotchilar</small><b>{{ K.suppliers }}</b><em>{{ K.markets }} ta bozor ro'yxatda</em></div></button>
      <button type="button" class="kpi kpi-click" @click="tab = 'orders'; ost = ''"><span class="ki b">📋</span><div><small>Joriy buyurtmalar</small><b>{{ K.active_orders }}</b><em>{{ K.on_way }} tasi tasdiqlangan</em></div></button>
      <button type="button" class="kpi kpi-click" @click="router.push('/inventory?tab=purchase')"><span class="ki o">🛒</span><div><small>Oylik xarid</small><b :title="money(K.month_total)">{{ short(K.month_total) }}</b><em v-if="K.month_delta != null">{{ K.month_delta >= 0 ? '↑' : '↓' }} {{ Math.abs(K.month_delta) }}% o'tgan oyga</em><em v-else>so'm, shu oy</em></div></button>
      <button type="button" class="kpi kpi-click" @click="tab = 'debts'"><span class="ki p">💳</span><div><small>Qarzdorlik</small><b :class="{ bad: K.overdue }" :title="money(K.debt)">{{ short(K.debt) }}</b><em>{{ K.debt_suppliers }} ta ta'minotchi{{ K.overdue ? ` · ${K.overdue} muddati o'tgan` : '' }}</em></div></button>
      <button type="button" class="kpi kpi-click" @click="tab = 'orders'; ost = 'confirmed'"><span class="ki r">🚚</span><div><small>Bugun keladi</small><b>{{ K.today }}</b><em>buyurtma</em></div></button>
    </section>

    <!-- «Nima kerak?» -->
    <div class="srch">
      <label class="sb"><UiIcon name="search" :size="18" /><input v-model="q" placeholder="Nima kerak? (masalan: go'sht, tovuq, kartoshka…)" aria-label="Nima kerak" /></label>
      <UiButton v-if="M.can_edit" variant="brand" @click="openOrder(null)"><UiIcon name="plus" :size="14" /> Yangi buyurtma</UiButton>
    </div>
    <div class="cats" role="tablist" aria-label="Toifalar">
      <button v-for="c in M.categories" :key="c.code" type="button" :class="{ on: cat === c.code }" @click="cat = cat === c.code ? '' : c.code"><span>{{ c.emoji }}</span>{{ c.name }}</button>
    </div>

    <nav class="tabs" role="tablist">
      <button :class="{ on: tab === 'home' }" @click="tab = 'home'">Bosh</button>
      <button :class="{ on: tab === 'suppliers' }" @click="tab = 'suppliers'">Ta'minotchilar</button>
      <button :class="{ on: tab === 'markets' }" @click="tab = 'markets'">Bozorlar (yuk olish joylari)</button>
      <button :class="{ on: tab === 'prices' }" @click="tab = 'prices'">Narxlar</button>
      <button :class="{ on: tab === 'orders' }" @click="tab = 'orders'">Buyurtmalar</button>
      <button :class="{ on: tab === 'debts' }" @click="tab = 'debts'">Qarzdorlik</button>
    </nav>

    <!-- BOSH / QIDIRUV NATIJASI -->
    <template v-if="tab === 'home'">
      <div v-if="R" class="res">
        <UiCard :title="`«${q || M.categories.find((c: any) => c.code === cat)?.name}» — kimda, qanchaga`" subtitle="Arzondan qimmatga · oxirgi narx" :padded="false">
          <template #actions><UiButton size="s" variant="ghost" @click="q = ''; cat = ''">Tozalash</UiButton></template>
          <div v-for="(o, i) in R.offers" :key="i" class="of">
            <span class="rk" :class="{ best: o.rank === 1 }">{{ o.rank }}</span>
            <span class="on"><b>{{ o.ingredient }}</b><small>{{ o.supplier ?? o.market }}{{ o.supplier && o.market ? ` · 📍 ${o.market}` : '' }}</small></span>
            <b class="pp">{{ money(o.price) }}<small>/{{ o.unit }}</small></b>
            <span class="ch" :class="o.change > 0 ? 'up' : o.change < 0 ? 'dn' : ''">{{ o.change ? `${o.change > 0 ? '↑' : '↓'} ${Math.abs(o.change)}%` : '' }}</span>
            <small class="vb">{{ o.vs_best ? `+${o.vs_best}% eng arzondan` : 'eng arzon' }}</small>
          </div>
          <UiEmpty v-if="!R.offers.length" title="Narx topilmadi" text="Ta'minotchi kartasida yoki «Narxlar» bo'limida narx kiriting." />
        </UiCard>
        <div class="rs">
          <UiCard title="Kim sotadi" :padded="false">
            <button v-for="s in R.suppliers" :key="s.id" type="button" class="sr" @click="openSup(s.id)"><span>{{ KIND_EMOJI[s.kind] }}</span><b>{{ s.name }}</b><small>{{ s.rating ? `★ ${s.rating}` : '' }} {{ s.market?.name ?? '' }}</small></button>
            <UiEmpty v-if="!R.suppliers.length" title="Ta'minotchi yo'q" />
          </UiCard>
          <UiCard title="Qaysi bozorda bor">
            <div class="mchips"><a v-for="m in R.markets" :key="m.id" :href="m.map_url" target="_blank" rel="noopener">📍 {{ m.name }}</a></div>
          </UiCard>
        </div>
      </div>
      <div v-else-if="O" class="home">
        <UiCard title="So'nggi buyurtmalar" :padded="false">
          <template #actions><button class="lnk" @click="tab = 'orders'">Barchasi</button></template>
          <button v-for="o in O.recent" :key="o.id" type="button" class="or" @click="openOrder(o.id)">
            <span><b>#{{ o.number }} {{ o.supplier }}</b><small>{{ d(o.created_at) }} · {{ o.items }} mahsulot</small></span>
            <b>{{ money(o.total) }}</b><UiChip :tone="TONE[o.status]">{{ o.status_label }}</UiChip>
          </button>
          <UiEmpty v-if="!O.recent.length" title="Hali buyurtma yo'q" text="«Yangi buyurtma» yoki Ombor → Xarid rejasi → «Buyurtma»." />
        </UiCard>
        <UiCard title="Eng ko'p olinadigan (shu oy)">
          <ul class="top"><li v-for="t in O.top" :key="t.id"><span>{{ t.name }}</span><span class="bar"><i :style="{ width: `${(100 * t.qty) / topMax}%` }"></i></span><b>{{ +t.qty.toFixed(1) }} {{ t.unit }}</b></li></ul>
          <UiEmpty v-if="!O.top.length" title="Bu oy kirim yo'q" />
        </UiCard>
        <UiCard title="Ta'minotchi reytingi" subtitle="Buyurtma qabul qilinganda beriladigan baho">
          <button v-for="(s, i) in O.ranking" :key="s.id" type="button" class="rr" @click="openSup(s.id)"><span class="rk">{{ i + 1 }}</span><b>{{ s.name }}</b><span class="st">{{ s.rating ? `★ ${s.rating}` : '—' }} <small>({{ s.reviews }})</small></span></button>
        </UiCard>
      </div>
    </template>

    <!-- TA'MINOTCHILAR -->
    <template v-else-if="tab === 'suppliers' && sup">
      <div class="sub">
        <button :class="{ on: kind === '' }" @click="kind = ''">Barchasi</button>
        <button v-for="k in M.supplier_kinds" :key="k.code" :class="{ on: kind === k.code }" @click="kind = k.code">{{ KIND_EMOJI[k.code] }} {{ k.label }}</button>
        <div class="sp"></div>
        <UiButton v-if="M.can_edit" size="s" variant="brand" @click="openSup(null, true)"><UiIcon name="plus" :size="14" /> Ta'minotchi</UiButton>
      </div>
      <div class="sl">
        <div v-for="s in sup.items" :key="s.id" class="sc" :class="{ off: !s.is_active }">
          <button type="button" class="av" @click="openSup(s.id)">{{ s.categories[0]?.emoji ?? KIND_EMOJI[s.kind] }}</button>
          <button type="button" class="sn" @click="openSup(s.id)">
            <b>{{ s.name }}</b>
            <small><span v-if="s.rating" class="stars">{{ stars(s.rating) }}</span> {{ s.rating ? `${s.rating} (${s.reviews})` : 'baho yo\'q' }}</small>
            <UiChip :tone="s.kind === 'company' ? 'ok' : s.kind === 'bazaar' ? 'warn' : 'info'">{{ s.kind_label }}</UiChip>
          </button>
          <span class="sp2"><small>Asosiy mahsulotlar</small>{{ s.products.join(', ') || s.categories.map((c: any) => c.name).join(', ') || '—' }}</span>
          <span class="lp"><small>Oxirgi narx</small><b v-if="s.last_price">{{ money(s.last_price.price) }}</b><em v-if="s.last_price">{{ s.last_price.ingredient }}, 1 {{ s.last_price.unit }}</em><template v-else>—</template></span>
          <span class="lo"><small>📍 {{ s.market?.name ?? (s.address || 'Shahar bo\'ylab') }}</small>{{ s.delivers ? '🚚 Yetkazib beradi' : '🧍 Olib ketamiz' }}{{ s.min_order ? ` · ${s.min_order}` : '' }}</span>
          <span class="bt">
            <a v-if="s.phone" :href="`tel:${s.phone}`" class="b1">📞 Qo'ng'iroq</a>
            <a v-if="s.telegram_url" :href="s.telegram_url" target="_blank" rel="noopener" class="b2">✈️ Telegram</a>
            <span v-if="s.debt" class="db" :class="{ bad: s.overdue }">Qarz {{ money(s.debt) }}</span>
          </span>
          <button v-if="M.can_edit" type="button" class="ed" aria-label="Tahrirlash" @click="openSup(s.id, true)"><UiIcon name="edit" :size="15" /></button>
        </div>
        <UiEmpty v-if="!sup.items.length" title="Ta'minotchi topilmadi" text="Toifa yoki turni o'zgartiring yoki yangi qo'shing." />
      </div>
    </template>

    <!-- BOZORLAR -->
    <template v-else-if="tab === 'markets'">
      <div class="sub"><p class="mut">Bozorchi yuk oladigan joylar: qachon borish, nima arzon, qanday borish. Ro'yxatni o'zingizga moslang.</p><div class="sp"></div>
        <UiButton v-if="M.can_edit" size="s" variant="brand" @click="editMarket()"><UiIcon name="plus" :size="14" /> Joy qo'shish</UiButton></div>
      <div class="mg">
        <div v-for="m in markets" :key="m.id" class="mc" :class="{ off: !m.is_active }">
          <div class="mh"><b>{{ m.name }}</b><UiChip :tone="m.kind === 'wholesale' ? 'accent' : m.kind === 'bazaar' ? 'warn' : 'info'">{{ m.kind_label }}</UiChip></div>
          <p class="md">📍 {{ [m.district, m.address].filter(Boolean).join(', ') || m.city }}{{ m.landmark ? ` (mo'ljal: ${m.landmark})` : '' }}</p>
          <p class="md">🕔 {{ m.hours || '—' }} · {{ m.days }}</p>
          <div class="me"><span v-for="c in m.categories" :key="c.code" :title="c.name">{{ c.emoji }} {{ c.name }}</span></div>
          <p v-if="m.tips" class="tip">💡 {{ m.tips }}</p>
          <div class="mf"><small>{{ m.suppliers }} ta'minotchi · {{ m.trips }} bozorlik</small>
            <a :href="m.map_url" target="_blank" rel="noopener">🗺 Xaritada</a>
            <button v-if="M.can_edit" type="button" @click="editMarket(m)">Tahrirlash</button></div>
        </div>
      </div>
    </template>

    <!-- NARXLAR -->
    <template v-else-if="tab === 'prices'">
      <UiCard>
        <UiSelect v-model="priceIng" label="Mahsulotni tanlang — kimda qanchaligini solishtiring" :options="[{ value: '', label: '— tanlang —' }, ...M.ingredients.map((i: any) => ({ value: String(i.id), label: `${i.name} (${i.unit})` }))]" />
      </UiCard>
      <div v-if="P" class="prs">
        <UiCard :title="`${P.ingredient.name} — 1 ${P.ingredient.unit}`" :subtitle="`Ombordagi o'rtacha narx: ${money(Math.round(P.ingredient.price))} so'm · qoldiq ${P.ingredient.stock} ${P.ingredient.unit}`" :padded="false">
          <div v-for="b in P.board" :key="`${b.supplier_id}-${b.market_id}`" class="of">
            <span class="rk" :class="{ best: b.rank === 1 }">{{ b.rank }}</span>
            <span class="on"><b>{{ b.supplier ?? b.market }}</b><small>{{ b.market && b.supplier ? `📍 ${b.market} · ` : '' }}{{ d(b.date) }} · {{ ({ manual: 'qo\'lda', order: 'buyurtmadan', trip: 'bozorlikdan' } as any)[b.source] }}</small></span>
            <b class="pp">{{ money(b.price) }}</b>
            <span class="ch" :class="b.change > 0 ? 'up' : b.change < 0 ? 'dn' : ''">{{ b.change ? `${b.change > 0 ? '↑' : '↓'} ${Math.abs(b.change)}%` : '—' }}</span>
            <small class="vb">{{ b.vs_best ? `+${b.vs_best}%` : 'eng arzon' }}</small>
          </div>
          <UiEmpty v-if="!P.board.length" title="Hali narx yo'q" />
        </UiCard>
        <UiCard title="Narx kiritish" subtitle="Bozordan qo'ng'iroq qilib bilgan narxingizni yozing">
          <UiSelect v-model="np.who" label="Kim / qayerda" :options="[{ value: '', label: '— tanlang —' }, ...M.suppliers.map((s: any) => ({ value: `s:${s.id}`, label: s.name })), ...M.markets.map((m: any) => ({ value: `m:${m.id}`, label: `📍 ${m.name}` }))]" />
          <UiInput v-model="np.price" type="number" :label="`Narx (so'm / ${P.ingredient.unit})`" />
          <UiButton variant="brand" style="margin-top: 10px" :disabled="!np.who || !np.price" @click="addPrice()">Qo'shish</UiButton>
          <h4>Tarix</h4>
          <ul class="hs"><li v-for="(h, i) in P.history" :key="i"><small>{{ d(h.date) }}</small><span>{{ h.who }}</span><b>{{ money(h.price) }}</b></li></ul>
        </UiCard>
      </div>
      <UiEmpty v-else title="Mahsulotni tanlang" text="Yoki yuqoridagi «Nima kerak?» qidiruvidan foydalaning." />
    </template>

    <!-- BUYURTMALAR -->
    <template v-else-if="tab === 'orders' && orders">
      <div class="sub">
        <button :class="{ on: ost === '' }" @click="ost = ''">Barchasi</button>
        <button v-for="s in M.order_statuses" :key="s.code" :class="{ on: ost === s.code }" @click="ost = s.code">{{ s.label }} <i>{{ orders.counts[s.code] }}</i></button>
      </div>
      <UiCard :padded="false">
        <button v-for="o in orders.items" :key="o.id" type="button" class="or" @click="openOrder(o.id)">
          <span><b>#{{ o.number }} {{ o.supplier }}</b><small>{{ d(o.created_at) }} · {{ o.items }} mahsulot{{ o.expected_date ? ` · kerak ${d(o.expected_date)}` : '' }}</small></span>
          <b>{{ money(o.total) }}</b><UiChip :tone="TONE[o.status]">{{ o.status_label }}</UiChip>
        </button>
        <UiEmpty v-if="!orders.items.length" title="Buyurtma yo'q" />
      </UiCard>
    </template>

    <!-- QARZDORLIK -->
    <template v-else-if="tab === 'debts' && D">
      <section class="kpis two"><div class="kpi"><div><small>Jami qarzimiz</small><b>{{ money(D.total) }}</b></div></div><div class="kpi"><div><small>Muddati o'tgan</small><b class="bad">{{ money(D.overdue) }}</b></div></div></section>
      <UiCard :padded="false" title="Ta'minotchilarga qarz">
        <div v-for="r in D.items.filter((x: any) => x.debt)" :key="r.supplier_id" class="dr">
          <span><b>{{ r.supplier }}</b><small>{{ r.phone }} · {{ ({ cash: 'naqd', transfer: 'o\'tkazma', credit: `nasiya ${r.credit_days} kun` } as any)[r.terms] }} · eng eski: {{ d(r.oldest) }}</small></span>
          <b :class="{ bad: r.overdue }">{{ money(r.debt) }}</b>
          <UiChip v-if="r.overdue" tone="danger">Muddati o'tgan</UiChip><span v-else></span>
          <UiButton v-if="M.can_pay" size="s" variant="brand" @click="pay = { supplier_id: r.supplier_id, supplier: r.supplier, amount: r.debt, method: 'cash', note: '' }">To'lash</UiButton>
        </div>
        <UiEmpty v-if="!D.items.some((x: any) => x.debt)" title="Qarz yo'q 🎉" />
      </UiCard>
      <UiCard title="So'nggi to'lovlar" :padded="false">
        <div v-for="p in D.recent_payments" :key="p.id" class="dr"><span><b>{{ p.supplier }}</b><small>{{ d(p.date) }} · {{ p.method }}</small></span><b>{{ money(p.amount) }}</b></div>
      </UiCard>
    </template>

    <OrderDrawer :open="od.open" :id="od.id" :preset="od.preset" :meta="M" @close="od.open = false" @changed="loadTab()" />
    <SupplierDrawer :open="sd.open" :id="sd.id" :edit="sd.edit" :meta="M" @close="sd.open = false" @changed="loadTab(); reloadMeta()"
      @order="(p: any) => { sd.open = false; openOrder(null, p) }" @pay="(p: any) => { sd.open = false; pay = { ...p, method: 'cash', note: '' } }" />
    <UiDrawer :open="!!pay" title="Ta'minotchiga to'lov" width="440px" @close="pay = null">
      <template v-if="pay">
        <p><b>{{ pay.supplier ?? M.suppliers.find((s: any) => s.id === pay.supplier_id)?.name }}</b></p>
        <UiInput v-model="pay.amount" type="number" label="Summa (so'm)" />
        <UiSelect v-model="pay.method" label="Qanday" :options="M.pay_methods.map((m: any) => ({ value: m.code, label: m.label }))" />
        <UiInput v-model="pay.note" label="Izoh" />
      </template>
      <template #footer><UiButton variant="ghost" @click="pay = null">Bekor</UiButton><UiButton variant="brand" @click="savePay()">To'lovni yozish</UiButton></template>
    </UiDrawer>
    <UiDrawer :open="!!mk" :title="mk?.id ? 'Bozorni tahrirlash' : 'Yangi yuk olish joyi'" width="520px" @close="mk = null">
      <template v-if="mk">
        <UiInput v-model="mk.name" label="Nomi" placeholder="Masalan: Qo'yliq ulgurji bozori" />
        <UiSelect v-model="mk.kind" label="Turi" :options="M.market_kinds.map((k: any) => ({ value: k.code, label: k.label }))" />
        <div class="g2"><UiInput v-model="mk.district" label="Tuman" /><UiInput v-model="mk.address" label="Manzil" /><UiInput v-model="mk.landmark" label="Mo'ljal" /><UiInput v-model="mk.hours" label="Ish vaqti" placeholder="05:00–18:00" /><UiInput v-model="mk.days" label="Kunlar" /><UiInput v-model="mk.phone" label="Telefon" /></div>
        <div class="cats sm"><button v-for="c in M.categories" :key="c.code" type="button" :class="{ on: mk.categories.includes(c.code) }" @click="toggleMkCat(c.code)"><span>{{ c.emoji }}</span>{{ c.name }}</button></div>
        <label class="fl"><span>Bozorchi uchun maslahat</span><textarea v-model="mk.tips" rows="3" placeholder="Ertalab 6 da boring, go'sht qatori chap tomonda, parking pullik…"></textarea></label>
        <UiToggle v-model="mk.is_active" label="Faol" />
      </template>
      <template #footer><UiButton variant="ghost" @click="mk = null">Bekor</UiButton><UiButton variant="brand" @click="saveMarket()">Saqlash</UiButton></template>
    </UiDrawer>
    <p class="foot">💡 Bozorchi uchun alohida sahifa: <RouterLink to="/market">Bozorlik va xarajat</RouterLink> — avans, chek rasmi, taksi/hammol, qaytgan pul.</p>
  </div>
</template>

<style scoped>
.pr { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; } .kpis.two { grid-template-columns: 1fr 1fr; }
.kpi { display: flex; gap: 12px; align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; text-align: left; font: inherit; color: var(--ink); min-width: 0; }
button.kpi { cursor: pointer; } button.kpi:hover { border-color: var(--accent); }
.kpi div { display: flex; flex-direction: column; min-width: 0; } .kpi small { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.kpi b { font-family: var(--font-display); font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .kpi em { font-style: normal; font-size: 11px; color: var(--muted); }
.ki { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; font-size: 20px; flex-shrink: 0; }
.ki.g { background: #E6F6EC; } .ki.b { background: #E7EEFD; } .ki.o { background: #FFF1E3; } .ki.p { background: #F1EAFE; } .ki.r { background: #FDECEC; }
.bad { color: var(--danger) !important; }
.srch { display: flex; gap: 10px; }
.sb { flex: 1; display: flex; align-items: center; gap: 10px; min-height: 50px; padding: 0 16px; border: 2px solid var(--line); border-radius: 14px; background: var(--surface); color: var(--muted); }
.sb:focus-within { border-color: var(--accent); } .sb input { flex: 1; border: 0; outline: none; font: inherit; font-size: var(--fs-m); background: transparent; color: var(--ink); min-width: 0; }
.cats { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: thin; padding-bottom: 2px; }
.cats > button { flex: 1 0 74px; }
.cats button { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 10px 6px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; color: var(--ink); text-align: center; line-height: 1.2; }
.cats button span { font-size: 28px; line-height: 1; } .cats button.on { border-color: var(--accent); background: var(--accent-tint); color: var(--accent); }
.cats.sm { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); margin: 10px 0; } .cats.sm button span { font-size: 20px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { flex-shrink: 0; border: 0; background: transparent; padding: 10px 14px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.sub { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.sub > button { display: inline-flex; align-items: center; gap: 4px; min-height: 36px; padding: 0 14px; border: 1px solid var(--line); border-radius: 99px; background: var(--surface); font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; color: var(--ink); }
.sub > button.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); } .sub i { font-style: normal; opacity: .7; font-size: 11px; } .sp { flex: 1; }
.mut { margin: 0; color: var(--muted); font-size: var(--fs-s); }
.res { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 14px; align-items: start; } .rs { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.of { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto 64px 110px; gap: 10px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.rk { width: 26px; height: 26px; border-radius: 8px; background: var(--surface-3); display: grid; place-items: center; font-weight: 800; font-size: 12px; } .rk.best { background: #F5B301; color: #fff; }
.on { display: flex; flex-direction: column; min-width: 0; } .on small { color: var(--muted); font-size: var(--fs-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pp { font-variant-numeric: tabular-nums; white-space: nowrap; } .pp small { color: var(--muted); font-weight: 500; }
.ch { font-weight: 800; font-size: var(--fs-xs); } .ch.up { color: var(--danger); } .ch.dn { color: var(--ok); } .vb { color: var(--muted); font-size: 11px; text-align: right; }
.sr { display: grid; grid-template-columns: 28px 1fr; gap: 0 8px; width: 100%; padding: 10px 14px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; cursor: pointer; color: var(--ink); }
.sr span { grid-row: span 2; font-size: 20px; } .sr small { color: var(--muted); font-size: var(--fs-xs); }
.mchips { display: flex; flex-wrap: wrap; gap: 6px; } .mchips a { padding: 6px 10px; border-radius: 99px; background: var(--surface-2); color: var(--ink); text-decoration: none; font-size: var(--fs-s); font-weight: 600; }
.home { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; } .home > :deep(.ui-card) { min-width: 0; }
.or { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; width: 100%; padding: 12px 16px; border: 0; border-top: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; cursor: pointer; color: var(--ink); }
.or:hover { background: var(--surface-2); } .or span { display: flex; flex-direction: column; min-width: 0; } .or b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .or small { color: var(--muted); font-size: var(--fs-xs); }
.lnk { border: 0; background: transparent; color: var(--accent); font-weight: 700; cursor: pointer; font: inherit; }
.top { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.top li { display: grid; grid-template-columns: minmax(0, 1fr) 90px auto; gap: 8px; align-items: center; font-size: var(--fs-s); }
.top li > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 8px; background: var(--surface-3); border-radius: 99px; overflow: hidden; } .bar i { display: block; height: 100%; background: var(--series-2); border-radius: 99px; }
.rr { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: center; width: 100%; padding: 9px 0; border: 0; border-bottom: 1px solid var(--line-2); background: transparent; text-align: left; font: inherit; cursor: pointer; color: var(--ink); }
.st { color: #D29A00; font-weight: 800; } .st small { color: var(--muted); font-weight: 500; }
.sl { display: flex; flex-direction: column; gap: 8px; }
.sc { display: grid; grid-template-columns: 56px minmax(0, 1.4fr) minmax(0, 1.4fr) 130px minmax(0, 1.1fr) 150px 32px; gap: 12px; align-items: center; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; }
.sc.off { opacity: .55; }
.av { width: 56px; height: 56px; border-radius: 14px; border: 0; background: var(--surface-2); font-size: 28px; cursor: pointer; }
.sn { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; border: 0; background: transparent; text-align: left; font: inherit; cursor: pointer; color: var(--ink); min-width: 0; }
.sn b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; } .sn small { color: var(--muted); font-size: var(--fs-xs); } .stars { color: #F5B301; letter-spacing: -1px; }
.sp2, .lp, .lo { display: flex; flex-direction: column; font-size: var(--fs-s); min-width: 0; } .sp2 small, .lp small, .lo small { color: var(--muted); font-size: 11px; }
.lp em { font-style: normal; font-size: 11px; color: var(--muted); }
.bt { display: flex; flex-direction: column; gap: 6px; }
.bt a { display: flex; align-items: center; justify-content: center; min-height: 32px; border-radius: 8px; font-weight: 700; font-size: var(--fs-xs); text-decoration: none; }
.b1 { border: 1px solid var(--ok); color: var(--ok); } .b2 { border: 1px solid #229ED9; color: #229ED9; }
.db { font-size: 11px; font-weight: 800; color: var(--warn-ink); text-align: center; } .db.bad { color: var(--danger); }
.ed { border: 0; background: transparent; color: var(--muted); cursor: pointer; }
.mg { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.mc { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 14px; display: flex; flex-direction: column; gap: 6px; } .mc.off { opacity: .55; }
.mh { display: flex; justify-content: space-between; gap: 8px; align-items: center; } .mh b { font-size: var(--fs-m); }
.md { margin: 0; font-size: var(--fs-s); color: var(--ink-2); }
.me { display: flex; flex-wrap: wrap; gap: 4px; } .me span { font-size: 11px; padding: 3px 8px; border-radius: 99px; background: var(--surface-2); font-weight: 600; }
.tip { margin: 0; font-size: var(--fs-xs); background: var(--warn-tint); padding: 8px 10px; border-radius: 10px; line-height: 1.4; }
.mf { display: flex; gap: 10px; align-items: center; margin-top: auto; padding-top: 6px; } .mf small { flex: 1; color: var(--muted); font-size: 11px; }
.mf a, .mf button { color: var(--accent); font-weight: 700; font-size: var(--fs-s); text-decoration: none; border: 0; background: transparent; cursor: pointer; font-family: inherit; }
.prs { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 14px; align-items: start; }
h4 { margin: 16px 0 6px; font-size: var(--fs-s); }
.hs { list-style: none; margin: 0; padding: 0; } .hs li { display: grid; grid-template-columns: 76px 1fr auto; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .hs small { color: var(--muted); }
.dr { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 12px; align-items: center; padding: 12px 16px; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.dr span { display: flex; flex-direction: column; min-width: 0; } .dr small { color: var(--muted); font-size: var(--fs-xs); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.fl { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; } .fl span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.fl textarea { border: 1px solid var(--line); border-radius: 12px; padding: 10px; font: inherit; background: var(--surface); color: var(--ink); }
.foot { margin: 0; color: var(--muted); font-size: var(--fs-s); } .foot a { color: var(--accent); font-weight: 700; }
@media (max-width: 1400px) { .sc { grid-template-columns: 56px minmax(0, 1.4fr) minmax(0, 1.4fr) 120px 150px 32px; } .sc .lo { display: none; } }
@media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .home { grid-template-columns: 1fr 1fr; } .home > :first-child { grid-column: 1 / -1; } .res, .prs { grid-template-columns: minmax(0, 1fr); }
  .sc { grid-template-columns: 56px minmax(0, 1fr) 140px 32px; } .sc .sp2, .sc .lp { display: none; } }
@media (max-width: 640px) {
  .kpis { grid-template-columns: 1fr 1fr; } .kpis > :first-child { grid-column: 1 / -1; } .kpi b { font-size: 17px; } .ki { width: 36px; height: 36px; font-size: 17px; }
  .srch { flex-direction: column; } .cats > button { flex: 0 0 72px; padding: 8px 2px; font-size: 10px; } .cats button span { font-size: 22px; }
  .or { grid-template-columns: minmax(0, 1fr) auto; } .or > :last-child { grid-column: 1 / -1; justify-self: start; }
  .home { grid-template-columns: minmax(0, 1fr); } .home > :first-child { grid-column: auto; }
  .of { grid-template-columns: 26px minmax(0, 1fr) auto; } .of .ch, .of .vb { display: none; }
  .sc { grid-template-columns: 48px minmax(0, 1fr) 32px; } .sc .ed { grid-column: 3; grid-row: 1; } .sc .bt { grid-column: 1 / -1; flex-direction: row; align-items: center; } .sc .bt a { flex: 1; } .av { width: 48px; height: 48px; font-size: 24px; }
  .dr { grid-template-columns: 1fr auto; } .g2 { grid-template-columns: 1fr; } .mg { grid-template-columns: minmax(0, 1fr); }
}
</style>
