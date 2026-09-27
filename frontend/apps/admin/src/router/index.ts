import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    {
      path: '/', component: () => import('@/layouts/AppShell.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { perm: 'core.dashboard.view' } },
        { path: 'my', name: 'my', component: () => import('@/views/MyView.vue'), meta: { title: 'Mening sahifam' } },
        { path: 's/:code', name: 'section', component: () => import('@/views/SectionView.vue'), meta: { title: "Bo'lim" } },
        { path: 'catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue'), meta: { module: 'catalog' } },
        { path: 'tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { module: 'tasks' } },
        { path: 'pos', name: 'pos', component: () => import('@/views/PosView.vue'), meta: { module: 'pos' } },
        { path: 'kds', name: 'kds', component: () => import('@/views/KdsView.vue'), meta: { module: 'kds' } },
        { path: 'tables', name: 'tables', component: () => import('@/views/TablesView.vue'), meta: { module: 'tables' } },
        { path: 'reservations', name: 'reservations', component: () => import('@/views/ReservationsView.vue'), meta: { module: 'reservations' } },
        { path: 'inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue'), meta: { module: 'inventory' } },
        { path: 'projects', name: 'projects', component: () => import('@/views/ProjectsView.vue'), meta: { module: 'projects', title: 'Loyihalar' } },
        { path: 'projects/:id', name: 'project', component: () => import('@/views/ProjectView.vue'), meta: { module: 'projects', title: 'Loyiha' } },
        { path: 'procurement', name: 'procurement', component: () => import('@/views/ProcurementView.vue'), meta: { module: 'procurement', title: 'Zakup (xarid)' } },
        { path: 'market', name: 'market', component: () => import('@/views/MarketView.vue'), meta: { module: 'procurement', title: 'Bozorlik va xarajat' } },
        { path: 'forecast', name: 'forecast', component: () => import('@/views/ForecastView.vue'), meta: { module: 'forecast', title: 'Bayram va ob-havo' } },
        { path: 'org', name: 'org', component: () => import('@/views/OrgView.vue'), meta: { module: 'ops', title: 'Tashkiliy tuzilma' } },
        { path: 'positions', name: 'positions', component: () => import('@/views/PositionsView.vue'), meta: { module: 'ops', title: 'Lavozimlar' } },
        { path: 'hr', name: 'hr', component: () => import('@/views/HrView.vue'), meta: { module: 'hr' } },
        { path: 'hr/employee/:id', name: 'hr-employee', component: () => import('@/views/EmployeeProfileView.vue'), meta: { module: 'hr', title: 'Xodim profili' } },
        { path: 'recruiting', name: 'recruiting', component: () => import('@/views/RecruitView.vue'), meta: { module: 'hr', title: 'Ishga olish' } },
        { path: 'kpi', name: 'kpi', component: () => import('@/views/KpiView.vue'), meta: { module: 'hr', title: 'Baholash va KPI' } },
        { path: 'reports', name: 'reports', component: () => import('@/views/ReportsView.vue'), meta: { module: 'finance' } },
        { path: 'ai', name: 'ai', component: () => import('@/views/AiView.vue'), meta: { module: 'ai', title: 'AI Kotib' } },
        { path: 'training', name: 'training', component: () => import('@/views/TrainingView.vue'), meta: { module: 'training' } },
        { path: 'training/course/:id', name: 'training-course', component: () => import('@/views/TrainingCourseView.vue'), meta: { module: 'training' } },
        { path: 'training/lesson/:id', name: 'training-lesson', component: () => import('@/views/TrainingLessonView.vue'), meta: { module: 'training' } },
        { path: 'training/quiz/:id', name: 'training-quiz', component: () => import('@/views/TrainingQuizView.vue'), meta: { module: 'training' } },
        { path: 'training/certificate/:id', name: 'training-cert', component: () => import('@/views/TrainingCertView.vue'), meta: { module: 'training' } },
        { path: 'crm', name: 'crm', component: () => import('@/views/CrmView.vue'), meta: { module: 'crm', title: 'Mijozlar va bonus' } },
        { path: 'telegram', name: 'telegram', component: () => import('@/views/TelegramView.vue'), meta: { module: 'telegram' } },
        { path: 'site', name: 'site', component: () => import('@/views/SiteView.vue'), meta: { module: 'cms' } },
        { path: 'branches', name: 'branches', component: () => import('@/views/BranchesView.vue'), meta: { perm: 'core.branches.manage' } },
        { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { perm: 'core.users.manage', title: 'Xodimlar va kirish' } },
        { path: 'modules', name: 'modules', component: () => import('@/views/ModulesView.vue'), meta: { perm: 'core.modules.manage' } },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
        { path: 'support', name: 'support', component: () => import('@/views/SupportView.vue'), meta: { title: 'Yordam va platforma', perm: 'core.settings.view' } },
        { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue'), meta: { title: "O'zgarishlar tarixi", perm: 'core.settings.view' } },
        { path: ':pathMatch(.*)*', redirect: '/' },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const a = useAuth()
  if (to.meta.public) return true
  if (!a.me) { try { await a.load() } catch { return '/login' } }
  const me = a.me!
  const home = me.home || '/'
  // umumiy raqamlarni ko'rmaydigan xodim — o'z sahifasiga
  if (to.meta.perm && !a.can(to.meta.perm as string)) return home
  if (to.meta.module) {
    const mod = to.meta.module as string
    if (!me.tenant.enabled_modules.includes(mod)) return a.can('core.modules.manage') ? '/modules' : home
    // modul sahifasi — faqat menyusida shu modul bo'lganlarga (ruxsat bo'yicha)
    if (!me.nav.some(n => n.module === mod)) return home
  }
  return true
})
