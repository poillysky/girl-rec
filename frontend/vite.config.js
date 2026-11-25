import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器：代理 /api 与 /ws 到后端 uvicorn (127.0.0.1:8000)
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1024,
  },
})