<script setup lang="ts">
/**
 * Shartnoma imzolangan restoranni HQ'dan ochish: restoran, egasi, hudud, filiallar, tarif va to'lov sharti, yuridik ma'lumot.
 * Bitta tugma: sxema + egasi + filiallar + modullar + shartnoma + billing. O'ngda — oylik to'lov va birinchi to'lov sanasi.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiIcon, toast } from '@restopos/ui'
import { money } from '../fmt'
import { useHq } from '../store'

const s = useHq(), router = useRouter()
const R = ref<any>(null)
const busy = ref(false)
const done = ref<any>(null)
const F = reactive({
  name: '', slug: '', preset: 'restaurant', owner_name: '', owner_phone: '', region: '', district: '', address: '',
  branches: ['Asosiy filial'] as string[], free_days: 30,
  contract: { tariff: 'base', price: 100 as number | null, currency: 'USD', billing_day: 5, included_branches: 1, extra_branch_price: 0,
    signed_at: new Date().toISOString().slice(0, 10), company: '', inn: '', contact_name: '', contact_phone: '', terms: '', manager_id: null as number | null },
})
const slugTouched = ref(false)
onMounted(async () => {
  R.value = await api.get('/hq/refs')
  F.free_days = R.value.trial_days ?? 30
  F.contract.price = R.value.tariffs.find((t: any) => t.code === 'base')?.price ?? 100
  F.contract.manager_id = s.me?.id ?? null
})
const translit = (v: string) => v.toLowerCase().replace(/[ʻʼ'`‘’]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 30)
watch(() => F.name, (v) => { if (!slugTouched.value) F.slug = translit(v) })
function pickTariff(code: string) {
  F.contract.tariff = code
  const p = R.value?.tariffs.find((t: any) => t.code === code)?.price
  if (p != null && F.contract.currency === 'USD') F.contract.price = p
}
const districts = computed(() => R.value?.regions.find((r: any) => r.name === F.region)?.districts ?? [])
const nBranches = computed(() => F.branches.filter(b => b.trim()).length || 1)
const monthly = computed(() => (Number(F.contract.price) || 0) + Math.max(0, nBranches.value - (Number(F.contract.included_branches) || 1)) * (Number(F.contract.extra_branch_price) || 0))
const paidFrom = computed(() => { const d = new Date(); d.setDate(d.getDate() + (Number(F.free_days) || 0)); return d })
const firstPay = computed(() => {
  const p = paidFrom.value, day = Math.min(28, Math.max(1, Number(F.contract.billing_day) || 5))
  let d = new Date(p.getFullYear(), p.getMonth(), day)
  if (d < p) d = new Date(p.getFullYear(), p.getMonth() + 1, day)
  return d
})
const OY = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr']
const fmtD = (d: Date) => `${d.getDate()}-${OY[d.getMonth()]} ${d.getFullYear()}`
const ready = computed(() => F.name.trim() && /^[a-z0-9][a-z0-9-]{2,30}$/.test(F.slug) && F.owner_phone.replace(/\D/g, '').length >= 9)

async function submit() {
  if (!ready.value) { toast('Restoran nomi, manzil va egasining telefonini kiriting', 'danger'); return }
  busy.value = true
  try {
    done.value = await api.post('/hq/tenants', { ...F, branches: F.branches.filter(b => b.trim()), free_days: Number(F.free_days) || 0,
      contract: { ...F.contract, price: Number(F.contract.price), billing_day: Number(F.contract.billing_day), included_branches: Number(F.contract.included_branches) || 1,
        extra_branch_price: Number(F.contract.extra_branch_price) || 0, signed_at: F.contract.signed_at || null, paid_from: null } })
    toast('Restoran ochildi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
</script>

<template>
  <div v-if="R" class="nt">
    <RouterLink to="/tenants" class="back">← Mijozlar</RouterLink>

    <UiCard v-if="done" class="ok-card">
      <div class="ok-in">
        <span class="okc">✓</span>
        <div>
          <h2>«{{ F.name }}» ochildi</h2>
          <p>Shartnoma <b>{{ done.contract.number }}</b> · {{ done.contract.tariff_label }} · {{ money(done.contract.price, done.contract.currency) }}/oy · birinchi to'lov {{ fmtD(firstPay) }}</p>
          <ul>
            <li>Panel: <a :href="done.admin_url" target="_blank" rel="noopener">{{ done.admin_url }}</a></li>
            <li>Egasi <b>{{ done.owner_phone }}</b> raqami bilan kiradi (SMS kod yoki parol).</li>
            <li>Filiallar: {{ done.branches.join(', ') }}</li>
          </ul>
          <div class="acts">
            <UiButton variant="brand" @click="router.push(`/tenants/${done.id}`)">Mijoz kartasini ochish</UiButton>
            <UiButton variant="ghost" @click="done = null; F.name = ''; F.slug = ''; F.owner_phone = ''; F.owner_name = ''; F.branches = ['Asosiy filial']">Yana restoran ochish</UiButton>
          </div>
        </div>
      </div>
    </UiCard>

    <div v-else class="grid">
      <div class="col">
        <UiCard title="1. Restoran">
          <div class="g2">
            <label class="f"><span>Restoran nomi *</span><input v-model="F.name" placeholder="Masalan: Somsa Markazi" /></label>
            <label class="f"><span>Manzil (panel havolasi) *</span><span class="slug"><input v-model="F.slug" placeholder="somsa-markazi" @input="slugTouched = true" /><em>.{{ R.domain }}</em></span></label>
            <label class="f"><span>Turi</span><select v-model="F.preset"><option v-for="p in R.presets" :key="p.code" :value="p.code">{{ p.name }}</option></select></label>
            <label class="f"><span>Mas'ul menejer</span><select v-model="F.contract.manager_id"><option :value="null">—</option><option v-for="x in R.staff" :key="x.id" :value="x.id">{{ x.name }}</option></select></label>
          </div>
        </UiCard>

        <UiCard title="2. Egasi">
          <div class="g2">
            <label class="f"><span>Ismi</span><input v-model="F.owner_name" placeholder="Sardor Karimov" /></label>
            <label class="f"><span>Telefon *</span><input v-model="F.owner_phone" type="tel" inputmode="tel" placeholder="+998 90 123 45 67" /></label>
          </div>
          <p class="hint">Egasi shu raqam bilan panelga kiradi va xodimlarini o'zi qo'shadi.</p>
        </UiCard>

        <UiCard title="3. Hudud va filiallar">
          <div class="g3">
            <label class="f"><span>Viloyat</span><select v-model="F.region" @change="F.district = ''"><option value="">—</option><option v-for="r in R.regions" :key="r.name" :value="r.name">{{ r.name }}</option></select></label>
            <label class="f"><span>Tuman / shahar</span><input v-model="F.district" list="ntDistricts" placeholder="Tanlang yoki yozing" /><datalist id="ntDistricts"><option v-for="d in districts" :key="d" :value="d" /></datalist></label>
            <label class="f"><span>Manzil</span><input v-model="F.address" placeholder="Ko'cha, uy" /></label>
          </div>
          <div class="br">
            <span class="lbl">Filiallar ({{ nBranches }})</span>
            <div v-for="(b, i) in F.branches" :key="i" class="bri">
              <input v-model="F.branches[i]" :placeholder="i ? `${i + 1}-filial nomi` : 'Asosiy filial'" />
              <button v-if="F.branches.length > 1" type="button" aria-label="Olib tashlash" @click="F.branches.splice(i, 1)">✕</button>
            </div>
            <button type="button" class="add" @click="F.branches.push('')"><UiIcon name="plus" :size="14" /> Filial qo'shish</button>
          </div>
        </UiCard>

        <UiCard title="4. Tarif va to'lov sharti">
          <div class="tar">
            <button v-for="t in R.tariffs" :key="t.code" type="button" :class="{ on: F.contract.tariff === t.code, ai: t.code === 'ai' }" @click="pickTariff(t.code)">
              <b>{{ t.name }}</b><small>sayt narxi: ${{ t.price }}/oy</small>
            </button>
          </div>
          <div class="g4">
            <label class="f"><span>Oylik narx (shartnoma)</span><input v-model.number="F.contract.price" type="number" min="0" /></label>
            <label class="f"><span>Valyuta</span><select v-model="F.contract.currency"><option v-for="c in R.currencies" :key="c.code" :value="c.code">{{ c.code }} ({{ c.name }})</option></select></label>
            <label class="f"><span>Har oy to'lov kuni</span><input v-model.number="F.contract.billing_day" type="number" min="1" max="28" /></label>
            <label class="f"><span>Bepul davr (kun)</span><input v-model.number="F.free_days" type="number" min="0" max="365" /></label>
            <label class="f"><span>Narx ichidagi filiallar</span><input v-model.number="F.contract.included_branches" type="number" min="1" /></label>
            <label class="f"><span>Qo'shimcha filial / oy</span><input v-model.number="F.contract.extra_branch_price" type="number" min="0" /></label>
            <label class="f"><span>Imzolangan sana</span><input v-model="F.contract.signed_at" type="date" /></label>
          </div>
        </UiCard>

        <UiCard title="5. Yuridik ma'lumot va maxsus shartlar">
          <div class="g2">
            <label class="f"><span>Yuridik nom</span><input v-model="F.contract.company" placeholder="«Somsa Markazi» MChJ" /></label>
            <label class="f"><span>STIR (INN)</span><input v-model="F.contract.inn" inputmode="numeric" maxlength="9" placeholder="9 ta raqam" /></label>
            <label class="f"><span>Aloqa uchun shaxs</span><input v-model="F.contract.contact_name" placeholder="Buxgalter / menejer" /></label>
            <label class="f"><span>Aloqa telefoni</span><input v-model="F.contract.contact_phone" type="tel" /></label>
          </div>
          <label class="f"><span>Maxsus kelishuvlar</span><textarea v-model="F.contract.terms" rows="3" placeholder="Chegirma, qo'shimcha ishlar, alohida talablar…"></textarea></label>
        </UiCard>
      </div>

      <aside class="sumc">
        <UiCard title="Xulosa">
          <dl>
            <dt>Restoran</dt><dd>{{ F.name || '—' }}</dd>
            <dt>Panel</dt><dd class="mono">{{ F.slug || '…' }}.{{ R.domain }}</dd>
            <dt>Hudud</dt><dd>{{ [F.region, F.district].filter(Boolean).join(', ') || '—' }}</dd>
            <dt>Filiallar</dt><dd>{{ nBranches }}</dd>
            <dt>Tarif</dt><dd>{{ R.tariffs.find((t: any) => t.code === F.contract.tariff)?.name }}</dd>
          </dl>
          <div class="pay">
            <small>Oylik to'lov</small>
            <b>{{ money(monthly, F.contract.currency) }}</b>
            <span v-if="nBranches > F.contract.included_branches && F.contract.extra_branch_price">{{ money(F.contract.price, F.contract.currency) }} + {{ nBranches - F.contract.included_branches }} × {{ money(F.contract.extra_branch_price, F.contract.currency) }}</span>
          </div>
          <dl>
            <dt>Bepul</dt><dd>{{ F.free_days }} kun — {{ fmtD(paidFrom) }} gacha</dd>
            <dt>Birinchi to'lov</dt><dd><b>{{ fmtD(firstPay) }}</b></dd>
            <dt>Keyin</dt><dd>har oyning {{ F.contract.billing_day }}-sanasi</dd>
          </dl>
          <UiButton variant="brand" block :loading="busy" :disabled="!ready" @click="submit()">Restoranni ochish</UiButton>
          <p class="hint">Sxema, egasi, filiallar, modullar ({{ F.contract.tariff === 'ai' ? 'AI Kotib bilan' : 'AI Kotibsiz' }}) va shartnoma bir vaqtda yaratiladi. 5–15 soniya.</p>
        </UiCard>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.nt { display: flex; flex-direction: column; gap: 14px; }
.back { color: #2563EB; text-decoration: none; font-weight: 700; font-size: var(--fs-s); }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; align-items: start; }
.col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.sumc { position: sticky; top: 84px; }
.g2, .g3, .g4 { display: grid; gap: 10px; } .g2 { grid-template-columns: repeat(2, minmax(0, 1fr)); } .g3 { grid-template-columns: repeat(3, minmax(0, 1fr)); } .g4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.f { display: flex; flex-direction: column; gap: 6px; min-width: 0; } .f > span:first-child { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); }
input, select, textarea { min-height: 42px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; background: var(--surface); color: var(--ink); width: 100%; box-sizing: border-box; }
textarea { padding: 10px 12px; resize: vertical; }
input:focus, select:focus, textarea:focus { outline: none; border-color: #2563EB; box-shadow: 0 0 0 3px #DBE7FF; }
.slug { display: flex; align-items: center; gap: 6px; } .slug em { font-style: normal; color: var(--muted); font-size: var(--fs-s); white-space: nowrap; }
.hint { margin: 8px 0 0; color: var(--muted); font-size: var(--fs-xs); }
.br { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; } .lbl { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); }
.bri { display: flex; gap: 6px; } .bri button { border: 1px solid var(--line); background: var(--surface); border-radius: 10px; width: 42px; cursor: pointer; color: var(--muted); }
.add { align-self: flex-start; display: inline-flex; align-items: center; gap: 6px; border: 1px dashed #93B4F5; background: #F5F8FF; color: #2563EB; border-radius: 10px; padding: 8px 12px; font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; }
.tar { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.tar button { border: 1.5px solid var(--line); border-radius: 14px; background: var(--surface); padding: 14px; text-align: left; cursor: pointer; font: inherit; color: var(--ink); display: flex; flex-direction: column; gap: 2px; }
.tar button.on { border-color: #2563EB; background: #EFF4FF; } .tar button.ai.on { border-color: #8B5CF6; background: #F5F0FF; } .tar small { color: var(--muted); font-size: var(--fs-xs); }
dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 12px; margin: 0 0 12px; font-size: var(--fs-s); } dt { color: var(--muted); } dd { margin: 0; text-align: right; overflow-wrap: anywhere; } .mono { font-family: ui-monospace, monospace; font-size: 12px; }
.pay { border-radius: 14px; background: linear-gradient(135deg, #EFF4FF, #F5F0FF); padding: 14px; margin: 4px 0 12px; display: flex; flex-direction: column; gap: 2px; }
.pay small { color: var(--muted); font-size: var(--fs-xs); font-weight: 700; } .pay b { font-family: var(--font-display); font-size: 28px; color: #1D4ED8; } .pay span { font-size: var(--fs-xs); color: var(--muted); }
.ok-in { display: flex; gap: 16px; align-items: flex-start; } .okc { width: 48px; height: 48px; border-radius: 50%; background: #16A34A; color: #fff; display: grid; place-items: center; font-size: 24px; font-weight: 900; flex-shrink: 0; }
.ok-in h2 { margin: 0 0 6px; font-family: var(--font-display); } .ok-in p { margin: 0 0 8px; color: var(--ink-2); } .ok-in ul { margin: 0 0 12px; padding-left: 18px; font-size: var(--fs-s); display: grid; gap: 4px; } .ok-in a { color: #2563EB; font-weight: 700; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; }
@media (max-width: 1100px) { .grid { grid-template-columns: minmax(0, 1fr); } .sumc { position: static; } .g4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .g2, .g3, .g4, .tar { grid-template-columns: minmax(0, 1fr); } }
</style>
