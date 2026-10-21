# 员工端接入器（hub_agent.py）

员工电脑上运行的一个脚本。它**不修改 Hermes 的代码**，只负责把 Hermes 接到企业中枢上：

1. **登录**：打开浏览器登录中枢（Casdoor 账号；首次登录需先把管理员给的初始密码改掉），拿到员工本人的令牌
2. **领取配置**：专属模型 key（按人计量）、中枢 MCP 地址、岗位包里的技能
3. **生成独立的 Hermes 配置**：默认在 `~/.hub-agent/hermes`，与员工个人的 Hermes（`~/.hermes`）完全隔开
4. **启动 Hermes**

## 前提

- 已安装 [Hermes Agent](https://github.com/NousResearch/hermes-agent)（`hermes` 命令可用）
- 已安装 [uv](https://docs.astral.sh/uv/)，用来运行脚本（依赖写在脚本头部，自动安装）

## 用法

```bash
# 登录（会打开浏览器）
uv run agent/hub_agent.py login --hub http://<中枢>:8088

# 开发/演示环境可用账号密码登录（中枢需开启 HUB_AGENT_PASSWORD_LOGIN）
uv run agent/hub_agent.py login --hub http://localhost:8088 --username zhouyinuo --password <密码>

# 启动 Hermes（每次启动都会先同步岗位包和技能）
uv run agent/hub_agent.py chat

# 单次提问，后面的参数原样交给 hermes chat
uv run agent/hub_agent.py chat -q "保湿精华有什么卖点？" --oneshot -Q

uv run agent/hub_agent.py status    # 查看登录状态和岗位包
uv run agent/hub_agent.py sync      # 手动重新同步
uv run agent/hub_agent.py logout    # 退出，清除本机的令牌、模型 key 和技能
```

环境变量 `HUB_AGENT_HOME` 可以改数据目录（默认 `~/.hub-agent`），同一台电脑上模拟多个员工时有用。

## 一键接入（推荐）

员工电脑上只需一条命令（控制台「能力 → 接入方式」页可直接复制，地址已填好）：

```powershell
# Windows（PowerShell）
powershell -ExecutionPolicy Bypass -c "irm http://<中枢>:8088/api/agent/install.ps1 | iex"
```
```bash
# macOS / Linux
curl -fsSL http://<中枢>:8088/api/agent/install.sh | sh
```

它会：没有 uv 就安装 → 下载接入器到 `~/.hub-agent/` → 打开浏览器用员工本人账号登录 → 检测本机的 WorkBuddy、Cursor、Claude 桌面版，把 `enterprise-hub` 写进它们的 MCP 配置（保留原有内容，改之前备份为 `*.bak-hub-<时间>`，格式有误的配置文件不覆盖）。重复运行是安全的。也可以把这条命令发给 WorkBuddy 这类能执行命令的 agent，让它自己接入。

一键脚本还会检测 **Node.js**（打开公司应用如小红书工作台需要）和 **CodeBuddy CLI**（只有工作台里的浏览器自动化需要），缺哪个就**询问是否安装**，不会静默安装：Windows 用 `winget install -e --id OpenJS.NodeJS.LTS` 装 Node.js，macOS 用 `brew install node`，CodeBuddy CLI 用 `npm install -g @tencent-ai/codebuddy-code`（macOS / Linux 装到 `~/.local`，不需要 sudo）。环境变量：`HUB_INSTALL_TOOLS=yes` 不询问直接装、`HUB_INSTALL_TOOLS=no` 一律不装、`HUB_INSTALL_DRYRUN=1` 只打印会装什么（演练，不登录）；没有交互终端（比如让 agent 代跑）时不会安装，只打印命令。

员工电脑不需要改防火墙（只有中枢那台需要放行 8088、8200、8000 端口），和中枢在同一个局域网即可。新员工从建账号到接通的完整步骤和常见问题，见控制台「能力 → 接入方式」页（含可一键复制的「发给员工的话」）。安装脚本通过局域网 HTTP 下发，只应在公司内网使用。

## 接 WorkBuddy 等桌面智能体（手动）

不用 Hermes 也可以：WorkBuddy、Cursor 这类支持本地（stdio）MCP 的桌面智能体，通过接入器的 `mcp` 子命令连中枢。它在本机把 MCP 请求转发给中枢，并自动续期令牌（员工令牌 24 小时过期、续期令牌 7 天），配置一次长期可用。

1. 先登录一次：`uv run agent/hub_agent.py login --hub http://<中枢>:8088`
2. 在桌面智能体的 MCP 配置里加一个服务器（WorkBuddy 是 `~/.workbuddy/mcp.json`）：

```json
"enterprise-hub": {
  "command": "C:\Users\<你>\.local\bin\uv.exe",
  "args": ["run", "<仓库路径>\agent\hub_agent.py", "mcp"],
  "env": {"PYTHONUTF8": "1"}
}
```

**技能自动同步**：如果本机装了 WorkBuddy（存在 `~/.workbuddy`），接入器每次 `sync`、以及 WorkBuddy 每次启动桥接时，都会把岗位包技能写到 `~/.workbuddy/skills/hub-<技能 id>/`，另加一个使用说明技能 `hub-guide`（告诉模型什么时候用中枢工具）。岗位包撤掉的技能会被删除；这些目录带 `.hub-managed` 标记，员工自己装的技能不受影响。目录可用环境变量 `HUB_WORKBUDDY_SKILLS` 修改。

权限和审计与 Hermes 完全相同（同一个员工令牌、同一套岗位包）。区别是桌面智能体用它自己的大模型，不走中枢的 New API，所以这部分模型用量不会记到「用量与成本」里。超过 7 天没用、续期令牌也过期时，重新执行一次 `login`。

## 接 CodeBuddy CLI（要让 agent 控制浏览器时用）

小红书工作台这类应用对 WorkBuddy、Cursor 等桌面 agent 只开放「收件箱模式」：任务末尾会带「只处理本地文件与资料，不得打开浏览器、访问平台或发布」，agent 照此拒绝开浏览器是正常的。要自动采集、发布、回评论，工作台得用 **CLI 模式**：由工作台在后台启动一个命令行 agent（CodeBuddy CLI、Claude Code、Codex 等）并配合浏览器工具完成。

一键接入（`setup`）会自动检测 CodeBuddy CLI（`~/.codebuddy` 存在，或 `codebuddy` 命令可用），并且：

- 把中枢写进它的 MCP 配置 `~/.codebuddy/.mcp.json`（已有 `mcp.json` 或旧的 `~/.codebuddy.json` 里已有服务器时写那个文件，避免顶掉员工原有的服务器）
- 把**岗位包允许的中枢模型**写进 `~/.codebuddy/models.json`：条目名带「公司中枢 · 」前缀，`url` 为完整的 `<模型网关>/v1/chat/completions`（CodeBuddy 要求写完整路径，只支持 OpenAI 接口格式），`apiKey` 是员工本人的模型 key（按岗位包限定模型和额度，调用记入「用量与成本」），文件权限 600
- 员工没自己选过默认模型时，在 `~/.codebuddy/settings.json` 把 `model` 设为中枢的默认模型；员工之后自己改了就不再覆盖
- 在同一个 `settings.json` 的 `permissions.allow` 里追加 `DeferExecuteTool`（保留员工原有规则）：CodeBuddy 把 MCP 工具当延迟加载工具，无人值守（`codebuddy -p`，工作台的 CLI 模式）时没有权限弹窗，不放行就会被拒绝。它对所有延迟加载的 MCP 工具生效；中枢工具本身仍由岗位包按人限制
- 之后每次 `sync` 都会更新密钥和模型列表；岗位包改成「自带模型」时，会清掉中枢写入的条目

改动前都会备份为 `*.bak-hub-<时间>`，格式有误的文件不覆盖。已在真实的 CodeBuddy CLI 2.171.0 上验证：识别中枢 MCP、调用中枢模型（用量记到员工本人的 key）、无人值守调用 `whoami` 和 `generate_image`。注意 CodeBuddy 每次请求带的上下文很大（约 2.5 万 token），岗位包的月度模型额度会消耗得比较快，额度不足时模型网关返回 403。

## 打开公司应用

对桌面智能体说「打开小红书工作台」即可（MCP 桥自动完成下载、校验、启动）。不走 MCP 桥的客户端：

```bash
uv run hub_agent.py open-app xhs-workbench
```

应用在 `app.json` 里声明依赖（CodeBuddy CLI、浏览器等）时，打开前会预检，缺什么会说明；应用照常打开，只有对应功能（如浏览器自动化）不可用。安装缺失项（会逐项询问，`--yes` 表示已同意）：

应用写在本机的工作成果会由 MCP 桥每 20 秒自动转发到中枢；不经过桥时可以手动转发：`uv run hub_agent.py flush-outbox [应用 id]`。

```bash
uv run hub_agent.py app-doctor xhs-workbench
```

## 本机会生成的文件

```
~/.hub-agent/
├── credentials.json     # 令牌（权限 600）
├── profile.json         # 最近一次领取的配置摘要
├── skills/<技能>/SKILL.md # 只包含岗位包里的技能，每次同步整体替换
├── apps/<应用>/<版本>/   # open_app 下载并校验过的应用包（保留最近 2 个版本）
├── hub-mcp.json         # 给应用里的 agent 用的 MCP 配置（嵌套桥）
├── capabilities/<应用>.json # 应用依赖的预检结果（不含密钥），应用据此禁用对应功能
├── outbox/<应用>.jsonl  # 应用写下的工作成果，MCP 桥每 20 秒转发到中枢（也可手动 flush-outbox）
└── hermes/              # 专用的 HERMES_HOME
    ├── config.yaml      # 模型 → New API，MCP → 中枢，技能目录 → 上面的 skills/
    └── .env             # HUB_AGENT_TOKEN、HUB_MODEL_KEY（权限 600）
```

设计说明见 [docs/agent.md](../docs/agent.md)。
