<script setup lang="ts">
/**
 * Taomnoma quruvchi: kategoriyalar (sudrab tartiblash), taomlar jadvali (inline tahrir, ommaviy amallar),
 * yon panel forma (drawer), rasm yuklash, Excel import, Qoralama → E'lon qilish.
 */
import { computed, onMounted, ref } from 'vue'
import draggable from 'vuedraggable'
import { api, type Category, type Product } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiDropzone, UiInput, UiSelect, UiTable, UiToggle, UiIcon, UiEmpty, money, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

const a = useAuth(), ui = useUi()
const cats = ref<Category[]>([]), products = ref<Product[]>([]), activeCat = ref<number | null>(null)
const q = ref(''), loading = ref(false), selected = ref<number[]>([])
const versions = ref<{ version: number; published_at: string }[]>([])
const drawer = ref(false), editing = ref<Partial<Product> | null>(null), saving = ref(false)
const catDrawer = ref(false), catEdit = ref<Partial<Category> | null>(null)
const importOpen = ref(false), importResult = ref<any>(null)
const canEdit = computed(() => a.can('catalog.edit'))

async function loadCats() { cats.value = await api.get('/catalog/categories'); if (!activeCat.value && cats.value.length) activeCat.value = cats.value[0].id }
async function loadProducts() {
  loading.value = true
  try { const r = await api.get<{ items: Product[] }>('/catalog/products', { category_id: activeCat.value, q: q.value, page_size: 200 }); products.value = r.items } finally { loading.value = false }
}
async function loadVersions() { versions.value = await api.get('/catalog/versions') }
onMounted(async () => { await loadCats(); await loadProducts(); await loadVersions() })

const columns = computed(() => [
  { key: 'name', label: 'Taom', width: '2 1 0' },
  { key: 'price', label: 'Narx, so\'m', editable: canEdit.value ? 'number' : undefined, align: 'right', format: (v: number) => money(v) },
  { key: 'cost', label: 'Tannarx', editable: canEdit.value ? 'number' : undefined, align: 'right', format: (v: number) => money(v), hideOnPhone: true },
  { key: 'margin_percent', label: 'Marja', align: 'right', format: (v: number | null) => (v === null ? '—' : v + '%'), hideOnPhone: true },
  { key: 'is_active', label: 'Faol', editable: canEdit.value ? 'boolean' : undefined, width: '0 0 60px' },
  { key: 'in_stop_list', label: 'Stop', editable: canEdit.value ? 'boolean' : undefined, width: '0 0 60px' },
] as any)

async function onEdit({ id, key, value }: { id: number; key: string; value: any }) {
  try { const p = await api.patch<Product>(`/catalog/products/${id}`, { [key]: value }); products.value = products.value.map(x => (x.id === id ? p : x)); toast('Saqlandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
function openNew() { editing.value = { category_id: activeCat.value ?? cats.value[0]?.id, name: { uz: '', ru: '', en: '' }, description: { uz: '', ru: '', en: '' }, price: 0, cost: 0, tags: [], is_active: true, in_stop_list: false, sku: '', ikpu_code: '', custom_data: {} }; drawer.value = true }
function openRow(p: Product) { editing.value = JSON.parse(JSON.stringify(p)); drawer.value = true }
async function save() {
  if (!editing.value) return
  saving.value = true
  const body = { ...editing.value, modifier_group_ids: editing.value.modifier_group_ids ?? [], weight_g: editing.value.weight_g || null, kcal: editing.value.kcal || null }
  try {
    const p = editing.value.id ? await api.put<Product>(`/catalog/products/${editing.value.id}`, body) : await api.post<Product>('/catalog/products', body)
    editing.value = p; await loadProducts(); await loadCats(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { saving.value = false }
}
async function remove() { if (!editing.value?.id || !confirm('Taomni o\'chirasizmi?')) return; await api.del(`/catalog/products/${editing.value.id}`); drawer.value = false; await loadProducts(); await loadCats(); toast('O\'chirildi') }
async function uploadImage(files: File[]) { if (!editing.value?.id) { toast('Avval saqlang', 'info'); return } const p = await api.upload<Product>(`/catalog/products/${editing.value.id}/image`, files[0]); editing.value = p; await loadProducts(); toast('Rasm yuklandi') }
async function bulk(patch: any) { if (!selected.value.length) return; await api.post('/catalog/products/bulk', { ids: selected.value, ...patch }); selected.value = []; await loadProducts(); toast('Ommaviy o\'zgarish saqlandi') }
async function reorderCats() { await api.post('/catalog/categories/reorder', { ids: cats.value.map(c => c.id) }) }
async function reorderProducts() { await api.post('/catalog/products/reorder', { ids: products.value.map(p => p.id) }) }
function openCat(c?: Category) { catEdit.value = c ? { ...c } : { name: { uz: '', ru: '', en: '' }, is_active: true }; catDrawer.value = true }
async function saveCat() {
  if (!catEdit.value) return
  const body = { name: catEdit.value.name, is_active: catEdit.value.is_active ?? true, custom_data: {} }
  try { catEdit.value.id ? await api.put(`/catalog/categories/${catEdit.value.id}`, body) : await api.post('/catalog/categories', body); catDrawer.value = false; await loadCats(); toast('Saqlandi') } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function removeCat() { if (!catEdit.value?.id || !confirm('Kategoriyani o\'chirasizmi?')) return; try { await api.del(`/catalog/categories/${catEdit.value.id}`); catDrawer.value = false; activeCat.value = null; await loadCats(); await loadProducts() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } }
async function publish() { const v = await api.post('/catalog/publish'); await loadVersions(); toast(`Taomnoma e'lon qilindi — v${v.version}`) }
async function doImport(files: File[]) { importResult.value = await api.upload('/catalog/import', files[0]); await loadCats(); await loadProducts(); toast(`Import: ${importResult.value.created} yangi, ${importResult.value.updated} yangilandi`) }
function selectCat(id: number) { activeCat.value = id; loadProducts() }
</script>
<template>
  <div class="cat">
    <div class="bar">
      <UiInput v-model="q" placeholder="Taom qidirish" @keydown.enter="loadProducts()" style="min-width:200px" />
      <UiButton variant="secondary" @click="importOpen = true"><UiIcon name="upload" /> Excel import</UiButton>
      <UiButton v-if="canEdit" variant="secondary" @click="openNew()"><UiIcon name="plus" /> Taom</UiButton>
      <div class="sp"></div>
      <span class="ver">{{ versions[0] ? `E'lon: v${versions[0].version}` : "Hali e'lon qilinmagan" }}</span>
      <UiButton v-if="a.can('catalog.publish')" variant="brand" @click="publish()">E'lon qilish</UiButton>
    </div>

    <div class="layout">
      <UiCard title="Kategoriyalar" :padded="false" class="cats">
        <template #actions><UiButton v-if="canEdit" size="s" variant="ghost" @click="openCat()"><UiIcon name="plus" /></UiButton></template>
        <draggable v-model="cats" item-key="id" handle=".h" :disabled="!canEdit" @end="reorderCats" class="clist">
          <template #item="{ element: c }">
            <div class="ci" :class="{ on: c.id === activeCat }" @click="selectCat(c.id)">
              <span class="h" title="Sudrab tartiblang"><UiIcon name="drag" :size="14" /></span>
              <span class="n">{{ t(c.name, ui.lang) }}</span>
              <span class="cnt">{{ c.products_count }}</span>
              <button v-if="canEdit" class="e" type="button" @click.stop="openCat(c)" aria-label="Tahrirlash"><UiIcon name="edit" :size="14" /></button>
            </div>
          </template>
        </draggable>
      </UiCard>

      <div class="prod">
        <div v-if="selected.length" class="bulk">
          <b>{{ selected.length }} ta tanlandi</b>
          <UiButton size="s" variant="secondary" @click="bulk({ price_percent: 10 })">Narx +10%</UiButton>
          <UiButton size="s" variant="secondary" @click="bulk({ price_percent: -10 })">Narx −10%</UiButton>
          <UiButton size="s" variant="secondary" @click="bulk({ is_active: false })">Nofaol qilish</UiButton>
          <UiButton size="s" variant="secondary" @click="bulk({ is_active: true })">Faol qilish</UiButton>
        </div>
        <UiTable :rows="products" :columns="columns" :selectable="canEdit" :loading="loading" @edit="onEdit" @row="openRow" @select="selected = $event as number[]">
          <template #name="{ row }">
            <span class="pn"><span v-if="row.image" class="thumb" :style="{ backgroundImage: `url(${row.image})` }"></span><span v-else class="thumb ph"></span><span><b>{{ t(row.name, ui.lang) }}</b><small v-if="row.tags?.length"> · {{ row.tags.join(', ') }}</small></span></span>
          </template>
          <template #empty>
            <UiEmpty title="Bu kategoriyada taom yo'q" text="Taom qo'shing yoki Excel import qiling"><UiButton v-if="canEdit" @click="openNew()">+ Taom</UiButton></UiEmpty>
          </template>
        </UiTable>
        <p class="hint">Narx/tannarx katagini bosib joyida tahrirlang · qatorni bosib to'liq forma · ommaviy amallar uchun belgilang</p>
      </div>
    </div>

    <!-- Taom formasi -->
    <UiDrawer :open="drawer" :title="editing?.id ? 'Taomni tahrirlash' : 'Yangi taom'" @close="drawer = false">
      <template v-if="editing">
        <div class="img">
          <div v-if="editing.image" class="preview" :style="{ backgroundImage: `url(${editing.image})` }"></div>
          <UiDropzone accept="image/*" label="Taom rasmi" hint="JPG/PNG/WebP · telefondan ham" @files="uploadImage" />
        </div>
        <UiSelect v-model="editing.category_id" label="Kategoriya" :options="cats.map(c => ({ value: c.id, label: t(c.name, ui.lang) }))" />
        <div class="i18n"><UiInput v-model="editing.name!.uz" label="Nomi (uz)" /><UiInput v-model="editing.name!.ru" label="Nomi (ru)" /><UiInput v-model="editing.name!.en" label="Nomi (en)" /></div>
        <UiInput v-model="editing.description!.uz" label="Tavsif (uz)" />
        <div class="i18n">
          <UiInput v-model="editing.price" type="number" label="Sotuv narxi" suffix="so'm" />
          <UiInput v-model="editing.cost" type="number" label="Tannarx" suffix="so'm" :hint="editing.price && editing.cost ? `marja ${Math.round((editing.price - editing.cost) / editing.price * 100)}%` : ''" />
        </div>
        <div class="i18n"><UiInput v-model="editing.weight_g" type="number" label="Og'irlik" suffix="g" /><UiInput v-model="editing.kcal" type="number" label="Kaloriya" suffix="kkal" /><UiInput v-model="editing.sku" label="SKU" /></div>
        <UiInput :model-value="(editing.tags ?? []).join(', ')" label="Teglar" hint="hit, new, spicy, value — vergul bilan" @update:model-value="editing!.tags = String($event).split(',').map(s => s.trim()).filter(Boolean)" />
        <UiInput v-model="editing.ikpu_code" label="IKPU kodi" hint="Fiskal chek uchun — Soliq qo'mitasi katalogidagi kod" />
        <div class="i18n"><UiToggle v-model="editing.is_active" label="Faol" /><UiToggle v-model="editing.in_stop_list" label="Stop-list" /></div>
      </template>
      <template #footer>
        <UiButton v-if="editing?.id && canEdit" variant="danger" @click="remove()">O'chirish</UiButton>
        <UiButton variant="secondary" @click="drawer = false">Yopish</UiButton>
        <UiButton v-if="canEdit" :loading="saving" @click="save()">Saqlash</UiButton>
      </template>
    </UiDrawer>

    <!-- Kategoriya formasi -->
    <UiDrawer :open="catDrawer" :title="catEdit?.id ? 'Kategoriya' : 'Yangi kategoriya'" width="420px" @close="catDrawer = false">
      <template v-if="catEdit"><UiInput v-model="catEdit.name!.uz" label="Nomi (uz)" /><UiInput v-model="catEdit.name!.ru" label="Nomi (ru)" /><UiInput v-model="catEdit.name!.en" label="Nomi (en)" /><UiToggle v-model="catEdit.is_active" label="Faol" /></template>
      <template #footer>
        <UiButton v-if="catEdit?.id" variant="danger" @click="removeCat()">O'chirish</UiButton>
        <UiButton @click="saveCat()">Saqlash</UiButton>
      </template>
    </UiDrawer>

    <!-- Import -->
    <UiDrawer :open="importOpen" title="Excel import" width="460px" @close="importOpen = false">
      <p class="hint">Ustunlar (1-qator): <code>kategoriya · nom_uz · nom_ru · nom_en · narx · tannarx · tavsif_uz · og'irlik · kkal · sku</code>. Mavjud taomlar (kategoriya + nom_uz) yangilanadi.</p>
      <UiDropzone accept=".xlsx" label="Excel faylni tashlang" @files="doImport" />
      <div v-if="importResult" class="res"><UiChip tone="ok">{{ importResult.created }} yangi</UiChip> <UiChip tone="info">{{ importResult.updated }} yangilandi</UiChip><ul v-if="importResult.errors?.length"><li v-for="e in importResult.errors" :key="e">{{ e }}</li></ul></div>
    </UiDrawer>
  </div>
</template>
<style scoped>
.cat { display: flex; flex-direction: column; gap: 14px; }
.bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .sp { flex: 1; } .ver { font-size: var(--fs-s); color: var(--muted); }
.layout { display: grid; grid-template-columns: 1fr; gap: 14px; }
@media (min-width: 1025px) { .layout { grid-template-columns: 260px 1fr; align-items: start; } }
.cats { padding: 12px !important; }
.clist { display: flex; flex-direction: column; gap: 2px; }
.ci { display: flex; align-items: center; gap: 8px; min-height: var(--touch); padding: 0 8px; border-radius: var(--radius); cursor: pointer; font-weight: 600; }
.ci:hover { background: var(--surface-2); } .ci.on { background: var(--accent-tint); color: var(--accent); }
.h { color: var(--muted); cursor: grab; display: grid; } .n { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .cnt { font-size: var(--fs-xs); color: var(--muted); }
.e { border: 0; background: transparent; color: var(--muted); cursor: pointer; display: grid; padding: 4px; }
.prod { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.bulk { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px 12px; border-radius: var(--radius); background: var(--accent-tint); }
.pn { display: flex; align-items: center; gap: 8px; } .pn small { color: var(--muted); }
.thumb { width: 32px; height: 32px; border-radius: 8px; background-size: cover; background-position: center; flex-shrink: 0; } .thumb.ph { background: var(--surface-3); }
.hint { font-size: var(--fs-xs); color: var(--muted); margin: 0; }
.i18n { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.img { display: grid; gap: 10px; } .preview { height: 160px; border-radius: var(--radius-l); background-size: cover; background-position: center; }
.res ul { margin: 8px 0 0; padding-left: 18px; font-size: var(--fs-s); color: var(--danger); }
code { font-size: var(--fs-xs); }
@media (max-width: 600px) { .clist { flex-direction: row; overflow-x: auto; } .ci { flex: 0 0 auto; } .h, .e { display: none; } }
</style>
