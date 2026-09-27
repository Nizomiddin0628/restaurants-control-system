/** Loyihalar: umumiy yorliqlar va ranglar. */
export const HEALTH_TONE: Record<string, any> = { ok: 'ok', risk: 'warn', late: 'danger', done: 'info', idle: 'neutral' }
export const HEALTH_COLOR: Record<string, string> = { ok: '#16A34A', risk: '#F59E0B', late: '#DC2626', done: '#2563EB', idle: '#94A3B8' }
export const STATUS_TONE: Record<string, any> = { plan: 'neutral', active: 'info', paused: 'warn', done: 'ok', cancelled: 'danger' }
export const PRIO: Record<string, { label: string; tone: any }> = {
  low: { label: 'Past', tone: 'neutral' }, normal: { label: "O'rta", tone: 'info' }, high: { label: 'Yuqori', tone: 'warn' }, critical: { label: 'Juda muhim', tone: 'danger' },
}
export const COLS = [
  { code: 'todo', label: 'Qilinadi', color: '#94A3B8' },
  { code: 'doing', label: 'Jarayonda', color: '#2563EB' },
  { code: 'review', label: 'Tekshiruvda', color: '#F59E0B' },
  { code: 'done', label: 'Bajarildi', color: '#16A34A' },
]
export const d = (s?: string | null) => (s ? s.slice(0, 10).split('-').reverse().join('.') : '—')
export const dShort = (s?: string | null) => { if (!s) return '—'; const [, m, dd] = s.slice(0, 10).split('-'); return `${dd}.${m}` }
export const MONTHS = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr']
export function left(days: number | null | undefined, done = false): string {
  if (done) return 'bajarildi'
  if (days == null) return 'muddatsiz'
  if (days < 0) return `${-days} kun kechikdi`
  if (days === 0) return 'bugun'
  if (days === 1) return 'ertaga'
  return `${days} kun qoldi`
}
export function ago(iso: string): string {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'hozir'
  if (m < 60) return `${m} daq oldin`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} soat oldin`
  return `${Math.round(h / 24)} kun oldin`
}
export const ACT_ICON: Record<string, string> = { created: '🚀', status: '🔄', task: '📝', done: '✅', comment: '💬', file: '📎', expense: '💸', member: '👤', milestone: '🏁', info: 'ℹ️' }
