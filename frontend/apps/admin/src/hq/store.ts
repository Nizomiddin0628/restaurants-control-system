import { defineStore } from 'pinia'
import { api, auth as tokenStore } from '@restopos/api'

/** HQ: platforma jamoasi a'zosi (restoran foydalanuvchisidan butunlay alohida). */
export const useHq = defineStore('hq', {
  state: () => ({ me: null as any, openTickets: 0 }),
  getters: { isAdmin: (s) => s.me?.role === 'superadmin', can: (s) => (...roles: string[]) => s.me?.role === 'superadmin' || roles.includes(s.me?.role) },
  actions: {
    async load() { if (!tokenStore.token) throw new Error('no token'); this.me = await api.get('/hq/me') },
    async verify(phone: string, code: string) { const r = await api.post('/hq/auth/verify', { phone, code }); tokenStore.set(r.token); this.me = r.staff },
    logout() { tokenStore.set(null); this.me = null; location.href = '/hq/login' },
  },
})
