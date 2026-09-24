<script setup lang="ts">
/** Sertifikat — ekranda ko'rish va chop etish (PDF saqlash: brauzerda "Chop etish → PDF"). */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiIcon, toast } from '@restopos/ui'
import { fmtDate } from '@/components/training/upload'
import '@/components/training/tr.css'

const route = useRoute(), router = useRouter()
const c = ref<any>(null)
const print = () => window.print()
onMounted(async () => { try { c.value = await api.get(`/training/my/certificates/${route.params.id}`) } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); router.back() } })
</script>

<template>
  <div v-if="c" class="cw">
    <div class="acts no-print">
      <button class="tr-back" type="button" @click="router.back()"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /> Orqaga</button>
      <button class="tr-btn" type="button" @click="print">🖨 Chop etish / PDF</button>
    </div>
    <article class="cert">
      <div class="frame">
        <div class="rest">{{ c.restaurant }}</div>
        <h1>{{ c.title }}</h1>
        <p class="lead">Ushbu sertifikat</p>
        <div class="name">{{ c.user }}</div>
        <p class="lead">ga quyidagi kursni muvaffaqiyatli tugatgani uchun berildi:</p>
        <div class="course">«{{ c.course }}»</div>
        <div v-if="c.score !== null" class="score">Test natijasi: <b>{{ c.score }}%</b></div>
        <footer>
          <div><small>Sana</small><b>{{ fmtDate(c.completed_at) }}</b></div>
          <div class="seal">🏅</div>
          <div><small>Mas'ul</small><b>{{ c.responsible ?? '—' }}</b></div>
        </footer>
        <div class="no">№ {{ c.certificate_no }}</div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.cw { max-width: 900px; width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.acts { display: flex; justify-content: space-between; align-items: center; }
.cert { background: #FFFDF8; color: #1C1512; border-radius: 16px; padding: 18px; box-shadow: var(--shadow); aspect-ratio: 1.414; }
.frame { height: 100%; box-sizing: border-box; border: 3px double #A8894F; border-radius: 10px; padding: 28px 24px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 8px; }
.rest { font-weight: 800; letter-spacing: .2em; text-transform: uppercase; color: #A8894F; font-size: 13px; }
h1 { margin: 0; font-family: var(--font-display); font-size: clamp(28px, 6vw, 48px); letter-spacing: .04em; color: #1C1512; }
.lead { margin: 0; color: #6B6A63; }
.name { font-size: clamp(22px, 4.5vw, 36px); font-weight: 800; border-bottom: 2px solid #A8894F; padding: 4px 24px; }
.course { font-size: clamp(16px, 3vw, 22px); font-weight: 800; }
.score { color: #1E7F4F; }
footer { width: 100%; display: flex; justify-content: space-around; align-items: flex-end; margin-top: 14px; }
footer div { display: flex; flex-direction: column; } footer small { color: #6B6A63; } .seal { font-size: 42px; }
.no { font-size: 12px; color: #6B6A63; margin-top: 6px; }
@media (max-width: 600px) { .cert { aspect-ratio: auto; padding: 10px; } .frame { padding: 20px 12px; } }
@media print {
  .no-print { display: none !important; }
  .cert { box-shadow: none; border-radius: 0; }
}
</style>
<style>
@media print { .side, .top, .tabbar { display: none !important; } .content { padding: 0 !important; } }
</style>
