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

## 后续

- 打包成安装程序（内置 uv 与 Hermes），并加托盘、确认弹窗（本机动作的确认分级）
- 岗位包里的「模型」与「每人月额度」落到 New API：按岗位包限制可用模型、设置 key 的额度
- 员工端在线状态与版本上报，控制台显示真实的「在线 agent」
