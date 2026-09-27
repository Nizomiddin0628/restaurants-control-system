import { defineStore } from 'pinia'
import { api, auth as tokenStore } from '@restopos/api'

const TOP = ['founder', 'developer', 'superadmin']

/** HQ: platforma jamoasi a'zosi (restoran foydalanuvchisidan butunlay alohida). */
export const useHq = defineStore('hq', {
  state: () => ({ me: null as any, openTickets: 0 }),
  getters: {
    /** Asoschi (founder), dasturchi (developer) va bosh administrator — hamma huquq */
    isAdmin: (s) => TOP.includes(s.me?.role),
    can: (s) => (...roles: string[]) => TOP.includes(s.me?.role) || roles.includes(s.me?.role),
    /** Restoran paneliga egasining ruxsatisiz kiradi (har kirish yoziladi) */
    direct: (s) => ['founder', 'developer'].includes(s.me?.role),
  },
  actions: {
    async load() { if (!tokenStore.token) throw new Error('no token'); this.me = await api.get('/hq/me') },
    async verify(phone: string, code: string) { const r = await api.post('/hq/auth/verify', { phone, code }); tokenStore.set(r.token); this.me = r.staff },
    logout() { tokenStore.set(null); this.me = null; location.href = '/hq/login' },
  },
})
