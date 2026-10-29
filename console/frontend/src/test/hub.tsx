import { App as AntApp } from 'antd'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { ThemeProvider } from '../theme'

/** 一个假的中枢：按路径返回 JSON。没列出的路径返回 404，这样页面多调了接口会立刻暴露。 */
export function fakeHub(routes: Record<string, unknown | ((init?: RequestInit) => { status?: number; body: unknown })>) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^\/api/, '').split('?')[0]
    calls.push(path)
    const r = routes[path]
    if (r === undefined) return new Response(JSON.stringify({ detail: `测试里没有 ${path}` }), { status: 404 })
    const out = typeof r === 'function' ? (r as (i?: RequestInit) => { status?: number; body: unknown })(init) : { body: r }
    return new Response(JSON.stringify(out.body), { status: out.status ?? 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

export function renderPage(ui: ReactElement, path = '/') {
  return render(
    <ThemeProvider>
      <AntApp>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </AntApp>
    </ThemeProvider>,
  )
}
