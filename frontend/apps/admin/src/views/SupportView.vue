<script setup lang="ts">
/**
 * Yordam va platforma: murojaat yozish va javob olish; yordamga vaqtincha kirishga ruxsat (1 soat / 1 kun / 3 kun);
 * kim qachon kirgani; ma'lumot ulashish roziligi. Hammasi egasi nazoratida.
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiToggle, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'

const a = useAuth()
const S = ref<any>(null)
const tickets = ref<any[]>([])
const T = ref<any>(null)
const nt = ref<any>(null)
const reply = ref('')
const busy = ref(false)
const canManage = computed(() => a.can('core.settings.edit'))
const TONE: Record<string, any> = { open: 'danger', progress: 'info', waiting: 'accent', closed: 'ok', low: 'neutral', normal: 'warn', high: 'danger', critical: 'danger' }
async function load() { ;[S.value, tickets.value] = await Promise.all([api.get('/platform/status'), api.get('/platform/tickets')]) }
onMounted(load)
const p2 = (n: number) => String(n).padStart(2, '0')
const dt = (s: string) => { const x = new Date(s); return `${p2(x.getDate())}.${p2(x.getMonth() + 1)}.${x.getFullYear()} ${p2(x.getHours())}:${p2(x.getMinutes())}` }

async function grant(hours: number) {
  busy.value = true
  try { await api.post('/platform/access', { hours }); toast('Ruxsat berildi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function revoke() {
  busy.value = true
  try { await api.del('/platform/access'); toast('Ruxsat bekor qilindi'); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { busy.value = false }
}
async function saveConsent(k: 'share_finance' | 'showcase', v: boolean) {
  try { await api.put('/platform/consent', { ...S.value.consent, [k]: v }); S.value.consent[k] = v; toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function newTicket() { nt.value = { subject: '', body: '', priority: 'normal', branch_name: '' } }
async function createTicket() {
  try { const r = await api.post('/platform/tickets', nt.value); nt.value = null; await load(); T.value = r; toast(`Murojaat #${r.number} yuborildi`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function openT(id: number) { T.value = await api.get(`/platform/tickets/${id}`); reply.value = '' }
async function send(close = false) {
  try { T.value = await api.post(`/platform/tickets/${T.value.id}/messages`, { body: reply.value, close }); reply.value = ''; await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div v-if="S" class="sp">
    <div v-if="S.access_request && !S.access" class="req">
      <span>🛟</span>
      <div><b>{{ S.platform }} yordami panelingizga kirish uchun ruxsat so'rayapti</b><small>{{ S.access_request.by }} · sabab: {{ S.access_request.reason }}</small></div>
      <template v-if="canManage"><UiButton variant="brand" size="s" @click="grant(24)">1 kunga ruxsat berish</UiButton><UiButton variant="ghost" size="s" @click="revoke()">Rad etish</UiButton></template>
    </div>

    <div class="grid">
      <UiCard title="Murojaatlar" subtitle="Muammo bo'lsa yozing — yordam jamoasi shu yerda javob beradi">
        <template #actions><UiButton variant="brand" size="s" @click="newTicket()"><UiIcon name="plus" :size="14" /> Murojaat</UiButton></template>
        <button v-for="k in tickets" :key="k.id" type="button" class="tk" @click="openT(k.id)">
          <span><b>#{{ k.number }} {{ k.subject }}</b><small>{{ dt(k.updated_at) }}</small></span>
          <UiChip :tone="TONE[k.status]">{{ k.status_label }}</UiChip>
        </button>
        <UiEmpty v-if="!tickets.length" title="Hali murojaat yo'q" text="«Murojaat» tugmasini bosing va muammoni oddiy so'zlar bilan yozing." />
      </UiCard>

      <div class="side">
        <UiCard title="Yordamga kirish ruxsati" subtitle="Siz ruxsat bermaguningizcha hech kim panelingizga kira olmaydi">
          <div v-if="S.access" class="acc on">✅ Ruxsat bor — <b>{{ dt(S.access.until) }}</b> gacha</div>
          <div v-else class="acc">🔒 Hozir ruxsat yo'q</div>
          <div v-if="canManage" class="btns">
            <UiButton size="s" variant="ghost" :disabled="busy" @click="grant(1)">1 soat</UiButton>
            <UiButton size="s" variant="ghost" :disabled="busy" @click="grant(24)">1 kun</UiButton>
            <UiButton size="s" variant="ghost" :disabled="busy" @click="grant(72)">3 kun</UiButton>
            <UiButton v-if="S.access" size="s" variant="danger" :disabled="busy" @click="revoke()">Bekor qilish</UiButton>
          </div>
          <p class="mut">Har bir kirish quyida va «O'zgarishlar tarixi»da yoziladi.</p>
          <ul class="ss"><li v-for="(x, i) in S.sessions" :key="i"><b>{{ x.staff }}</b><span>{{ x.reason }}</span><small>{{ dt(x.at) }}</small></li></ul>
        </UiCard>
        <UiCard title="Ma'lumot ulashish" subtitle="Platforma xizmatni yaxshilashi uchun">
          <div class="cn"><UiToggle :model-value="S.consent.share_finance" :disabled="!canManage" label="Savdo statistikasini ulashish (umumiy raqamlar)" @update:model-value="(v: boolean) => saveConsent('share_finance', v)" />
            <small>Kunlik savdo, buyurtmalar soni va eng ko'p sotilgan taomlar. Mijozlaringiz ma'lumoti, xodimlar ismi va maoshi ulashilmaydi.</small></div>
          <div class="cn"><UiToggle :model-value="S.consent.showcase" :disabled="!canManage" label="«Bizning mijozlarimiz» ro'yxatida ko'rsatishga roziman" @update:model-value="(v: boolean) => saveConsent('showcase', v)" />
            <small>Restoraningiz nomi va logotipi platforma saytida chiqishi mumkin.</small></div>
        </UiCard>
      </div>
    </div>

    <UiDrawer :open="!!nt" title="Yangi murojaat" width="520px" @close="nt = null">
      <template v-if="nt">
        <UiInput v-model="nt.subject" label="Qisqacha: nima ishlamayapti?" placeholder="Masalan: kassada chek chiqmayapti" />
        <label class="fl"><span>Batafsil (ixtiyoriy)</span><textarea v-model="nt.body" rows="5" placeholder="Qachondan beri, qaysi filialda, qaysi ekranda…"></textarea></label>
        <div class="pr"><span>Qanchalik shoshilinch?</span>
          <button v-for="p in [['low', 'Kutsa bo\'ladi'], ['normal', 'Oddiy'], ['high', 'Tezroq'], ['critical', 'Ish to\'xtadi!']]" :key="p[0]" type="button" :class="[p[0], { on: nt.priority === p[0] }]" @click="nt.priority = p[0]">{{ p[1] }}</button></div>
        <UiInput v-model="nt.branch_name" label="Filial (ixtiyoriy)" />
      </template>
      <template #footer><UiButton variant="ghost" @click="nt = null">Bekor</UiButton><UiButton variant="brand" @click="createTicket()">Yuborish</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!T" :title="T ? `#${T.number} ${T.subject}` : ''" width="560px" @close="T = null">
      <template v-if="T">
        <p class="mut"><UiChip :tone="TONE[T.status]">{{ T.status_label }}</UiChip> · {{ T.priority_label }} · {{ dt(T.created_at) }}</p>
        <ul class="chat"><li v-for="(m, i) in T.messages" :key="i" :class="{ them: m.from_staff }"><b>{{ m.from_staff ? `🛟 ${m.author}` : m.author }}</b><p>{{ m.body }}</p><small>{{ dt(m.at) }}</small></li></ul>
        <textarea v-if="T.status !== 'closed'" v-model="reply" rows="3" placeholder="Javob yozing…"></textarea>
      </template>
      <template #footer>
        <UiButton v-if="T && T.status !== 'closed'" variant="ghost" @click="send(true)">Hal bo'ldi — yopish</UiButton>
        <div style="flex: 1"></div>
        <UiButton variant="brand" :disabled="!reply.trim()" @click="send(false)">Yuborish</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.sp { display: flex; flex-direction: column; gap: 14px; }
.req { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 14px 16px; border-radius: 14px; background: var(--warn-tint); border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--line)); }
.req > span { font-size: 28px; } .req div { flex: 1; min-width: 200px; display: flex; flex-direction: column; } .req small { color: var(--ink-2); }
.grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 14px; align-items: start; } .grid > :deep(.ui-card) { min-width: 0; }
.side { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.tk { display: flex; align-items: center; gap: 10px; width: 100%; padding: 12px 4px; border: 0; border-bottom: 1px solid var(--line-2); background: transparent; font: inherit; text-align: left; cursor: pointer; color: var(--ink); min-height: 56px; }
.tk > span:first-child { flex: 1; display: flex; flex-direction: column; min-width: 0; } .tk b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .tk small { color: var(--muted); font-size: var(--fs-xs); }
.acc { padding: 10px 12px; border-radius: 10px; background: var(--surface-2); font-size: var(--fs-s); } .acc.on { background: var(--ok-tint); }
.btns { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.mut { color: var(--muted); font-size: var(--fs-xs); margin: 10px 0 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ss { list-style: none; margin: 8px 0 0; padding: 0; } .ss li { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; padding: 8px 0; border-top: 1px solid var(--line-2); font-size: var(--fs-s); }
.ss span { grid-column: 1 / -1; color: var(--ink-2); } .ss small { color: var(--muted); grid-row: 1; grid-column: 2; }
.cn { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; } .cn small { color: var(--muted); font-size: var(--fs-xs); padding-left: 52px; }
.fl { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; } .fl span, .pr span { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; font: inherit; background: var(--surface); color: var(--ink); }
.pr { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 12px 0; } .pr span { grid-column: 1 / -1; }
.pr button { min-height: 48px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font: inherit; font-weight: 700; font-size: var(--fs-xs); cursor: pointer; color: var(--ink); }
.pr button.on { border-width: 2px; } .pr .low.on { border-color: var(--muted); } .pr .normal.on { border-color: var(--warn); background: var(--warn-tint); } .pr .high.on, .pr .critical.on { border-color: var(--danger); background: var(--danger-tint); }
.chat { list-style: none; margin: 12px 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.chat li { max-width: 85%; align-self: flex-end; padding: 10px 12px; border-radius: 12px; background: var(--accent-tint); } .chat li.them { align-self: flex-start; background: var(--surface-2); }
.chat b { font-size: var(--fs-xs); } .chat p { margin: 2px 0; white-space: pre-wrap; font-size: var(--fs-s); } .chat small { color: var(--muted); font-size: 11px; }
@media (max-width: 900px) { .grid { grid-template-columns: minmax(0, 1fr); } .pr { grid-template-columns: 1fr 1fr; } }
</style>
