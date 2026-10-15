import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthGate, CallbackPage } from './auth'
import './index.css'
import ConsoleLayout from './layout/ConsoleLayout'
import Audit from './pages/Audit'
import Knowledge from './pages/Knowledge'
import Members from './pages/Members'
import Overview from './pages/Overview'
import RolePacks from './pages/RolePacks'
import Skills from './pages/Skills'
import UsagePage from './pages/Usage'

// 与 index.css 中的设计令牌保持一致
const theme = {
  token: {
    colorPrimary: '#5b5bd6',
    colorText: '#1b1a17',
    colorTextSecondary: '#57564f',
    colorTextTertiary: '#8e8d85',
    colorBorder: '#e6e5df',
    colorBorderSecondary: '#efeee9',
    colorBgLayout: '#f6f6f3',
    colorFillTertiary: '#f2f1ed',
    colorSuccess: '#30a46c',
    colorWarning: '#f5a524',
    colorError: '#e5484d',
    borderRadius: 8,
    borderRadiusLG: 12,
    fontSize: 13,
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif",
    controlHeight: 32,
    boxShadowSecondary: '0 12px 32px -8px rgba(27,26,23,.18), 0 0 0 1px rgba(27,26,23,.06)',
  },
  components: {
    Table: { headerBg: '#fafaf8', rowHoverBg: '#fafaf8', cellPaddingBlock: 12, cellPaddingInline: 16 },
    Drawer: { paddingLG: 24 },
    Segmented: { itemSelectedColor: '#1b1a17' },
    Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 500 },
  },
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route path="callback" element={<CallbackPage />} />
            <Route element={<AuthGate><ConsoleLayout /></AuthGate>}>
              <Route index element={<Overview />} />
              <Route path="members" element={<Members />} />
              <Route path="role-packs" element={<RolePacks />} />
              <Route path="skills" element={<Skills />} />
              <Route path="knowledge" element={<Knowledge />} />
              <Route path="audit" element={<Audit />} />
              <Route path="usage" element={<UsagePage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
)
