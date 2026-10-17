# 中台控制台（console）

> 后续开发主机为 Windows；容器优先的启动步骤见 [Windows开发交接.md](../docs/Windows开发交接.md)。下文宿主机热更新方式是可选模式，不能替代同机 ComfyUI 的容器连通验收。

管理员和老板使用的 Web 控制台：成员与岗位包分配、技能库、知识库、审计日志、用量与成本。

支持两种模式（`HUB_CONSOLE_MODE`）：

| 模式 | 登录 | 成员与组织 | 其余模块 |
|---|---|---|---|
| `demo`（默认） | 不需要 | 演示数据 | 演示数据 |
| `casdoor` | Casdoor 登录，仅组织管理员可进入 | Casdoor 实时数据（生产环境由钉钉同步） | 岗位包、审计、技能、知识库为真实数据；用量与 GPU 节点仍为演示 |

演示数据在内存里，修改后立即生效，重启恢复初始状态。casdoor 模式下，岗位包和成员分配存在中枢数据库（PostgreSQL 的 `hub` 库），审计日志来自中枢 MCP Server。

同一个 Python 项目里还有**中枢 MCP Server**（`app/mcp_server.py`，端口 8200），见 [docs/mcp-server.md](../docs/mcp-server.md)。

## 技术栈

- 前端：React 19 + TypeScript + Vite + Ant Design 6 + ECharts（`frontend/`）
- 后端：Python + FastAPI，用 uv 管理依赖（`backend/`）

## 本地运行

```bash
# 后端：http://localhost:8100（接口文档 /docs）
cd console/backend
uv sync
uv run uvicorn app.main:app --reload --port 8100

# 前端：http://localhost:5173（/api、/v1 自动代理到 8100；/v1 是员工模型调用代理，见 docs/audit.md）
cd console/frontend
npm install
npm run dev
```

在 Claude Code 桌面版中，也可以直接用 `.claude/launch.json` 里的 `console-api` 和 `console-web` 两项启动。

测试：`cd console/backend && uv run pytest`

部署时控制台和 MCP Server 都在 Docker 里运行，见 [hub/README.md](../hub/README.md)。下面是**本地开发**的方式：后端和前端在宿主机上直接运行，改代码热更新。

### 用本地 Casdoor 运行（casdoor 模式）

```bash
# 1. 只启动 Casdoor 和 PostgreSQL（需要 hub/.env，见 hub/README.md；本机开发把 CASDOOR_ORIGIN 设为 http://localhost:8000）
cd hub && docker compose up -d casdoor
make db-hub   # 已有数据目录时补建中枢数据库；全新初始化会自动创建

# 2. 写入测试组织、控制台 / agent / 外部智能体三个应用、9 个部门和 18 名成员；
#    应用凭证写回 hub/.env，开发配置写入 console/backend/.env
cd console/backend && uv run python scripts/casdoor_bootstrap.py --demo --console-env .env

# 3. 重启后端，打开 http://localhost:5173，会跳转到 Casdoor 登录
#    账号 admin，密码见 hub/.env 的 XINGHE_ADMIN_PASSWORD

# 4. 启动 MCP Server，并模拟几名员工的 agent 调用（结果会出现在控制台审计日志）
uv run uvicorn app.mcp_server:app --reload --port 8200
uv run python scripts/mcp_smoke.py
```

初始化脚本可重复运行。`--demo` 只用于开发和演示；生产环境的部门和成员来自钉钉同步。

## 环境变量（后端）

| 变量 | 默认值 | 说明 |
|---|---|---|
开发时写在 `console/backend/.env`（可参考 `.env.example`），启动时自动加载。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HUB_CONSOLE_MODE` | `demo` | `demo` 或 `casdoor` |
| `HUB_CONSOLE_CORS` | `http://localhost:5173` | 允许跨域访问的前端地址，多个用逗号分隔 |
| `CONSOLE_PUBLIC_URL` | `http://localhost:5173` | 浏览器访问控制台的地址，登录回调为 `<地址>/callback` |
| `CASDOOR_ENDPOINT` | — | 服务端访问 Casdoor 的地址（容器内为 `http://casdoor:8000`） |
| `CASDOOR_PUBLIC_URL` | 同 `CASDOOR_ENDPOINT` | 浏览器访问 Casdoor 的地址，用于登录跳转和退出 |
| `CASDOOR_ORG` | — | 企业在 Casdoor 中的组织名 |
| `CASDOOR_APP` | — | 控制台在 Casdoor 中的应用名 |
| `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET` | — | 该应用的 OAuth 凭证（同时用于读取和更新成员） |
| `HUB_COOKIE_SECURE` | `false` | 有 HTTPS 时设为 `true`，会话 cookie 只走 HTTPS |
| `HUB_DATABASE_URL` | — | 中枢数据库，如 `postgresql://hub:<密码>@127.0.0.1:25432/hub`（casdoor 模式必填） |
| `HUB_SKILLS_DIR` / `HUB_VAULT_DIR` | 仓库根目录下的 `skills/`、`vault/` | 技能仓库与知识库目录 |
| `HUB_MCP_PUBLIC_URL` | `http://localhost:8200/mcp` | MCP Server 对外地址 |
| `HUB_AGENT_CLIENT_IDS` | — | 「官方 agent」应用的 client id，逗号分隔 |
| `HUB_EXTERNAL_CLIENT_IDS` | — | 「外部智能体」应用的 client id，逗号分隔 |

## 页面

| 页面 | 路径 | 内容 |
|---|---|---|
| 总览 | `/` | 在线 agent、今日任务、月花费与预算、越权拦截、GPU 节点、待确认动作 |
| 成员与组织 | `/members` | 钉钉组织架构、成员 agent 状态、为成员切换岗位包 |
| 岗位包 | `/role-packs` | 技能、知识库、工具、模型、额度、动作上限、外部智能体接入，可编辑 |
| 技能库 | `/skills` | SKILL.md 列表与预览 |
| 知识库 | `/knowledge` | 按部门和密级管理，是否开放给外部智能体 |
| 审计日志 | `/audit` | 按任务查看完整调用链路，支持 `?trace=` `?outcome=` 直达 |
| 用量与成本 | `/usage` | 按部门、模型、个人统计花费与额度 |

设计说明见 [docs/console.md](../docs/console.md)。
