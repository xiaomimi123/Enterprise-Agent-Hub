import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import ConsoleLayout from './layout/ConsoleLayout'
import Audit from './pages/Audit'
import Knowledge from './pages/Knowledge'
import Members from './pages/Members'
import Overview from './pages/Overview'
import RolePacks from './pages/RolePacks'
import Skills from './pages/Skills'
import UsagePage from './pages/Usage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#3b5bdb', borderRadius: 8 } }}>
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route element={<ConsoleLayout />}>
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
