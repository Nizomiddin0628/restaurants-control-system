import { defineStore } from 'pinia'
export type Theme = 'light' | 'dark' | 'auto'
const KEY = 'restopos.theme'

export function applyTheme(t?: Theme) {
  let theme: Theme = t ?? 'auto'
  try { theme = t ?? ((localStorage.getItem(KEY) as Theme) || 'auto') } catch {}
  const root = document.documentElement
  if (theme === 'auto') root.removeAttribute('data-theme'); else root.dataset.theme = theme
  // TV / katta ekran zichligi
  if (window.matchMedia('(min-width: 1921px)').matches || /SmartTV|SMART-TV|Tizen|WebOS|Android TV/i.test(navigator.userAgent)) root.dataset.density = 'tv'
}

export const useUi = defineStore('ui', {
  state: () => ({ theme: (() => { try { return (localStorage.getItem(KEY) as Theme) || 'auto' } catch { return 'auto' as Theme } })(), sidebarOpen: false, lang: 'uz' }),
  actions: {
    setTheme(t: Theme) { this.theme = t; try { localStorage.setItem(KEY, t) } catch {}; applyTheme(t) },
    cycleTheme() { this.setTheme(this.theme === 'light' ? 'dark' : this.theme === 'dark' ? 'auto' : 'light') },
  },
})
