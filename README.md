# 企业智能体中枢

> **当前开发方案（2026-10-17）**：后续在 Windows 工作站（RTX 5080 16GB / 9950X3D / 64GB DDR5）开发。中枢用 Docker Desktop + WSL2，ComfyUI 复用 Windows 原生安装；容器通过 `host.docker.internal:8188` 访问，不依赖 Tailscale/frp。开始前请读 [Windows 开发交接](docs/Windows开发交接.md)。正式生产部署位置另行决定。

面向约 50 人企业的私有化多智能体平台：一个中枢统一管理身份、权限、知识、技能和审计，每个岗位配一个能在本机干活的 AI 助手。

- 权限在中枢强制执行，不靠提示词
- 「管 agent，不管人」：管理员下发任务和策略、查看 agent 操作日志，不看屏幕
- 两级接入：自研 agent（Hermes 改造，可本机操作）+ 第三方智能体（MCP 只读接入）

> 当前阶段：**阶段 0 · 最小链路验证（5 步全部完成）**。控制台已接入 Casdoor 登录；中枢 MCP Server 完成（令牌鉴权、按岗位包过滤、审计落库）；员工端 Hermes 已通过接入器接入（专属模型 key、按人计量）；GPU 生图与短视频链路已做模拟验证（Windows 节点单机运行见交接报告，中枢到真机的完整联调待验收）；审计串联完成（模型调用经中枢代理，登录 → 查询 → 出图 → token 消耗一条链路）；RAGFlow 检索接入完成（灌库脚本就绪，本体待台式机验证）。计划见 [docs/00-启动计划.md](docs/00-启动计划.md)，给领导演示的脚本见 [docs/demo.md](docs/demo.md)，客户现场部署照 [docs/部署清单.md](docs/部署清单.md) 执行。

## 架构

| 角色 | 部署位置 | 组成 |
|---|---|---|
| 中枢 | 1 台服务器（无需 GPU） | Casdoor（钉钉登录）、RAGFlow（知识库）、New API（模型网关）、自研 MCP Server、模型代理（/v1）、任务队列、审计串联 |
| GPU 能力节点 | 带 N 卡的机器（可与中枢同网直连，或经内置 frp 隧道跨网接入） | ComfyUI |
| 员工端 | 每位员工电脑 | Hermes agent，通过 MCP 连中枢 |

## 技术栈

Python / FastAPI（自研 MCP Server、任务队列、控制台后端）· React + Ant Design（控制台前端）· Docker Compose · Casdoor · RAGFlow · New API · ComfyUI · Hermes Agent

## 目录结构

```
console/          中台控制台（Web 管理端，自研）
hub/mcp-server/   中枢 MCP Server 说明（代码在 console/backend/app/mcp_server.py；模型代理在 app/model_proxy.py）
gpu-node/         GPU 节点的 ComfyUI 工作流模板（调度代码在 console/backend/app/gpu.py）
agent/            员工端接入器 hub_agent.py（把 Hermes 接到中枢）
skills/           岗位技能仓库（<部门>/<技能 id>/SKILL.md，可用 Obsidian 编辑）
vault/            企业知识库（Obsidian vault，每个文件夹一个知识库）
docs/             方案、阶段计划、决策记录（docs/decisions/）
```

## 快速开始

中枢服务在 Docker 里运行；ComfyUI 保留 Windows 原生服务。Windows 开发请按上面的交接文档在 WSL Ubuntu 中执行；下面是通用 Bash/Makefile 入口：

```bash
cd hub
make env              # 生成 .env（随机密码），再把 HUB_HOST、CASDOOR_ORIGIN 改成服务器 IP
make up               # 构建并启动：控制台 :8088、MCP Server :8200、Casdoor :8000、New API :3000
make bootstrap-demo   # 首次：初始化 Casdoor 并创建测试部门和成员（生产环境用 make bootstrap）
```

打开 `http://<服务器>:8088` 登录控制台。部署细节见 [hub/README.md](hub/README.md)，本地开发（不用 Docker、热更新）见 [console/README.md](console/README.md)。
