import { createRouter, createWebHistory } from 'vue-router'
import { useHq } from './store'

export const hqRouter = createRouter({
  history: createWebHistory('/hq/'),
  routes: [
    { path: '/login', component: () => import('./views/HqLogin.vue'), meta: { public: true } },
    {
      path: '/', component: () => import('./HqShell.vue'),
      children: [
        { path: '', component: () => import('./views/HqDashboard.vue'), meta: { title: 'Bosh sahifa' } },
        { path: 'tenants', component: () => import('./views/HqTenants.vue'), meta: { title: 'Mijozlar' } },
        { path: 'tenants/new', component: () => import('./views/HqNewTenant.vue'), meta: { title: 'Yangi restoran (shartnoma)' } },
        { path: 'tenants/:id', component: () => import('./views/HqTenant.vue'), meta: { title: 'Mijoz' } },
        { path: 'billing', component: () => import('./views/HqBilling.vue'), meta: { title: 'Billing' } },
        { path: 'tickets', component: () => import('./views/HqTickets.vue'), meta: { title: 'Vazifalar doskasi' } },
        { path: 'health', component: () => import('./views/HqHealth.vue'), meta: { title: 'Tizim holati' } },
        { path: 'site', component: () => import('./views/HqSite.vue'), meta: { title: 'Sayt va narxlar' } },
        { path: 'system', component: () => import('./views/HqSystem.vue'), meta: { title: 'Funksiyalar va jamoa' } },
        { path: ':pathMatch(.*)*', redirect: '/' },
      ],
    },
  ],
})

hqRouter.beforeEach(async (to) => {
  if (to.meta.public) return true
  const s = useHq()
  if (!s.me) { try { await s.load() } catch { return '/login' } }
  return true
})
