import {
  ApartmentOutlined,
  AuditOutlined,
  BookOutlined,
  DashboardOutlined,
  FundOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Layout, Menu, Tag, Tooltip, theme } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

const { Sider, Header, Content } = Layout

const MENU = [
  { key: '/', icon: <DashboardOutlined />, label: '总览' },
  {
    key: 'org', label: '组织与权限', type: 'group' as const,
    children: [
      { key: '/members', icon: <ApartmentOutlined />, label: '成员与组织' },
      { key: '/role-packs', icon: <SafetyCertificateOutlined />, label: '岗位包' },
    ],
  },
  {
    key: 'cap', label: '能力', type: 'group' as const,
    children: [
      { key: '/skills', icon: <ThunderboltOutlined />, label: '技能库' },
      { key: '/knowledge', icon: <BookOutlined />, label: '知识库' },
    ],
  },
  {
    key: 'gov', label: '监管', type: 'group' as const,
    children: [
      { key: '/audit', icon: <AuditOutlined />, label: '审计日志' },
      { key: '/usage', icon: <FundOutlined />, label: '用量与成本' },
    ],
  },
]

const TITLES: Record<string, string> = {
  '/': '总览',
  '/members': '成员与组织',
  '/role-packs': '岗位包',
  '/skills': '技能库',
  '/knowledge': '知识库',
  '/audit': '审计日志',
  '/usage': '用量与成本',
}

export default function ConsoleLayout() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  const { token } = theme.useToken()
  const selected = '/' + (pathname.split('/')[1] ?? '')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="dark" breakpoint="lg" collapsedWidth={64} style={{ position: 'sticky', top: 0, height: '100vh' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '20px 20px 16px', color: '#fff' }}>
          <RobotOutlined style={{ fontSize: 22, color: '#748ffc' }} />
          <div style={{ lineHeight: 1.2 }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>智能体中枢</div>
            <div style={{ fontSize: 12, opacity: 0.55 }}>管 agent，不管人</div>
          </div>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={MENU} onClick={(e) => nav(e.key)} />
      </Sider>
      <Layout>
        <Header
          style={{
            background: token.colorBgContainer, padding: '0 24px', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', borderBottom: `1px solid ${token.colorBorderSecondary}`,
            position: 'sticky', top: 0, zIndex: 10,
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 600 }}>{TITLES[selected] ?? ''}</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 12, color: token.colorTextSecondary }}>
            <Tooltip title="当前展示的是演示数据，接入 Casdoor / New API / RAGFlow 后切换为真实数据">
              <Tag color="orange">演示数据</Tag>
            </Tooltip>
            星河品牌（演示） · 管理员
          </span>
        </Header>
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
