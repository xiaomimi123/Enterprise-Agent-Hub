# 中台控制台（console）

管理员和老板使用的 Web 控制台：成员与岗位包分配、技能库、知识库、审计日志、用量与成本。

目前是**演示数据模式**：数据由后端在内存中生成，修改岗位包和成员分配会立即生效，重启后恢复初始状态。

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

## 环境变量（后端）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HUB_CONSOLE_MODE` | `demo` | 数据模式，目前只有 `demo` |
| `HUB_CONSOLE_CORS` | `http://localhost:5173` | 允许跨域访问的前端地址，多个用逗号分隔 |

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
