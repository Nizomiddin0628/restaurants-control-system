/** Katta fayl (video) yuklash — foiz ko'rsatkichi bilan. `api.upload` fetch'da progress yo'q, shuning uchun XHR. */
import { auth, ApiError } from '@restopos/api'

export function uploadWithProgress<T = any>(path: string, file: File, onProgress?: (pct: number) => void, extra: Record<string, string> = {}): Promise<T> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('file', file)
    const url = new URL('/api/v1' + path, location.origin)
    Object.entries(extra).forEach(([k, v]) => v && url.searchParams.set(k, v))
    const x = new XMLHttpRequest()
    x.open('POST', url.toString())
    if (auth.token) x.setRequestHeader('Authorization', `Bearer ${auth.token}`)
    x.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(Math.round((100 * e.loaded) / e.total)) }
    x.onload = () => {
      let data: any = null
      try { data = JSON.parse(x.responseText) } catch { data = x.responseText }
      if (x.status >= 200 && x.status < 300) resolve(data as T)
      else reject(new ApiError(x.status, (data && data.detail) || `Xato ${x.status}`, data))
    }
    x.onerror = () => reject(new ApiError(0, "Internet uzildi — qaytadan urinib ko'ring"))
    x.send(fd)
  })
}

export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—')
export const fmtDateTime = (s?: string | null) => (s ? new Date(s).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—')
export const fmtDur = (sec: number) => { const m = Math.floor(sec / 60), s = Math.floor(sec % 60); return `${m}:${String(s).padStart(2, '0')}` }
export const initials = (n?: string | null) => (n || '?').split(' ').map((x) => x[0]).join('').slice(0, 2).toUpperCase()
export const daysLeft = (s?: string | null) => (s ? Math.ceil((new Date(s).getTime() - Date.now()) / 86400000) : null)

/** YouTube havolasidan video id: youtu.be/ID, youtube.com/watch?v=ID, /shorts/ID, /embed/ID */
export function youtubeId(url?: string | null): string | null {
  if (!url) return null
  const m = url.match(/(?:youtu\.be\/|v=|\/shorts\/|\/embed\/)([A-Za-z0-9_-]{11})/)
  return m ? m[1] : null
}

export const SUB_STATUS: Record<string, { label: string; tone: 'ok' | 'warn' | 'danger' | 'info' | 'neutral' }> = {
  todo: { label: 'Bajarilmagan', tone: 'neutral' },
  submitted: { label: 'Tekshiruvda', tone: 'info' },
  approved: { label: 'Qabul qilindi', tone: 'ok' },
  rejected: { label: 'Qaytarildi', tone: 'danger' },
}
