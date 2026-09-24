<script setup lang="ts">
/** Kurslar boshqaruvi: ro'yxat, yaratish/tahrirlash, har kurs bo'yicha kim tugatdi / kim boshlamadi. */
import { onMounted, ref } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiChip, UiDrawer, UiEmpty, UiIcon, toast } from '@restopos/ui'
import TrCourseEditor from './TrCourseEditor.vue'
import { fmtDate } from './upload'

const props = defineProps<{ meta: any }>()
const list = ref<any[]>([])
const archived = ref(false)
const editId = ref<number | null>(null)
const editOpen = ref(false)
const rep = ref<any>(null)

async function load() { list.value = await api.get('/training/courses', { archived: archived.value }) }
onMounted(load)
function openEdit(id: number | null) { editId.value = id; editOpen.value = true }
async function openRep(c: any) { rep.value = await api.get(`/training/report/courses/${c.id}`) }
async function archive(c: any) {
  if (!confirm(`«${c.title}» arxivga olinsinmi? Xodimlar natijalari saqlanadi.`)) return
  await api.del(`/training/courses/${c.id}`); toast('Arxivga olindi'); await load()
}
async function unarchive(c: any) {
  await api.put(`/training/courses/${c.id}`, { ...c, is_archived: false, responsible_id: c.responsible_id }); toast('Tiklandi'); await load()
}
const ST: Record<string, any> = { assigned: ['Boshlamagan', 'neutral'], in_progress: ["O'qiyapti", 'info'], completed: ['Tugatgan', 'ok'] }
void props
</script>

<template>
  <div class="tc">
    <div class="bar">
      <UiButton variant="brand" @click="openEdit(null)"><UiIcon name="plus" :size="15" /> Kurs</UiButton>
      <span class="sp"></span>
      <label class="arch"><input v-model="archived" type="checkbox" @change="load" /> Arxiv</label>
    </div>
    <div class="rows">
      <article v-for="c in list" :key="c.id" class="row">
        <button type="button" class="cov" :style="c.cover ? { backgroundImage: `url(${c.cover})` } : {}" @click="openEdit(c.id)"><UiIcon v-if="!c.cover" name="book" :size="22" /></button>
        <button type="button" class="info" @click="openEdit(c.id)">
          <b>{{ c.title }}</b>
          <small>{{ c.category || 'Bo\'limsiz' }} · {{ c.lessons_count }} dars · {{ c.quizzes_count }} test<template v-if="c.responsible"> · Mas'ul: {{ c.responsible.full_name }}</template></small>
          <span class="chips">
            <UiChip :tone="c.is_published ? 'ok' : 'neutral'">{{ c.is_published ? "E'lon qilingan" : 'Qoralama' }}</UiChip>
            <UiChip v-if="c.is_mandatory" tone="warn">Majburiy</UiChip>
            <UiChip v-if="c.everyone" tone="info">Hamma</UiChip>
            <UiChip v-for="r in c.roles" :key="r" tone="neutral">{{ meta.roles.find((x: any) => x.code === r)?.name ?? r }}</UiChip>
          </span>
        </button>
        <button type="button" class="stat" @click="openRep(c)">
          <span class="big">{{ c.completed }}<small>/{{ c.enrolled }}</small></span><span>tugatgan</span>
          <div class="tr-bar"><i :style="{ width: (c.enrolled ? (100 * c.completed) / c.enrolled : 0) + '%' }"></i></div>
          <span v-if="c.overdue" class="late">{{ c.overdue }} kechikkan</span>
        </button>
        <div class="acts">
          <UiButton v-if="!archived" size="s" variant="ghost" aria-label="Arxivga" @click="archive(c)"><UiIcon name="archive" :size="15" /></UiButton>
          <UiButton v-else size="s" variant="secondary" @click="unarchive(c)">Tiklash</UiButton>
        </div>
      </article>
      <UiEmpty v-if="!list.length" :title="archived ? 'Arxiv bo\'sh' : 'Hali kurs yo\'q'" text="«Kurs» tugmasi bilan birinchi kursni yarating: darslar, video, test." />
    </div>

    <UiDrawer :open="editOpen" :title="editId ? 'Kursni tahrirlash' : 'Yangi kurs'" width="760px" @close="editOpen = false; load()">
      <TrCourseEditor v-if="editOpen" :course-id="editId" :meta="meta" @saved="load" />
    </UiDrawer>

    <UiDrawer :open="!!rep" :title="rep ? rep.course.title : ''" width="720px" @close="rep = null">
      <template v-if="rep">
        <div class="kp">
          <div><b>{{ rep.course.enrolled }}</b><span>Biriktirilgan</span></div>
          <div><b>{{ rep.course.completed }}</b><span>Tugatgan</span></div>
          <div><b>{{ rep.rows.filter((r: any) => r.status === 'assigned').length }}</b><span>Boshlamagan</span></div>
          <div :class="{ warn: rep.course.overdue }"><b>{{ rep.course.overdue }}</b><span>Kechikkan</span></div>
        </div>
        <div v-for="r in rep.rows" :key="r.enrollment_id" class="rr">
          <span class="nm"><b>{{ r.user.full_name }}</b><small>{{ r.lessons_done }}/{{ r.lessons_total }} dars<template v-if="r.best_score !== null"> · test {{ r.best_score }}%</template><template v-if="r.due_at && r.status !== 'completed'"> · muddat {{ fmtDate(r.due_at) }}</template></small></span>
          <div class="tr-bar pb"><i :style="{ width: r.progress + '%' }"></i></div>
          <UiChip :tone="r.is_overdue ? 'danger' : ST[r.status][1]">{{ r.is_overdue ? 'Kechikdi' : ST[r.status][0] }}</UiChip>
        </div>
        <UiEmpty v-if="!rep.rows.length" title="Hali hech kimga biriktirilmagan" text="Kursni e'lon qiling va kimlar o'qishini tanlang." />
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.tc { display: flex; flex-direction: column; gap: 12px; }
.bar { display: flex; align-items: center; gap: 10px; } .sp { flex: 1; }
.arch { display: inline-flex; gap: 6px; align-items: center; font-weight: 700; color: var(--muted); font-size: 14px; }
.rows { display: flex; flex-direction: column; gap: 10px; }
.row { display: grid; grid-template-columns: 120px 1fr 160px auto; gap: 14px; align-items: center; padding: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; }
.cov { aspect-ratio: 16/9; border-radius: 10px; border: 0; cursor: pointer; background: linear-gradient(135deg, #3a2f22, #8a6d3b) center / cover; color: #fff; display: grid; place-items: center; }
.info { text-align: left; border: 0; background: none; cursor: pointer; font: inherit; color: inherit; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.info b { font-size: 16px; } .info small { color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.stat { border: 0; background: var(--surface-2); border-radius: 12px; padding: 10px; cursor: pointer; font: inherit; color: inherit; display: flex; flex-direction: column; gap: 4px; text-align: left; }
.stat .big { font-size: 20px; font-weight: 800; } .stat .big small { font-size: 13px; color: var(--muted); } .stat > span { font-size: 12px; color: var(--muted); }
.stat .late { color: var(--danger); font-weight: 700; }
.kp { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.kp div { background: var(--surface-2); border-radius: 12px; padding: 10px; display: flex; flex-direction: column; } .kp b { font-size: 20px; } .kp span { font-size: 12px; color: var(--muted); } .kp .warn b { color: var(--danger); }
.rr { display: grid; grid-template-columns: 1fr 120px auto; gap: 12px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--line-2); }
.nm { display: flex; flex-direction: column; } .nm small { color: var(--muted); font-size: 12px; }
@media (max-width: 800px) { .row { grid-template-columns: 90px 1fr; } .stat { grid-column: 1 / -1; } .acts { position: absolute; } .row { position: relative; } .acts { top: 8px; right: 8px; } }
@media (max-width: 600px) { .kp { grid-template-columns: repeat(2, 1fr); } .rr { grid-template-columns: 1fr auto; } .pb { grid-column: 1 / -1; grid-row: 2; } }
</style>
