<script setup lang="ts">
/**
 * Kassa — planshet/telefon uchun: katta tugmalar, 3 bosqich: taom → savat → to'lov.
 * IT tushunmaydigan kassir uchun: minimal matn, katta raqamlar, xato bo'lsa oddiy tilda.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, money, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import ShiftPanel from '@/components/pos/ShiftPanel.vue'

const a = useAuth(), ui = useUi()
const menu = ref<any>({ categories: [], payment_methods: [], order_types: [] })
const activeCat = ref<number | null>(null)
const q = ref('')
const cart = ref<{ product: any; qty: number }[]>([])
const orderType = ref('takeaway')
const tableNo = ref('')
const phone = ref('')
const discount = ref(0)
const shift = ref<any>(null)
const summary = ref<any>(null)
const orders = ref<any[]>([])
const paying = ref(false)
const payDrawer = ref(false)
const ordersDrawer = ref(false)
const shiftDrawer = ref(false)
const payLink = ref<string | null>(null)
const lastPaid = ref<any>(null)

const products = computed(() => {
  const cat = menu.value.categories.find((c: any) => c.id === activeCat.value)
  const all = cat ? cat.products : menu.value.categories.flatMap((c: any) => c.products)
  const qq = q.value.toLowerCase()
  return qq ? menu.value.categories.flatMap((c: any) => c.products).filter((p: any) => t(p.name, ui.lang).toLowerCase().includes(qq)) : all
})
const subtotal = computed(() => cart.value.reduce((s, i) => s + i.product.price * i.qty, 0))
// CRM: telefon/promokod kiritilsa — server hisoblaydi (mijoz kartasi, aksiya, bonus)
const crmOn = computed(() => a.hasModule('crm'))
const promoCode = ref('')
const useBonus = ref(false)
const quote = ref<any>(null)
let qTimer: any = null
async function reQuote() {
  if (!crmOn.value || !cart.value.length || (phone.value.replace(/\D/g, '').length < 9 && !promoCode.value.trim())) { quote.value = null; return }
  try {
    quote.value = await api.post('/crm/quote', { phone: phone.value, promo_code: promoCode.value, manual_discount: Number(discount.value || 0),
      use_bonus: useBonus.value ? null : 0, items: cart.value.map(i => ({ product_id: i.product.id, qty: i.qty })) })
  } catch { quote.value = null }
}
watch([phone, promoCode, useBonus, discount, () => cart.value.map(i => i.qty + ':' + i.product.id).join()], () => { clearTimeout(qTimer); qTimer = setTimeout(reQuote, 300) })
const total = computed(() => quote.value ? quote.value.total : Math.max(0, subtotal.value - Number(discount.value || 0)))
const count = computed(() => cart.value.reduce((s, i) => s + i.qty, 0))
const METHOD_ICON: Record<string, string> = { cash: 'receipt', card: 'box', click: 'globe', payme: 'globe', uzum: 'globe', transfer: 'chart' }

async function load() {
  menu.value = await api.get('/pos/menu')
  activeCat.value = menu.value.categories[0]?.id ?? null
  shift.value = await api.get('/pos/shift')
  summary.value = await api.get('/pos/summary')
}
onMounted(load)

function add(p: any) {
  if (p.in_stop_list) { toast('Bu taom hozir yo\'q (stop-list)', 'danger'); return }
  const i = cart.value.find(x => x.product.id === p.id)
  i ? i.qty++ : cart.value.push({ product: p, qty: 1 })
}
function dec(i: any) { i.qty > 1 ? i.qty-- : cart.value.splice(cart.value.indexOf(i), 1) }

async function pay(method: string) {
  if (!cart.value.length) return
  paying.value = true
  try {
    const o = await api.post('/pos/orders', { items: cart.value.map(i => ({ product_id: i.product.id, qty: i.qty })), type: orderType.value,
      table_no: tableNo.value, customer_phone: phone.value, discount: Number(discount.value || 0) })
    if (quote.value) {
      await api.post(`/crm/orders/${o.id}/attach`, { phone: phone.value, promo_code: promoCode.value, manual_discount: Number(discount.value || 0),
        use_bonus: useBonus.value ? quote.value.bonus : 0 })
    }
    if (method === 'click' || method === 'payme') {
      const link = await api.post('/payments/link', { order_id: o.id, provider: method }).catch(() => null)
      if (link?.ok) { payLink.value = link.url; window.open(link.url, '_blank') }
      else if (link && !link.ok) toast(link.error, 'danger')
    }
    const paid = await api.post(`/pos/orders/${o.id}/pay`, { payment_method: method })
    lastPaid.value = paid
    cart.value = []; discount.value = 0; tableNo.value = ''; phone.value = ''; promoCode.value = ''; useBonus.value = false; quote.value = null; payDrawer.value = false
    summary.value = await api.get('/pos/summary')
    toast(`Buyurtma #${paid.number} — ${money(paid.total)} ✓`)
  } catch (e: any) { toast(e.detail ?? 'To\'lov o\'tmadi', 'danger') } finally { paying.value = false }
}

async function openOrders() { orders.value = await api.get('/pos/orders', { today: true }); ordersDrawer.value = true }
async function cancelOrder(o: any) {
  const reason = prompt('Bekor qilish sababi:'); if (reason === null) return
  try { await api.post(`/pos/orders/${o.id}/cancel`, { reason }); await openOrders(); summary.value = await api.get('/pos/summary') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function onShiftChanged(s: any) { shift.value = s; summary.value = await api.get('/pos/summary').catch(() => summary.value) }
// kassaga kirim / chiqim (xarajat, inkassatsiya, maydalash)
const moveOpen = ref(false), move = ref({ kind: 'out', amount: '' as number | '', reason: '' })
const MOVE_REASONS = { out: ['Inkassatsiya (rahbarga)', 'Xarajat: non/suv', 'Bozorlik', 'Taksi/yetkazish'], in: ['Maydalash uchun pul', 'Qarz qaytarildi', 'Boshqa kirim'] } as Record<string, string[]>
async function saveMove() {
  try {
    shift.value = await api.post(`/pos/shift/${shift.value.id}/move`, { kind: move.value.kind, amount: Number(move.value.amount || 0), reason: move.value.reason })
    moveOpen.value = false; toast(move.value.kind === 'in' ? 'Kirim yozildi' : 'Chiqim yozildi'); move.value = { kind: 'out', amount: '', reason: '' }
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function printReceipt(o: any) {
  const w = window.open('', '_blank', 'width=380,height=600'); if (!w) return
  w.document.write(`<pre style="font:14px/1.4 monospace;padding:12px">${a.me?.tenant.name}\nBuyurtma #${o.number}\n${new Date(o.paid_at).toLocaleString('uz-UZ')}\n${'-'.repeat(32)}\n` +
    o.items.map((i: any) => `${i.name} x${i.qty}\n${' '.repeat(20)}${money(i.line_total)}`).join('\n') +
    `\n${'-'.repeat(32)}\n${o.discount ? 'Chegirma: -' + money(o.discount) + '\n' : ''}JAMI: ${money(o.total)}\nTo'lov: ${o.payment_method}\n\nRahmat! Yana kutamiz.</pre>`)
  w.document.close(); w.print()
}
</script>

<template>
  <div class="pos">
    <header class="bar">
      <div v-if="summary" class="sum">
        <span><b>{{ money(summary.total) }}</b><small>bugun</small></span>
        <span><b>{{ summary.orders }}</b><small>chek</small></span>
        <span><b>{{ money(summary.avg_check) }}</b><small>o'rtacha</small></span>
      </div>
      <div class="sp"></div>
      <UiChip v-if="shift" tone="ok"><UiIcon name="clock" :size="13" /> Smena ochiq · {{ new Date(shift.opened_at).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }) }}</UiChip>
      <UiChip v-else tone="warn">Smena yopiq</UiChip>
      <UiButton v-if="shift && a.can('pos.shift')" size="s" variant="secondary" @click="moveOpen = true">💵 Kirim / chiqim</UiButton>
      <UiButton v-if="a.can('pos.shift')" size="s" :variant="shift ? 'secondary' : 'brand'" @click="shiftDrawer = true">{{ shift ? '🤝 Kassani topshirish' : 'Smena ochish' }}</UiButton>
      <UiButton size="s" variant="secondary" @click="openOrders()"><UiIcon name="list" :size="14" /> Bugungi cheklar</UiButton>
    </header>

    <div class="work">
      <section class="menu">
        <div class="cats">
          <button :class="{ on: activeCat === null && !q }" @click="activeCat = null; q = ''">Hammasi</button>
          <button v-for="c in menu.categories" :key="c.id" :class="{ on: activeCat === c.id && !q }" @click="activeCat = c.id; q = ''">{{ t(c.name, ui.lang) }}</button>
          <UiInput v-model="q" placeholder="Qidirish…" class="srch" />
        </div>
        <div class="grid">
          <button v-for="p in products" :key="p.id" class="prod" :class="{ stop: p.in_stop_list }" @click="add(p)">
            <img v-if="p.image" :src="p.image" alt="" loading="lazy" referrerpolicy="no-referrer" @error="p.image = null" />
            <span v-else class="ph">{{ t(p.name, ui.lang).slice(0, 1) }}</span>
            <b>{{ t(p.name, ui.lang) }}</b>
            <span class="pr">{{ money(p.price) }}</span>
            <span v-if="p.in_stop_list" class="stopl">Yo'q</span>
          </button>
          <UiEmpty v-if="!products.length" title="Taom topilmadi" />
        </div>
      </section>

      <aside class="cart">
        <div class="types">
          <button v-for="ty in menu.order_types" :key="ty.code" :class="{ on: orderType === ty.code }" @click="orderType = ty.code">{{ ty.label }}</button>
        </div>
        <div v-if="orderType === 'dine_in'" class="row2"><UiInput v-model="tableNo" placeholder="Stol №" /><UiInput v-model="phone" placeholder="Mijoz tel (bonus)" /></div>
        <UiInput v-else v-model="phone" placeholder="Mijoz telefoni (bonus uchun, ixtiyoriy)" />
        <div v-if="quote?.customer" class="cust">
          <b>{{ quote.customer.name || quote.customer.phone }}<span v-if="quote.customer.birthday_soon"> 🎂</span></b>
          <UiChip :tone="quote.customer.level.code === 'gold' ? 'warn' : quote.customer.level.code === 'silver' ? 'info' : 'neutral'">{{ quote.customer.level.name }}</UiChip>
          <span class="bal">bonus <b>{{ money(quote.customer.balance) }}</b></span>
        </div>
        <div v-else-if="quote?.is_new" class="cust new">Yangi mijoz — karta ochiladi va sovg'a bonus beriladi 🎁</div>
        <div class="items">
          <div v-for="i in cart" :key="i.product.id" class="it">
            <div class="n"><b>{{ t(i.product.name, ui.lang) }}</b><small>{{ money(i.product.price) }}</small></div>
            <div class="qty"><button @click="dec(i)">−</button><b>{{ i.qty }}</b><button @click="i.qty++">+</button></div>
            <b class="lt">{{ money(i.product.price * i.qty) }}</b>
          </div>
          <p v-if="!cart.length" class="empty">Taomni bosing — savatga tushadi</p>
        </div>
        <div class="tot">
          <div class="disc"><span>Chegirma</span><input v-model="discount" type="number" min="0" step="1000" /><span>so'm</span></div>
          <template v-if="crmOn">
            <div class="disc"><span>Promokod</span><input v-model="promoCode" class="code" placeholder="—" /></div>
            <div v-if="quote?.promo" class="crmline ok"><span>🏷 {{ quote.promo.name }}</span><b>−{{ money(quote.promo.discount) }}</b></div>
            <div v-else-if="quote?.promo_error" class="crmline bad">{{ quote.promo_error }}</div>
            <label v-if="quote?.customer && quote.customer.balance > 0" class="crmline usebonus"><input v-model="useBonus" type="checkbox" /><span>Bonus bilan to'lash</span><b v-if="useBonus">−{{ money(quote.bonus) }}</b><small v-else>{{ money(quote.max_bonus) }} gacha</small></label>
            <div v-if="quote?.will_earn" class="crmline earn">Mijozga qaytadi: +{{ money(quote.will_earn) }} bonus</div>
          </template>
          <div class="line"><span>{{ count }} ta</span><b>{{ money(total) }}</b></div>
          <UiButton variant="brand" size="l" block :disabled="!cart.length" @click="payDrawer = true"><UiIcon name="check" :size="18" /> To'lash · {{ money(total) }}</UiButton>
          <div class="row2 mini"><UiButton variant="ghost" size="s" block :disabled="!cart.length" @click="cart = []">Tozalash</UiButton><UiButton v-if="lastPaid" variant="ghost" size="s" block @click="printReceipt(lastPaid)">Chek #{{ lastPaid.number }}</UiButton></div>
        </div>
      </aside>
    </div>

    <UiDrawer :open="payDrawer" title="To'lov usuli" width="460px" @close="payDrawer = false">
      <div class="pay-total"><span>To'lanadi</span><b>{{ money(total) }}</b></div>
      <div class="pay-grid">
        <button v-for="m in menu.payment_methods" :key="m.code" class="pay" :disabled="paying" @click="pay(m.code)">
          <UiIcon :name="METHOD_ICON[m.code] ?? 'receipt'" :size="22" /><b>{{ m.label }}</b>
        </button>
      </div>
      <p class="hint">Click / Payme — mijozga to'lov havolasi/QR ochiladi (Sozlamalar → To'lovlar'da merchant kalitlari kerak). Naqd/karta — darhol yopiladi.</p>
    </UiDrawer>

    <UiDrawer :open="ordersDrawer" title="Bugungi cheklar" width="560px" @close="ordersDrawer = false">
      <div v-for="o in orders" :key="o.id" class="ord" :class="o.status">
        <div class="oh"><b>#{{ o.number }}</b><span class="mut">{{ new Date(o.created_at).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }) }} · {{ o.cashier }}</span>
          <UiChip :tone="o.status === 'paid' ? 'ok' : o.status === 'open' ? 'warn' : 'danger'">{{ ({ paid: o.payment_method, open: 'ochiq', cancelled: 'bekor' } as Record<string, string>)[o.status] }}</UiChip><b class="ot">{{ money(o.total) }}</b></div>
        <small>{{ o.items.map((i: any) => `${i.name} ×${i.qty}`).join(', ') }}</small>
        <div class="oa"><UiButton size="s" variant="ghost" @click="printReceipt(o)">Chek</UiButton><UiButton v-if="o.status !== 'cancelled'" size="s" variant="ghost" @click="cancelOrder(o)">Bekor</UiButton></div>
      </div>
      <UiEmpty v-if="!orders.length" title="Bugun chek yo'q" />
    </UiDrawer>

    <ShiftPanel :open="shiftDrawer" :shift="shift" :branch-id="ui.branch" @close="shiftDrawer = false" @changed="onShiftChanged" />
    <UiDrawer :open="moveOpen" title="Kassaga kirim / chiqim" width="440px" @close="moveOpen = false">
      <div class="mvk"><button type="button" :class="{ on: move.kind === 'out' }" @click="move.kind = 'out'">↑ Chiqim (pul olindi)</button><button type="button" :class="{ on: move.kind === 'in' }" @click="move.kind = 'in'">↓ Kirim (pul qo'yildi)</button></div>
      <UiInput v-model="move.amount" type="number" label="Summa" suffix="so'm" />
      <UiInput v-model="move.reason" label="Sababi" placeholder="Masalan: non uchun" />
      <div class="mvr"><button v-for="r in MOVE_REASONS[move.kind]" :key="r" type="button" @click="move.reason = r">{{ r }}</button></div>
      <p class="mut">Kassa topshirilganda kutilgan naqd shunga qarab hisoblanadi.</p>
      <template #footer><span style="flex:1"></span><UiButton variant="brand" @click="saveMove">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.pos { display: flex; flex-direction: column; gap: 12px; min-height: calc(100vh - var(--topbar-h) - 2 * var(--gutter)); }
.bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sum { display: flex; gap: 14px; } .sum span { display: flex; flex-direction: column; } .sum b { font-family: var(--font-display); font-size: var(--fs-l); } .sum small { color: var(--muted); font-size: var(--fs-xs); }
.sp { flex: 1; }
.work { display: grid; grid-template-columns: 1fr 360px; gap: 12px; flex: 1; min-height: 0; }
.menu { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.cats { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.cats button { min-height: var(--touch); padding: 0 14px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); font-weight: 700; cursor: pointer; }
.cats button.on { background: var(--ink); color: var(--ink-inv); border-color: var(--ink); }
.srch { min-width: 160px; margin-left: auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.prod { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 10px; border-radius: var(--radius-l); border: 1px solid var(--line); background: var(--surface); cursor: pointer; text-align: left; min-height: 120px; }
.prod:active { transform: scale(.98); } .prod.stop { opacity: .5; }
.prod img, .prod .ph { width: 100%; aspect-ratio: 4/3; object-fit: cover; border-radius: var(--radius); background: var(--surface-3); display: grid; place-items: center; font-family: var(--font-display); font-size: 28px; font-weight: 800; color: var(--muted); }
.prod b { font-size: var(--fs-s); line-height: 1.25; } .pr { color: var(--accent); font-weight: 800; }
.stopl { position: absolute; top: 8px; right: 8px; background: var(--danger); color: #fff; border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 800; }
.cart { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px; display: flex; flex-direction: column; gap: 10px; position: sticky; top: calc(var(--topbar-h) + var(--gutter)); max-height: calc(100vh - var(--topbar-h) - 2 * var(--gutter)); }
.types { display: flex; gap: 4px; background: var(--surface-2); border-radius: var(--radius); padding: 3px; }
.types button { flex: 1; min-height: 44px; padding: 4px 6px; border: 0; border-radius: var(--radius-s); background: transparent; font-weight: 700; font-size: var(--fs-s); line-height: 1.15; color: var(--ink-2); cursor: pointer; }
.types button.on { background: var(--surface); box-shadow: var(--shadow); }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.items { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; min-height: 120px; }
.it { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--line-2); }
.it .n { display: flex; flex-direction: column; min-width: 0; } .it .n b { font-size: var(--fs-s); } .it small { color: var(--muted); }
.qty { display: flex; align-items: center; gap: 4px; } .qty button { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface); font-size: 18px; cursor: pointer; }
.qty b { min-width: 20px; text-align: center; } .lt { font-size: var(--fs-s); min-width: 74px; text-align: right; }
.empty { color: var(--muted); text-align: center; margin: auto; font-size: var(--fs-s); }
.tot { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--line); padding-top: 10px; }
.disc { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); color: var(--muted); } .disc input { flex: 1; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 6px 8px; }
.line { display: flex; justify-content: space-between; align-items: baseline; } .line b { font-family: var(--font-display); font-size: var(--fs-2xl); }
.mini { margin-top: 2px; }
.cust { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--accent-tint); border-radius: var(--radius); font-size: var(--fs-s); flex-wrap: wrap; }
.cust.new { color: var(--accent); font-weight: 700; } .cust .bal { margin-left: auto; } .cust .bal b { color: var(--accent); }
.crmline { display: flex; align-items: center; gap: 8px; font-size: var(--fs-s); padding: 2px 0; } .crmline b { margin-left: auto; }
.crmline.ok { color: var(--ok); font-weight: 700; } .crmline.bad { color: var(--danger); font-size: var(--fs-xs); }
.crmline.earn { color: var(--muted); font-size: var(--fs-xs); } .usebonus { cursor: pointer; font-weight: 700; } .usebonus small { margin-left: auto; color: var(--muted); }
.usebonus input { width: 18px; height: 18px; accent-color: var(--accent); }
.code { text-transform: uppercase; }
.pay-total { display: flex; flex-direction: column; align-items: center; padding: 14px; background: var(--surface-2); border-radius: var(--radius-l); margin-bottom: 12px; }
.pay-total span { color: var(--muted); font-size: var(--fs-s); } .pay-total b { font-family: var(--font-display); font-size: var(--fs-3xl); }
.pay-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.pay { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 18px 10px; border-radius: var(--radius-l); border: 1px solid var(--line); background: var(--surface); cursor: pointer; font-size: var(--fs-b); }
.pay:hover { border-color: var(--accent); background: var(--accent-tint); }
.hint, .mut { color: var(--muted); font-size: var(--fs-xs); }
.ord { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; display: flex; flex-direction: column; gap: 4px; } .ord.cancelled { opacity: .55; }
.oh { display: flex; align-items: center; gap: 8px; } .ot { margin-left: auto; } .oa { display: flex; gap: 4px; }
@media (max-width: 900px) { .work { grid-template-columns: 1fr; } .cart { position: static; max-height: none; } .grid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); } }
.mvk { display: flex; gap: 6px; } .mvk button { flex: 1; min-height: 44px; border: 1px solid var(--line); background: var(--surface-2); border-radius: 12px; font: inherit; font-weight: 800; cursor: pointer; color: var(--ink-2); }
.mvk button.on { background: var(--ink); color: var(--surface); border-color: var(--ink); }
.mvr { display: flex; gap: 6px; flex-wrap: wrap; } .mvr button { border: 1px dashed var(--line); background: transparent; border-radius: 999px; padding: 5px 11px; font: inherit; font-size: var(--fs-xs); font-weight: 700; cursor: pointer; color: var(--ink-2); }
</style>
