# 中枢 MCP Server

## 目的

员工的 agent（以及经授权的外部智能体）通过 MCP 连到中枢，使用技能和企业知识库。MCP Server 是「权限在中枢强制执行」的落点：每次调用都核对员工身份和岗位包，并写入审计日志。

代码：`console/backend/app/mcp_server.py`（和控制台后端在同一个 Python 项目里，共用数据库、权限和内容模块）。

部署时作为 compose 里的 `hub-mcp` 服务运行（与控制台后端同一镜像），地址 `http://<中枢>:8200/mcp`（Streamable HTTP）。本地开发也可以直接运行：

```bash
cd console/backend
uv run uvicorn app.mcp_server:app --reload --port 8200
```

## 工具

| 工具 | 作用 | 权限要求 |
|---|---|---|
| `whoami` | 当前员工、部门、入口、岗位包、可用技能和知识库 | 有效令牌 |
| `list_skills` | 岗位包内的技能列表 | 官方 agent，岗位包含 `skill.read` |
| `read_skill(skill_id)` | 读取 SKILL.md 全文 | 同上，且技能在岗位包内 |
| `search_knowledge(query, knowledge_base?)` | 检索知识库；指定库名则只查该库 | 岗位包含 `kb.search`；外部智能体另需岗位包「外部只读」且知识库开放给外部 |
| `generate_cover(title, description?)` | 派发到 GPU 节点生成 3 版封面，最多等 90 秒，见 [gpu.md](gpu.md) | 官方 agent，岗位包含 `image.cover` |
| `get_cover_task(task_id)` | 查询封面任务进度和图片链接 | 只能查自己的任务 |

被拒绝时返回明确原因（例如「岗位包『小红书运营』没有『财务制度与报表』的检索权限」），并记一条「拒绝」审计。

## 关键设计

**身份 = Casdoor 令牌。** 请求头 `Authorization: Bearer <JWT>`。MCP Server 用 Casdoor 的 JWKS 校验签名和有效期，并要求令牌属于本企业组织。

**入口由签发应用决定，而不是请求头。** Casdoor 里有两个应用：
- `hub-agent`：员工端官方 agent → 入口「官方 agent」，享有岗位包的全部能力
- `hub-external`：ChatGPT、Claude 等外部智能体 → 入口「外部智能体」，只能检索开放给外部的知识库，不能读技能

控制台应用 `hub-console` 签发的令牌不被 MCP 接受。请求头是客户端可以随意填写的，所以只用来传递任务描述，不用来判断权限。

**权限判断集中在 `policy.py`。** 岗位包和成员分配从数据库实时读取，控制台一改，下一次 MCP 调用立即生效。提示词里怎么写都绕不过去：注入「忽略限制」的请求和普通越权请求一样被拒绝。

**审计。** 每次工具调用写一条 `audit_events`。同一任务共用 `trace_id`：优先取请求头 `X-Hub-Trace-Id`，否则用 MCP 会话 ID。请求头 `X-Hub-Task`（URL 编码）可以带上任务描述，显示在控制台审计日志中。

**内容。**
- 技能：`skills/<部门>/<技能 id>/SKILL.md`
- 知识库：`vault/<知识库名>/*.md`（Obsidian vault）。当前用字符二元组做关键词检索，接入 RAGFlow 后替换 `content.search()`，目录和接口不变

## 数据库

PostgreSQL 的 `hub` 库（`hub/docker-compose.yml` 里的同一个 PostgreSQL），由控制台后端或 MCP Server 启动时自动建表：

| 表 | 内容 |
|---|---|
| `role_packs` | 岗位包定义；首次启动时写入演示岗位包作为初始数据 |
| `role_assignments` | 成员 → 岗位包；没有记录的成员按部门默认岗位包 |
| `audit_events` | 审计事件，一步一行 |

## 本地验证

```bash
cd hub && make up && make bootstrap-demo                 # 启动全部服务，创建应用和测试成员
cd ../console/backend && uv run python scripts/mcp_smoke.py   # 模拟运营、财务员工和外部智能体调用
```

冒烟脚本覆盖：运营员工正常读技能和查知识、越权查财务被拒、提示词注入被拒、财务员工正常查报销制度、外部智能体只能读开放的知识库。跑完后，控制台审计日志里能看到这几条链路。

## 取舍与后续

- 开发环境的 agent 应用开启了 password 授权，方便脚本取令牌；生产环境应改为授权码或设备码流程，由员工端 agent 引导员工扫码登录
- 还没有模型调用、生图、本机动作相关的工具，审计里的 Token 和花费暂时为空；接入 New API 和 GPU 任务队列后补上
- 已容器化：与控制台后端共用 `hub-backend` 镜像，见 `hub/docker-compose.yml`
