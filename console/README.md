# 中台控制台（console）

管理员和老板使用的 Web 控制台：成员与岗位包分配、技能库、知识库、审计日志、用量与成本。

支持两种模式（`HUB_CONSOLE_MODE`）：

| 模式 | 登录 | 成员与组织 | 其余模块 |
|---|---|---|---|
| `demo`（默认） | 不需要 | 演示数据 | 演示数据 |
| `casdoor` | Casdoor 登录，仅组织管理员可进入 | Casdoor 实时数据（生产环境由钉钉同步） | 演示数据 |

演示数据在内存里，修改后立即生效，重启恢复初始状态。Casdoor 模式下，成员的岗位包保存在 Casdoor 用户属性 `hub_role_pack` 中。

## 技术栈

- 前端：React 19 + TypeScript + Vite + Ant Design 6 + ECharts（`frontend/`）
- 后端：Python + FastAPI，用 uv 管理依赖（`backend/`）

## 本地运行

```bash
# 后端：http://localhost:8100（接口文档 /docs）
cd console/backend
uv sync
uv run uvicorn app.main:app --reload --port 8100

# 前端：http://localhost:5173（/api 自动代理到 8100）
cd console/frontend
npm install
npm run dev
```

在 Claude Code 桌面版中，也可以直接用 `.claude/launch.json` 里的 `console-api` 和 `console-web` 两项启动。

测试：`cd console/backend && uv run pytest`

### 用本地 Casdoor 运行（casdoor 模式）

```bash
# 1. 启动 Casdoor（需要 hub/.env，见 hub/README.md；本机开发可把 CASDOOR_ORIGIN 设为 http://localhost:8000）
cd hub && docker compose up -d casdoor

# 2. 写入测试组织、控制台应用、9 个部门和 18 名成员，并生成 console/backend/.env
cd console/backend && uv run python scripts/casdoor_dev_seed.py

# 3. 重启后端，打开 http://localhost:5173，会跳转到 Casdoor 登录
#    账号 admin，密码见 hub/.env 的 XINGHE_ADMIN_PASSWORD
```

种子脚本可重复运行，只用于开发环境；生产环境的部门和成员来自钉钉同步。

## 环境变量（后端）

| 变量 | 默认值 | 说明 |
|---|---|---|
开发时写在 `console/backend/.env`（可参考 `.env.example`），启动时自动加载。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HUB_CONSOLE_MODE` | `demo` | `demo` 或 `casdoor` |
| `HUB_CONSOLE_CORS` | `http://localhost:5173` | 允许跨域访问的前端地址，多个用逗号分隔 |
| `CONSOLE_PUBLIC_URL` | `http://localhost:5173` | 浏览器访问控制台的地址，登录回调为 `<地址>/callback` |
| `CASDOOR_ENDPOINT` | — | Casdoor 地址，如 `http://192.168.1.10:8000` |
| `CASDOOR_ORG` | — | 企业在 Casdoor 中的组织名 |
| `CASDOOR_APP` | — | 控制台在 Casdoor 中的应用名 |
| `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET` | — | 该应用的 OAuth 凭证（同时用于读取和更新成员） |
| `HUB_COOKIE_SECURE` | `false` | 有 HTTPS 时设为 `true`，会话 cookie 只走 HTTPS |

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
