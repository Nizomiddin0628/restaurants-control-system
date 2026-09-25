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

const p2 = (n: number) => String(n).padStart(2, '0')
/** 25.09.2026 — brauzer tiliga bog'liq emas (uz-UZ ba'zi brauzerlarda 2026-09-25 chiqaradi) */
export const fmtDate = (s?: string | null) => { if (!s) return '—'; const d = new Date(s); return `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.${d.getFullYear()}` }
/** 25.09 14:30 */
export const fmtDateTime = (s?: string | null) => { if (!s) return '—'; const d = new Date(s); return `${p2(d.getDate())}.${p2(d.getMonth() + 1)} ${p2(d.getHours())}:${p2(d.getMinutes())}` }
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

/** Havola turini aniqlash (backend media.py bilan bir xil) — muharrirda darhol ko'rsatish uchun */
export function linkKind(url?: string | null): 'none' | 'youtube' | 'drive' | 'vimeo' | 'video' | 'image' | 'pdf' | 'link' {
  const u = (url || '').trim()
  if (!u) return 'none'
  if (youtubeId(u)) return 'youtube'
  if (/drive\.google\.com\/(file\/d\/|open\?id=|uc\?)/.test(u)) return 'drive'
  if (/vimeo\.com\/(video\/)?\d{6,}/.test(u)) return 'vimeo'
  const path = u.split(/[?#]/)[0].toLowerCase()
  const ext = path.includes('.') ? path.split('.').pop()! : ''
  if (['mp4', 'webm', 'mov', 'm4v', 'ogg'].includes(ext)) return 'video'
  if (['jpg', 'jpeg', 'png', 'webp', 'gif'].includes(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  return 'link'
}
export const LINK_LABEL: Record<string, string> = {
  youtube: '▶ YouTube — ko\'rilgan foiz aniq o\'lchanadi', video: '🎬 Video fayl havolasi — aniq o\'lchanadi',
  drive: '📁 Google Drive — sahifada o\'tkazilgan vaqt o\'lchanadi', vimeo: '▶ Vimeo — sahifada o\'tkazilgan vaqt o\'lchanadi',
  image: '🖼 Rasm havolasi', pdf: '📄 PDF havolasi', link: '🔗 Oddiy havola — sahifada o\'tkazilgan vaqt o\'lchanadi',
}
export const isUrl = (s: string) => /^https?:\/\/\S+$/i.test((s || '').trim())
