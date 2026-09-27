/**
 * Menyu tuzilmasi: asosiy bo'limlar → ichki modullar.
 * Modullar menyusi backenddan (me.nav, rol va yoqilgan modullar bo'yicha) keladi; bu yerda faqat qaysi bo'limga tegishliligi.
 * Yangi modul qo'shilsa — `routes` ga yo'lini yozing (yozilmasa «Boshqa» bo'limiga tushadi).
 */
import { computed, ref } from 'vue'
import { api } from '@restopos/api'
import { useRoute } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'

export type NavItem = { route: string; label: { uz?: string; ru?: string; en?: string }; icon: string; order: number; perm?: string }
export type Section = { code: string; title: string; icon: string; emoji: string; color: string; desc: string; routes: string[] }
export type SectionView = Section & { items: (NavItem & { desc: string })[] }

export const SECTIONS: Section[] = [
  { code: 'sales', title: 'Savdo va xizmat', icon: 'receipt', emoji: '💳', color: '#EA580C', desc: 'Kassa, oshxona ekrani, zal va bron',
    routes: ['/pos', '/kds', '/tables', '/reservations', '/delivery'] },
  { code: 'menu', title: 'Menyu', icon: 'book', emoji: '🍽️', color: '#DB2777', desc: 'Taomlar, narxlar, stop-list, eng ko\'p sotilganlar',
    routes: ['/catalog'] },
  { code: 'clients', title: 'Mijozlar va marketing', icon: 'star', emoji: '❤️', color: '#E11D48', desc: 'Mijozlar va bonus, Telegram bot, sayt',
    routes: ['/crm', '/telegram', '/site'] },
  { code: 'stock', title: 'Ombor va xarid', icon: 'box', emoji: '📦', color: '#2563EB', desc: 'Qoldiq va tannarx, zakup, bozorlik, bayram prognozi',
    routes: ['/inventory', '/procurement', '/market', '/forecast'] },
  { code: 'team', title: 'Xodimlar', icon: 'users', emoji: '👥', color: '#059669', desc: 'Xodimlar va kirish (login/parol), smena, davomat, ishga olish, KPI, tuzilma',
    routes: ['/hr', '/users', '/recruiting', '/kpi', '/org', '/positions'] },
  { code: 'training', title: "O'qitish", icon: 'book', emoji: '🎓', color: '#CA8A04', desc: 'Kurslar, video darslar, testlar, standartlar',
    routes: ['/training'] },
  { code: 'work', title: 'Vazifa va loyihalar', icon: 'check', emoji: '✅', color: '#7C3AED', desc: 'Kundalik vazifalar, muammolar va katta loyihalar',
    routes: ['/tasks', '/projects'] },
  { code: 'finance', title: 'Moliya va hisobot', icon: 'chart', emoji: '📊', color: '#0891B2', desc: 'Savdo, foyda-zarar, food cost, menyu tahlili',
    routes: ['/reports'] },
  { code: 'settings', title: 'Sozlamalar', icon: 'sliders', emoji: '⚙️', color: '#64748B', desc: 'Filiallar, modullar, restoran sozlamalari, yordam',
    routes: ['/branches', '/modules', '/settings', '/support', '/audit'] },
]

/** Har modul kartasi uchun bir qatorli tushuntirish (bo'lim sahifasida) */
export const DESC: Record<string, string> = {
  '/pos': "Buyurtma olish, to'lov, smena ochish-yopish",
  '/kds': 'Oshpazlar uchun buyurtmalar ekrani',
  '/tables': 'Zal xaritasi, stollar holati, ofitsiantlar',
  '/reservations': 'Stol bron qilish va navbat',
  '/delivery': 'Yetkazib berish buyurtmalari va kuryerlar',
  '/catalog': 'Taomlar, narxlar, qo\'shimchalar, stop-list',
  '/crm': 'Mijozlar bazasi, keshbek, promo-kodlar',
  '/telegram': 'Bot, Mini App, xabar tarqatish',
  '/site': 'Restoran sayti, logotip va ranglar',
  '/inventory': 'Qoldiq, kirim, tex-karta, tannarx, xarid rejasi',
  '/procurement': "Ta'minotchilar, bozorlar ro'yxati, narx, buyurtma, qarz",
  '/market': 'Bozorchi avansi, xarid, taksi/hammol, kamomad',
  '/forecast': 'Bayramlar, ob-havo va savdo prognozi',
  '/hr': 'Xodimlar ro\'yxati, smena, davomat, oylik',
  '/recruiting': 'Vakansiyalar, nomzodlar, suhbatlar',
  '/kpi': 'Baholash, KPI va reyting',
  '/training': 'Kurslar, testlar, sertifikatlar, standartlar',
  '/org': "Bo'limlar va kim kimga bo'ysunadi",
  '/positions': 'Lavozim vazifalari va talablari',
  '/tasks': 'Kundalik vazifalar, muammolar, nazorat',
  '/projects': "Filial ochish, yangi menyu, ta'mir — katta ishlar",
  '/reports': 'Savdo, foyda-zarar, food cost, menyu tahlili',
  '/branches': "Filiallar, manzil, ish vaqti",
  '/users': 'Kim tizimga kiradi: login, parol, rollar va ruxsatlar',
  '/modules': "Modullarni yoqish va o'chirish",
  '/settings': 'Restoran va profil sozlamalari',
  '/support': 'Texnik yordam va platforma bilan aloqa',
  '/audit': "Kim, qachon, nimani o'zgartirgani",
}

const TAIL: NavItem[] = [
  { route: '/branches', label: { uz: 'Filiallar', ru: 'Филиалы', en: 'Branches' }, icon: 'store', order: 80, perm: 'core.branches.manage' },
  { route: '/users', label: { uz: 'Kirish va rollar', ru: 'Доступ и роли', en: 'Access & roles' }, icon: 'users', order: 85, perm: 'core.users.manage' },
  { route: '/modules', label: { uz: 'Modullar', ru: 'Модули', en: 'Modules' }, icon: 'sliders', order: 95, perm: 'core.modules.manage' },
  { route: '/settings', label: { uz: 'Sozlamalar', ru: 'Настройки', en: 'Settings' }, icon: 'bars', order: 96, perm: 'core.settings.view' },
  { route: '/support', label: { uz: 'Yordam', ru: 'Поддержка', en: 'Support' }, icon: 'headset', order: 97, perm: 'core.settings.view' },
  { route: '/audit', label: { uz: "O'zgarishlar tarixi", ru: 'Журнал изменений', en: 'Audit log' }, icon: 'clock', order: 98, perm: 'core.settings.view' },
]
export const HOME: NavItem = { route: '/', label: { uz: 'Boshqaruv paneli', ru: 'Панель', en: 'Dashboard' }, icon: 'home', order: 0 }

export const matches = (route: string, path: string) => (route === '/' ? path === '/' : path === route || path.startsWith(route + '/'))

export function useNav() {
  const a = useAuth(), route = useRoute()
  const items = computed<NavItem[]>(() => [...((a.me?.nav ?? []) as NavItem[]), ...TAIL.filter(i => !i.perm || a.can(i.perm))])
  const sections = computed<SectionView[]>(() => {
    const used = new Set<string>()
    const out: SectionView[] = SECTIONS.map(s => {
      const its = items.value.filter(i => s.routes.includes(i.route)).sort((x, y) => s.routes.indexOf(x.route) - s.routes.indexOf(y.route))
      its.forEach(i => used.add(i.route))
      return { ...s, items: its.map(i => ({ ...i, desc: DESC[i.route] ?? '' })) }
    })
    const rest = items.value.filter(i => !used.has(i.route))
    if (rest.length) out.splice(out.length - 1, 0, { code: 'other', title: 'Boshqa', icon: 'bars', emoji: '🧩', color: '#475569', desc: 'Qo\'shimcha modullar', routes: rest.map(r => r.route), items: rest.map(i => ({ ...i, desc: DESC[i.route] ?? '' })) })
    return out.filter(s => s.items.length)
  })
  /** Joriy sahifa qaysi bo'limda: /s/<kod> yoki modul yo'li bo'yicha (ichki sahifalar ham, masalan /projects/5) */
  const current = computed<SectionView | null>(() => {
    const p = route.path
    if (p.startsWith('/s/')) return sections.value.find(s => s.code === p.slice(3)) ?? null
    return sections.value.find(s => s.items.some(i => matches(i.route, p))) ?? null
  })
  const currentItem = computed(() => current.value?.items.find(i => matches(i.route, route.path)) ?? null)
  /** Bo'limga kirish: bitta modul bo'lsa — to'g'ridan-to'g'ri o'sha sahifaga */
  const sectionLink = (s: SectionView) => (s.items.length === 1 ? s.items[0].route : `/s/${s.code}`)
  return { items, sections, current, currentItem, sectionLink }
}

/** Bo'lim ko'rsatkichlari (/dashboard/sections) — bir marta yuklanadi, 60 soniyada yangilanadi, sahifalar o'rtasida ulashiladi */
export type Kpi = { label: string; value: string | number; hint: string; tone: '' | 'ok' | 'warn' | 'bad'; route: string; icon: string }
const stats = ref<Record<string, Kpi[]> | null>(null)
let loadedAt = 0
let loadedFor = ''
let pending: Promise<void> | null = null
export function useSectionStats() {
  /** period: today | yesterday | week | month | year — plitkalardagi raqamlar shu davr bo'yicha */
  async function load(force = false, period = 'today'): Promise<void> {
    if (pending) await pending
    const ui = useUi(), b = ui.branch, key = `${b}|${period}`
    if (key !== loadedFor) force = true
    if (!force && stats.value && Date.now() - loadedAt < 60_000) return
    pending = api.get<Record<string, Kpi[]>>('/dashboard/sections', { ...(b ? { branch_id: b } : {}), period })
      .then((r) => { stats.value = r; loadedAt = Date.now(); loadedFor = key }).catch(() => { /* ko'rsatkichsiz ham ishlaydi */ }).finally(() => { pending = null })
    return pending
  }
  return { stats, load }
}
