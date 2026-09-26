<script setup lang="ts">
/**
 * Bayram va ob-havo: yaqin bayram ogohlantirishlari · 7 kunlik ob-havo va maslahatlar · yil bo'yicha bayramlar
 * (tizim bayramlari avtomatik, egasi foiz/sana/ogohlantirishni o'zgartiradi yoki o'z bayramini qo'shadi).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, UiToggle, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'
import WeatherStrip from '@/components/forecast/WeatherStrip.vue'

const a = useAuth(), router = useRouter()
const O = ref<any>(null)
const year = ref(new Date().getFullYear())
const list = ref<any[]>([])
const showOff = ref(false)
const canEdit = computed(() => a.can('forecast.edit'))
const refreshing = ref(false)

async function load() {
  O.value = await api.get('/forecast/overview')
  await loadList()
}
async function loadList() { list.value = await api.get('/forecast/holidays', { year: year.value }) }
onMounted(load)
watch(year, loadList)

const rows = computed(() => list.value.filter(h => showOff.value || h.is_active))
const KIND_TONE: Record<string, any> = { official: 'info', religious: 'ok', commercial: 'accent', season: 'warn', local: 'neutral' }
const WD = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba']
const fmtD = (x: string) => x.split('-').reverse().join('.')
const wd = (x: string) => WD[new Date(x + 'T00:00:00').getDay()]
const pct = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`
function leftLabel(h: any): [string, any] {
  if (h.is_now) return ['Bugun', 'ok']
  if (h.is_past) return ["O'tdi", 'neutral']
  if (h.days_left <= h.prep_days) return [`${h.days_left} kun`, 'warn']
  return [`${h.days_left} kun`, 'neutral']
}

async function refreshWeather() {
  refreshing.value = true
  try { O.value.weather = await api.post('/forecast/weather/refresh'); toast('Ob-havo yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { refreshing.value = false }
}

// ---- tahrirlash
const ed = ref<any>(null)
function openEd(h?: any) {
  ed.value = h ? { ...h, name: { ...h.name } }
    : { name: { uz: '', ru: '', en: '' }, date: `${year.value}-${String(new Date().getMonth() + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`, days: 1, kind: 'local', uplift_percent: 20, prep_days: 7, is_approx: false, is_active: true, note: '' }
}
async function save() {
  const body = { name: ed.value.name, date: ed.value.date, days: Number(ed.value.days), kind: ed.value.kind, uplift_percent: Number(ed.value.uplift_percent),
    prep_days: Number(ed.value.prep_days), is_approx: !!ed.value.is_approx, is_active: !!ed.value.is_active, note: ed.value.note ?? '' }
  try {
    ed.value.id ? await api.put(`/forecast/holidays/${ed.value.id}`, body) : await api.post('/forecast/holidays', body)
    ed.value = null; toast('Saqlandi'); await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function learn() {
  try { const r = await api.post(`/forecast/holidays/${ed.value.id}/learn`); ed.value.uplift_percent = r.uplift_percent; toast(`O'tgan yilgi natija: ${pct(r.uplift_percent)}`); await loadList() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function remove() {
  if (!confirm(ed.value.builtin ? "Bu bayram o'chirib qo'yiladi (ogohlantirish chiqmaydi). Davom etilsinmi?" : "Bayram o'chirilsinmi?")) return
  try { await api.del(`/forecast/holidays/${ed.value.id}`); ed.value = null; await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div v-if="O" class="fc">
    <div v-if="O.alerts.length" class="alerts">
      <HolidayAlert v-for="al in O.alerts" :key="al.id" :a="al" @plan="id => router.push(`/inventory?tab=plan&holiday=${id}`)" />
    </div>

    <div class="grid">
      <UiCard :title="`Ob-havo — 7 kun · ${O.weather.location.name}`" subtitle="Yomg'ir, jazirama va sovuq savdoga ta'sir qiladi — xarid rejasida hisobga olinadi">
        <template #actions>
          <UiButton v-if="canEdit" size="s" variant="ghost" :loading="refreshing" @click="refreshWeather()"><UiIcon name="repeat" :size="14" /> Yangilash</UiButton>
        </template>
        <p v-if="O.weather.demo" class="note">Namunaviy prognoz — internetga ulanganda haqiqiy ob-havo (Open-Meteo) o'zi yuklanadi.</p>
        <p v-else-if="O.weather.error" class="note">{{ O.weather.error }}</p>
        <WeatherStrip v-if="O.weather.days.length" :days="O.weather.days" :hints="6" />
        <UiEmpty v-else title="Ob-havo ma'lumoti yo'q" text="Internet ulanganda «Yangilash» tugmasini bosing. Shaharni Modullar → Sozlamalar'da tanlang." />
      </UiCard>

      <UiCard title="Qanday hisoblanadi">
        <ol class="how">
          <li><b>Odatiy savdo.</b> Oxirgi 4 hafta sotuvidan har taomning kunlik o'rtachasi olinadi.</li>
          <li><b>Kun ko'paytuvchisi.</b> Hafta kuni (juma-shanba yuqori) × bayram (+%) × ob-havo.</li>
          <li><b>Xomashyo.</b> Taom × tex-karta = ehtiyoj. Ehtiyoj + minimal qoldiq − ombordagi qoldiq = xarid.</li>
          <li><b>Ogohlantirish.</b> Bayramdan N kun oldin panelda chiqadi va ta'minot vazifasi ochiladi.</li>
        </ol>
        <p class="note">Bayram foizini o'tgan yilgi haqiqiy savdodan olish mumkin — bayramni oching va «O'tgan yildan olish»ni bosing.</p>
      </UiCard>
    </div>

    <UiCard :padded="false" title="Bayramlar va muhim kunlar" subtitle="Kutilgan — prognozda ishlatiladigan foiz · Haqiqiy — savdo tarixidan">
      <template #actions>
        <div class="yr">
          <button type="button" aria-label="Oldingi yil" @click="year--"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /></button>
          <b>{{ year }}</b>
          <button type="button" aria-label="Keyingi yil" @click="year++"><UiIcon name="chevron" :size="16" style="transform: rotate(-90deg)" /></button>
        </div>
        <button class="chip-btn" :class="{ on: showOff }" @click="showOff = !showOff">O'chirilganlar</button>
        <UiButton v-if="canEdit" variant="brand" size="s" @click="openEd()"><UiIcon name="plus" :size="14" /> Bayram</UiButton>
      </template>
      <div class="lst">
        <div class="l-h"><span>Sana</span><span>Bayram</span><span>Qoldi</span><span>Kutilgan</span><span>Haqiqiy</span><span>Ogohlantirish</span></div>
        <button v-for="h in rows" :key="h.id" type="button" class="l-r" :class="{ off: !h.is_active, past: h.is_past }" @click="canEdit && openEd(h)">
          <span class="dt"><b>{{ fmtD(h.date) }}</b><small>{{ wd(h.date) }}{{ h.days > 1 ? ` · ${h.days} kun` : '' }}</small></span>
          <span class="nm"><b>{{ h.name.uz }}</b><small><UiChip :tone="KIND_TONE[h.kind]">{{ h.kind_label }}</UiChip><UiChip v-if="h.is_approx" tone="neutral">taxminiy</UiChip><UiChip v-if="!h.is_active" tone="danger">o'chiq</UiChip></small></span>
          <span><UiChip :tone="leftLabel(h)[1]">{{ leftLabel(h)[0] }}</UiChip></span>
          <span class="n" :class="h.uplift_percent >= 0 ? 'up' : 'dn'">{{ pct(h.uplift_percent) }}</span>
          <span class="n mut" :title="h.is_past ? 'Shu bayramdagi haqiqiy o\'sish' : 'O\'tgan yilgi haqiqiy o\'sish'">{{ pct(h.is_past ? h.actual_percent : h.last_year_percent) }}<small v-if="!h.is_past && h.last_year_percent != null"> o'tgan yil</small></span>
          <span class="mut">{{ h.prep_days }} kun oldin</span>
        </button>
        <UiEmpty v-if="!rows.length" title="Bu yil uchun bayram yo'q" text="«Bayram» tugmasi bilan qo'shing." />
      </div>
    </UiCard>

    <UiDrawer :open="!!ed" :title="ed?.id ? ed.name.uz : 'Yangi bayram'" width="480px" @close="ed = null">
      <template v-if="ed">
        <UiInput v-model="ed.name.uz" label="Nomi" placeholder="Masalan: Filial yubileyi" />
        <UiInput v-model="ed.name.ru" label="Nomi (ru)" />
        <div class="g2">
          <UiInput v-model="ed.date" type="date" label="Sana" />
          <UiInput v-model="ed.days" type="number" label="Necha kun" />
          <UiInput v-model="ed.uplift_percent" type="number" label="Savdo o'zgarishi" suffix="%" />
          <UiInput v-model="ed.prep_days" type="number" label="Necha kun oldin ogohlantirish" />
        </div>
        <UiSelect v-model="ed.kind" label="Turi" :options="O.kinds.map((k: any) => ({ value: k.code, label: k.label }))" />
        <UiInput v-model="ed.note" label="Izoh (tayyorgarlik)" placeholder="Maxsus menyu, bron, qo'shimcha xodim…" />
        <div class="tg">
          <UiToggle v-model="ed.is_approx" label="Sana taxminiy" />
          <UiToggle v-model="ed.is_active" label="Ogohlantirish yoqilgan" />
        </div>
        <div v-if="ed.id && ed.builtin" class="lrn">
          <span>O'tgan yilgi haqiqiy o'sish: <b>{{ pct(ed.last_year_percent) }}</b></span>
          <UiButton size="s" variant="ghost" :disabled="ed.last_year_percent == null" @click="learn()">O'tgan yildan olish</UiButton>
        </div>
        <p class="note">Masalan, +40% — bayram kuni odatdagidan 40% ko'p sotuv kutiladi, xomashyo shunga qarab ko'proq xarid qilinadi.</p>
      </template>
      <template #footer>
        <UiButton v-if="ed?.id" variant="danger" @click="remove()">{{ ed.builtin ? "O'chirib qo'yish" : "O'chirish" }}</UiButton>
        <div style="flex: 1"></div>
        <UiButton variant="ghost" @click="ed = null">Bekor</UiButton><UiButton variant="brand" @click="save()">Saqlash</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.fc { display: flex; flex-direction: column; gap: 14px; }
.alerts { display: flex; flex-direction: column; gap: 10px; }
.grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.grid > :deep(.ui-card) { min-width: 0; }
.note { margin: 0 0 10px; font-size: var(--fs-xs); color: var(--muted); background: var(--surface-2); border-radius: 10px; padding: 8px 10px; }
.how { margin: 0 0 10px; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-s); color: var(--ink-2); }
.yr { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--line); border-radius: 10px; padding: 2px; }
.yr button { border: 0; background: transparent; width: 32px; height: 32px; border-radius: 8px; cursor: pointer; color: var(--ink); display: grid; place-items: center; }
.yr button:hover { background: var(--surface-2); } .yr b { font-variant-numeric: tabular-nums; padding: 0 4px; }
.chip-btn { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; }
.chip-btn.on { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); }
.lst { display: flex; flex-direction: column; }
.l-h, .l-r { display: grid; grid-template-columns: 120px minmax(0, 2fr) 90px 90px 110px 120px; gap: 10px; align-items: center; padding: 9px 14px; text-align: left; font-size: var(--fs-s); }
.l-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.l-r { border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; color: var(--ink); cursor: pointer; }
.l-r:hover { background: var(--accent-tint); } .l-r.off { opacity: .5; } .l-r.past .dt b { color: var(--muted); }
.dt, .nm { display: flex; flex-direction: column; gap: 3px; min-width: 0; } .dt small { color: var(--muted); font-size: var(--fs-xs); }
.nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { display: flex; gap: 4px; flex-wrap: wrap; }
.n { font-weight: 800; font-variant-numeric: tabular-nums; } .n small { font-weight: 500; font-size: 11px; } .up { color: var(--ok); } .dn { color: var(--danger); } .mut { color: var(--muted); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tg { display: flex; gap: 18px; flex-wrap: wrap; margin: 6px 0; }
.lrn { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border-radius: 10px; background: var(--surface-2); font-size: var(--fs-s); margin: 8px 0; flex-wrap: wrap; }
@media (max-width: 1100px) { .grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 720px) {
  .l-h { display: none; }
  .l-r { grid-template-columns: 1fr 1fr 1fr; gap: 6px 10px; }
  .l-r > .nm { grid-column: 1 / -1; order: -1; }
  .l-r > span:last-child { display: none; }
  .g2 { grid-template-columns: 1fr; }
}
</style>
