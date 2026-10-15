import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发时把 /api 转发给 FastAPI 后端
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8100',
    },
  },
})
