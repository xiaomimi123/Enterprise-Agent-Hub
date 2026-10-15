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

**岗位包管住员工端（2026-10-15）。** 岗位包里的三项配置在员工端真正生效（`app/entitlements.py`）：

| 岗位包配置 | 落地方式 | 生效时机 |
|---|---|---|
| 可用模型 | 员工 key 的模型白名单 = 岗位包模型 ∩ 模型网关里实际可用的模型；交集为空则禁用 key | 领取配置时；控制台改岗位包或分配后立即推送；调度服务每 10 分钟巡检 |
| 每人月额度 | key 的剩余额度 = 月额度 − 本月已用（按 New API 日志计算）；用完则标记「已耗尽」，跨月巡检自动恢复 | 同上 |
| 本机动作上限 | 翻译成 Hermes 配置，见下表 | 员工下次启动 `chat` 时 |

| 本机动作上限 | Hermes 配置 |
|---|---|
| 只读 | 关闭 terminal、file、code_execution、browser、computer_use、messaging、cronjob、delegation |
| 需确认 | 关闭 messaging、computer_use；危险命令 `approvals.mode: manual`；写文件限定在工作区 |
| 需二次确认 | 关闭 computer_use；其余同「需确认」，允许对外发消息（发送前同样确认） |

写文件限制用 Hermes 的 `HERMES_WRITE_SAFE_ROOT`，只允许写员工工作区（默认 `~/Documents/中枢工作区`）和 agent 自己的配置目录；终端也在工作区里启动。

已知限制：额度用尽时模型网关统一返回「Invalid token」，无法改提示文字，所以接入器在同步时明确告诉员工「本月额度已用完」。

**在线状态。** 员工端领取配置、或调用中枢 MCP 时刷新 `agent_presence`（同一员工 60 秒内只写一次）。控制台：10 分钟内活跃为「在线」，用过但超过 10 分钟为「离线」，从没用过为「未安装」，并显示系统和接入器版本。

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

- 已验证（岗位包落地）：运营 / 客服 / 财务三种岗位包分别下发「需确认 / 只读 / 无可用模型」；模型白名单拦截 `hub-mock-pro`；控制台把额度改小后立即无法调用、改回立即恢复；Hermes 实际交给模型的工具与配置一致（只读无终端和写文件，需确认无对外发消息）；控制台在线状态
- 已验证：账号密码登录、领取配置、Hermes 经 New API 调模型、Hermes 调中枢 MCP（查到知识、越权被拒、身份查询）、按人计量进入控制台、令牌过期自动续期、PKCE 授权码换取（用接口模拟浏览器登录）、错误校验码与重复使用授权码被拒
- 未验证：真人在浏览器里走完整的登录页面（需要员工操作）；Windows 上的运行情况；写文件限定在工作区（依赖 Hermes 的 `HERMES_WRITE_SAFE_ROOT`，模拟模型不会主动写文件，未实测拦截）

## 后续

- 打包成安装程序（内置 uv 与 Hermes），并加托盘、确认弹窗（本机动作的确认分级）
- 心跳：Hermes 长时间空闲不调用中枢时会显示为「离线」，后续由桌面外壳定时上报
