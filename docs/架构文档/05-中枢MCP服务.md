# 5 中枢 MCP 服务

hub-mcp 是员工 agent 使用公司能力的唯一入口，基于 MCP Python SDK，以 Streamable HTTP 方式提供服务（`http://<中枢>:8200/mcp`）。除了技能、知识、生成这些「用公司能力」的工具，现在还包括让 agent 反馈问题（改进建议）和汇报产出（工作成果）的工具。

## 5.1 协议要点

- **Streamable HTTP**：客户端以 POST 发送 JSON-RPC 消息；服务端可直接返回 JSON，也可返回 `text/event-stream` 分帧推送。首次 `initialize` 的响应头带 `mcp-session-id`，后续请求回传它以复用会话。
- **鉴权**：请求头 `Authorization: Bearer <Casdoor JWT>`，由 SDK 的 `token_verifier` 钩子调用 4.1 节的校验器。
- **会话与追踪**：同一 MCP 会话共用一个追踪 ID；客户端也可用请求头 `X-Hub-Trace-Id` 显式指定，`X-Hub-Task`（URL 编码）带上任务描述，显示在审计里。
- **服务端说明**：`initialize` 响应里的 `instructions` 告诉 agent 这是「本公司」的中枢、什么时候用哪个工具（先查知识库、先读技能、何时提改进建议），这是让通用 agent 稳定使用中枢的关键。

{{code console/backend/app/mcp_server.py::\_trace | console/backend/app/mcp_server.py — 追踪 ID 来源（显式 → 会话 → 请求）}}

每次调用先解析出 `Principal`（用户、部门、入口、是否管理员、岗位包），后续所有判断都基于它：

{{code console/backend/app/mcp_server.py::\_principal | console/backend/app/mcp_server.py}}

## 5.2 工具清单与权限

| 工具                              | 作用                               | 权限要求                                |
| ------------------------------- | -------------------------------- | ----------------------------------- |
| `whoami`                        | 当前身份、部门、入口、岗位包、可用技能与知识库          | 有效令牌                                |
| `list_skills` / `read_skill`    | 岗位包内技能列表 / SKILL.md 全文（当前已生效的版本） | 官方 agent，岗位包含 `skill.read`，技能在岗位包内  |
| `search_knowledge`              | 检索公司知识库，可指定库名                    | 岗位包含 `kb.search`；外部智能体另需双重开放        |
| `generate_cover`                | 小红书封面，3:4 × 3 张                  | 官方 agent，`image.cover`              |
| `generate_image`                | 文生图，5 种画幅，1–4 张                  | 官方 agent，`image.generate`           |
| `generate_video`                | 文生视频（带声音），2–10 秒                 | 官方 agent，`video.generate`           |
| `generate_video_from_image`     | 图生视频，参考图只收中枢签发链接                 | 同上                                  |
| `get_task`（旧名 `get_cover_task`） | 生成任务进度与结果链接                      | 只能查自己的任务                            |
| `list_apps` / `open_app`        | 当前岗位包能在本机打开的应用 / 返回带签名下载链接的启动凭证  | 官方 agent，岗位包 `apps` 含该应用            |
| `propose_improvement`           | 对技能 / 知识库文档提改进建议（只是建议，人审核后才生效）   | 能读到该技能 / 知识库的员工；外部入口不可用；每天最多 10 条   |
| `my_proposals`                  | 查看自己提交的建议和处理结果                   | 只看自己                                |
| `report_work` / `my_work`       | 上报工作成果与进度 / 查看自己上报的              | 所有人；只能改自己的条目                        |
| `team_report`                   | 团队成果与进度汇总（日报素材），含逾期复核的知识库和待处理建议数 | 老板 / 管理员看全公司，部门主管只看自己部门，其他人和外部入口不可用 |

生成类工具每人最多同时 3 个未完成任务（`HUB_GPU_MAX_PENDING_PER_USER`）。外部智能体只能使用 `search_knowledge`（且只能查开放给外部的知识库）。

## 5.3 工具设计原则

- **说明面向「本公司」**：工具描述明确写出「回答本公司相关问题前先查 `search_knowledge`，不要联网搜索代替」「生成优先用公司 GPU」「发现技能有错再提建议，不要每次都提」。模型正是靠这些描述选工具的。
- **拒绝要可解释**：被拒绝时返回具体原因（如「岗位包『小红书运营』没有『财务制度与报表』的检索权限」），模型能如实转告员工，而不是反复重试。
- **长任务有界等待**：生成工具最多等 90 秒，未完成返回任务号，由 `get_task` 查询，避免占住 agent 的工具调用超时。
- **副作用记录在先**：每次通过与拒绝都写审计；拒绝路径与通过路径一样留痕，是审计价值的主要来源。
- **agent 能写的东西要受限**：`report_work` 只能写自己的条目，只存标题 / 状态 / 链接，不存正文；`propose_improvement` 有限额、去重、大小上限，内容只给人看（8 章）。
- **角色由服务端算**：`team_report` 的范围取决于调用者的控制台角色，而不是参数，agent 无法通过传参看到不该看的部门（4.5 节）。

## 5.4 已用真实 agent 验证的链路

- **CodeBuddy CLI 2.171.0**：识别中枢 MCP、调用中枢模型（用量记到员工本人的 key）、无人值守调用 `whoami` 和 `generate_image`；读取中枢技能（先看手册里的「中枢技能」声明，再 `list_skills` / `read_skill`）；在用户确认业务事实后调用 `propose_improvement` 提交建议并说明没有改技能原文。
- **端到端测试**：`scripts/e2e_proposals.py` 用真实 Casdoor 登录（员工走 hub-agent 的 PKCE）、真实 MCP HTTP（`initialize` → `tools/call`）和真实控制台接口，覆盖建议的提交、限额、权限、采纳、驳回、过期确认、新增文档同步 RAGFlow 并被员工的 agent 检索到等 38 项。
