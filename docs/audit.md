# 审计串联（trace）

## 目的

启动计划第 5 步：**登录 → 查询 → 出图，全程带同一个 trace ID**。在控制台输入一个员工（如运营部的林小满），能看到他当天完整的链路——查了什么、被拒绝了什么、生成了什么、花了多少 token。

审计不是单独的日志文件，而是控制台的核心产品：每一次调用（模型对话、知识检索、技能读取、GPU 出图、越权拦截）都写一行 `audit_events`，同一会话共用 `trace_id`，控制台「审计日志」按 trace 聚合成一条条可读的链路。

## 链路怎么串起来

```
员工启动对话（hub_agent.py chat 生成 trace id，如 chat-079e33ba88ea）
  │
  ├─ 领取配置  POST /api/agent/enroll ──────── 请求头 X-Hub-Trace-Id ─→ 审计「登录」
  ├─ 模型调用  Hermes ──→ 中枢 /v1 代理 ──→ New API ─→ 模型
  │                        请求头 X-Hub-Trace-Id（model.default_headers）   ─→ 审计「模型」（token 数）
  └─ 中枢工具  Hermes ──→ hub-mcp（whoami / search_knowledge / generate_cover…）
                           请求头 X-Hub-Trace-Id（mcp_servers.hub.headers）  ─→ 审计「登录/检索/工具/拦截」
                                 └─ GPU 任务（gpu_tasks.trace_id）─────────── ─→ 审计「工具」（出图结果）
```

三处共用同一个 trace ID：

| 调用方 | trace 从哪来 | 谁写审计 |
|---|---|---|
| 员工端领取配置 | `hub_agent.py chat` 启动时生成，随 `X-Hub-Trace-Id` 头发给 enroll | console-api `agent_api.py` |
| 模型调用 | Hermes 配置的 `model.default_headers`（`${HUB_TRACE_ID}`）发给中枢 `/v1` 代理 | console-api `model_proxy.py` |
| 中枢 MCP 工具 | Hermes 配置的 `mcp_servers.hub.headers`（同一个头）发给 hub-mcp | hub-mcp `mcp_server.py` |

`hub_agent.py` 单独执行 `sync`（不在对话中）时不带 trace 头，enroll 自成一条 `enroll-*` 记录；MCP 调用没带头时退回 MCP 会话 ID；模型调用没带头时每次单独一条 `llm-*`。也就是：**能串则串，绝不丢审计**。

## 中枢模型代理（`model_proxy.py`）

员工的模型 key 原本直连 New API，中枢看不到调用；第 5 步起员工的模型地址改为**中枢的 `/v1`**（console-web 的 nginx 转发 `/v1` 到 console-api）：

1. **识别**：`Authorization: Bearer sk-…` 是员工专属 key。发放时（`entitlements.apply_model_limits`）把 key 的哈希 → 员工 登记进 `model_keys` 表，代理据此把调用归属到人（只存哈希，不存明文 key）
2. **转发**：原样转发给 New API——模型白名单、月额度、按人计量仍由模型网关执行，中枢不重复造轮子
3. **审计**：流式响应边转发边留末尾 256KB 解析 usage；非流式解析 JSON。每次调用写一条「模型」审计：模型名、输入/输出 token 数、问题摘录（最后一条用户消息前 80 字）
4. **错误**：网关拒绝（模型不在白名单、额度用尽）原样透传状态码和错误信息，审计记「拒绝」，链路结果显示「被拦截」

**直连封堵**：compose 里 New API 的端口只绑 `127.0.0.1`（管理员本机开后台用），局域网内员工只能经中枢 `/v1` 调模型——绕过中枢的调用无法认证，也就绕不过审计。

## 控制台展示

- **审计日志页**：左侧筛选（全部 / 成功 / 被拦截 / 待审批、部门、成员或任务搜索），点开一条链路看逐步时间线；模型步骤显示 `模型名 · N tokens`
- **用量与成本页**：金额以 New API 的计量为准（按人、按部门、按模型），审计链路里记 token 数，两者互补

## 边界与取舍

- 审计里没有金额：New API 的 HTTP 响应不带每笔扣费，金额从 New API 的用量日志来（控制台「用量与成本」页），链路里记 token 数已满足「花了多少 token」的验证标准
- 问题摘录截取最后一条用户消息的前 80 字，只用于审计可读性；完整对话不上传中枢（阶段 0 取舍：员工电脑上的对话内容由本机动作上限约束）
- `model_keys` 只在发放/巡检时刷新；员工在 New API 后台手动重建 key 会脱离映射（阶段 0 员工没有后台权限，不处理）

## 验证记录（2026-10-15）

以运营部测试成员 linxiaoman（林小满）用接入器真实登录并对话「帮我查一下保湿精华的卖点，然后生成一张小红书封面图」：

- 同一 trace `chat-079e33ba88ea` 下：3 次模型调用（7046 / 8056 / 561 tokens）+ 派发封面任务 + GPU 生成 3 张，控制台聚合为一条链路，token 合计 15663
- New API 端口已绑回环；`http://<中枢>:8088/v1/models` 无 key 返回 401
- 单元测试 `tests/test_model_proxy.py`：key 识别、流式/非流式转发与 usage 解析、网关拒绝透传、网关不可达

## 待办（阶段 1）

- Casdoor 登录本身的事件也进链路（当前登录以 enroll/whoami 为准）
- 模型调用的金额并入链路（从 New API 日志回填）
- 外部智能体（二级接入）的调用审计已支持（channel 区分），待真实接入验证
