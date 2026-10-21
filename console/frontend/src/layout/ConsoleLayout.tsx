import {
  AppWindow, Backpack, Cpu, ChartPie, ChevronRight, ClipboardCheck, ClipboardList, Network, LayoutDashboard, Library, LogOut, Menu, Moon, NotebookPen, Palette, Plug, Sun, Users,
} from 'lucide-react'
import { Drawer, Dropdown, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useSession } from '../auth'
import { useRequest } from '../lib'
import { useTheme } from '../theme'
import { Avatar } from '../ui'

type Role = 'admin' | 'boss' | 'manager'
const ROLE_LABEL: Record<Role, string> = { admin: '系统管理员', boss: '老板', manager: '部门主管' }
const ALL: Role[] = ['admin', 'boss', 'manager']
const ADMIN_BOSS: Role[] = ['admin', 'boss']

// roles：哪些角色能看到这一项。服务端对老板 / 主管做了白名单限制，这里只是不显示进不去的菜单
const NAV = [
  { group: '工作台', items: [{ path: '/', icon: <LayoutDashboard />, label: '总览', roles: ADMIN_BOSS }] },
  {
    group: '组织与权限', items: [
      { path: '/members', icon: <Users />, label: '成员与组织', roles: ALL },
      { path: '/org', icon: <Network />, label: '部门与角色', roles: ['admin'] as Role[] },
      { path: '/role-packs', icon: <Backpack />, label: '岗位包', roles: ['admin'] as Role[] },
    ],
  },
  {
    group: '能力', items: [
      { path: '/skills', icon: <NotebookPen />, label: '技能库', roles: ALL },
      { path: '/knowledge', icon: <Library />, label: '知识库', roles: ALL },
      { path: '/models', icon: <Cpu />, label: '模型', roles: ['admin'] as Role[] },
      { path: '/apps', icon: <AppWindow />, label: '应用', roles: ADMIN_BOSS },
      { path: '/connect', icon: <Plug />, label: '接入方式', roles: ['admin'] as Role[] },
    ],
  },
  {
    group: '监管', items: [
      { path: '/work', icon: <ClipboardList />, label: '工作看板', roles: ALL },
      { path: '/audit', icon: <ClipboardCheck />, label: '审计日志', badge: true, roles: ADMIN_BOSS },
      { path: '/tasks', icon: <Palette />, label: '生成任务', roles: ADMIN_BOSS },
      { path: '/usage', icon: <ChartPie />, label: '用量与成本', roles: ADMIN_BOSS },
    ],
  },
]

const TITLES: Record<string, [string, string]> = {
  '/': ['工作台', '总览'],
  '/members': ['组织与权限', '成员与组织'],
  '/role-packs': ['组织与权限', '岗位包'],
  '/skills': ['能力', '技能库'],
  '/knowledge': ['能力', '知识库'],
  '/models': ['能力', '模型'],
  '/apps': ['能力', '应用'],
  '/connect': ['能力', '接入方式'],
  '/work': ['监管', '工作看板'],
  '/org': ['组织与权限', '部门与角色'],
  '/audit': ['监管', '审计日志'],
  '/tasks': ['监管', '生成任务'],
  '/usage': ['监管', '用量与成本'],
}

export default function ConsoleLayout() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  const selected = '/' + (pathname.split('/')[1] ?? '')
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const session = useSession()
  const role = session.user.role
  const ov = useRequest(() => (role === 'manager' ? Promise.resolve(undefined) : api.overview()), [role])
  const live = session.mode !== 'demo'
  const theme = useTheme()

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 4)
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [selected])

  const services = ov.data?.services ?? []
  const healthy = services.filter((s) => s.status === '正常').length
  const [group, title] = TITLES[selected] ?? ['', '']
  const paths = NAV.flatMap((g) => g.items).filter((it) => it.roles.includes(role)).map((it) => it.path)
  const allowed = paths.includes(selected)
  const home = paths[0] ?? '/work'
  const go = (path: string) => {
    setMenuOpen(false)
    nav(path)
  }

  const sidebar = (
    <>
      <div className="brand">
        <div className="brand-mark">3·6</div>
        <div>
          <div className="brand-name">三年级六班集团</div>
          <div className="brand-sub">智能体中枢</div>
        </div>
      </div>

      {NAV.map((g) => ({ ...g, items: g.items.filter((it) => it.roles.includes(role)) })).filter((g) => g.items.length).map((g) => (
        <div className="nav-group" key={g.group}>
          <div className="nav-label">{g.group}</div>
          {g.items.map((it) => (
            <div key={it.path} className={`nav-item ${selected === it.path ? 'active' : ''}`} onClick={() => go(it.path)}>
              <span className="nav-ic">{it.icon}</span>
              <span>{it.label}</span>
              {'badge' in it && it.badge && !!ov.data?.stats.denied_today && (
                <Tooltip title="今日越权拦截" placement="right">
                  <span className="nav-badge num">{ov.data.stats.denied_today}</span>
                </Tooltip>
              )}
            </div>
          ))}
        </div>
      ))}

      <div className="side-foot">
        {role !== 'manager' && <div className="health">
          <div className="health-row" style={{ justifyContent: 'space-between' }}>
            <span className="health-row">
              <span className={`dot ${healthy === services.length ? 'green' : 'amber'} pulse`} />
              <b style={{ fontWeight: 600 }}>全班到齐，运行中</b>
            </span>
            <span className="muted num">{healthy}/{services.length}</span>
          </div>
          <div className="muted" style={{ marginTop: 6, lineHeight: 1.5 }}>
            私有化部署 · v0.1.0
          </div>
        </div>}
        <Dropdown
          trigger={['click']}
          placement="topLeft"
          menu={{
            items: live ? [{ key: 'logout', icon: <LogOut />, label: '退出登录' }] : [{ key: 'demo', label: '演示模式无需登录', disabled: true }],
            onClick: ({ key }) => key === 'logout' && session.logout(),
          }}
        >
          <div className="user-row nav-item" style={{ height: 'auto' }}>
            <Avatar name={session.user.display_name} size={28} />
            <div style={{ lineHeight: 1.3, minWidth: 0 }}>
              <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{session.user.display_name}</div>
              <div className="muted" style={{ fontSize: 11.5, fontWeight: 400 }}>
                {live ? `${session.user.org} · ${ROLE_LABEL[role]}` : '演示账号'}
              </div>
            </div>
          </div>
        </Dropdown>
      </div>
    </>
  )

  return (
    <div className="shell">
      <aside className="sidebar">
        {sidebar}
      </aside>

      <div className="main">
        <header className={`topbar ${scrolled ? 'scrolled' : ''}`}>
          <button className="menu-btn" onClick={() => setMenuOpen(true)} aria-label="打开导航"><Menu /></button>
          <div className="crumb">
            <span>{group}</span>
            <ChevronRight style={{ fontSize: 12 }} />
            <b>{title}</b>
          </div>
          <div className="top-right">
            <Tooltip title="切换亮色（作业本）/ 暗色（黑板）">
              <span className="chip theme-toggle" role="button" onClick={theme.toggle}>
                <span className={theme.mode === 'light' ? 'on' : ''}><Sun />亮</span>
                <span className={theme.mode === 'dark' ? 'on' : ''}><Moon />暗</span>
              </span>
            </Tooltip>
            {live ? (
              <>
                <Tooltip title="成员与组织来自 Casdoor（生产环境由钉钉同步），用量来自模型网关 New API，审计来自中枢 MCP Server">
                  <span className="chip"><span className="dot green" />真实数据</span>
                </Tooltip>
              </>
            ) : (
              <Tooltip title="当前为演示数据。接入 Casdoor / New API / RAGFlow 后自动切换为真实数据">
                <span className="chip warn">演示数据</span>
              </Tooltip>
            )}
          </div>
        </header>
        <Drawer open={menuOpen} onClose={() => setMenuOpen(false)} placement="left" size={260} closable={false}
          styles={{ body: { padding: 0 } }}>
          <div className="sidebar in-drawer">{sidebar}</div>
        </Drawer>
        <main className="content">
          {allowed ? <Outlet /> : <Navigate to={home} replace />}
        </main>
      </div>
    </div>
  )
}
