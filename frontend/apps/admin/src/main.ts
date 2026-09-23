import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@restopos/tokens/tokens.css'
import App from './App.vue'
import { router } from './router'
import { applyTheme } from './stores/ui'

applyTheme()
createApp(App).use(createPinia()).use(router).mount('#app')
