import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 4320,
    proxy: {
      // 可用 ZHIBI_API_URL 指向另一个后端（例如单独的预览实例）
      '/api': { target: process.env.ZHIBI_API_URL ?? 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
