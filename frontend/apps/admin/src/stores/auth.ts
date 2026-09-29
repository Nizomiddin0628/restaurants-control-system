import { defineStore } from 'pinia'
import { api, auth as tokenStore, type Me } from '@restopos/api'

export const useAuth = defineStore('auth', {
  state: () => ({ me: null as Me | null, loading: false }),
  getters: {
    can: (s) => (code: string) => {
      const p = s.me?.permissions ?? []
      if (p.includes('*') || p.includes(code)) return true
      const parts = code.split('.')
      for (let i = 1; i < parts.length; i++) if (p.includes(parts.slice(0, i).join('.') + '.*')) return true
      return false
    },
    hasModule: (s) => (code: string) => !!s.me?.tenant.enabled_modules.includes(code),
  },
  actions: {
    async load() { if (!tokenStore.token) throw new Error('no token'); this.me = await api.get<Me>('/me') },
    async requestOtp(phone: string) { return api.post<{ ok: boolean; dev_code?: string; via?: string }>('/auth/otp', { phone }) },
    async verify(phone: string, code: string) { const r = await api.post<{ token: string; user: Me; reset_token?: string }>('/auth/verify', { phone, code }); tokenStore.set(r.token); this.me = r.user; return r.reset_token ?? '' },
    async check(phone: string) { return api.post<{ phone: string; has_password: boolean; telegram: boolean; bot: string }>('/auth/check', { phone }) },
    async setPassword(password: string, reset_token: string) { await api.post('/me/password', { new_password: password, reset_token }); if (this.me) this.me.has_password = true },
    async login(phone: string, password: string) { const r = await api.post<{ token: string; user: Me }>('/auth/login', { phone, password }); tokenStore.set(r.token); this.me = r.user },
    async tgStart(phone: string) { return api.post<{ ok: boolean; reason?: string; id?: string; secret?: string; ttl?: number; bot_username?: string; link?: string; linked?: boolean }>('/auth/tg-login', { phone }) },
    async tgPoll(id: string, secret: string) {
      const r = await api.get<{ status: string; token?: string; user?: Me; reset_token?: string }>(`/auth/tg-login/${id}`, { secret })
      if (r.status === 'ok' && r.token && r.user) { tokenStore.set(r.token); this.me = r.user }
      return r
    },
    async switchIn(code: string) { const r = await api.post<{ token: string; user: Me }>('/auth/switch', { code }); tokenStore.set(r.token); this.me = r.user },
    logout() { tokenStore.set(null); this.me = null; location.href = '/admin/login' },
  },
})
