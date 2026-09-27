/** Kirish huquqlari (backend core/access.py bilan bir xil mantiq) */
export type Level = 'none' | 'view' | 'edit' | 'full' | 'custom'
export type Area = { code: string; section: string; title: string; module: string | null; view: string[]; edit: string[]; full: string[]
  levels: { key: Level; label: string }[]; perms: { code: string; label: string }[] }
export type RoleT = { id: number; code: string; name: string; description: string; level: number; is_system: boolean; permissions: string[]; members: number; grantable: boolean; editable: boolean }
export type Person = { id: string; phone: string; full_name: string; avatar: string | null; is_active: boolean; roles: { code: string; name: string; level: number }[]
  branch_ids: number[]; all_branches: boolean; extra_permissions: string[]; level: number; areas: Record<string, Level>; role_areas: Record<string, Level>
  ai: boolean; ai_by_role: boolean; editable: boolean; is_me: boolean; has_password: boolean; telegram_linked: boolean; last_seen_at: string | null }
export type Meta = { sections: { code: string; title: string }[]; areas: Area[]; roles: RoleT[]; branches: { id: number; name: string }[]
  me: { level: number; all_branches: boolean; can_roles: boolean }; ai: { enabled: boolean; seats: number; used: number; free: number | null; daily_limit_cap: number } | null }

export const RANK: Record<Level, number> = { none: 0, custom: 1, view: 1, edit: 2, full: 3 }

export function covers(perms: string[] | Set<string>, code: string): boolean {
  const p = perms instanceof Set ? perms : new Set(perms)
  if (p.has('*') || p.has(code)) return true
  const parts = code.split('.')
  for (let i = 1; i < parts.length; i++) if (p.has(parts.slice(0, i).join('.') + '.*')) return true
  return false
}

export function areaLevel(perms: string[], a: Area): Level {
  if (a.full.length && a.full.every(x => covers(perms, x))) return 'full'
  if (a.edit.length && a.edit.every(x => covers(perms, x))) return 'edit'
  if (a.view.length && a.view.every(x => covers(perms, x))) return 'view'
  return a.perms.some(x => covers(perms, x.code)) || [...a.full, ...a.edit, ...a.view].some(x => covers(perms, x)) ? 'custom' : 'none'
}

/** Bo'lim bo'yicha barcha ruxsat kodlari (o'chirishda shaxsiy ro'yxatdan olib tashlash uchun) */
export function areaCodes(a: Area): string[] {
  return [...new Set([...a.view, ...a.edit, ...a.full, ...a.perms.map(p => p.code)])]
}

/** Shaxsiy ruxsatlarda bo'lim darajasini o'rnatish */
export function setLevel(extra: string[], a: Area, lv: Level): string[] {
  const drop = new Set(areaCodes(a))
  const out = extra.filter(p => !drop.has(p))
  const add = lv === 'view' ? a.view : lv === 'edit' ? a.edit : lv === 'full' ? a.full : []
  return [...new Set([...out, ...add])]
}

export const LEVEL_HINT: Record<string, string> = {
  none: 'Bu bo\'lim ko\'rinmaydi', view: 'Faqat ko\'radi, o\'zgartira olmaydi', edit: 'Ko\'radi va kundalik ishni qiladi', full: 'Hamma narsa, sozlamalari ham', custom: 'Alohida tanlangan ruxsatlar',
}
export const levelTone = (lv: number) => (lv >= 100 ? 'accent' : lv >= 80 ? 'info' : lv >= 60 ? 'ok' : 'neutral') as 'accent' | 'info' | 'ok' | 'neutral'
export const levelName = (lv: number) => (lv >= 100 ? 'Superadmin' : lv >= 80 ? 'Bosh menejer' : lv >= 60 ? 'Filial admini' : 'Xodim')
