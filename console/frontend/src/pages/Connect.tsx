import { Check, Copy } from 'lucide-react'
import { Input, Tabs } from 'antd'
import { useState } from 'react'
import { api, type ConnectInfo } from '../api'
import { copyText, useRequest } from '../lib'
import { PageHeader, Panel, Pill, Seg } from '../ui'

type OS = 'Windows' | 'macOS'

function Code({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState<'ok' | 'fail'>()
  const copy = async () => {
    setDone((await copyText(text)) ? 'ok' : 'fail')
    setTimeout(() => setDone(undefined), 1800)
  }
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="muted">{label}</span>
        <a onClick={copy}>{done === 'ok' ? <><Check /> 已复制</> : done === 'fail' ? '复制失败，请手动选中' : <><Copy /> 复制</>}</a>
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
  const [quickOs, setQuickOs] = useState<OS>(navigator.userAgent.includes('Mac') ? 'macOS' : 'Windows')
  const [manual, setManual] = useState(false)
  const [account, setAccount] = useState('')
  const [initPw, setInitPw] = useState('')
  const d: ConnectInfo | undefined = info.data
  if (!d) return <PageHeader title="接入方式" sub="加载中…" />

  const quickCmd = quickOs === 'Windows'
    ? `powershell -ExecutionPolicy Bypass -c "irm ${d.hub_url}/api/agent/install.ps1 | iex"`
    : `curl -fsSL ${d.hub_url}/api/agent/install.sh | sh`
  const verifyPrompt = '请调用企业智能体中枢的 whoami，告诉我我是谁、在哪个部门、有哪些技能'
  const winCmd = `powershell -ExecutionPolicy Bypass -c "irm ${d.hub_url}/api/agent/install.ps1 | iex"`
  const macCmd = `curl -fsSL ${d.hub_url}/api/agent/install.sh | sh`
  // 员工把这一段原样发给自己的 agent，由 agent 自己执行命令；不要求员工打开命令行
  const agentPrompt = `请帮我把这台电脑接入公司的企业智能体中枢，按下面步骤做：\n` +
    `1. 看一下我电脑的系统，在终端里执行对应的那一条命令（Windows 用 PowerShell 那条，macOS / Linux 用 curl 那条）：\n` +
    `Windows：${winCmd}\nmacOS / Linux：${macCmd}\n` +
    `2. 命令会打开浏览器让我登录公司账号，请等我自己登录完成（首次登录需要先修改初始密码），不要替我输入密码。\n` +
    `3. 如果输出提示缺少 Node.js 或 CodeBuddy CLI（你在终端里运行时它不会自己询问），先问我要不要装；我同意后，Windows 先执行 $env:HUB_INSTALL_TOOLS="yes"、macOS / Linux 先执行 export HUB_INSTALL_TOOLS=yes，再重新运行一遍同一条命令。\n` +
    `4. 命令执行结束后，把最后几行输出告诉我，并提醒我完全退出、重新打开你自己。`
  const welcome = `你好，公司「企业智能体中枢」账号已开通：\n账号：${account.trim() || '<账号>'}\n初始密码：${initPw.trim() || '<初始密码>'}（首次登录需要修改）\n\n` +
    `接入方法（不需要自己敲命令，需要和公司在同一个局域网）：\n` +
    `1. 打开你的 WorkBuddy，把下面横线之间的整段话粘贴给它，发送：\n----------\n${agentPrompt}\n----------\n` +
    `2. 它会弹出浏览器，用上面的账号和初始密码登录，按提示改成自己的新密码\n` +
    `3. 它提示完成后，完全退出并重新打开 WorkBuddy\n` +
    `4. 对它说：${verifyPrompt}\n能说出你的姓名、部门和岗位包，就接通了。`

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
        <p className="muted">接入器在本机把请求转发给中枢，并自动续期登录令牌，配置一次长期可用。{app === 'WorkBuddy' ? '每次 WorkBuddy 启动时，岗位包里的技能会自动同步到它的技能目录（hub-* 开头），不用手动安装。' : ''}{app} 用它自己的大模型和积分，中枢只管知识库、技能和出图出视频的权限、审计与 GPU 用量。</p>
      </div>
    ),
  })

  return (
    <>
      <PageHeader
        title="接入方式"
        sub="新员工接入只要两步：管理员建账号，把一段话发给员工。剩下的由员工的 agent 和一键脚本自动完成，包括检测并询问安装 Node.js 和 CodeBuddy CLI，不需要单独去装。"
      />
      <div className="stack">
        <Panel title="给新员工接入" sub="管理员建账号 → 把下面这段话发给员工 → 员工粘贴给自己的 agent，全程不用敲命令">
          <div className="stack-sm">
            <div><Pill tone="accent" dot={false}>1</Pill> 在「成员与组织」页点「新建成员」（或「批量导入」），记下账号和初始密码，初始密码只显示一次。</div>
            <div><Pill tone="accent" dot={false}>2</Pill> 填入账号和初始密码，复制生成的话发给员工（钉钉 / 微信 / 邮件都行）。员工和公司在同一个局域网即可，不用改防火墙。</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Input size="small" variant="filled" placeholder="账号" value={account} onChange={(e) => setAccount(e.target.value)} style={{ width: 180 }} />
              <Input size="small" variant="filled" placeholder="初始密码" value={initPw} onChange={(e) => setInitPw(e.target.value)} style={{ width: 180 }} />
            </div>
            <Code label="发给员工的话" text={welcome} />
            <div><Pill tone="accent" dot={false}>3</Pill> 员工按话里的步骤做完后，对 agent 说下面这句话验证；能说出姓名、部门和岗位包就接通了。</div>
            <Code label="验证接通" text={verifyPrompt} />
          </div>
        </Panel>

        <Panel title="一键脚本会自动做什么">
          <div className="stack-sm">
            <div>① 检测 <b>Node.js</b> 和 <b>CodeBuddy CLI</b>：缺哪个就<b>询问是否安装</b>，不会静默安装（没有交互终端时只打印命令）。</div>
            <div>② 打开浏览器，用员工<b>本人</b>的账号登录；首次登录先改初始密码。</div>
            <div>③ 检测本机的 WorkBuddy、CodeBuddy CLI、Cursor、Claude 桌面版并写好配置（原配置先备份），岗位包允许的中枢模型一并写进 CodeBuddy。</div>
            <div>④ 之后令牌自动续期、岗位包技能自动同步，不需要再操作；超过 7 天没用时重新运行一次。</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
              <span className="muted">不想让 agent 代跑？直接复制命令：</span>
              <Seg value={quickOs} onChange={setQuickOs} options={(['Windows', 'macOS'] as OS[]).map((v) => ({ value: v, label: v }))} />
            </div>
            <Code label={quickOs === 'Windows' ? 'PowerShell' : '终端'} text={quickCmd} />
          </div>
        </Panel>

        <Panel title="需要 agent 自动操作浏览器（采集 / 对标）" sub="WorkBuddy 等桌面 agent 在工作台里按设计只能「收件箱模式」，不开浏览器；要自动操作浏览器，用 CodeBuddy CLI">
          <div className="stack-sm">
            <div><Pill tone="accent" dot={false}>1</Pill> 上面的一键脚本装好 Node.js 和 CodeBuddy CLI（询问时选「是」）；装好后<b>再运行一次</b>脚本，写好中枢的 MCP 和岗位包允许的模型。</div>
            <div><Pill tone="accent" dot={false}>2</Pill> 打开小红书工作台，在「连接与设置」里点 CodeBuddy 旁边的「测试并使用」。</div>
            <div><Pill tone="accent" dot={false}>3</Pill> 回到 WorkBuddy，对它说「为小红书工作台开启浏览器控制」。第一次打开小红书会停在登录页，请员工<b>本人</b>扫码登录（agent 不碰密码和验证码）。</div>
          </div>
        </Panel>

        <a onClick={() => setManual(!manual)} style={{ alignSelf: 'flex-start' }}>
          {manual ? '收起' : '管理员排错与手动配置（员工连不上、一键命令用不了、要接 Hermes 或 HTTP 接口时展开）'}
        </a>
        {manual && (<>
        <Panel title="管理员检查：中枢这台机器" sub="员工连不上时先看这里">
          <div className="stack-sm">
            <div>防火墙放行端口 <span className="mono">8088</span>（控制台 / 登录入口）、<span className="mono">8200</span>（MCP）、<span className="mono">8000</span>（Casdoor 登录页），网络类型设为「专用网络」，只对局域网开放。</div>
            <div>用 <span className="mono">{d.hub_url}</span> 访问的地址要和 <span className="mono">.env</span> 里的 <span className="mono">HUB_HOST</span> 一致；这台电脑换了网络或 IP，需要改 <span className="mono">.env</span> 后重新 <span className="mono">make up</span>。</div>
            <Code label="在员工电脑上测试能否连通（PowerShell）" text={`Test-NetConnection ${new URL(d.hub_url).hostname} -Port 8088; Test-NetConnection ${new URL(d.hub_url).hostname} -Port 8200`} />
          </div>
        </Panel>

        <Panel title="中枢地址">
          <div className="connect-grid">
            <Field k="MCP 地址（Streamable HTTP）" v={d.mcp_url} />
            <Field k="控制台 / 员工登录" v={d.hub_url} />
            <Field k="生成接口（HTTP）" v={d.api_base} />
            <Field k="接入器脚本下载" v={d.script_url} />
          </div>
        </Panel>

        <Panel title="手动安装 Node.js 和 CodeBuddy CLI（一键脚本没装成功时）" extra={<Seg value={quickOs} onChange={setQuickOs} options={(['Windows', 'macOS'] as OS[]).map((v) => ({ value: v, label: v }))} />}>
          <div className="stack-sm">
            <Code label={quickOs === 'Windows' ? '安装 Node.js（PowerShell）' : '安装 Node.js（macOS 用 Homebrew；Linux 用系统包管理器或 nodejs.org）'} text={quickOs === 'Windows' ? 'winget install -e --id OpenJS.NodeJS.LTS' : 'brew install node'} />
            <Code label="安装 CodeBuddy CLI（装好 Node.js 后；Windows 装完要重新打开终端）" text={quickOs === 'Windows' ? 'npm install -g @tencent-ai/codebuddy-code' : 'npm install -g --prefix ~/.local @tencent-ai/codebuddy-code'} />
            <Code label="想让一键脚本不再询问、直接装好（先设环境变量，再运行一键命令）" text={quickOs === 'Windows' ? '$env:HUB_INSTALL_TOOLS = "yes"' : 'export HUB_INSTALL_TOOLS=yes'} />
            <Code label="验证 CodeBuddy 已用上中枢模型（在员工电脑的终端里）" text={'codebuddy -p "你好，请用一句话介绍你自己"'} />
            <p className="muted">岗位包选「自带模型」时，中枢不下发模型，CodeBuddy 用员工自己的模型和积分。CodeBuddy 每次请求带的上下文很大，月度模型额度会消耗得比较快，额度不足时请在「岗位包」页调高。</p>
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
            <div><Pill tone="accent" dot={false}>2</Pill> 登录：会打开浏览器，用员工本人的账号登录</div>
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
        </>)}
        <Panel title="常见问题">
          <div className="stack-sm">
            <div><b>登录时提示「登录状态校验失败」</b>：登录页放了一会儿，或同时开了多个登录页。关掉它，回到 <span className="mono">{d.hub_url}</span> 重新进入再登录一次，不要用旧的登录页。</div>
            <div><b>密码输对了还是登录失败</b>：连续输错 5 次会被锁定 15 分钟，等一会儿再试；或请管理员在「成员与组织」页重置密码。</div>
            <div><b>提示「账号已被停用」</b>：账号被管理员停用了，请联系管理员启用。</div>
            <div><b>agent 里看不到中枢的工具</b>：确认接入命令执行完成，并且已经<b>完全退出</b>再重新打开 agent（只关窗口不够）。</div>
            <div><b>超过 7 天没用，提示登录过期</b>：重新运行一次接入命令（或 <span className="mono">hub_agent.py login</span>）。</div>
            <div><b>whoami 能用，但不能出图 / 查某些知识库</b>：这是岗位包没有授权，请管理员在「岗位包」页调整，调整后下一次调用立即生效。</div>
          </div>
        </Panel>
      </div>
    </>
  )
}
