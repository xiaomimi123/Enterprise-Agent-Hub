// 前端冒烟测试：用假的中枢接口渲染真实页面，防止「页面白屏 / 数字对不上 / 登录守卫失效」这类问题没人发现。
// 数据来自后端演示模式的真实输出（fixtures/），接口形状变了这里会先报错。
import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AuthGate, useSession } from '../auth'
import membersFixture from './fixtures/members.json'
import overviewFixture from './fixtures/overview.json'
import Members from '../pages/Members'
import Overview from '../pages/Overview'
import { fakeHub, renderPage } from './hub'

vi.mock('../components/EChart', async (orig) => ({ ...(await orig<object>()), default: () => <div data-testid="chart" /> }))   // jsdom 没有 canvas，图表换成占位

const admin = { mode: 'casdoor', user: { name: 'admin', display_name: '管理员', role: 'admin', depts: null } }

function Who() {
  return <div>你好 {useSession().user.display_name}</div>
}

describe('登录守卫', () => {
  it('已登录：渲染子页面', async () => {
    fakeHub({ '/auth/me': admin })
    renderPage(<AuthGate><Who /></AuthGate>)
    expect(await screen.findByText('你好 管理员')).toBeInTheDocument()
  })

  it('没有权限（403）：显示「无权访问控制台」而不是白屏', async () => {
    fakeHub({ '/auth/me': () => ({ status: 403, body: { detail: '需要管理员' } }) })
    renderPage(<AuthGate><Who /></AuthGate>)
    expect(await screen.findByText('无权访问控制台')).toBeInTheDocument()
    expect(screen.queryByText(/你好/)).not.toBeInTheDocument()
  })

  it('中枢连不上：显示重试，不放行', async () => {
    fakeHub({ '/auth/me': () => ({ status: 500, body: { detail: '数据库不可用' } }) })
    renderPage(<AuthGate><Who /></AuthGate>)
    expect(await screen.findByText('暂时无法连接中枢')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
    expect(screen.queryByText(/你好/)).not.toBeInTheDocument()
  })

  it('未登录（401）：去取登录地址', async () => {
    const calls = fakeHub({ '/auth/me': () => ({ status: 401, body: { detail: '未登录' } }), '/auth/login': { url: '/__login_stub__' } })
    renderPage(<AuthGate><Who /></AuthGate>)
    await waitFor(() => expect(calls).toContain('/auth/login'))
    expect(screen.queryByText(/你好/)).not.toBeInTheDocument()
  })
})

describe('总览', () => {
  it('在线人数、今日活跃、拦截次数和接口数据一致', async () => {
    const ov = structuredClone(overviewFixture) as typeof overviewFixture
    ov.stats.agents_online = 7
    ov.stats.denied_today = 3
    ov.daily_ops[ov.daily_ops.length - 1].online = 12
    fakeHub({ '/auth/me': admin, '/overview': ov })
    renderPage(<AuthGate><Overview /></AuthGate>)
    const sub = await screen.findByText(/现在有/)
    expect(sub.textContent).toMatch(/现在有\s*7\s*人在线，今天共\s*12\s*人用过/)
    expect(sub.textContent).toMatch(/拦截了\s*3\s*次/)
  })

  it('接口出错：显示错误提示，不是空白', async () => {
    fakeHub({ '/auth/me': admin, '/overview': () => ({ status: 500, body: { detail: '统计失败' } }) })
    renderPage(<AuthGate><Overview /></AuthGate>)
    expect(await screen.findByText('加载失败')).toBeInTheDocument()
    expect(screen.getByText('统计失败')).toBeInTheDocument()
  })
})

describe('成员与组织', () => {
  it('列出成员，在线 / 离线状态来自接口；按状态筛选', async () => {
    const rows = (membersFixture as Array<{ name: string } & Record<string, unknown>>).slice(0, 4).map((m, i) => ({
      ...m, agent_status: i === 0 ? '在线' : '离线', last_active: new Date(Date.now() - 3 * 3600_000).toISOString(),
    }))
    fakeHub({ '/auth/me': admin, '/members': rows, '/departments': [], '/role-packs': [] })
    renderPage(<AuthGate><Members /></AuthGate>)
    const first = await screen.findByText(rows[0].name)
    const row = first.closest('tr') as HTMLElement
    expect(within(row).getByText('在线')).toBeInTheDocument()
    expect(within(row).getByText(/3 小时前/)).toBeInTheDocument()
    for (const m of rows.slice(1)) {
      expect(within((await screen.findByText(m.name)).closest('tr') as HTMLElement).getByText('离线')).toBeInTheDocument()
    }
  })
})
