# 企业智能体中枢

面向约 50 人企业的私有化多智能体平台：一个中枢统一管理身份、权限、知识、技能和审计，每个岗位配一个能在本机干活的 AI 助手。

- 权限在中枢强制执行，不靠提示词
- 「管 agent，不管人」：管理员下发任务和策略、查看 agent 操作日志，不看屏幕
- 两级接入：自研 agent（Hermes 改造，可本机操作）+ 第三方智能体（MCP 只读接入）

> 当前阶段：**阶段 0 · 最小链路验证**。控制台已接入 Casdoor 登录；中枢 MCP Server 第一版完成（令牌鉴权、按岗位包过滤、审计落库）。计划见 [docs/00-启动计划.md](docs/00-启动计划.md)。

## 架构

| 角色 | 部署位置 | 组成 |
|---|---|---|
| 中枢 | 1 台服务器（无需 GPU） | Casdoor（钉钉登录）、RAGFlow（知识库）、New API（模型网关）、自研 MCP Server、任务队列、审计日志 |
| GPU 能力节点 | 带 N 卡的机器 | ComfyUI |
| 员工端 | 每位员工电脑 | Hermes agent，通过 MCP 连中枢 |

## 技术栈

Python / FastAPI（自研 MCP Server、任务队列、控制台后端）· React + Ant Design（控制台前端）· Docker Compose · Casdoor · RAGFlow · New API · ComfyUI · Hermes Agent

## 目录结构

```
console/          中台控制台（Web 管理端，自研）
hub/mcp-server/   中枢 MCP Server 说明（代码在 console/backend/app/mcp_server.py）
hub/task-queue/   GPU 任务队列（自研）
gpu-node/         ComfyUI 工作流与节点注册
agent/            Hermes 员工端配置与改造
skills/           岗位技能仓库（<部门>/<技能 id>/SKILL.md，可用 Obsidian 编辑）
vault/            企业知识库（Obsidian vault，每个文件夹一个知识库）
docs/             方案、阶段计划、决策记录（docs/decisions/）
```

## 快速开始

全部服务都在 Docker 里运行。在中枢服务器上执行：

```bash
cd hub
make env              # 生成 .env（随机密码），再把 HUB_HOST、CASDOOR_ORIGIN 改成服务器 IP
make up               # 构建并启动：控制台 :8088、MCP Server :8200、Casdoor :8000、New API :3000
make bootstrap-demo   # 首次：初始化 Casdoor 并创建测试部门和成员（生产环境用 make bootstrap）
```

打开 `http://<服务器>:8088` 登录控制台。部署细节见 [hub/README.md](hub/README.md)，本地开发（不用 Docker、热更新）见 [console/README.md](console/README.md)。
