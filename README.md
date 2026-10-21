# 企业智能体中枢

面向约 50 人企业的私有化多智能体平台：一个中枢统一管理身份、权限、知识、技能、模型、GPU 和审计，每个岗位配一个能在本机干活的 AI 助手。

- 权限在中枢强制执行，不靠提示词
- 「管 agent，不管人」：管理员下发任务和策略、查看 agent 操作日志，不看屏幕
- 两级接入：官方 agent（WorkBuddy、CodeBuddy CLI、Hermes 等，经接入器连中枢，可在本机干活）+ 第三方智能体（MCP 只读接入）

> 最近的变化见 [docs/CHANGELOG.md](docs/CHANGELOG.md)；开发约定、常用命令和已知的坑见 [CLAUDE.md](CLAUDE.md)；全部文档见 [docs/README.md](docs/README.md)。

## 当前状态（2026-10-21，本机 Docker 开发环境，尚未上云）

**已完成并验证**
- **身份**：Casdoor 自建账号（不接钉钉）；控制台可新建 / 导入 / 重置密码 / 停用成员，停用 30 秒内令牌失效并回收模型 key
- **权限与审计**：岗位包（技能、知识库、工具、模型、额度、可打开的应用）；同一追踪 ID 贯通登录、检索、出图与模型调用
- **MCP Server**：令牌鉴权、按岗位包过滤、审计落库；知识库走 RAGFlow（失败回退本地）
- **模型**：控制台「模型」页接入对话模型上游、按模型设置价格；员工专属 key 按人计量，月度额度落到 key
- **出图出视频**：本机 GPU（ComfyUI）、第三方 apimart API、H3 生成网关三条线，通道手动切换，调度容错
- **员工接入**：一键接入（发一段话给员工的 agent 即可）、本地 MCP 桥；WorkBuddy / CodeBuddy CLI / Cursor / Claude 桌面版
- **应用分发**：`open_app` 下载、校验、启动本机应用（小红书运营工作台）

**未完成 / 计划中**：云服务器部署（香港 + 隧道连本地 GPU，暂缓）、生产环境账号登录收口（员工端改走浏览器登录，已有实现，待端到端实测）、模型网关的真实价格需管理员按厂商价格设置。

## 架构

| 角色 | 部署位置 | 组成 |
|---|---|---|
| 中枢 | 1 台服务器（无需 GPU） | Casdoor（身份）、RAGFlow（知识库）、New API（模型网关）、自研 MCP Server、任务队列、审计日志、控制台 |
| GPU 能力节点 | 带 N 卡的机器 | ComfyUI（本机 GPU 通道）；H3 生成网关（可选，REST） |
| 员工端 | 每位员工电脑 | WorkBuddy / CodeBuddy CLI 等 agent，通过接入器的 MCP 桥连中枢 |

## 技术栈

Python / FastAPI（MCP Server、任务队列、控制台后端）· React 19 + Ant Design 6（控制台前端）· PostgreSQL · Docker Compose · Casdoor · RAGFlow · New API · ComfyUI

## 目录结构

```
console/          中台控制台（后端 + MCP Server + 调度服务，前端；自研）
hub/              部署：docker-compose、Makefile、Casdoor 静态资源
agent/            员工端接入器 hub_agent.py 与一键安装脚本
apps/             应用发布目录（zip 与 app.json 不入库，只在部署机上）
gpu-node/         ComfyUI 工作流模板（调度代码在 console/backend/app/gpu.py）
skills/           岗位技能仓库（<部门>/<技能 id>/SKILL.md，可用 Obsidian 编辑）
vault/            企业知识库（Obsidian vault，每个文件夹一个知识库）
docs/             文档：更新记录、专题文档、设计与决策（见 docs/README.md）
```

小红书运营工作台是**独立项目**（有自己的仓库），通过 `apps/` 分发，见 [CLAUDE.md](CLAUDE.md)「小红书运营工作台」。

## 快速开始

全部服务都在 Docker 里运行。在中枢服务器上执行：

```bash
cd hub
make env              # 生成 .env（随机密码），再把 HUB_HOST、CASDOOR_ORIGIN 改成服务器 IP
make up               # 构建并启动：控制台 :8088、MCP Server :8200、Casdoor :8000、New API :3000
make bootstrap-demo   # 首次：初始化 Casdoor 并创建测试部门和成员（生产环境用 make bootstrap）
```

打开 `http://<服务器>:8088` 登录控制台。成员接入见控制台「接入方式」页；计费与额度见 [docs/billing.md](docs/billing.md)；部署细节见 [hub/README.md](hub/README.md)，本地开发（不用 Docker、热更新）见 [console/README.md](console/README.md)。
