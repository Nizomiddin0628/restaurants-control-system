import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@restopos/tokens/tokens.css'
import './styles/mobile.css'
import './styles/kpi.css'
import { IS_HQ, auth } from '@restopos/api'
import { applyTheme } from './stores/ui'

applyTheme()

// Platforma yordami: HQ dan «Kirish» → ?support_token=... (egasi bergan ruxsat muddatigacha amal qiladi)
const sp = new URLSearchParams(location.search)
const st = sp.get('support_token')
if (st && !IS_HQ) {
  auth.set(st)
  sp.delete('support_token')
  history.replaceState(null, '', location.pathname + (sp.toString() ? `?${sp}` : ''))
}

async function boot() {
  if (IS_HQ) {
    const [{ default: HqApp }, { hqRouter }] = await Promise.all([import('./hq/HqApp.vue'), import('./hq/router')])
    createApp(HqApp).use(createPinia()).use(hqRouter).mount('#app')
  } else {
    const [{ default: App }, { router }] = await Promise.all([import('./App.vue'), import('./router')])
    createApp(App).use(createPinia()).use(router).mount('#app')
  }
}
boot()
