// 「应用」页按应用展示接入说明，「接入方式」页只写中枢本身（2026-10-29 拆分：以后每个岗位一个应用，各自的步骤不能再堆进接入方式页）
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AuthGate } from '../auth'
import Apps from '../pages/Apps'
import Connect from '../pages/Connect'
import { fakeHub, renderPage } from './hub'

const admin = { mode: 'casdoor', user: { name: 'admin', display_name: '管理员', role: 'admin', depts: null } }
const info = {
  hub_url: 'http://hub.test:8088', mcp_url: 'http://hub.test:8200/mcp', api_base: 'http://hub.test:8088/api/v1',
  script_url: 'http://hub.test:8088/api/agent/hub_agent.py', bundle: null, agent_version: '0.5.12',
}
const guide = {
  summary: '演示岗位应用：做 A 和 B', audience: ['演示岗'], open: '双击桌面图标「演示应用」',
  employee_steps: [{ title: '先登录', body: '用自己的账号登录一次' }, { title: '再选模式', body: '选只读模式' }],
  admin_notes: ['每台电脑一个账号'], limits: ['不会自动发布'], faq: [{ q: '打不开怎么办', a: '重新双击' }], docs: [{ title: '指南', path: 'docs/x.md' }],
}
const app = (over: object = {}) => ({
  id: 'demo', name: '演示应用', version: '1.2.3', description: '演示', sha256: 'a'.repeat(64), size: 2048,
  requires: { node: '>=18', agent_cli: 'codebuddy', capabilities: ['browser'], base_min: '1.0.0' },
  guide, auto_upgrade: true, allowed_packs: [{ id: 'rp1', name: '演示岗位' }], opens_7d: 3, last_open: null, ...over,
})

describe('应用页', () => {
  it('每个应用一份接入说明：给谁用、怎么打开、环境、员工首次要做的事、限制、常见问题', async () => {
    fakeHub({ '/auth/me': admin, '/apps': [app()] })
    renderPage(<AuthGate><Apps /></AuthGate>)
    const g = await screen.findByTestId('guide-demo')
    const text = g.textContent ?? ''
    for (const t of ['演示岗位应用：做 A 和 B', '演示岗', '双击桌面图标「演示应用」', '先登录', '再选模式', '每台电脑一个账号', '不会自动发布', '打不开怎么办', 'docs/x.md']) {
      expect(text).toContain(t)
    }
    expect(text).toContain('Node.js >=18')            // requires 翻成人话
    expect(text).toContain('CodeBuddy CLI')
    expect(text).toContain('能控制浏览器')
    expect(text).toContain('双击图标自动升级')
  })

  it('多个应用分页签；没有 guide.json 的应用提示去补，不报错', async () => {
    fakeHub({ '/auth/me': admin, '/apps': [app(), app({ id: 'second', name: '第二个岗位应用', guide: null, auto_upgrade: false, requires: {} })] })
    renderPage(<AuthGate><Apps /></AuthGate>)
    await screen.findByTestId('guide-demo')
    await userEvent.click(screen.getByRole('tab', { name: '第二个岗位应用' }))
    const g = await screen.findByTestId('guide-second')
    expect(within(g).getByText(/还没有接入说明/)).toBeInTheDocument()
    expect(g.textContent).toContain('apps/second/guide.json')
  })
})

describe('接入方式页只写中枢本身', () => {
  const page = async (apps: unknown[]) => {
    fakeHub({ '/auth/me': admin, '/connect': info, '/apps': apps })
    renderPage(<AuthGate><Connect /></AuthGate>)
    await screen.findByText('一键脚本会自动做什么')
    await screen.findByText('各岗位的应用')
    return document.body.textContent ?? ''
  }

  it('不再有小红书专属的采集面板，改为指向「应用」页', async () => {
    const text = await page([app({ name: '小红书运营工作台' })])
    expect(text).not.toContain('小红书采集：只走 WorkBuddy 浏览器插件')
    expect(text).not.toContain('采集只走 WorkBuddy 浏览器插件')   // 原来在常见问题里的那条也搬走了
    expect(text).toContain('去「应用」页查看各应用的接入说明')
    expect(text).toContain('小红书运营工作台')                     // 列出了有哪些应用
  })

  it('「发给员工的话」自动接上各应用的首次使用步骤，应用没有说明的不写', async () => {
    const text = await page([app(), app({ id: 'bare', name: '没说明的应用', guide: null })])
    expect(text).toContain('6. 要用「演示应用」')
    expect(text).toContain('(1) 先登录：用自己的账号登录一次')
    expect(text).toContain('(2) 再选模式：选只读模式')
    expect(text).not.toContain('要用「没说明的应用」')
    expect(text).toContain('没说明的应用（还没有接入说明）')
  })

  it('取不到应用列表时页面照常显示（装机说明不依赖应用）', async () => {
    fakeHub({ '/auth/me': admin, '/connect': info })   // /apps 404
    renderPage(<AuthGate><Connect /></AuthGate>)
    expect(await screen.findByText('一键脚本会自动做什么')).toBeInTheDocument()
    expect(screen.getByText('还没有发布应用。')).toBeInTheDocument()
  })
})
