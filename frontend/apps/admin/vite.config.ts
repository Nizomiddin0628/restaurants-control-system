import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev: http://lazzat.localhost:5173 → API so'rovlari o'sha hostning :8000 portiga (tenant domeni saqlanadi)
export default defineConfig({
  plugins: [vue()],
  base: '/static/admin/',
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: false }, '/media': 'http://localhost:8000' },
  },
  build: { outDir: '../../../backend/website/static/admin', emptyOutDir: true, sourcemap: false },
})
