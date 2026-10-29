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

  // -NoExit：窗口不会一闪而过，出错信息能看到；Win+R 里直接粘贴就能跑，不经过任何 agent 沙箱
  const winCmd = `powershell -NoProfile -NoExit -ExecutionPolicy Bypass -c "irm ${d.hub_url}/api/agent/install.ps1 | iex"`
  const macCmd = `curl -fsSL ${d.hub_url}/api/agent/install.sh | sh`
  const quickCmd = quickOs === 'Windows'
    ? winCmd
    : macCmd
  const verifyPrompt = '请调用企业智能体中枢的 whoami，告诉我我是谁、在哪个部门、有哪些技能'
  const welcome = `你好，公司「企业智能体中枢」账号已开通：
账号：${account.trim() || '<账号>'}
初始密码：${initPw.trim() || '<初始密码>'}（首次登录需要修改）

` +
    `接入方法（需要和公司在同一个局域网）：
` +
    `【推荐，最稳】自己运行一条命令：
` +
    `1. 按键盘 Win + R（Mac 打开「终端」），粘贴下面这一行，回车：
${quickOs === 'Windows' ? winCmd : macCmd}
` +
    `   Windows 下它在你自己的窗口里运行，不受 WorkBuddy 等 agent 的安全限制；缺 Node.js / CodeBuddy 时会问你要不要装，按提示回答 y。
` +
    `2. 弹出浏览器后，用上面的账号和初始密码登录，按提示改成自己的新密码；登录完回到命令窗口等它跑完
` +
    `3. 完全退出并重新打开 WorkBuddy
` +
    `4. 对它说：${verifyPrompt}
能说出你的姓名、部门和岗位包，就接通了。
` +
    `5. 要用 CodeBuddy 做浏览器自动化的话，另开一个终端运行 codebuddy，输入 /login 登录你自己的 CodeBuddy 账号（只需一次）。
` +
    `6. 要用小红书运营工作台做对标采集：WorkBuddy →「设置 → 智能体 → 浏览器操控」打开「让 WorkBuddy 控制浏览器」，按提示在 Edge 里装扩展；再在 Edge 里登录你自己的小红书。然后双击桌面的工作台图标，在「连接与设置 → 执行 Agent 与浏览器」里把浏览器方式选成「WorkBuddy 浏览器插件」（新电脑默认没选，漏了采集会被拒）。采集的总开关默认是关的，由你自己在「竞品对标 → 采集状态」里打开。

` +
    `注意：请自己在 Win+R（Mac 用终端）里运行，不要让 WorkBuddy 等 agent 代跑——agent 的沙箱会拦截安装步骤（iex、启动进程、写启动项等），而且它退出时会把它拉起的程序一起结束。`

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
        sub="新员工接入只要两步：管理员建账号，把一段话发给员工。剩下的由一键脚本自动完成：先自检，再从中枢下载运行环境并询问是否安装 CodeBuddy CLI，不需要单独去装。员工要在自己的 Win+R 窗口里运行，不要让 agent 代跑。"
      />
      <div className="stack">
        <Panel title="给新员工接入" sub="管理员建账号 → 把下面这段话发给员工 → 员工自己用 Win+R 粘贴一行命令（不要让 agent 代跑，会被沙箱拦截）">
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
            <div>① 先做<b>安装前自检</b>（Windows，只读，不改任何东西）：系统版本、PowerShell 是否被限制、磁盘空间、到中枢和登录 / MCP 端口的网络、登录回调端口、杀毒软件等。有会导致装不上的问题就<b>停下</b>并写明原因和处理办法；错误码会匿名回传到「应用健康」页。</div>
            <div>② 所有东西装进员工自己的 <span className="mono">%USERPROFILE%\HubApps</span>（不需要管理员权限）：从<b>中枢</b>下载并校验（SHA-256）固定版本的<b>底座</b>——Node.js 22、uv、Python 3.12 和接入器的依赖库，装机不再依赖员工电脑访问外网；<b>CodeBuddy CLI</b> 会<b>先询问</b>再装（没有交互终端时跳过），默认走国内 npm 镜像，失败退回官方源。</div>
            <div>③ 打开浏览器，用员工<b>本人</b>的账号登录；首次登录先改初始密码。</div>
            <div>④ 检测本机的 WorkBuddy、CodeBuddy CLI、Cursor、Claude 桌面版并写好配置（原配置先备份），岗位包允许的中枢模型一并写进 CodeBuddy。</div>
            <div>⑤ 把 HubApps 登记为 WorkBuddy、CodeBuddy 允许读写的目录（原配置先备份），并为岗位包里的应用在桌面和开始菜单建<b>带应用图标</b>的快捷方式：<b>双击打开应用</b>，agent 退出也不会把它带走。</div>
            <div>⑥ 之后令牌自动续期、岗位包技能自动同步，接入器本身也会自动更新（0.5.8 起；更早装的电脑重新运行一次这条命令就会带上），不需要再操作；超过 7 天没用时重新运行一次。安装和打开应用出的错会自动回传到「应用健康」页。</div>
            <div><b>以前装过的电脑怎么升级</b>：重新运行同一条命令即可，<b>不需要先卸载或清理</b>。底座按版本号比对、只在不同时更新（旧版里装在 Node 目录下的 CodeBuddy 会保留）；接入器重新下载；工作台下次打开自动更新；快捷方式重建并补上图标；工作台数据和 CodeBuddy 登录不受影响。只有一种情况要手工处理：以前在 agent 的技能目录里留下的工作台旧副本（安装输出会提示，删掉那个文件夹）。</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
              <span className="muted">自己运行（Win+R 粘贴）的命令：</span>
              <Seg value={quickOs} onChange={setQuickOs} options={(['Windows', 'macOS'] as OS[]).map((v) => ({ value: v, label: v }))} />
            </div>
            <Code label={quickOs === 'Windows' ? 'PowerShell' : '终端'} text={quickCmd} />
          </div>
        </Panel>

        <Panel title="小红书采集：只走 WorkBuddy 浏览器插件" sub="采集在员工自己的浏览器里、由 CodeBuddy 通过 WorkBuddy 的浏览器扩展完成，不再用 Playwright 直连；每台电脑一个员工、一个小红书号">
          <div className="stack-sm">
            <div><Pill tone="accent" dot={false}>1</Pill> 上面的一键脚本装好 Node.js 和 CodeBuddy CLI（询问时选「是」）；员工在自己的终端运行 <span className="mono">codebuddy</span>，输入 <span className="mono">/login</span> 登录一次 CodeBuddy 自己的账号。</div>
            <div><Pill tone="accent" dot={false}>2</Pill> WorkBuddy →「设置 → 智能体 → 浏览器操控」：打开「让 WorkBuddy 控制浏览器」，按提示在 Edge 里装扩展；然后员工<b>本人</b>在 Edge 里登录小红书（agent 不碰密码和验证码）。</div>
            <div><Pill tone="accent" dot={false}>3</Pill> 双击桌面「小红书运营工作台」→「连接与设置 → 执行 Agent 与浏览器」：对话通道选 CodeBuddy，浏览器方式选<b>「WorkBuddy 浏览器插件」</b>，权限档保持「只读档」。<b>新电脑默认是「未选择」，漏了这步所有采集都会被拒</b>（采集卡片里也会提示）。</div>
            <div><Pill tone="accent" dot={false}>4</Pill> 「账号管理 → 在浏览器里登录这个账号」：agent 在员工自己的浏览器里<b>只读</b>核对登录的小红书号，并根据主页自动填好账号的<b>定位 / 目标人群 / 内容风格</b>（只填空的、可以再改）。核对结果会保存，刷新页面还在；没有已发布笔记时，「数据复盘」只能读到账号概览。</div>
            <div><Pill tone="accent" dot={false}>5</Pill> 「竞品对标 → 采集状态」：采集总开关<b>默认关</b>，由运营本人打开；有每天笔记 / 主页上限、两次采集间隔、允许时段，遇到平台提示可以设冷静期。工作台只读分析，不会自动发布。</div>
            <div className="muted">WorkBuddy 等桌面 agent 作为工作台的执行者只能「收件箱模式」，不开浏览器；工作台的默认执行者是 CodeBuddy CLI。</div>
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

        <Panel title="底座包与安装前自检（Windows）" sub="员工装机从中枢下载固定版本的运行环境，装之前先自检；这里看当前状态">
          <div className="stack-sm">
            {d.bundle ? (
              <div>
                <Pill tone="ok">已发布</Pill> 底座版本 <b>{d.bundle.base}</b>（构建于 {d.bundle.built_at.slice(0, 16).replace('T', ' ')} UTC）：
                {d.bundle.components.map((c) => ` ${c.name} ${c.version}（${(c.size / 1048576).toFixed(1)} MB）`).join('、')}。接入器版本 <b>{d.agent_version || '未知'}</b>。
              </div>
            ) : (
              <div><Pill tone="warn">没有底座包</Pill> 员工装机会退回到联网下载 Node.js / uv / Python（需要员工电脑能访问外网，更容易装不上）。在部署机上构建后即时生效，不用重启：</div>
            )}
            <Code label="构建 / 升级底座包（在有外网的部署机上，仓库根目录）" text={['node tools/build-bundle/build.mjs            # 默认版本号见脚本', 'node tools/build-bundle/build.mjs --base 1.0.2   # 改了组件或接入器依赖就升版本号'].join('\n')} />
            <div className="muted">应用要求最低底座版本：应用的 <span className="mono">app.json</span> 里写 <span className="mono">requires.base_min</span>，员工机底座过旧时打开应用会提示重新运行安装命令（不拦打开）。</div>
            <div><b>安装前自检</b>：装之前只读检查员工电脑，有问题就停下并写明原因。失败的电脑没有登录，所以走匿名上报，错误码（<span className="mono">PREFLIGHT_*</span>）会出现在「应用健康」页，显示为「未登录设备 xxxxxx（安装前自检）」。单独运行：</div>
            <Code label="只做自检、不安装（员工电脑 Win+R）" text={`powershell -NoProfile -NoExit -ExecutionPolicy Bypass -c "irm ${d.hub_url}/api/agent/preflight.ps1 | iex"`} />
            <div className="muted">可用的环境变量（先设再运行安装命令）：<span className="mono">HUB_PREFLIGHT=skip</span> 跳过自检；<span className="mono">HUB_BUNDLE=off</span> 不用底座包（退回联网下载）；<span className="mono">HUB_NPM_REGISTRY</span> 换 npm 镜像；<span className="mono">HUB_INSTALL_TOOLS=yes</span> 不询问直接装 CodeBuddy。</div>
            <div className="muted">发版前的干净机器验收：Windows 沙盒 / 虚拟机里跑一遍安装命令，见仓库 <span className="mono">tools/clean-room/README.md</span>。</div>
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
            <Code label="安装 CodeBuddy CLI（装好 Node.js 后；Windows 装完要重新打开终端）" text={quickOs === 'Windows' ? 'npm install -g --registry https://registry.npmmirror.com @tencent-ai/codebuddy-code' : 'npm install -g --prefix ~/.local --registry https://registry.npmmirror.com @tencent-ai/codebuddy-code'} />
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
                    <Code label="参考图生图（1–4 张，每张 ≤10MB）" text={`curl -X POST ${d.api_base}/images/with-references -H "Authorization: Bearer <员工令牌>" \\\n  -F images=@ref.png -F prompt="换成暖色木桌背景" -F aspect=3:4 -F count=1`} />
                    <Code label="小红书封面（3:4，一次 3 版）" text={`curl -X POST ${d.api_base}/covers -H "Authorization: Bearer <员工令牌>" -H "Content-Type: application/json" \\\n  -d '{"title": "秋天第一杯", "description": "暖色柔和"}'`} />
                    <Code label="查询任务（结果里的 via 是实际走的通道）" text={`curl ${d.api_base}/tasks/<任务号> -H "Authorization: Bearer <员工令牌>"`} />
                    <Code label="当前出图 / 出视频通道、能不能带参考图" text={`curl ${d.api_base}/capabilities -H "Authorization: Bearer <员工令牌>"`} />
                    <p className="muted">参考图生图只有「模型」页把出图通道选成第三方 API 时可用，其他通道返回 400 并说明；JSON 接口多写或写错字段会返回 422（指出是哪个字段），不再被悄悄忽略。</p>
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
            <div><b>之前让 WorkBuddy 等 agent 代跑，卡住或被拦截（iex、启动进程、计划任务、注册表被拒绝）</b>：这是 agent 沙箱的安全策略，不是中枢的问题。改用 Win+R 粘贴命令自己运行；之后工作台等后台程序也最好用你自己的窗口或开始菜单启动，不要让 agent 拉起（agent 退出时会连带结束它拉起的程序）。</div>
            <div><b>浏览器登录页一直转圈</b>：确认命令窗口还在运行；浏览器要用你平时的那个，登录页可能开在后台标签里。仍不行就关掉命令重新运行一次，只保留一个登录页。</div>
            <div><b>电脑没有 winget、没有管理员权限</b>：不需要。运行环境从中枢下载，装在你自己的用户目录；中枢没有底座包时脚本会改用 Node.js 官方便携版。</div>
            <div><b>命令一开始就停下，写着 [FAIL]</b>：这是「安装前自检」发现这台电脑照现在的状态装不上，什么都没装。看 FAIL 那几行和括号里的错误码（如 <span className="mono">PREFLIGHT_HUB_UNREACHABLE</span> 连不上中枢、<span className="mono">PREFLIGHT_PORT_CALLBACK</span> 登录端口被占用、<span className="mono">PREFLIGHT_AGENT_SANDBOX</span> 在 agent 里启动），按提示处理后重新运行。要把原因发给管理员，发 FAIL 那几行和 <span className="mono">%TEMP%\hub-preflight.json</span>。</div>
            <div><b>窗口停在 Downloading / Unpacking 很久</b>：正在下载或解压运行环境（约 95 MB，解压有几千个小文件），虚拟机里可能要几十秒到几分钟，别关窗口。0.5 版以前的脚本在虚拟机里会因为进度条显得像卡死，重新运行命令即可用上新版。</div>
            <div><b>桌面上的应用图标是空白的</b>：重新运行一次安装命令，会下载图标并重建快捷方式；仍是空白就刷新桌面（F5）或重启资源管理器，Windows 有图标缓存。</div>
            <div><b>CodeBuddy 装不上（npm 报错）</b>：默认走国内镜像，失败会退回官方源。两边都不通时检查网络或代理，管理员可以用环境变量 <span className="mono">HUB_NPM_REGISTRY</span> 指定公司内部镜像。</div>
            <div><b>CodeBuddy 登录完了，还是提示「Authentication required」</b>：CodeBuddy 的登录凭据和 WorkBuddy 桌面共用一份存储，偶尔会读不出 / 写不进（日志里是 missing-key、safe-delete）。关掉 WorkBuddy 桌面和所有 codebuddy 窗口 → Win+R 输入 <span className="mono">cmd</span> 回车（自己开的窗口，不要从 WorkBuddy 或工作台里开）→ 输入 <span className="mono">codebuddy</span>，再输 <span className="mono">/login</span> 授权，然后 <span className="mono">/exit</span>。还不行，把 <span className="mono">%LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth</span> 改名加 <span className="mono">.bak</span>（不要删）再登录一次——WorkBuddy 桌面也会要求重新登录。装机后可以用 <span className="mono">hub-check.cmd --deep</span> 提前发现。</div>
            <div><b>CodeBuddy 提示未登录</b>：CodeBuddy 要用它自己的账号登录（和中枢账号无关）：运行 <span className="mono">codebuddy</span>，输入 <span className="mono">/login</span> 完成一次即可。</div>
            <div><b>超过 7 天没用，提示登录过期</b>：重新运行一次接入命令（或 <span className="mono">hub_agent.py login</span>）。</div>
            <div><b>agent 报「400 Missing session ID」，中枢工具全部用不了</b>：接入器是旧版本（0.5.6 有这个缺陷：中枢重启或会话过期后不会重连）。重新运行一次接入命令换成最新版；0.5.8 起接入器会自动更新。临时办法：完全退出 agent 再打开。</div>
            <div><b>工作台里点「开始采集」提示「采集只走 WorkBuddy 浏览器插件」</b>：浏览器方式还没选。到工作台「连接与设置 → 执行 Agent 与浏览器」选「WorkBuddy 浏览器插件」；按钮是灰的，就先在 WorkBuddy「设置 → 智能体 → 浏览器操控」里打开「让 WorkBuddy 控制浏览器」并装好 Edge 扩展。</div>
            <div><b>换电脑 / 给新员工装机</b>：每台电脑重新运行接入命令、本人登录。<b>不要</b>把别的电脑上的 <span className="mono">~/.hub-agent/credentials.json</span> 或工作台数据目录 <span className="mono">XHS-Workbench</span> 拷过去：前者会让两台电脑变成同一个身份，后者会把别人的账号、采集记录和冷静期带过来。</div>
            <div><b>whoami 能用，但不能出图 / 查某些知识库</b>：这是岗位包没有授权，请管理员在「岗位包」页调整，调整后下一次调用立即生效。</div>
          </div>
        </Panel>
      </div>
    </>
  )
}
