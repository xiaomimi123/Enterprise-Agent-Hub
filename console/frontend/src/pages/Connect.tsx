import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { Input, Tabs } from 'antd'
import { useState } from 'react'
import { api, type ConnectInfo } from '../api'
import { useRequest } from '../lib'
import { PageHeader, Panel, Pill, Seg } from '../ui'

type OS = 'Windows' | 'macOS'

function Code({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setDone(true)
      setTimeout(() => setDone(false), 1500)
    })
  }
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="muted">{label}</span>
        <a onClick={copy}>{done ? <><CheckOutlined /> 已复制</> : <><CopyOutlined /> 复制</>}</a>
      </div>
      <pre>{text}</pre>
    </div>
  )
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div className="connect-field">
      <div className="muted" style={{ fontSize: 12 }}>{k}</div>
      <Code text={v} />
    </div>
  )
}

/** 桌面智能体的 MCP 配置片段：本地命令方式启动接入器的 mcp 桥 */
function bridgeJson(script: string) {
  return JSON.stringify({ mcpServers: { 'enterprise-hub': { command: 'uv', args: ['run', script, 'mcp'], env: { PYTHONUTF8: '1' } } } }, null, 2)
}

export default function Connect() {
  const info = useRequest(api.connect)
  const [os, setOs] = useState<OS>('Windows')
  const [user, setUser] = useState('')
  const d: ConnectInfo | undefined = info.data
  if (!d) return <PageHeader title="接入方式" sub="加载中…" />

  const name = user.trim() || '<用户名>'
  const home = os === 'Windows' ? `C:\\Users\\${name}` : `/Users/${name}`
  const sep = os === 'Windows' ? '\\' : '/'
  const script = `${home}${sep}.hub-agent${sep}hub_agent.py`
  const install = os === 'Windows'
    ? `powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"\nmkdir "$env:USERPROFILE\\.hub-agent" -Force\ncurl.exe -o "$env:USERPROFILE\\.hub-agent\\hub_agent.py" ${d.script_url}`
    : `curl -LsSf https://astral.sh/uv/install.sh | sh\nmkdir -p ~/.hub-agent\ncurl -o ~/.hub-agent/hub_agent.py ${d.script_url}`
  const login = `uv run "${script}" login --hub ${d.hub_url}`
  const cfgPath = (app: string) => ({
    WorkBuddy: os === 'Windows' ? `${home}\\.workbuddy\\mcp.json` : '~/.workbuddy/mcp.json',
    Cursor: os === 'Windows' ? `${home}\\.cursor\\mcp.json` : '~/.cursor/mcp.json',
    'Claude 桌面版': os === 'Windows' ? '%APPDATA%\\Claude\\claude_desktop_config.json' : '~/Library/Application Support/Claude/claude_desktop_config.json',
  })[app]

  const desktopTab = (app: string) => ({
    key: app,
    label: app,
    children: (
      <div className="stack-sm">
        <p className="muted">在 <code>{cfgPath(app)}</code> 的 <code>mcpServers</code> 里加入下面这一项（已有其他服务器时只加 <code>enterprise-hub</code> 这一段），然后重启 {app}。</p>
        <Code label="mcp.json" text={bridgeJson(script)} />
        <p className="muted">接入器在本机把请求转发给中枢，并自动续期登录令牌，配置一次长期可用。{app} 用它自己的大模型和积分，中枢只管知识库、技能和出图出视频的权限、审计与 GPU 用量。</p>
      </div>
    ),
  })

  return (
    <>
      <PageHeader
        title="接入方式"
        sub="员工的 agent 通过 MCP 连到中枢，使用知识库、技能和 GPU 出图出视频。权限按员工本人的岗位包执行，每次调用都记入审计。"
      />
      <div className="stack">
        <Panel title="中枢地址">
          <div className="connect-grid">
            <Field k="MCP 地址（Streamable HTTP）" v={d.mcp_url} />
            <Field k="控制台 / 员工登录" v={d.hub_url} />
            <Field k="生成接口（HTTP）" v={d.api_base} />
            <Field k="接入器脚本下载" v={d.script_url} />
          </div>
        </Panel>

        <Panel
          title="员工电脑上的准备（一次）"
          extra={
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Input size="small" variant="filled" placeholder="电脑用户名（用于填路径）" value={user} onChange={(e) => setUser(e.target.value)} style={{ width: 190 }} />
              <Seg value={os} onChange={setOs} options={(['Windows', 'macOS'] as OS[]).map((v) => ({ value: v, label: v }))} />
            </div>
          }
        >
          <div className="stack-sm">
            <div><Pill tone="accent" dot={false}>1</Pill> 安装 uv（Python 运行器），下载接入器</div>
            <Code label={os === 'Windows' ? 'PowerShell' : '终端'} text={install} />
            <div><Pill tone="accent" dot={false}>2</Pill> 登录：会打开浏览器，用员工本人的账号登录（生产环境为钉钉扫码）</div>
            <Code label={os === 'Windows' ? 'PowerShell' : '终端'} text={login} />
          </div>
        </Panel>

        <Panel title="把 agent 接上中枢">
          <Tabs
            items={[
              desktopTab('WorkBuddy'),
              desktopTab('Cursor'),
              desktopTab('Claude 桌面版'),
              {
                key: 'hermes', label: 'Hermes（中枢模型）',
                children: (
                  <div className="stack-sm">
                    <p className="muted">中枢官方方式：接入器生成专用的 Hermes 配置，模型用中枢下发的员工专属 key（按人计量），技能自动同步。需要先安装 Hermes Agent。</p>
                    <Code label={os === 'Windows' ? 'PowerShell' : '终端'} text={`uv run "${script}" chat`} />
                  </div>
                ),
              },
              {
                key: 'remote', label: '远程直连（高级）',
                children: (
                  <div className="stack-sm">
                    <p className="muted">支持远程 MCP 且能自定义请求头的 agent 可以直连。令牌 24 小时过期，需要自己续期，一般推荐上面的本地接入器方式。</p>
                    <Code label="mcp.json" text={JSON.stringify({ mcpServers: { 'enterprise-hub': { type: 'streamable-http', url: d.mcp_url, headers: { Authorization: 'Bearer <员工令牌>' } } } }, null, 2)} />
                  </div>
                ),
              },
              {
                key: 'http', label: 'HTTP 接口',
                children: (
                  <div className="stack-sm">
                    <p className="muted">脚本或其他系统直接提交生成任务：提交后立即返回任务号（HTTP 202），用任务号查询进度和下载链接。每人最多同时 3 个未完成任务，超出返回 429。</p>
                    <Code label="文生图" text={`curl -X POST ${d.api_base}/images -H "Authorization: Bearer <员工令牌>" -H "Content-Type: application/json" \\\n  -d '{"prompt": "一杯热拿铁放在木桌上", "aspect": "3:4", "count": 2}'`} />
                    <Code label="文生视频" text={`curl -X POST ${d.api_base}/videos -H "Authorization: Bearer <员工令牌>" -H "Content-Type: application/json" \\\n  -d '{"prompt": "蒸汽缓缓升起，镜头缓慢推进", "aspect": "9:16", "seconds": 4}'`} />
                    <Code label="图生视频" text={`curl -X POST ${d.api_base}/videos/from-image -H "Authorization: Bearer <员工令牌>" \\\n  -F image=@cover.png -F prompt="画面轻轻动起来" -F seconds=4`} />
                    <Code label="查询任务" text={`curl ${d.api_base}/tasks/<任务号> -H "Authorization: Bearer <员工令牌>"`} />
                  </div>
                ),
              },
            ]}
          />
        </Panel>
      </div>
    </>
  )
}
