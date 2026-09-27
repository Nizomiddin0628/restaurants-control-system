<script setup lang="ts">
/**
 * O'qitish va komplayens — bosh sahifa.
 * Har xodim: «Mening o'qishim». Egasi/menejer qo'shimcha: kurslar, topshiriqlar, standartlar, hisobot.
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiIcon } from '@restopos/ui'
import TrMy from '@/components/training/TrMy.vue'
import TrCourses from '@/components/training/TrCourses.vue'
import TrAssignments from '@/components/training/TrAssignments.vue'
import TrStandards from '@/components/training/TrStandards.vue'
import TrReport from '@/components/training/TrReport.vue'
import '@/components/training/tr.css'

type Tab = 'my' | 'courses' | 'assignments' | 'standards' | 'report'
const route = useRoute(), router = useRouter()
const meta = ref<any>(null)
const courses = ref<any[]>([])
const tab = ref<Tab>((route.query.tab as Tab) || 'my')
watch(tab, (v) => router.replace({ query: { tab: v } }))
onMounted(async () => {
  meta.value = await api.get('/training/meta')
  if (meta.value.can.manage) courses.value = await api.get('/training/courses')
  if (tab.value !== 'my' && !meta.value.can.review) tab.value = 'my'
  // rahbar uchun ochilganda — jamoa hisobotidan boshlanadi (o'zining kursi bo'lmasa «Mening o'qishim» bo'sh ko'rinadi)
  else if (!route.query.tab && meta.value.can.review) tab.value = 'report'
})
</script>

<template>
  <div v-if="meta" class="tv">
    <nav v-if="meta.can.review" class="tr-seg top">
      <button :class="{ on: tab === 'my' }" @click="tab = 'my'"><UiIcon name="play" :size="15" /> Mening o'qishim</button>
      <button v-if="meta.can.manage" :class="{ on: tab === 'courses' }" @click="tab = 'courses'"><UiIcon name="book" :size="15" /> Kurslar</button>
      <button :class="{ on: tab === 'assignments' }" @click="tab = 'assignments'"><UiIcon name="camera" :size="15" /> Topshiriqlar</button>
      <button v-if="meta.can.manage" :class="{ on: tab === 'standards' }" @click="tab = 'standards'"><UiIcon name="shield" :size="15" /> Standartlar</button>
      <button :class="{ on: tab === 'report' }" @click="tab = 'report'"><UiIcon name="chart" :size="15" /> Hisobot</button>
    </nav>
    <TrMy v-if="tab === 'my'" />
    <TrCourses v-else-if="tab === 'courses'" :meta="meta" />
    <TrAssignments v-else-if="tab === 'assignments'" :meta="meta" :courses="courses" />
    <TrStandards v-else-if="tab === 'standards'" :meta="meta" />
    <TrReport v-else-if="tab === 'report'" />
  </div>
</template>

<style scoped>
.tv { display: flex; flex-direction: column; gap: 16px; }
.top { align-self: flex-start; max-width: 100%; }
@media (max-width: 600px) { .top { align-self: stretch; } .top button { flex: none; } }
</style>
