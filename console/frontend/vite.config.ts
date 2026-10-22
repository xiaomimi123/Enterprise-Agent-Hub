import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发时把 /api 转发给 FastAPI 后端
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.HUB_API ?? 'http://localhost:8100',  // 本机 8100 被占用时可用 HUB_API 指定后端地址
    },
  },
})
