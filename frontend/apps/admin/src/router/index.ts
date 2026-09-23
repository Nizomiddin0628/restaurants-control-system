import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    {
      path: '/', component: () => import('@/layouts/AppShell.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue'), meta: { module: 'catalog' } },
        { path: 'tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { module: 'tasks' } },
        { path: 'pos', name: 'pos', component: () => import('@/views/PosView.vue'), meta: { module: 'pos' } },
        { path: 'kds', name: 'kds', component: () => import('@/views/KdsView.vue'), meta: { module: 'kds' } },
        { path: 'tables', name: 'tables', component: () => import('@/views/TablesView.vue'), meta: { module: 'tables' } },
        { path: 'reservations', name: 'reservations', component: () => import('@/views/ReservationsView.vue'), meta: { module: 'reservations' } },
        { path: 'inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue'), meta: { module: 'inventory' } },
        { path: 'hr', name: 'hr', component: () => import('@/views/HrView.vue'), meta: { module: 'hr' } },
        { path: 'reports', name: 'reports', component: () => import('@/views/ReportsView.vue'), meta: { module: 'finance' } },
        { path: 'site', name: 'site', component: () => import('@/views/SiteView.vue'), meta: { module: 'cms' } },
        { path: 'branches', name: 'branches', component: () => import('@/views/BranchesView.vue') },
        { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue') },
        { path: 'modules', name: 'modules', component: () => import('@/views/ModulesView.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
        { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue') },
        { path: ':pathMatch(.*)*', redirect: '/' },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const a = useAuth()
  if (to.meta.public) return true
  if (!a.me) { try { await a.load() } catch { return '/login' } }
  if (to.meta.module && !a.me!.tenant.enabled_modules.includes(to.meta.module as string)) return '/modules'
  return true
})
