// 测试配置单独放一个文件：vitest 自带的 vite 类型和项目的 vite 版本不同，写在 vite.config.ts 里会类型冲突。
// JSX 由 tsconfig 的 react-jsx 处理，不需要 react 插件。
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
