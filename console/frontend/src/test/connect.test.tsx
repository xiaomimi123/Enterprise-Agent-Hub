// 「接入方式」页：员工要复制的安装命令和升级说法不能悄悄变样（2026-10-29 曾因命令缺 -NoProfile、升级说法过时让员工装不上 / 停在旧版本）
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AuthGate } from '../auth'
import Connect from '../pages/Connect'
import { fakeHub, renderPage } from './hub'

const admin = { mode: 'casdoor', user: { name: 'admin', display_name: '管理员', role: 'admin', depts: null } }
const info = {
  hub_url: 'http://hub.test:8088', mcp_url: 'http://hub.test:8200/mcp', api_base: 'http://hub.test:8088/api/v1',
  script_url: 'http://hub.test:8088/api/agent/hub_agent.py', bundle: null, agent_version: '0.5.11',
}

async function page() {
  fakeHub({ '/auth/me': admin, '/connect': info })
  renderPage(<AuthGate><Connect /></AuthGate>)
  await screen.findByText('一键脚本会自动做什么')
  return document.body.textContent ?? ''
}

describe('接入方式', () => {
  it('Windows 安装命令带 -NoProfile / -NoExit，用的是当前中枢地址；自检命令同样', async () => {
    const text = await page()
    expect(text).toContain('powershell -NoProfile -NoExit -ExecutionPolicy Bypass -c "irm http://hub.test:8088/api/agent/install.ps1 | iex"')
    expect(text).toContain('powershell -NoProfile -NoExit -ExecutionPolicy Bypass -c "irm http://hub.test:8088/api/agent/preflight.ps1 | iex"')
    expect(text).not.toMatch(/powershell -NoExit -ExecutionPolicy/)   // 旧写法（没有 -NoProfile）不能再出现
  })

  it('有备用方法（先下载脚本再 -File 运行）和「出错先看哪里」', async () => {
    const text = await page()
    expect(text).toContain('http://hub.test:8088/api/agent/install.ps1')
    expect(text).toContain(String.raw`-File "%USERPROFILE%\Downloads\install.ps1"`)
    expect(text).toContain('出错先看哪里')
    expect(text).toContain('拒绝访问')
  })

  it('「发给员工的话」写明出问题怎么办（整个窗口截图 + 备用方法）', async () => {
    const text = await page()
    expect(text).toContain('把【整个命令窗口】截图发给管理员')
    expect(text).toContain('命令跑不起来时的备用方法')
  })

  it('升级说法是现在的行为：双击图标自动升级；重新运行安装命令不会升级正在运行的工作台', async () => {
    const text = await page()
    expect(text).toContain('双击桌面图标就会自动升级')
    expect(text).toContain('重新运行安装命令不会升级正在运行的工作台')
    expect(text).not.toContain('工作台下次打开自动更新')   // 旧说法：员工因此以为重新跑命令就会升级
  })
})
