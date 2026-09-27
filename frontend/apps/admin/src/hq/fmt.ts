/** HQ uchun qisqa formatlar: 1 245 000 000 → «1,2 mlrd», sana → 27.09.2026. */
export const sum = (v: number | null | undefined) => v == null ? '—' : Math.round(v).toLocaleString('ru-RU').replace(/,/g, ' ').replace(/ /g, ' ')
export function big(v: number | null | undefined) {
  if (v == null) return '—'
  const a = Math.abs(v)
  if (a >= 1e9) return `${(v / 1e9).toFixed(1).replace('.', ',')} mlrd`
  if (a >= 1e6) return `${(v / 1e6).toFixed(1).replace('.', ',')} mln`
  if (a >= 1e4) return `${Math.round(v / 1e3)} ming`
  return sum(v)
}
export const d = (s: string | null | undefined) => s ? s.slice(0, 10).split('-').reverse().join('.') : '—'
const p2 = (n: number) => String(n).padStart(2, '0')
export const dt = (s: string | null | undefined) => { if (!s) return '—'; const x = new Date(s); return `${p2(x.getDate())}.${p2(x.getMonth() + 1)}.${x.getFullYear()} ${p2(x.getHours())}:${p2(x.getMinutes())}` }
export function ago(s: string | null | undefined) {
  if (!s) return '—'
  const m = Math.round((Date.now() - new Date(s).getTime()) / 60000)
  return m < 1 ? 'hozir' : m < 60 ? `${m} daq oldin` : m < 1440 ? `${Math.floor(m / 60)} soat oldin` : `${Math.floor(m / 1440)} kun oldin`
}
export const HEALTH: Record<string, [string, string]> = { healthy: ['Sog\'lom', 'ok'], warning: ['E\'tibor kerak', 'warn'], critical: ['Kritik', 'danger'] }
export const STATUS_TONE: Record<string, any> = { active: 'ok', trial: 'info', stopped: 'danger', paid: 'ok', pending: 'warn', overdue: 'danger', cancelled: 'neutral',
  open: 'danger', progress: 'info', waiting: 'accent', closed: 'ok', low: 'neutral', normal: 'warn', high: 'danger', critical: 'danger' }
export const ACTION: Record<string, string> = { login: 'tizimga kirdi', impersonate: 'restoran paneliga kirdi', access_request: 'kirish ruxsatini so\'radi',
  suspend: 'to\'xtatdi', activate: 'faollashtirdi', plan: 'tarifni o\'zgartirdi', trial: 'sinov muddatini uzaytirdi', modules: 'modullarni o\'zgartirdi',
  ticket_update: 'murojaatni yangiladi', ticket_reply: 'murojaatga javob berdi', invoice_paid: 'to\'lovni tasdiqladi', invoice_cancelled: 'hisobni bekor qildi',
  flag: 'bayroqni o\'zgartirdi', release: 'reliz qo\'shdi', staff_add: 'jamoaga a\'zo qo\'shdi', stats_refresh: 'statistikani yangiladi' }
/** Grafik boshidagi bo'sh (0) oylarni olib tashlash — platforma ishga tushgan oydan boshlab ko'rsatiladi. */
export function trimZeros(pts: { label: string; value: number }[], keep = 3): { label: string; value: number }[] {
  const i = pts.findIndex(p => p.value > 0)
  return i < 0 ? pts.slice(-keep) : pts.slice(Math.min(i, Math.max(0, pts.length - keep)))
}
