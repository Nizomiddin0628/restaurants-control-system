<script setup lang="ts">
/**
 * Sayt quruvchi: sozlamalar (nom, telefon, Telegram, tillar), tema ranglari, bo'limlar (yoqish/o'chirish, sudrab tartiblash, matn),
 * logo va media kutubxona. Barcha o'zgarishlar saytga darhol tarqaladi (deploy yo'q).
 */
import { onMounted, ref } from 'vue'
import draggable from 'vuedraggable'
import { api, type MediaAsset, type SiteSection, type SiteSettings } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiDropzone, UiIcon, UiInput, UiSelect, UiToggle, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
const s = ref<SiteSettings | null>(null), sections = ref<SiteSection[]>([]), types = ref<{ code: string; label: string }[]>([]), media = ref<MediaAsset[]>([])
const saving = ref(false), secDrawer = ref(false), sec = ref<SiteSection | null>(null), tab = ref<'site' | 'theme' | 'sections' | 'media'>('site')
const langs = ['uz', 'ru', 'en']

onMounted(async () => { [s.value, sections.value, types.value, media.value] = await Promise.all([api.get('/cms/settings'), api.get('/cms/sections'), api.get('/cms/section-types'), api.get('/cms/media')]) })

async function save() {
  if (!s.value) return
  saving.value = true
  const { id, logo, favicon, updated_at, ...body } = s.value
  try { s.value = await api.put('/cms/settings', body); toast('Sayt saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
function toggleLang(l: string, on: boolean) { if (!s.value) return; s.value.languages = on ? [...new Set([...s.value.languages, l])] : s.value.languages.filter(x => x !== l) }
async function uploadLogo(files: File[]) { s.value = await api.upload('/cms/settings/logo', files[0]); toast('Logo yuklandi') }
async function reorder() { await api.post('/cms/sections/reorder', { ids: sections.value.map(x => x.id) }); toast('Tartib saqlandi') }
async function toggleSection(x: SiteSection, on: boolean) { x.is_enabled = on; await api.put(`/cms/sections/${x.id}`, { type: x.type, title: x.title, props: x.props, is_enabled: on }) }
function openSection(x?: SiteSection) { sec.value = x ? JSON.parse(JSON.stringify(x)) : { id: 0, type: 'text', title: { uz: '' }, props: {}, is_enabled: true, sort_order: sections.value.length }; secDrawer.value = true }
async function saveSection() {
  if (!sec.value) return
  const body = { type: sec.value.type, title: sec.value.title, props: sec.value.props, is_enabled: sec.value.is_enabled }
  try { sec.value.id ? await api.put(`/cms/sections/${sec.value.id}`, body) : await api.post('/cms/sections', body); sections.value = await api.get('/cms/sections'); secDrawer.value = false; toast('Bo\'lim saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function removeSection() { if (!sec.value?.id || !confirm('Bo\'limni o\'chirasizmi?')) return; await api.del(`/cms/sections/${sec.value.id}`); sections.value = await api.get('/cms/sections'); secDrawer.value = false }
async function uploadMedia(files: File[]) { for (const f of files) await api.upload('/cms/media', f, { folder: 'sayt' }); media.value = await api.get('/cms/media'); toast(`${files.length} ta fayl yuklandi`) }
async function removeMedia(m: MediaAsset) { if (!confirm('O\'chirasizmi?')) return; await api.del(`/cms/media/${m.id}`); media.value = media.value.filter(x => x.id !== m.id) }
const propKeys = (x: SiteSection) => ({ hero: ['title', 'subtitle', 'cta'], menu: ['title'], bonus: ['title', 'percent', 'gift_visit'], branches: ['title'], delivery: ['title'], contact: ['title'], text: ['body'], gallery: [] } as Record<string, string[]>)[x.type] ?? []
</script>
<template>
  <div v-if="s" class="site">
    <div class="tabs">
      <button v-for="tb in [['site', 'Sozlamalar'], ['theme', 'Tema'], ['sections', 'Bo\'limlar'], ['media', 'Media']]" :key="tb[0]" class="tab" :class="{ on: tab === tb[0] }" type="button" @click="tab = tb[0] as any">{{ tb[1] }}</button>
      <div class="sp"></div>
      <a class="lnk" href="/" target="_blank" rel="noopener"><UiIcon name="eye" /> Saytni ko'rish</a>
      <UiButton v-if="a.can('cms.edit') && tab !== 'sections' && tab !== 'media'" :loading="saving" @click="save()">Saqlash</UiButton>
    </div>

    <UiCard v-if="tab === 'site'" title="Sayt sozlamalari" subtitle="Nom, aloqa, tillar — sayt, Telegram bot va Mini App shu ma'lumotdan foydalanadi">
      <div class="grid2">
        <UiInput v-model="s.title" label="Restoran nomi" />
        <UiInput v-model="s.phone" label="Telefon" type="tel" placeholder="+998 71 200 00 00" />
        <UiInput v-model="s.telegram" label="Telegram" placeholder="@lazzat_bot" />
        <UiInput v-model="s.instagram" label="Instagram" placeholder="@lazzat.uz" />
        <UiInput v-model="s.address" label="Manzil" />
        <UiSelect v-model="s.default_language" label="Asosiy til" :options="langs.map(l => ({ value: l, label: l.toUpperCase() }))" />
        <UiInput v-model="s.tagline.uz" label="Shior (uz)" placeholder="Issiq, tez va har buyurtmadan bonus" />
        <UiInput v-model="s.tagline.ru" label="Shior (ru)" />
      </div>
      <div class="row"><span class="lbl">Tillar</span><UiToggle v-for="l in langs" :key="l" :model-value="s.languages.includes(l)" :label="l.toUpperCase()" @update:model-value="toggleLang(l, $event)" /></div>
      <div class="grid2">
        <UiInput v-model="s.delivery.free_from" type="number" label="Bepul yetkazish (dan)" suffix="so'm" />
        <UiInput v-model="s.delivery.fee" type="number" label="Yetkazish narxi" suffix="so'm" />
        <UiInput v-model="s.delivery.eta_min" type="number" label="Yetkazish vaqti (min)" suffix="daq" />
        <UiInput v-model="s.delivery.eta_max" type="number" label="Yetkazish vaqti (max)" suffix="daq" />
        <UiInput v-model="s.seo.title" label="SEO sarlavha" />
        <UiInput v-model="s.seo.description" label="SEO tavsif" />
      </div>
      <div class="logo">
        <div v-if="s.logo" class="lg" :style="{ backgroundImage: `url(${s.logo})` }"></div>
        <UiDropzone accept="image/*" label="Logo yuklash" hint="kvadrat PNG, 512×512" @files="uploadLogo" />
      </div>
      <UiToggle v-model="s.is_published" label="Sayt ochiq (mijozlar ko'radi)" />
    </UiCard>

    <UiCard v-if="tab === 'theme'" title="Tema" subtitle="Ranglar saytga, Mini App'ga va TV menyu-bordga birdek qo'llanadi">
      <div class="grid2">
        <label v-for="k in ['primary', 'accent', 'bg', 'ink']" :key="k" class="color"><span>{{ { primary: 'Asosiy (tugmalar)', accent: 'Ikkilamchi', bg: 'Fon', ink: 'Matn' }[k] }}</span><input type="color" v-model="s.theme[k]" /><code>{{ s.theme[k] }}</code></label>
        <UiInput v-model="s.theme.radius" type="number" label="Burchak yumaloqligi" suffix="px" />
        <UiSelect v-model="s.theme.font" label="Shrift" :options="['Manrope', 'Inter', 'Golos Text', 'Nunito'].map(f => ({ value: f, label: f }))" />
      </div>
      <UiToggle v-model="s.theme.dark_default" label="Sayt qorong'i rejimda ochilsin" />
      <div class="preview" :style="{ background: s.theme.bg, color: s.theme.ink, borderRadius: (s.theme.radius ?? 16) + 'px' }">
        <b style="font-size:22px">{{ s.title || 'Restoran' }}</b><p style="margin:6px 0 12px">{{ s.tagline?.uz || 'Shior shu yerda ko\'rinadi' }}</p>
        <span class="pbtn" :style="{ background: s.theme.primary }">Buyurtma berish</span> <span class="pbtn" :style="{ background: s.theme.accent }">Bonus</span>
      </div>
      <UiInput v-model="s.custom_css" label="Qo'shimcha CSS (ixtiyoriy)" hint="Faqat bilganlar uchun; boshqa hamma narsa panelda" />
    </UiCard>

    <UiCard v-if="tab === 'sections'" title="Sayt bo'limlari" subtitle="Sudrab tartiblang, yoqing/o'chiring, matnlarni tahrirlang — sayt darhol yangilanadi">
      <template #actions><UiButton v-if="a.can('cms.edit')" size="s" variant="secondary" @click="openSection()"><UiIcon name="plus" /> Bo'lim</UiButton></template>
      <draggable v-model="sections" item-key="id" handle=".h" :disabled="!a.can('cms.edit')" class="secs" @end="reorder">
        <template #item="{ element: x }">
          <div class="sec" :class="{ off: !x.is_enabled }">
            <span class="h"><UiIcon name="drag" /></span>
            <div class="si" @click="openSection(x)"><b>{{ types.find(y => y.code === x.type)?.label ?? x.type }}</b><span class="muted">{{ t(x.title, ui.lang) || x.props?.title || '—' }}</span></div>
            <UiChip v-if="!x.is_enabled" tone="neutral">yashirin</UiChip>
            <UiToggle :model-value="x.is_enabled" :disabled="!a.can('cms.edit')" @update:model-value="toggleSection(x, $event)" />
          </div>
        </template>
      </draggable>
    </UiCard>

    <UiCard v-if="tab === 'media'" title="Media kutubxona" subtitle="Rasm, video, PDF — taomlar, sayt, o'qitish uchun. Telefondan ham yuklanadi.">
      <UiDropzone accept="image/*,video/*,.pdf" multiple label="Fayllarni tashlang" hint="rasm 20 MB, video 500 MB gacha" @files="uploadMedia" />
      <div class="media">
        <div v-for="m in media" :key="m.id" class="m">
          <div v-if="m.kind === 'image'" class="mi" :style="{ backgroundImage: `url(${m.url})` }"></div><div v-else class="mi ph">{{ m.kind }}</div>
          <span class="mt">{{ m.title }}</span><small>{{ m.width ? `${m.width}×${m.height} · ` : '' }}{{ Math.round(m.size_bytes / 1024) }} KB</small>
          <div class="ma"><a :href="m.url" target="_blank" rel="noopener"><UiIcon name="eye" :size="14" /></a><button type="button" @click="removeMedia(m)" aria-label="O'chirish"><UiIcon name="trash" :size="14" /></button></div>
        </div>
      </div>
    </UiCard>

    <UiDrawer :open="secDrawer" :title="sec?.id ? 'Bo\'limni tahrirlash' : 'Yangi bo\'lim'" @close="secDrawer = false">
      <template v-if="sec">
        <UiSelect v-model="sec.type" label="Turi" :options="types.map(y => ({ value: y.code, label: y.label }))" :disabled="!!sec.id" />
        <UiInput v-model="sec.title.uz" label="Sarlavha (uz)" /><UiInput v-model="sec.title.ru" label="Sarlavha (ru)" />
        <UiInput v-for="k in propKeys(sec)" :key="k" v-model="sec.props[k]" :label="{ title: 'Ichki sarlavha', subtitle: 'Qisqa matn', cta: 'Tugma matni', percent: 'Bonus %', gift_visit: 'Sovg\'a — nechanchi buyurtma', body: 'Matn' }[k] ?? k" />
        <UiToggle v-model="sec.is_enabled" label="Saytda ko'rinadi" />
      </template>
      <template #footer>
        <UiButton v-if="sec?.id" variant="danger" @click="removeSection()">O'chirish</UiButton>
        <UiButton @click="saveSection()">Saqlash</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>
<style scoped>
.site { display: flex; flex-direction: column; gap: 14px; }
.tabs { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.tab { min-height: var(--touch); padding: 0 14px; border-radius: var(--radius); border: 0; background: transparent; font-weight: 700; color: var(--muted); cursor: pointer; }
.tab.on { background: var(--ink); color: var(--ink-inv); }
.sp { flex: 1; }
.lnk { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: var(--fs-s); text-decoration: none; padding: 0 10px; min-height: var(--touch); }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.row { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; } .lbl { font-size: var(--fs-s); font-weight: 700; color: var(--muted); }
.logo { display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: center; } .lg { width: 72px; height: 72px; border-radius: 16px; background-size: cover; background-position: center; border: 1px solid var(--line); }
.color { display: flex; flex-direction: column; gap: 6px; font-size: var(--fs-s); font-weight: 700; color: var(--muted); } .color input { width: 100%; height: var(--touch); border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); padding: 4px; }
.preview { padding: 20px; border: 1px solid var(--line); } .pbtn { display: inline-block; padding: 10px 16px; border-radius: 999px; color: #fff; font-weight: 700; }
.secs { display: flex; flex-direction: column; gap: 6px; }
.sec { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.sec.off { opacity: .6; } .h { cursor: grab; color: var(--muted); display: grid; }
.si { flex: 1; display: flex; flex-direction: column; cursor: pointer; min-width: 0; } .si span { font-size: var(--fs-s); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted { color: var(--muted); }
.media { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.m { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); } .mi { aspect-ratio: 1; border-radius: var(--radius); background-size: cover; background-position: center; border: 1px solid var(--line); } .mi.ph { display: grid; place-items: center; color: var(--muted); background: var(--surface-3); }
.mt { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } small { color: var(--muted); }
.ma { display: flex; gap: 6px; } .ma a, .ma button { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); cursor: pointer; }
</style>
