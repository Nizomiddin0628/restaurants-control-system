/**
 * @restopos/api — bitta HTTP mijoz: token, tenant domeni, Idempotency-Key, xatolar.
 * Barcha ilovalar (admin, POS, KDS, Mini App, mobil) shu klientdan foydalanadi.
 * `pnpm api:generate` backend OpenAPI'dan TypeScript tiplarini (schema.d.ts) yaratadi.
 */
export type Json = Record<string, any>
export class ApiError extends Error {
  constructor(public status: number, public detail: string, public body?: any) { super(detail) }
}

/** HQ (platforma paneli, /hq) va restoran paneli (/admin) tokenlari alohida saqlanadi — bir-birini bosib ketmaydi. */
export const IS_HQ = typeof location !== 'undefined' && location.pathname.startsWith('/hq')
const TOKEN_KEY = IS_HQ ? 'restroos.hq.token' : 'restopos.token'
let token: string | null = null
try { token = localStorage.getItem(TOKEN_KEY) } catch {}

export const auth = {
  get token() { return token },
  set(t: string | null) { token = t; try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch {} },
}

/** API manzili: dev'da Vite proxy (/api → :8000), prod'da o'sha domen. */
export const BASE = (import.meta as any).env?.VITE_API_BASE || ''
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random())

async function request<T = any>(method: string, path: string, body?: any, opts: { form?: boolean; idempotent?: boolean; query?: Json } = {}): Promise<T> {
  const url = new URL(BASE + '/api/v1' + path, location.origin)
  if (opts.query) Object.entries(opts.query).forEach(([k, v]) => v !== undefined && v !== null && v !== '' && url.searchParams.set(k, String(v)))
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (opts.idempotent || (method !== 'GET' && !opts.form)) headers['Idempotency-Key'] = uuid()
  let payload: any
  if (opts.form) { payload = body } else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const r = await fetch(url.toString(), { method, headers, body: payload })
  if (r.status === 401) { auth.set(null); const login = IS_HQ ? '/hq/login' : '/admin/login'; if (!location.pathname.endsWith(login)) location.href = login }
  const text = await r.text()
  const data = text ? (() => { try { return JSON.parse(text) } catch { return text } })() : null
  if (!r.ok) throw new ApiError(r.status, (data && (data.detail || data.message)) || `Xato ${r.status}`, data)
  return data as T
}

export const api = {
  get: <T = any>(p: string, query?: Json) => request<T>('GET', p, undefined, { query }),
  post: <T = any>(p: string, b?: any) => request<T>('POST', p, b),
  put: <T = any>(p: string, b?: any) => request<T>('PUT', p, b),
  patch: <T = any>(p: string, b?: any) => request<T>('PATCH', p, b),
  del: <T = any>(p: string) => request<T>('DELETE', p),
  upload: <T = any>(p: string, file: File, extra: Json = {}) => {
    const fd = new FormData(); fd.append('file', file); Object.entries(extra).forEach(([k, v]) => fd.append(k, String(v)))
    return request<T>('POST', p, fd, { form: true })
  },
}

// ---- domen tiplari (qo'lda; generatsiya qilingan schema.d.ts bilan almashtiriladi)
export type I18n = { uz?: string; ru?: string; en?: string }
export type Me = { id: string; phone: string; full_name: string; language: string; avatar: string | null; roles: string[]; role_names?: string[]; permissions: string[]; tenant: { name: string; slug: string; preset: string; schema: string; enabled_modules: string[]; settings: Json; trial_ends_at: string | null }; nav: NavItem[] }
export type NavItem = { route: string; label: I18n; icon: string; order: number; perm?: string; module: string }
export type ModuleInfo = { code: string; name: I18n; version: string; phase: number; implemented: boolean; depends: string[]; permissions: string[]; nav: NavItem[]; settings_schema: Json; order: number; enabled: boolean; allowed_by_plan: boolean }
export type Category = { id: number; name: I18n; image: string | null; sort_order: number; is_active: boolean; products_count: number }
export type Product = { id: number; category_id: number; name: I18n; description: I18n; sku: string; price: number; cost: number; margin_percent: number | null; image: string | null; weight_g: number | null; kcal: number | null; tags: string[]; modifier_group_ids: number[]; is_active: boolean; in_stop_list: boolean; sort_order: number; ikpu_code: string; image_url?: string; custom_data: Json }
export type Branch = { id: number; name: string; address: string; phone: string; lat: number | null; lng: number | null; working_hours: Json; is_active: boolean; settings: Json; disabled_modules: string[]; sort_order: number }
export type SiteSettings = { id: number; title: string; tagline: I18n; logo: string | null; favicon: string | null; phone: string; telegram: string; instagram: string; address: string; languages: string[]; default_language: string; theme: Json; seo: Json; delivery: Json; custom_css: string; is_published: boolean; updated_at: string }
export type SiteSection = { id: number; type: string; title: I18n; props: Json; is_enabled: boolean; sort_order: number }
export type MediaAsset = { id: number; url: string; kind: string; folder: string; title: string; alt: string; width: number | null; height: number | null; size_bytes: number; created_at: string }

// ---- vazifalar va muammolar moduli
export type UserMini = { id: string; full_name: string; phone: string; avatar: string | null }
export type TaskColumn = { id: number; code: string; name: I18n; kind: 'backlog' | 'active' | 'review' | 'done' | 'cancelled'; color: string; wip_limit: number; sort_order: number; count: number; tasks?: TaskCard[] }
export type TaskDepartment = { id: number; code: string; name: I18n; color: string; head_id: string | null; is_active: boolean }
export type TaskCategory = { id: number; code: string; name: I18n; icon: string; color: string; sla_hours: number; default_priority: string; requires_proof: boolean; requires_approval: boolean; default_steps: string[]; department_id: number | null; is_active: boolean }
export type TaskLabel = { id: number; name: string; color: string }
export type TaskStep = { id: number; title: string; is_done: boolean; requires_photo: boolean; done_at: string | null; done_by: UserMini | null; sort_order: number }
export type TaskAttachment = { id: number; url: string; kind: 'photo' | 'proof' | 'doc'; caption: string; is_image: boolean; created_at: string; uploaded_by: UserMini | null }
export type TaskComment = { id: number; body: string; is_system: boolean; created_at: string; author: UserMini | null }
export type TaskActivity = { id: number; at: string; action: string; detail: string; meta: Json; actor: UserMini | null }
export type TaskCard = {
  id: number; number: number; title: string; column_id: number; priority: 'low' | 'normal' | 'high' | 'urgent'
  source: string; status: string; progress: number; is_overdue: boolean; due_at: string | null
  branch_name: string | null; department: { id: number; name: I18n; color: string } | null
  assignee: UserMini | null; labels: TaskLabel[]; comments_count: number; attachments_count: number
  steps_total: number; steps_done: number; sort_order: number
}
export type Task = TaskCard & {
  description: string; location: string; branch_id: number | null; category_id: number | null; department_id: number | null
  supervisor: UserMini | null; reporter: UserMini | null; start_at: string | null; submitted_at: string | null
  done_at: string | null; approved_at: string | null; approved_by: UserMini | null
  estimated_cost: number; actual_cost: number; requires_proof: boolean; requires_approval: boolean
  rework_count: number; is_archived: boolean; created_at: string; steps: TaskStep[]; attachments: TaskAttachment[]; can_approve: boolean
}
export type TaskStats = {
  total: number; open: number; in_progress: number; review: number; done: number; overdue: number
  by_column: { code: string; name: I18n; kind: string; color: string; count: number }[]
  by_department: { name: I18n; color: string; count: number }[]
  by_priority: Record<string, number>
  avg_hours_to_done: number | null; rework_rate: number
}
export type TaskMeta = {
  columns: TaskColumn[]; departments: TaskDepartment[]; categories: TaskCategory[]; labels: TaskLabel[]
  branches: { id: number; name: string }[]; users: UserMini[]; priorities: { code: string; label: string }[]
  can: { create: boolean; edit: boolean; assign: boolean; approve: boolean; admin: boolean; delete: boolean; view_all: boolean }
}
export type TaskRecurrence = { id: number; title: string; description: string; freq: 'daily' | 'weekly' | 'monthly'; interval: number; weekdays: number[]; day_of_month: number; time_of_day: string; due_in_hours: number; is_active: boolean; priority: string; steps: string[]; category_id: number | null; department_id: number | null; branch_id: number | null; assignee: UserMini | null; last_created_on: string | null }
