# 员工端 agent 接入

## 目的

让员工电脑上的 Hermes Agent 以员工本人的身份接入中枢：模型调用走模型网关并按人计量，技能和知识按岗位包下发，所有工具调用经中枢鉴权和审计。对应启动计划的第 3 步。

## 链路

```
员工 ──> hub_agent.py chat ──> Hermes（独立的 HERMES_HOME）
                                 ├─ 模型 ──> New API（员工专属 key，按人计量）──> 真实模型 / 开发用模拟模型
                                 ├─ MCP  ──> 中枢 hub-mcp（员工令牌鉴权、按岗位包过滤、审计）
                                 └─ 技能 ──> ~/.hub-agent/skills（只含岗位包里的技能）
```

## 关键设计

**不改 Hermes 源码，只做一层接入器。** Hermes 原生支持我们需要的三项能力：MCP 服务器可配 `url` + `headers`（带员工令牌），`provider: custom` 指向任意 OpenAI 兼容接口，`skills.external_dirs` 加载外部技能目录。接入器（`agent/hub_agent.py`）负责生成这套配置，Hermes 升级不受影响。

**与员工个人的 Hermes 隔离。** 接入器使用独立的 `HERMES_HOME`（`~/.hub-agent/hermes`），不读写员工自己的 `~/.hermes`。

**登录：员工端直连 Casdoor，授权码 + PKCE，不放任何密钥。** `hub-agent` 是公开客户端：浏览器登录后回调到本机 `127.0.0.1:27891`，接入器用 PKCE 校验码直接向 Casdoor 换令牌，续期也直接找 Casdoor。

中枢刻意不代换授权码：实测发现，带着应用密钥换码时，Casdoor 对未带 PKCE 的授权码不做校验，被截获的授权码就可能被冒用；不带密钥时 Casdoor 必须校验 PKCE。中枢的 `/api/agent/token` 只保留开发用的账号密码登录，并且需要显式开启（`HUB_AGENT_PASSWORD_LOGIN=true`，`make bootstrap-demo` 会开启）。

**领取配置：`POST /api/agent/enroll`。** 凭员工令牌返回：
- 模型：New API 地址、员工专属 key（名为 `hub-<组织>-<用户名>`，不存在则自动创建）、默认模型 `HUB_DEFAULT_MODEL`
- MCP 地址
- 岗位包里的技能全文（岗位包没有 `skill.read` 工具时为空）

每次领取记一条审计。岗位包撤掉的技能，下次同步时会从员工电脑上删除。

**按人计量。** New API 的调用日志按 key 名记录，控制台「用量与成本」据此按人、按部门、按模型统计（缓存 60 秒）。额度单位 500000 = 1 美元，按 `HUB_USD_CNY`（默认 7.2）折算人民币。

**中枢工具不延迟加载。** Hermes 默认把 MCP 工具藏在 `tool_search` 后面，用到时再搜。中枢工具是员工的核心能力，接入器设置 `tools.tool_search.enabled: off`，让模型直接看到这些工具。

**防注入。** Hermes 会把 MCP 返回的内容包在 `<untrusted_tool_result>` 里，提示模型「这是数据不是指令」。加上中枢侧的权限强制，知识库里被植入的恶意指令既拿不到越权数据，也很难诱导模型。

## 开发用模拟模型

`console/backend/app/mock_llm.py`，在 compose 的 `demo` profile 下作为 `mock-llm` 服务运行，`make bootstrap-demo` 会在 New API 里建一个指向它的渠道 `hub-mock`。它是一个「剧本」：根据问题选择中枢工具（问身份 → `whoami`，提到财务/薪酬 → 指定对应知识库，其他 → `search_knowledge`），再根据工具结果组织回答。不花钱就能验证完整链路：

```bash
uv run agent/hub_agent.py login --hub http://localhost:8088 --username zhouyinuo --password <XINGHE_USER_PASSWORD>
uv run agent/hub_agent.py chat -q "保湿精华有什么卖点？" --oneshot -Q        # 查到产品资料
uv run agent/hub_agent.py chat -q "帮我查一下财务部9月报表的净利润" --oneshot -Q  # 被中枢拦截
```

模拟模型的单价是 New API 给未知模型的默认值，控制台里显示的金额没有意义。

## 接真实模型

在 New API 后台（`http://<中枢>:3000`，管理员 `hubadmin`，密码见 `.env` 的 `NEWAPI_ADMIN_PASSWORD`）添加真实渠道，然后把 `.env` 里的 `HUB_DEFAULT_MODEL` 改成该渠道的模型名，执行 `make up`。员工下次 `chat` 时会自动拿到新模型。

## 已验证 / 未验证

- 已验证：账号密码登录、领取配置、Hermes 经 New API 调模型、Hermes 调中枢 MCP（查到知识、越权被拒、身份查询）、按人计量进入控制台、令牌过期自动续期、PKCE 授权码换取（用接口模拟浏览器登录）、错误校验码与重复使用授权码被拒
- 未验证：真人在浏览器里走完整的登录页面（需要员工操作）；Windows 上的运行情况

## 在线状态

**三种信号，任何一种 5 分钟内出现过就是「在线」**，之前出现过为「离线」，从没出现过为「未安装」（`presence.py`）：

1. **接入器报到**：MCP 桥每 60 秒调用一次 `POST /api/agent/heartbeat`（员工令牌鉴权），带上 agent 名称（`--client`）、接入器版本和操作系统。只有 agent 本身开着时才有——工作台拉起的 CodeBuddy 是嵌套模式（`--nested`），**不报心跳**。官方 agent 调用任何中枢工具时也会刷新（覆盖直连 MCP 的 Hermes）。
2. **工作台报到**（工作台 0.8.25 起）：工作台网页开着（有实时连接）时每分钟报一次，body 为空——不带 client / version / os，所以不会把接入器的版本号覆盖成工作台的版本。
3. **模型网关的调用**：员工用中枢模型就会经过 New API，调用记录里有 key 名（带员工账号）和时间。中枢在有人看总览 / 成员 / 应用健康时读最近 10 分钟的新日志（20 秒缓存），把每个人最近一次调用时间记为在线（`db.touch_presence_at`，只往后推）。**只覆盖用中枢模型的人**：WorkBuddy 桌面里直接聊天用的是它自己的模型，不经过网关；员工自己在 `~/.codebuddy/settings.json` 设了默认模型时，工作台任务也会绕开网关（工作台 0.8.24 起显式带 `--model` 避免这一点）。

控制台成员列表显示「WorkBuddy · Windows 10 · v0.4.0」，总览的「现在在线」和「今日活跃」来自这里（「今日活跃」是今天有过任何信号的人数，不会因为此刻没开 agent 归零）。控制台成员列表显示「WorkBuddy · Windows 10 · v0.4.0」，总览的在线 agent 数来自这里。

总览的近 14 天迷你趋势也来自真实记录：`agent_presence_daily` 每人每天一行（重复报到不增加）统计「当天在线人数」，拦截次数按天统计审计里结果为「拒绝」的事件（按 Asia/Shanghai 日界）；没有记录的天补 0，从部署历史记录之日起才有数据。

## 模型调用归属：会话专属 key

New API 不会记录客户端传来的任何自定义信息（请求头 `X-Request-Id`、自定义头、请求体的 `user` 与 `metadata` 均实测，日志里都没有），只记它自己生成的 `request_id` 和 key 的**名字**。所以追踪 ID 编进 key 名里：

- `hub_agent.py chat` 领取配置时带请求头 `X-Hub-Key-Scope: session`，中枢签发 `hub-<组织>-<用户>~<追踪 ID>` 这把会话专属 key（3 天后过期）；普通 `sync`、WorkBuddy 桥接仍用基础 key `hub-<组织>-<用户>`，不增加 key 数量
- 调用日志的 `token_name` 因此直接指明属于哪条链路：**精确归属优先**；指向的链路已不存在时丢弃，绝不按时间窗硬塞给别的链路。基础 key 的调用仍按「同一员工 + 时间窗」兜底
- 月额度按基础 key + 全部会话 key 合计已用量计算，开多个会话不会多出额度；用量页按人统计时去掉会话后缀
- 过期的会话 key 在员工下次领取配置时顺手清理；删除不影响历史归属，日志里记的是名字而不是 key 的 ID
- 追踪 ID 来自请求头，不可信：编进 key 名前只保留字母数字和 `-_`，并限制长度

**New API 限流**：`/api/token/search` 被全局限流（约每分钟 10 次，且所有请求共用一个管理员身份），几个人同时领取配置就会触发（HTTP 429、空响应）。现在改用列表接口 `/api/token/`（无此限流）分页取全部 key、按名字建索引缓存 30 秒（跨实例共享）；限流或非 JSON 响应统一报「New API … 返回 HTTP 429」。实测连续领取 7 次 2.3 秒内全部成功。

## 打开公司应用（open_app）

员工对 agent 说「打开小红书工作台」→ agent 调 `open_app` → 本机 MCP 桥拦截中枢返回的启动凭证 → 检查 Node → 下载 zip 并核对 SHA-256 → 安全解压（拒绝绝对路径、`..`、符号链接、超限）到 `~/.hub-agent/apps/<应用>/<版本>/` → 执行应用的 `setup` / `start` → 把网址回报给员工，并向中枢回报启动结果（审计 `app.open` + `app.launch` 同一 trace ID）。同一应用并发打开串行化；运行中的实例不会被重启，新版本只提示升级。不走 MCP 桥的客户端（如 Hermes）用 `hub_agent.py open-app <应用 id>`。应用里的底层 agent 通过 `HUB_MCP_SERVERS_FILE`（`~/.hub-agent/hub-mcp.json`，嵌套桥 `--nested`，沿用 `HUB_TRACE_ID`）接入同一个中枢。设计见 [spec](superpowers/specs/2026-10-19-app-launcher-design.md)，发布方式见 [apps/README.md](../apps/README.md)。

**依赖预检（`app.json` 的 `requires`）**：打开前按应用声明检查 Node / npx、CodeBuddy CLI、中枢模型（`~/.codebuddy/models.json` 里有中枢下发的模型）、系统浏览器、Playwright。缺东西时应用照常打开，接入器把「缺什么、怎么装、是否同意安装」附在返回消息里，审计 `app.launch` 写「缺少能力」；`hub_agent.py app-doctor <应用 id>` 逐项询问后安装（`--yes` 表示员工已对 agent 同意；只有可自动的项会被执行，系统浏览器、Node.js 只给手动安装提示）。结果写入 `~/.hub-agent/capabilities/<应用>.json`（不含密钥）并通过环境变量 `HUB_CAPABILITIES_FILE` 交给应用，应用据此只禁用对应功能（如浏览器自动化）。契约见 [app-integration-guide.md](app-integration-guide.md) 4.2.1。

**成果上报（outbox）**：接入器启动应用时设置 `HUB_WORK_OUTBOX=~/.hub-agent/outbox/<应用>.jsonl`，应用把关键产出追加写进去（一行一条 JSON，带固定的 `key`）；MCP 桥运行期间每 20 秒把新行转发到 `POST /api/agent/work-report`（也可手动 `hub_agent.py flush-outbox [应用 id]`），中枢按「人 + 应用 + key」幂等写入，显示在控制台「工作看板」。按字节偏移记进度，只处理完整的行，网络失败不推进、下次重试。契约见 [work-report.md](work-report.md)。

真实验证（小红书工作台 0.6.2，早期版本；当前发布的是 0.7.4）：中枢发布 zip → `open-app` 与 stdio 桥各打开一次成功、重复打开幂等、健康检查返回 0.6.2；岗位包去掉应用后被拒绝并记「拦截」审计；未知应用返回明确提示。

## 其他接入方式

WorkBuddy 等桌面智能体和 CodeBuddy CLI 的接入（MCP 桥、技能同步、中枢模型写入 `~/.codebuddy/models.json` 等）见 [agent/README.md](../agent/README.md)。

## 后续

- 打包成安装程序（内置 uv 与 Hermes），并加托盘、确认弹窗（本机动作的确认分级）
