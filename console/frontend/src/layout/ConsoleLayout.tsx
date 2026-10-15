import {
  ApartmentOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BookOutlined,
  FundOutlined,
  LogoutOutlined,
  MenuOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Drawer, Dropdown, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useSession } from '../auth'
import { useRequest } from '../lib'
import { Avatar } from '../ui'

const NAV = [
  { group: '工作台', items: [{ path: '/', icon: <AppstoreOutlined />, label: '总览' }] },
  {
    group: '组织与权限', items: [
      { path: '/members', icon: <ApartmentOutlined />, label: '成员与组织' },
      { path: '/role-packs', icon: <SafetyCertificateOutlined />, label: '岗位包' },
    ],
  },
  {
    group: '能力', items: [
      { path: '/skills', icon: <ThunderboltOutlined />, label: '技能库' },
      { path: '/knowledge', icon: <BookOutlined />, label: '知识库' },
    ],
  },
  {
    group: '监管', items: [
      { path: '/audit', icon: <AuditOutlined />, label: '审计日志', badge: true },
      { path: '/usage', icon: <FundOutlined />, label: '用量与成本' },
    ],
  },
]

const TITLES: Record<string, [string, string]> = {
  '/': ['工作台', '总览'],
  '/members': ['组织与权限', '成员与组织'],
  '/role-packs': ['组织与权限', '岗位包'],
  '/skills': ['能力', '技能库'],
  '/knowledge': ['能力', '知识库'],
  '/audit': ['监管', '审计日志'],
  '/usage': ['监管', '用量与成本'],
}

export default function ConsoleLayout() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  const selected = '/' + (pathname.split('/')[1] ?? '')
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const ov = useRequest(api.overview)
  const session = useSession()
  const live = session.mode !== 'demo'

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
  const go = (path: string) => {
    setMenuOpen(false)
    nav(path)
  }

  const sidebar = (
    <>
      <div className="brand">
        <div className="brand-mark">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="2.4" fill="#fff" />
            <path d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity=".85" />
          </svg>
        </div>
        <div>
          <div className="brand-name">智能体中枢</div>
          <div className="brand-sub">{ov.data?.company ?? '…'}</div>
        </div>
      </div>

      {NAV.map((g) => (
        <div className="nav-group" key={g.group}>
          <div className="nav-label">{g.group}</div>
          {g.items.map((it) => (
            <div key={it.path} className={`nav-item ${selected === it.path ? 'active' : ''}`} onClick={() => go(it.path)}>
              {it.icon}
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
        <div className="health">
          <div className="health-row" style={{ justifyContent: 'space-between' }}>
            <span className="health-row">
              <span className={`dot ${healthy === services.length ? 'green' : 'amber'} pulse`} />
              <b style={{ fontWeight: 600 }}>中枢运行中</b>
            </span>
            <span className="muted num">{healthy}/{services.length}</span>
          </div>
          <div className="muted" style={{ marginTop: 6, lineHeight: 1.5 }}>
            私有化部署 · v0.1.0
          </div>
        </div>
        <Dropdown
          trigger={['click']}
          placement="topLeft"
          menu={{
            items: live ? [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录' }] : [{ key: 'demo', label: '演示模式无需登录', disabled: true }],
            onClick: ({ key }) => key === 'logout' && session.logout(),
          }}
        >
          <div className="user-row nav-item" style={{ height: 'auto' }}>
            <Avatar name={session.user.display_name} size={28} />
            <div style={{ lineHeight: 1.3, minWidth: 0 }}>
              <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{session.user.display_name}</div>
              <div className="muted" style={{ fontSize: 11.5, fontWeight: 400 }}>
                {live ? `${session.user.org} · ${session.user.title || '管理员'}` : '演示账号'}
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
          <button className="menu-btn" onClick={() => setMenuOpen(true)} aria-label="打开导航"><MenuOutlined /></button>
          <div className="crumb">
            <span>{group}</span>
            <RightOutlined style={{ fontSize: 9 }} />
            <b>{title}</b>
          </div>
          <div className="top-right">
            {live ? (
              <>
                <Tooltip title="成员与组织来自 Casdoor（生产环境由钉钉同步）">
                  <span className="chip"><span className="dot green" />组织：Casdoor 实时</span>
                </Tooltip>
                <Tooltip title="技能、知识库、审计、用量仍为演示数据，接入 RAGFlow / New API / MCP Server 后切换">
                  <span className="chip warn">其余模块为演示数据</span>
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
          <Outlet />
        </main>
      </div>
    </div>
  )
}
