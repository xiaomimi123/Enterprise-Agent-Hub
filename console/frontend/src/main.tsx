import { App as AntApp } from 'antd'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthGate, CallbackPage } from './auth'
import './index.css'
import ConsoleLayout from './layout/ConsoleLayout'
import Apps from './pages/Apps'
import Models from './pages/Models'
import Audit from './pages/Audit'
import Connect from './pages/Connect'
import Knowledge from './pages/Knowledge'
import Members from './pages/Members'
import Overview from './pages/Overview'
import RolePacks from './pages/RolePacks'
import Skills from './pages/Skills'
import Tasks from './pages/Tasks'
import UsagePage from './pages/Usage'
import WorkPage from './pages/Work'
import OrgPage from './pages/Org'
import ProposalsPage from './pages/Proposals'
import HealthPage from './pages/Health'
import { ThemeProvider } from './theme'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
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
              <Route path="apps" element={<Apps />} />
              <Route path="models" element={<Models />} />
              <Route path="connect" element={<Connect />} />
              <Route path="audit" element={<Audit />} />
              <Route path="tasks" element={<Tasks />} />
              <Route path="org" element={<OrgPage />} />
              <Route path="proposals" element={<ProposalsPage />} />
              <Route path="work" element={<WorkPage />} />
              <Route path="usage" element={<UsagePage />} />
              <Route path="health" element={<HealthPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ThemeProvider>
  </StrictMode>,
)
